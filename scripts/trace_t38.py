#!/usr/bin/env python3
"""Full prompt + reasoning trace for a single benchmark task (default: t38).

Runs ONE task through the real pipeline (orchestrator -> run_pipeline) against a
live benchmark trial, and records a structured JSONL trace that — beyond the
built-in agent.trace records — also captures the model's chain-of-thought
reasoning and the un-stripped raw response per LLM call.

Reasoning capture is handled by the production machinery in agent/reasoning_capture.py
(active when ECOM_TRACE_REASONING=1, set below). TraceLogger natively stamps
seq / prev_llm_seq / reasoning / raw_response_full on every llm_call record.

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
import sys
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
os.environ.setdefault("ECOM_TRACE_REASONING", "1")  # prod reasoning capture (B2)

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
import agent.llm as _llm_init  # noqa: E402,F401  triggers env load + reasoning-capture install
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

    trace = TraceLogger(run_dir / f"{TASK}.jsonl", TASK)
    set_trace(trace)
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
    llm_records = [r for r in records if r.get("type") == "llm_call"]
    reasoning_records = [r for r in llm_records if r.get("reasoning_available")]
    print(
        f"[trace] llm_calls={len(llm_records)}  "
        f"with_reasoning={len(reasoning_records)}  "
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
