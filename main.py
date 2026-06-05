import datetime
import json
import os
import sys
import re
import textwrap
import threading
import time
import zoneinfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import IO

_task_local = threading.local()
_run_dir: "Path | None" = None
_stats_fh: "IO[str] | None" = None  # opened by _setup_logging()
_ansi_re = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")


def _log_stats(text: str) -> None:
    if _stats_fh is not None:
        _stats_fh.write(_ansi_re.sub("", text) + "\n")
        _stats_fh.flush()


def _setup_logging() -> None:
    """Create run dir, open main.log for stats, wrap stdout for [task_id] terminal prefix."""
    _env_path = Path(__file__).parent / ".env"
    _dotenv: dict[str, str] = {}
    try:
        for _line in _env_path.read_text().splitlines():
            _s = _line.strip()
            if _s and not _s.startswith("#") and "=" in _s:
                _k, _, _v = _s.partition("=")
                _dotenv[_k.strip()] = _v.strip()
    except Exception:
        pass

    model = os.getenv("MODEL") or _dotenv.get("MODEL") or "unknown"
    log_level = (os.getenv("LOG_LEVEL") or _dotenv.get("LOG_LEVEL") or "INFO").upper()

    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    _tz_name = os.environ.get("TZ", "")
    try:
        _tz = zoneinfo.ZoneInfo(_tz_name) if _tz_name else None
    except Exception:
        _tz = None
    _now = datetime.datetime.now(tz=_tz) if _tz else datetime.datetime.now()
    _safe = model.replace("/", "-").replace(":", "-")
    run_name = f"{_now.strftime('%Y%m%d_%H%M%S')}_{_safe}"
    run_path = logs_dir / run_name
    run_path.mkdir(exist_ok=True)

    global _run_dir, _stats_fh
    _run_dir = run_path
    _stats_fh = open(run_path / "main.log", "w", buffering=1, encoding="utf-8")
    _stats_fh.write(f"[LOG] {run_path}/  (LOG_LEVEL={log_level})\n")
    _stats_fh.flush()

    _orig = sys.stdout

    class _PrefixWriter:
        def write(self, data: str) -> None:
            prefix = getattr(_task_local, "task_id", None)
            if prefix and data and data != "\n":
                _orig.write(f"[{prefix}] {data}")
            else:
                _orig.write(data)

        def writelines(self, lines) -> None:
            for line in lines:
                self.write(line)

        def flush(self) -> None:
            _orig.flush()

        def isatty(self) -> bool:
            return _orig.isatty()

        @property
        def encoding(self) -> str:
            return _orig.encoding

    sys.stdout = _PrefixWriter()
    print(f"[LOG] {run_path}/  (LOG_LEVEL={log_level})")


_setup_logging()

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest, EvalPolicy, GetBenchmarkRequest,
    StartRunRequest, StartTrialRequest,
    StatusRequest, SubmitRunRequest, TRIAL_STATE_DONE,
)
from connectrpc.errors import ConnectError

from agent import run_agent
from agent.learned_store import save_last_run
from agent.pipeline import learn_from_grader
from agent.trace import TraceLogger, set_trace

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"
BITGN_API_KEY = os.getenv("BITGN_API_KEY") or ""
_base_run_name = os.getenv("BITGN_RUN_NAME") or ""
BITGN_RUN_NAME = f"{_base_run_name}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}" if _base_run_name else ""
PARALLEL_TASKS = max(1, int(os.getenv("PARALLEL_TASKS", "1")))
TRAIN_MAX_CYCLES = max(1, int(os.getenv("TRAIN_MAX_CYCLES", "1")))

_MODELS_JSON = Path(__file__).parent / "models.json"
_raw = json.loads(_MODELS_JSON.read_text())
MODEL_CONFIGS: dict[str, dict] = {k: v for k, v in _raw.items() if not k.startswith("_")}

def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise ValueError(f"Env var {name} is required but not set.")
    return v

_model_default = _require_env("MODEL")
print(f"[MODEL] default={_model_default}")

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"
CLI_BLUE = "\x1B[34m"


def _run_single_task(trial_id: str, task_filter: list, train_cycle: int = 1) -> tuple:
    """Execute one benchmark trial. Score is read later from SubmitRun.

    `train_cycle` is appended to the trace filename so successive cycles
    in TRAIN_MAX_CYCLES > 1 don't overwrite each other.
    """
    client = HarnessServiceClientSync(BITGN_URL)
    trial = client.start_trial(StartTrialRequest(trial_id=trial_id))
    task_id = trial.task_id

    if task_filter and task_id not in task_filter:
        client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
        return (task_id, trial.trial_id, 0.0, {}, None, True)

    _task_local.task_id = task_id
    assert _run_dir is not None
    trace_name = f"{task_id}.jsonl" if train_cycle <= 1 else f"{task_id}.c{train_cycle}.jsonl"
    _trace = TraceLogger(_run_dir / trace_name, task_id)
    set_trace(_trace)
    try:
        task_start = time.time()
        print(f"\n{'=' * 30} Starting task: {task_id} {'=' * 30}")
        print(f"{CLI_BLUE}{trial.instruction}{CLI_CLR}\n{'-' * 80}")
        _trace.log_header(trial.instruction, model=os.getenv("MODEL", "unknown"))
        token_stats: dict = {"input_tokens": 0, "output_tokens": 0}
        try:
            token_stats = run_agent({}, trial.harness_url, trial.instruction, task_id=task_id)
        except Exception as exc:
            print(exc)
        task_elapsed = time.time() - task_start
        client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
        in_t = token_stats.get("input_tokens", 0)
        out_t = token_stats.get("output_tokens", 0)
        cycles = token_stats.get("cycles_used", 0)
        m_short = (token_stats.get("model_used") or "—").split("/")[-1]
        print(
            f"[{task_id}] trial done in {task_elapsed:.1f}s"
            f" | in {in_t:,} / out {out_t:,} tok"
            f" | cycles={cycles} | {m_short}"
        )
        return (task_id, trial.trial_id, task_elapsed, token_stats, _trace, False)
    finally:
        set_trace(None)


def _finalize_task_trace(
    trace: "TraceLogger | None",
    task_id: str,
    score: float,
    detail: list,
    elapsed: float,
    token_stats: dict,
) -> None:
    if trace is None:
        return
    trace.log_task_result(
        outcome=token_stats.get("outcome", ""),
        score=float(score),
        cycles=token_stats.get("cycles_used", 0),
        total_in=token_stats.get("input_tokens", 0),
        total_out=token_stats.get("output_tokens", 0),
        elapsed_ms=int(elapsed * 1000),
        score_detail=detail,
    )
    trace.close()


def _print_table_header() -> None:
    lines = [
        f"\n{'=' * 80}",
        f"{'ИТОГОВАЯ СТАТИСТИКА':^80}",
        '=' * 80,
        f"{'Задание':<10} {'Оценка':>7} {'Время':>8}  {'Вход(tok)':>10} {'Выход(tok)':>10}  {'Циклы':>6}  {'Модель':<30}  Проблемы",
        "-" * 80,
    ]
    for line in lines:
        print(line)
        _log_stats(line)


def _print_table_row(task_id: str, score: float, detail: list, elapsed: float, ts: dict) -> None:
    issues = "; ".join(detail) if score < 1.0 else "—"
    in_t = ts.get("input_tokens", 0)
    out_t = ts.get("output_tokens", 0)
    m = ts.get("model_used", "—")
    m_short = m.split("/")[-1] if "/" in m else m
    cycles = ts.get("cycles_used", 0)
    line = f"{task_id:<10} {score:>7.2f} {elapsed:>7.1f}s  {in_t:>10,} {out_t:>10,}  {cycles:>6}  {m_short:<30}  {issues}"
    print(line)
    _log_stats(line)


def _write_summary(scores: list, run_start: float) -> None:
    n = len(scores)
    total = sum(s for _, s, *_ in scores) / n * 100.0
    total_elapsed = time.time() - run_start
    total_in = sum(ts.get("input_tokens", 0) for *_, ts in scores)
    total_out = sum(ts.get("output_tokens", 0) for *_, ts in scores)
    lines = [
        '=' * 80,
        f"{'ИТОГО':<10} {total:>6.2f}% {total_elapsed:>7.1f}s  {total_in:>10,} {total_out:>10,}",
        '=' * 80,
    ]
    for line in lines:
        print(line)
        _log_stats(line)


def _run_one_pass(client, task_filter: list, train_cycle: int):
    """One StartRun → trial loop → SubmitRun. Returns (scores, submit_result).

    `train_cycle` is threaded down to `_run_single_task` for trace naming.
    """
    run = client.start_run(StartRunRequest(
        name=BITGN_RUN_NAME,
        benchmark_id=BENCHMARK_ID,
        api_key=BITGN_API_KEY,
    ))
    print(f"Run started: {run.run_id} ({len(run.trial_ids)} trials)")

    pending: dict[str, tuple] = {}
    try:
        with ThreadPoolExecutor(max_workers=PARALLEL_TASKS) as pool:
            futures = {
                pool.submit(_run_single_task, tid, task_filter, train_cycle): tid
                for tid in run.trial_ids
            }
            for fut in as_completed(futures):
                try:
                    task_id, trial_id, task_elapsed, token_stats, trace, filtered = fut.result()
                except Exception as exc:
                    failed_tid = futures[fut]
                    print(f"{CLI_RED}[{failed_tid}] Task error: {exc}{CLI_CLR}")
                    continue
                if filtered:
                    continue
                pending[task_id] = (trial_id, task_elapsed, token_stats, trace)
    finally:
        print(f"\n{CLI_GREEN}>>>> Submitting run... <<<<{CLI_CLR}")
        result = client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))
        print(f"Run submitted: {run.run_id}")
        scores = _settle_scores(result, pending)
    return scores, result


def main() -> None:
    task_filter = [t for arg in sys.argv[1:] for t in arg.split(",") if t]

    run_start = time.time()
    try:
        client = HarnessServiceClientSync(BITGN_URL)
        print("Connecting to BitGN", client.status(StatusRequest()))
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCHMARK_ID))
        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} "
            f"with {len(res.tasks)} tasks.\n{CLI_GREEN}{res.description}{CLI_CLR}"
        )

        # Training loop: per-task. Each cycle is a fresh StartRun → SubmitRun.
        # Subsequent cycles target only tasks that scored < 1.0 in the prior pass.
        # Grader feedback distilled via `learn_from_grader` between cycles.
        final_state: dict[str, tuple] = {}  # task_id -> (score, detail, elapsed, ts)
        current_filter = task_filter
        last_result = None

        for cycle in range(1, TRAIN_MAX_CYCLES + 1):
            if cycle > 1:
                print(
                    f"\n{CLI_BLUE}>>>> Training cycle {cycle}/{TRAIN_MAX_CYCLES}: "
                    f"retrying {len(current_filter)} task(s) <<<<{CLI_CLR}"
                )

            try:
                scores, last_result = _run_one_pass(client, current_filter, cycle)
            except ConnectError as exc:
                print(f"{exc.code}: {exc.message}")
                break

            next_filter: list[str] = []
            for row in scores:
                task_id, score, detail, elapsed, token_stats = row
                final_state[task_id] = (score, detail, elapsed, token_stats)
                if score < 1.0:
                    next_filter.append(task_id)
                    if cycle < TRAIN_MAX_CYCLES:
                        if learn_from_grader(task_id, list(detail)):
                            print(
                                f"{CLI_BLUE}[{task_id}] LEARN distilled from grader feedback{CLI_CLR}"
                            )

            if not next_filter:
                if TRAIN_MAX_CYCLES > 1:
                    print(f"{CLI_GREEN}>>>> All targeted tasks passed at cycle {cycle} <<<<{CLI_CLR}")
                break
            current_filter = next_filter

        if final_state:
            final_rows = [(tid, *vals) for tid, vals in final_state.items()]
            _print_table_header()
            for row in final_rows:
                _print_table_row(*row)
            _write_summary(final_rows, run_start)
        if last_result is not None and last_result.score_available:
            print(f"\n{CLI_GREEN}FINAL SCORE: {last_result.score:0.2f}{CLI_CLR}")
        else:
            print(f"\n{CLI_RED}Score is not available. Results are sealed and will be revealed later{CLI_CLR}\n")

    except ConnectError as exc:
        print(f"{exc.code}: {exc.message}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")


def _settle_scores(submit_result, pending: dict) -> list:
    """Match SubmitRunResponse.trials back to pending per-task data.
    Writes deferred trace task_result rows, save_last_run for failures, prints per-task line."""
    rows = []
    incomplete = 0
    seen: set[str] = set()
    for t in submit_result.trials:
        task_id = t.task_id
        if task_id not in pending:
            continue
        seen.add(task_id)
        trial_id, task_elapsed, token_stats, trace = pending[task_id]
        score = float(t.score) if t.score_available else 0.0
        detail = list(t.score_detail)
        if t.state != TRIAL_STATE_DONE:
            incomplete += 1
        _finalize_task_trace(trace, task_id, score, detail, task_elapsed, token_stats)
        if t.score_available and score < 1.0:
            save_last_run(
                task_id,
                status="failure",
                outcome=token_stats.get("outcome", "OUTCOME_OK"),
                cycles_used=token_stats.get("cycles_used", 0),
            )
        style = CLI_GREEN if score == 1 else CLI_RED
        detail_str = "\n" + textwrap.indent("\n".join(detail), "  ") if detail else ""
        in_t = token_stats.get("input_tokens", 0)
        out_t = token_stats.get("output_tokens", 0)
        cycles = token_stats.get("cycles_used", 0)
        m_short = (token_stats.get("model_used") or "—").split("/")[-1]
        print(
            f"{style}[{task_id}] Score: {score:0.2f}"
            f" | {task_elapsed:.1f}s"
            f" | in {in_t:,} / out {out_t:,} tok"
            f" | cycles={cycles} | {m_short}"
            f"{detail_str}{CLI_CLR}"
        )
        rows.append((task_id, score, detail, task_elapsed, token_stats))
    # close + emit unmatched (e.g., sealed-eval blind runs return no per-trial scores)
    for task_id, (_, task_elapsed, token_stats, trace) in pending.items():
        if task_id in seen:
            continue
        _finalize_task_trace(trace, task_id, 0.0, [], task_elapsed, token_stats)
    if incomplete > 0:
        print(f"{CLI_RED}incomplete trials: {incomplete}{CLI_CLR}")
    return rows


if __name__ == "__main__":
    main()
