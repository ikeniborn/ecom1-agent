#!/usr/bin/env python3
"""Full prompt + reasoning trace for a single benchmark task (default: t38).

Runs ONE task through the real pipeline (orchestrator -> run_pipeline) against a
live benchmark trial, and records a structured JSONL trace that — beyond the
built-in agent.trace records — also captures the model's chain-of-thought
reasoning and the un-stripped raw response per LLM call.

Why a standalone script (no repo source touched): the production trace
(agent/trace.py) logs system+user prompts and the *stripped* assistant text, but
the model's reasoning is discarded before it reaches the trace
(`_THINK_RE.sub(...)` in agent/llm.py strips `<think>...</think>`; the Anthropic
path keeps only `type="text"` blocks; the claude-code path requests
`--output-format json`, whose envelope carries only the final text). This script
monkeypatches the LLM call seams at runtime to tee the reasoning into a
thread-local sink, and subclasses TraceLogger to fold it into each `llm_call`
record.

Reasoning capture per provider:
  * Ollama (`<think>` inline content, or `reasoning_content` / `reasoning`
    fields)  -> captured  [deepseek-v4-flash:cloud uses this, ollama_think]
  * OpenRouter (`<think>` inline / `reasoning`)                 -> captured
  * Anthropic (thinking blocks)            -> captured IF thinking is enabled
  * claude-code (iclaude): captured by swapping --output-format json ->
    stream-json at the spawn seam and sniffing assistant `thinking` blocks; the
    final `result` line keeps the same shape so cc_client parses it unchanged.
    NOTE: with low reasoning effort the model may emit no thinking blocks at all
    — then reasoning_available=false for those calls (honestly reported).

Dependency model of the emitted JSONL (how to read request/response order):
  * Every record carries a monotonic `seq` (global order) + `ts` + `task_id`.
  * `llm_call` records carry `cycle` and `phase`:
        cycle 0  -> pre-phase (DOC_SELECT / oracle rerank) + INTENT (frozen)
        cycle N  -> PLAN / LEARN(iLEARN) of interpreter cycle N
  * `prev_llm_seq` chains each llm_call to the previous one.
  * The `user_msg` of a PLAN at cycle N embeds PREVIOUS_ERROR + OBSERVED_RPC_
    OUTPUTS produced while interpreting cycle N-1 — that is the data dependency
    between an answer and the next request.

Usage (run from anywhere; the script chdirs to the repo root):
    uv run python scripts/trace_t38.py [task_id] [model]
    # defaults: task_id=t38  model=deepseek-v4-flash:cloud
    # CC example:  uv run python scripts/trace_t38.py t38 claude-code/haiku

Outputs (under logs/trace_<task>_<ts>_<model>/):
    <task>.jsonl         structured trace (this script's enriched records)
    <task>.detail.log    readable digest (auto, from agent.trace.render_trace)
    <task>.reasoning.md  readable interleave of system/user/reasoning/response
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

# --- repo root: chdir so .env / data/ / logs/ resolve, and importable ---------
_REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_REPO_ROOT)
sys.path.insert(0, str(_REPO_ROOT))

# --- CLI args -----------------------------------------------------------------
TASK = sys.argv[1] if len(sys.argv) > 1 else "t38"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "deepseek-v4-flash:cloud"
_IS_CC = MODEL.startswith("claude-code/")

# Force the model for THIS run BEFORE importing agent.llm (it reads env at import,
# and _load_env_file uses `key not in os.environ`, so our value wins over .env).
os.environ["ECOM_MODEL"] = MODEL

# claude-code mode: the pipeline calls the CC tier with cfg={}, so cc_model /
# cc_effort are resolved from ECOM_CC_DEFAULT_* — seed them from models.json so a
# `claude-code/haiku` run actually drives haiku at its configured effort. Both
# the CC enable flag and these defaults must exist BEFORE importing agent.llm
# (cc_client reads _CC_ENABLED at import). setdefault: a real .env/shell value wins.
if _IS_CC:
    os.environ.setdefault("ECOM_CC_ENABLED", "1")
    try:
        _mc = json.loads((_REPO_ROOT / "models.json").read_text()).get(MODEL, {})
        if _mc.get("cc_model"):
            os.environ.setdefault("ECOM_CC_DEFAULT_MODEL", str(_mc["cc_model"]))
        _opts = _mc.get("cc_options") or {}
        if _opts.get("cc_effort"):
            os.environ.setdefault("ECOM_CC_DEFAULT_EFFORT", str(_opts["cc_effort"]))
        if _opts.get("cc_timeout_s"):
            os.environ.setdefault("ECOM_CC_DEFAULT_TIMEOUT_S", str(_opts["cc_timeout_s"]))
        if _opts.get("cc_exclude_dynamic"):
            os.environ.setdefault("ECOM_CC_DEFAULT_EXCLUDE_DYNAMIC", "1")
    except Exception:
        pass

# Importing agent.llm triggers _load_env_file(".env") -> all ECOM_* config loads,
# including the harness/benchmark vars and the Ollama base URL.
import agent.cc_client as CC  # noqa: E402
import agent.llm as L  # noqa: E402
from agent import run_agent  # noqa: E402
from agent.trace import TraceLogger, set_trace  # noqa: E402

from bitgn.harness_connect import HarnessServiceClientSync  # noqa: E402
from bitgn.harness_pb2 import (  # noqa: E402
    EndTrialRequest,
    StartRunRequest,
    StartTrialRequest,
    StatusRequest,
    SubmitRunRequest,
    TRIAL_STATE_DONE,
)

# Harness config (same env keys main.py reads, now that .env is loaded).
BITGN_URL = os.getenv("ECOM_BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("ECOM_BENCHMARK_ID") or "bitgn/pac1-dev"
BITGN_API_KEY = os.getenv("ECOM_BITGN_API_KEY") or ""
_base_run_name = os.getenv("ECOM_BITGN_RUN_NAME") or ""
RUN_NAME = (
    f"{_base_run_name}-trace-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if _base_run_name
    else ""
)

# ---------------------------------------------------------------------------
# Reasoning capture — thread-local sink shared by all provider seams
# ---------------------------------------------------------------------------
_sink = threading.local()
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _push(reasoning: str, raw_full: str) -> None:
    items = getattr(_sink, "items", None)
    if items is None:
        items = []
        _sink.items = items
    items.append({"reasoning": reasoning or "", "raw_full": raw_full or ""})


def _pop() -> dict:
    """Return the capture for the just-completed logical LLM call and reset.

    A logical call may issue several spawns/creates (retries / fallback model);
    take the last one carrying reasoning, else the last one at all."""
    items = getattr(_sink, "items", [])
    _sink.items = []
    chosen = None
    for it in items:
        if it["reasoning"]:
            chosen = it
    if chosen is None and items:
        chosen = items[-1]
    return chosen or {"reasoning": "", "raw_full": ""}


# ---------------------------------------------------------------------------
# Seam 1 — OpenAI-compatible clients (Ollama / OpenRouter): tee reasoning
# ---------------------------------------------------------------------------
def _reasoning_from_openai_resp(resp) -> tuple[str, str]:
    """(reasoning, full_content) from an OpenAI-compatible chat completion.

    Handles three reasoning conventions: a `reasoning_content` field (DeepSeek),
    a `reasoning` field (OpenRouter-normalized), and `<think>...</think>` inlined
    in the message content (Ollama think models)."""
    reasoning = ""
    full = ""
    try:
        data = resp.model_dump()
    except Exception:
        data = None
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            full = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if not reasoning and full:
                m = _THINK_RE.search(full)
                if m:
                    reasoning = m.group(1).strip()
    return (reasoning or ""), (full or "")


def _wrap_openai_client(client) -> None:
    if client is None:
        return
    comp = client.chat.completions  # cached_property -> stable instance
    orig = comp.create

    def wrapped(*a, **k):
        resp = orig(*a, **k)
        try:
            _push(*_reasoning_from_openai_resp(resp))
        except Exception:
            pass
        return resp

    comp.create = wrapped


def _wrap_anthropic_client(client) -> None:
    if client is None:
        return
    orig = client.messages.create

    def wrapped(*a, **k):
        resp = orig(*a, **k)
        try:
            think = "".join(
                getattr(b, "thinking", "") or ""
                for b in resp.content
                if getattr(b, "type", None) == "thinking"
            )
            text = "\n".join(
                getattr(b, "text", "") or ""
                for b in resp.content
                if getattr(b, "type", None) == "text"
            )
            _push(think, text)
        except Exception:
            pass
        return resp

    client.messages.create = wrapped


# ---------------------------------------------------------------------------
# Seam 2 — claude-code: swap json -> stream-json at the spawn, sniff thinking
# ---------------------------------------------------------------------------
def _parse_stream_reasoning(lines: list[str]) -> tuple[str, str]:
    """(reasoning, assistant_text) from iclaude --output-format stream-json NDJSON.

    Collects every `thinking` content block from `assistant` events; the final
    `result` line is left untouched for cc_client._parse_envelope to consume."""
    parts: list[str] = []
    text_parts: list[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            obj = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        tt = obj.get("type")
        if tt == "assistant":
            msg = obj.get("message") or {}
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "thinking":
                    parts.append(b.get("thinking") or "")
                elif bt == "redacted_thinking":
                    parts.append("[redacted_thinking]")
                elif bt == "text":
                    text_parts.append(b.get("text") or "")
        elif tt == "thinking":  # some versions emit a top-level thinking event
            parts.append(obj.get("thinking") or obj.get("text") or "")
    return "\n".join(p for p in parts if p), "\n".join(t for t in text_parts if t)


def _install_cc_stream_capture() -> None:
    """Wrap cc_client._spawn_once so every iclaude spawn uses stream-json (exposing
    thinking) while cc_client._parse_envelope still parses the terminal result line
    unchanged. Pushes captured reasoning into the sink."""
    _orig_spawn = CC._spawn_once

    def _spawn(cmd, cwd, env, timeout_s, stdin_data=None):
        cmd = list(cmd)
        if "--output-format" in cmd:
            i = cmd.index("--output-format")
            if i + 1 < len(cmd):
                cmd[i + 1] = "stream-json"
        else:
            cmd += ["--output-format", "stream-json"]
        if "--verbose" not in cmd:  # required with --print --output-format stream-json
            cmd.append("--verbose")
        lines, exit_code, fail = _orig_spawn(cmd, cwd, env, timeout_s, stdin_data=stdin_data)
        try:
            _push(*_parse_stream_reasoning(lines))
        except Exception:
            pass
        return lines, exit_code, fail

    CC._spawn_once = _spawn


# install the seams relevant to this run
if _IS_CC:
    _install_cc_stream_capture()
else:
    _wrap_openai_client(L.ollama_client)
    _wrap_openai_client(L.openrouter_client)
    _wrap_anthropic_client(L.anthropic_client)


# ---------------------------------------------------------------------------
# Enriched trace logger — adds seq, prev_llm_seq, reasoning, raw_response_full
# ---------------------------------------------------------------------------
class ReasoningTrace(TraceLogger):
    def __init__(self, path: Path, task_id: str) -> None:
        super().__init__(path, task_id)
        self._seq = 0
        self._last_llm_seq = None
        self.llm_count = 0
        self.reasoning_count = 0

    def _write(self, record: dict) -> None:
        record["seq"] = self._seq
        self._seq += 1
        super()._write(record)

    def log_meta(self, model: str) -> None:
        self._write(
            {
                "type": "meta",
                "schema_version": 1,
                "task_id": self._task_id,
                "model": model,
                "dependency_model": (
                    "Records ordered by `seq`. llm_call carries `cycle`+`phase`: "
                    "cycle 0 = pre-phase (DOC_SELECT/rerank) + INTENT (frozen); "
                    "cycle N = PLAN/LEARN of interpreter cycle N. `prev_llm_seq` "
                    "chains llm_calls. A PLAN user_msg at cycle N embeds "
                    "PREVIOUS_ERROR + OBSERVED_RPC_OUTPUTS from cycle N-1 (the "
                    "request<-answer data dependency). `reasoning` = model "
                    "chain-of-thought when the provider exposes it; "
                    "`raw_response_full` = un-stripped assistant content."
                ),
            }
        )

    def log_llm_call(
        self,
        phase: str,
        cycle: int,
        system,
        user_msg: str,
        raw_response: str,
        parsed_output,
        tokens_in: int,
        tokens_out: int,
        duration_ms: int,
    ) -> None:
        sha = self._ensure_header_system(system)
        cap = _pop()
        reasoning = cap.get("reasoning", "")
        raw_full = cap.get("raw_full", "")
        avail = bool(reasoning)
        self.llm_count += 1
        if avail:
            self.reasoning_count += 1
        rec = {
            "type": "llm_call",
            "cycle": cycle,
            "phase": phase,
            "prev_llm_seq": self._last_llm_seq,
            "system_sha256": sha,
            "user_msg": user_msg,
            "reasoning": reasoning,
            "reasoning_available": avail,
            "raw_response": raw_response,
            "raw_response_full": raw_full,
            "parsed_output": parsed_output,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "duration_ms": duration_ms,
            "success": parsed_output is not None or bool(raw_response),
        }
        self._last_llm_seq = self._seq  # seq this record will receive in _write
        self._write(rec)


# ---------------------------------------------------------------------------
# Readable companion: interleave system / user / reasoning / response per call
# ---------------------------------------------------------------------------
def render_reasoning_md(records: list[dict]) -> str:
    out: list[str] = []
    seen_sys: set[str] = set()
    systems = {
        r["sha256"]: r.get("blocks")
        for r in records
        if r.get("type") == "header_system"
    }

    def sys_text(sha: str) -> str:
        blocks = systems.get(sha) or []
        if isinstance(blocks, str):
            return blocks
        return "\n".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in blocks
        )

    for r in records:
        t = r.get("type")
        if t == "meta":
            out.append(f"# Trace — {r.get('task_id')} · model={r.get('model')}")
            out.append("")
            out.append(f"> {r.get('dependency_model', '')}")
            out.append("")
        elif t == "header":
            out.append(f"## TASK {r.get('task_id')} · model={r.get('model')}")
            out.append("")
            out.append("**Instruction:**")
            out.append("")
            out.append("```")
            out.append(r.get("task_text", ""))
            out.append("```")
            out.append("")
        elif t == "facts":
            gs = json.dumps(r.get("gather_status") or {}, ensure_ascii=False)
            inv = [p for p in (r.get("docs_inventory") or "").splitlines() if p]
            out.append(f"### PRE-PHASE FACTS  (gather_status={gs}, docs={len(inv)})")
            out.append("")
        elif t == "llm_call":
            sha = r.get("system_sha256", "")
            prev = r.get("prev_llm_seq")
            avail = "yes" if r.get("reasoning_available") else "no"
            out.append("---")
            out.append(
                f"### seq {r.get('seq')} · cycle {r.get('cycle')} · "
                f"{r.get('phase')} · {r.get('duration_ms', 0)}ms · "
                f"tok {r.get('tokens_in', 0)}/{r.get('tokens_out', 0)} · "
                f"reasoning={avail} · prev_llm_seq={prev}"
            )
            out.append("")
            if sha not in seen_sys:
                seen_sys.add(sha)
                out.append(f"<details><summary>SYSTEM ({sha[:8]})</summary>")
                out.append("")
                out.append("```")
                out.append(sys_text(sha))
                out.append("```")
                out.append("")
                out.append("</details>")
                out.append("")
            else:
                out.append(f"*SYSTEM ({sha[:8]}) — same as a prior call*")
                out.append("")
            out.append("**USER (request):**")
            out.append("")
            out.append("```")
            out.append(r.get("user_msg", ""))
            out.append("```")
            out.append("")
            if r.get("reasoning"):
                out.append("**REASONING (chain-of-thought):**")
                out.append("")
                out.append("```")
                out.append(r.get("reasoning", ""))
                out.append("```")
                out.append("")
            out.append("**ASSISTANT (response):**")
            out.append("")
            out.append("```")
            out.append(r.get("raw_response", ""))
            out.append("```")
            out.append("")
        elif t == "vm_call":
            a = r.get("args") or {}
            loc = a.get("path") or a.get("root") or a.get("pattern") or ""
            head = (r.get("result_head") or "").strip().splitlines()
            first = head[0] if head else "<empty>"
            mut = " [MUTATED]" if r.get("mutated") else ""
            out.append(f"- `[{r.get('rpc')} {loc}]{mut}` -> {first}")
        elif t == "answer":
            out.append("")
            out.append(f"### ANSWER (cycle {r.get('cycle')}) — {r.get('outcome')}")
            out.append(f"- message: {r.get('message')!r}")
            out.append(f"- refs: {r.get('refs')!r}")
            out.append("")
        elif t == "task_result":
            out.append("---")
            out.append(
                f"## RESULT — {r.get('outcome')} · score={r.get('score')} · "
                f"cycles={r.get('cycles_used')} · "
                f"tok {r.get('total_tokens_in')}/{r.get('total_tokens_out')} · "
                f"{r.get('elapsed_ms')}ms"
            )
            for line in r.get("score_detail") or []:
                out.append(f"- {line}")
            out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Harness flow — StartRun, find the target trial, run it, SubmitRun for score
# ---------------------------------------------------------------------------
def main() -> None:
    safe = MODEL.replace("/", "-").replace(":", "-")
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = _REPO_ROOT / "logs" / f"trace_{TASK}_{ts}_{safe}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[trace] task={TASK} model={MODEL} cc_mode={_IS_CC}")
    print(f"[trace] benchmark={BENCHMARK_ID} host={BITGN_URL}")
    print(f"[trace] out_dir={run_dir}")

    client = HarnessServiceClientSync(BITGN_URL)
    print("[trace] status:", client.status(StatusRequest()))

    run = client.start_run(
        StartRunRequest(name=RUN_NAME, benchmark_id=BENCHMARK_ID, api_key=BITGN_API_KEY)
    )
    print(f"[trace] run_id={run.run_id} ({len(run.trial_ids)} trials) — locating {TASK}")

    target = None
    for tid in run.trial_ids:
        trial = client.start_trial(StartTrialRequest(trial_id=tid))
        if trial.task_id == TASK and target is None:
            target = trial  # keep open; run below
        else:
            # release every non-target trial immediately (mirrors main.py filter)
            client.end_trial(EndTrialRequest(trial_id=trial.trial_id))

    if target is None:
        print(f"[trace] ERROR: task {TASK} not present in benchmark {BENCHMARK_ID}")
        client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))
        sys.exit(2)

    trace = ReasoningTrace(run_dir / f"{TASK}.jsonl", TASK)
    set_trace(trace)
    trace.log_meta(MODEL)
    trace.log_header(target.instruction, model=MODEL)
    print(f"\n{'=' * 30} {TASK} {'=' * 30}\n{target.instruction}\n{'-' * 72}")

    t0 = time.time()
    token_stats: dict = {}
    try:
        token_stats = run_agent({}, target.harness_url, target.instruction, task_id=TASK)
    except Exception as exc:  # never lose the partial trace
        print(f"[trace] run_agent error: {exc}")
    elapsed = time.time() - t0
    client.end_trial(EndTrialRequest(trial_id=target.trial_id))

    print(f"\n{'=' * 30} SubmitRun {'=' * 30}")
    result = client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))

    score = 0.0
    detail: list[str] = []
    state_done = False
    for tr in result.trials:
        if tr.task_id == TASK:
            score = float(tr.score) if tr.score_available else 0.0
            detail = list(tr.score_detail)
            state_done = tr.state == TRIAL_STATE_DONE
            break

    trace.log_task_result(
        outcome=token_stats.get("outcome", ""),
        score=score,
        cycles=token_stats.get("cycles_used", 0),
        total_in=token_stats.get("input_tokens", 0),
        total_out=token_stats.get("output_tokens", 0),
        elapsed_ms=int(elapsed * 1000),
        score_detail=detail,
    )
    trace.close()
    set_trace(None)

    # readable companion from the final record set
    records = [
        json.loads(ln)
        for ln in (run_dir / f"{TASK}.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    (run_dir / f"{TASK}.reasoning.md").write_text(
        render_reasoning_md(records), encoding="utf-8"
    )

    # summary
    print(f"\n{'=' * 72}")
    print(f"[trace] DONE  task={TASK}  score={score:.2f}  done={state_done}")
    print(
        f"[trace] outcome={token_stats.get('outcome', '')}  "
        f"cycles={token_stats.get('cycles_used', 0)}  "
        f"tok in={token_stats.get('input_tokens', 0):,} "
        f"out={token_stats.get('output_tokens', 0):,}  "
        f"elapsed={elapsed:.1f}s"
    )
    print(
        f"[trace] llm_calls={trace.llm_count}  "
        f"with_reasoning={trace.reasoning_count}  "
        f"records={len(records)}"
    )
    if detail:
        print("[trace] score_detail:")
        for d in detail:
            print(f"  - {d}")
    print(f"[trace] jsonl      : {run_dir / f'{TASK}.jsonl'}")
    print(f"[trace] detail.log : {run_dir / f'{TASK}.detail.log'}")
    print(f"[trace] reasoning  : {run_dir / f'{TASK}.reasoning.md'}")


if __name__ == "__main__":
    main()
