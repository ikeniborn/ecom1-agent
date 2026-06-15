# Agent Architecture Guide

Dense, reference-style companion to `agent-architecture.excalidraw`. One section
per diagram region on the canvas, plus a shape legend and a module map. Audience:
project developers who already know the domain. References are `path:line` into
the working tree; regenerate the canvas with `uv run python tools/gen_excalidraw.py`
when the architecture changes.

## Overview

Each benchmark task runs `main.py` harness → `agent/orchestrator.py:run_agent`
→ `agent/pipeline.py:run_pipeline`, which forks on `INTERPRETER_ENABLED` between
the legacy DESIGN→CODEGEN loop (Diagram 2) and the deterministic Plan-IR
interpreter (Diagram 3). LLM-call budget per task: **1** (hard-stop), **2** (best
happy path), **7** (worst, `MAX_STEPS=3`) (the knowledge oracle's re-rank adds +1 when `ORACLE_RANK_ENABLED=1`, the default).

## Diagram 1 — End-to-end flow (harness → pipeline)

The harness drives a `StartRun → trials-loop → SubmitRun → EndTrial` cycle; the
`TRAIN_MAX_CYCLES` outer training loop feeds grader feedback back through
`learn_from_grader` (dashed edge). The orchestrator opens the VM, reads
`/AGENTS.MD`, and gathers pre-phase facts (schema, sample rows, docs inventory,
learned deep-read paths) before dispatching the pipeline.

- `main.py:286` — `main()` entry; training loop at `main.py:306`, `TRAIN_MAX_CYCLES` at `main.py:109`
- `main.py:241` — `run_once`: `StartRun` at `main.py:245`, `SubmitRun` at `main.py:280`, `EndTrial` at `main.py:141`
- `main.py:326` — `learn_from_grader` call between cycles
- `agent/orchestrator.py:548` — `run_agent`; reads `/AGENTS.MD` at `agent/orchestrator.py:21`
- `agent/orchestrator.py:393` — `gather_prephase_facts`
- `agent/orchestrator.py:112` — `_discover_schema`; sample rows at `agent/orchestrator.py:130`; relevance gate at `agent/orchestrator.py:153`
- `agent/orchestrator.py:404` — learned `prephase_deep_read` load; docs inventory at `agent/orchestrator.py:440`
- `agent/pipeline.py:928` — `run_pipeline`; branch on `INTERPRETER_ENABLED` at `agent/pipeline.py:943`

## Diagram 2 — Pipeline loop + gates (legacy, default branch)

`DESIGN` is a single frozen LLM call; `outcome_override` short-circuits to a
terminal answer. The loop (`cycle = 1..MAX_STEPS`) runs CODEGEN, then three gates
— AST lint, `check_retry_loop`, fidelity (subprocess) — before the terminal
`ANSWER` one-shot via `_AnswerGuard`. Gate failures route through
`LEARN + CONSOLIDATE` (dashed) into the next cycle. The ANSWER script can emit any of the four outcomes (OUTCOME_OK / NONE_CLARIFICATION / NONE_UNSUPPORTED / DENIED_SECURITY); an `outcome_override` short-circuits to one of the three non-OK outcomes.

- `agent/pipeline.py:984` — DESIGN call; `outcome_override` exit at `agent/pipeline.py:1008`
- `agent/pipeline.py:1052` — CODEGEN + ANSWER retry loop (`MAX_STEPS` counter)
- `agent/pipeline.py:1073` — AST lint (`ast.parse`)
- `agent/pipeline.py:1096` — `check_retry_loop` break
- `agent/pipeline.py:1102` — `generate_fidelity_test`; subprocess exec at `agent/pipeline.py:1103`
- `agent/fidelity.py:52` — `generate_fidelity_test`; `agent/fidelity.py:90` — `exec_fidelity_in_subprocess`
- `agent/pipeline.py:676` — `_AnswerGuard` terminal one-shot proxy
- `agent/pipeline.py:271` — `_learn_consolidate` (LEARN + CONSOLIDATE)

## Diagram 3 — Deterministic interpreter (INTERPRETER_ENABLED)

The interpreter branch emits *data*, not code: `run_intent` → `run_plan` build a
`PlanIR`, which is linted security-first and then executed by a deterministic
`interpret()` (no LLM inside the loop). The result is a `CapturedAnswer` the
pipeline submits after `verify()`; its outcome is plan-driven and can be any of
the four terminal outcomes.

- `agent/pipeline.py:338` — `_run_interpreted`; dispatched from `agent/pipeline.py:944`
- `agent/reason.py:60` — `run_intent`; `agent/reason.py:77` — `run_plan`
- `agent/ir_models.py:81` — `IntentSpec`; `agent/ir_models.py:171` — `PlanIR`
- `agent/interpreter.py:191` — `lint_security_first`
- `agent/interpreter.py:209` — `interpret`; `agent/interpreter.py:53` — `CapturedAnswer`
- `agent/verify.py:12` — `verify` (independent re-check of the CapturedAnswer before submit)

## Diagram 4 — Cross-cutting subsystems

- **LEARN / learned_store** → `data/learned/{tid}.yaml` (active rules + `prephase_deep_read` + `last_run`): `agent/learned_store.py:64` `load_entries`, `agent/learned_store.py:79` `apply_learn_diff`, `agent/learned_store.py:113` `save_last_run`, `agent/learned_store.py:147` `load_prephase_deep_read`
- **Knowledge oracle** (`agent/oracle.py:90` `retrieve`): cosine top-N at `agent/oracle.py:63` → LLM re-rank → K atoms injected into CODEGEN; bank at `data/oracle/atoms.yaml`
- **LLM routing** (`agent/llm.py:529` `call_llm_raw`): tiers anthropic / openrouter / ollama / claude-code with `MODEL_FALLBACK` (`agent/llm.py:250`), driven by `models.json`; trace JSONL via `agent/trace.py:43` `TraceLogger` (`agent/trace.py:90` `log_llm_call`)

## Legend

| Shape / color | Meaning |
|---------------|---------|
| Blue rectangle | LLM call (DESIGN / CODEGEN / LEARN / oracle re-rank) |
| Grey rectangle | Deterministic step / gate (AST lint, retry-guard, fidelity, interpret) |
| Green ellipse | Storage (yaml / json / atoms) — the spec's "cylinder", rendered as a single-primitive ellipse |
| Yellow diamond | Branch / condition |
| Red rounded rectangle | Terminal outcome |
| Solid arrow | Control flow |
| Dashed arrow | Feedback / learning (LEARN, training loop) |

## Where to change what

| Module | Responsibility |
|--------|----------------|
| `main.py` | Harness driver; training loop (`TRAIN_MAX_CYCLES`) |
| `agent/orchestrator.py` | VM open, `/AGENTS.MD` read, pre-phase fact gathering |
| `agent/pipeline.py` | DESIGN, CODEGEN loop + gates, `_AnswerGuard`, interpreter dispatch, `learn_from_grader` |
| `agent/reason.py` + `agent/ir_models.py` + `agent/interpreter.py` | Plan-IR branch (INTENT/PLAN → lint → interpret) |
| `agent/fidelity.py` | Fidelity gate test generation + subprocess exec |
| `agent/learned_store.py` | Per-task learned rules + `prephase_deep_read` + `last_run` |
| `agent/oracle.py` | Knowledge-atom retrieval (cosine → re-rank → inject) |
| `agent/llm.py` + `agent/trace.py` + `models.json` | Provider routing, fallback, JSONL traces |
| `data/prompts/*.md` | Phase guides (general structural rules only — never task-specific) |
