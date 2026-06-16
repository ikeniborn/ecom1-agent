# Agent Architecture Guide

Dense, reference-style companion to `agent-architecture.excalidraw`. One section
per diagram region on the canvas, plus a shape legend and a module map. Audience:
project developers who already know the domain. References are `path:line` into
the working tree; regenerate the canvas with `uv run python tools/gen_excalidraw.py`
when the architecture changes.

> **IR-only pipeline.** The legacy DESIGN→CODEGEN loop and the `INTERPRETER_ENABLED`
> fork were removed; `run_pipeline` is now a single deterministic-interpreter path:
> INTENT → (PLAN → lint → interpret → verify) loop → one `vm.answer`.

## Overview

Each benchmark task runs `main.py` harness → `agent/orchestrator.py:run_agent`
→ `agent/pipeline.py:run_pipeline`. The pipeline freezes one `IntentSpec`, then
loops `run_plan → lint_security_first → interpret → verify` up to
`INTERPRETER_MAX_STEPS` times, distilling a LEARN rule between failed cycles, and
calls `vm.answer` exactly once. LLM-call budget per task: **INTENT 1** (frozen,
retried only on transient parse failure) + **PLAN 1 per cycle** (× up to
`INTERPRETER_MAX_STEPS`, default 6) + **`_ilearn` 1 per failed cycle**; **+1** oracle
re-rank when `ORACLE_RANK_ENABLED=1`; **+1** distill on success. `interpret()` and
`verify()` are 0-LLM. Best path ≈ **2** (INTENT + PLAN); worst ≈ INTENT + 6×(PLAN + LEARN).

## Diagram 1 — End-to-end flow (harness → pipeline)

The harness drives a `StartRun → StartTrial → SubmitRun → EndTrial` cycle; the
`TRAIN_MAX_CYCLES` outer training loop feeds grader feedback back through
`learn_from_grader` (dashed edge). The orchestrator opens the VM, reads
`/AGENTS.MD`, and gathers pre-phase facts (schema, sample rows, docs inventory,
learned deep-read paths) before dispatching the IR-only pipeline.

- `main.py:286` — `main()` entry; training loop at `main.py:306`, `TRAIN_MAX_CYCLES` at `main.py:109`
- `main.py:240` — `_run_one_pass`: `StartRun` at `main.py:245`, `StartTrial` at `main.py:137`, `SubmitRun` at `main.py:280`, `EndTrial` at `main.py:141`
- `main.py:326` — `learn_from_grader` call between cycles
- `agent/orchestrator.py:548` — `run_agent`; reads `/AGENTS.MD` via `_read_agents_md` at `agent/orchestrator.py:20`
- `agent/orchestrator.py:393` — `gather_prephase_facts`
- `agent/orchestrator.py:112` — `_discover_schema`; sample rows at `agent/orchestrator.py:130`; relevance gate at `agent/orchestrator.py:153`
- `agent/orchestrator.py:404` — learned `prephase_deep_read` load; docs inventory at `agent/orchestrator.py:440`
- `agent/pipeline.py:214` — `run_pipeline` (IR-only; no `INTERPRETER_ENABLED` fork)

## Diagram 2 — IR pipeline cycle + gates

`INTENT` (`run_intent`) is a single frozen call, retried only on transient
parse/empty failures. The loop (`cycle = 1..INTERPRETER_MAX_STEPS`) runs `run_plan`
(seeing `learn_ctx` + retrieved atoms + last cycle's observed RPC output), lints it
security-first, short-circuits to `OUTCOME_NONE_CLARIFICATION` on an identical
repeated plan (no progress), runs the deterministic `interpret()`, then `verify()`.
On pass it calls `vm.answer` once (carrying the plan-chosen outcome) and persists +
distils. Plan/lint errors, interpret errors, and verify failures each route through
`_ilearn` (dashed) into the next cycle; exhausting the cycles ends in
`OUTCOME_NONE_CLARIFICATION`.

- `agent/pipeline.py:244` — INTENT, frozen + retried (`run_intent` call at `agent/pipeline.py:247`)
- `agent/pipeline.py:260` — the `INTERPRETER_MAX_STEPS` cycle loop
- `agent/pipeline.py:266` — `run_plan` (with `learn_ctx`, `oracle_atoms`, `observed`)
- `agent/pipeline.py:269` — `lint_security_first`
- `agent/pipeline.py:277` — identical-plan short-circuit (`_plan_signature` at `agent/pipeline.py:29`)
- `agent/pipeline.py:284` — `interpret`; `agent/pipeline.py:308` — `verify`
- `agent/pipeline.py:312` — the single `vm.answer`; persist at `agent/pipeline.py:313`, distill at `agent/pipeline.py:314`
- `agent/pipeline.py:155` — `_ilearn` (LEARN between cycles); `agent/pipeline.py:330` — terminal `_terminal_clarification`
- `agent/reason.py:60` — `run_intent`; `agent/reason.py:77` — `run_plan`

## Diagram 3 — `interpret()` + `verify()` internals

Zoom into one cycle's deterministic core (0 LLM). `interpret()` consumes a
`PlanIR`: it resolves column aliases, runs the steps + VM RPC ops, classifies the
outcome from the exit spec, projects the required refs for that outcome, and emits a
`CapturedAnswer`. An unresolved required ref on an `OUTCOME_OK` answer refuses
inside `interpret()`. `verify()` then re-checks invariants (I1 ref-grounding, I3
independent security re-check) plus the `IntentSpec.success_criteria`.

- `agent/interpreter.py:209` — `interpret`
- `agent/interpreter.py:80` — `_classify_from_exit` (uses `OutcomeFromExit`, `agent/ir_models.py:141`)
- `agent/interpreter.py:122` — `_project_required_refs`; `agent/interpreter.py:144` — `_refuse`
- `agent/interpreter.py:53` — `CapturedAnswer`; `agent/interpreter.py:191` — `lint_security_first`
- `agent/verify.py:12` — `verify` (I1/I3 + success_criteria)
- `agent/ir_models.py:171` — `PlanIR`; `agent/ir_models.py:81` — `IntentSpec`; `agent/ir_models.py:108` — `RowSet`; `agent/ir_models.py:116` — `ComputeStep`

## Diagram 4 — Cross-cutting subsystems

- **LEARN / learned_store** → `data/learned/{tid}.yaml` (active rules + `prephase_deep_read` + `last_run`): `agent/pipeline.py:155` `_ilearn`; `agent/learned_store.py:64` `load_entries`, `agent/learned_store.py:79` `apply_learn_diff`, `agent/learned_store.py:113` `save_last_run`, `agent/learned_store.py:147` `load_prephase_deep_read`
- **Knowledge oracle** (`agent/oracle.py:90` `retrieve`): cosine top-N at `agent/oracle.py:63` → LLM re-rank (`agent/oracle_rank.py:15`) → K atoms into PLAN; on success the validated plan distils a new atom back into the bank (`agent/oracle.py:122` `distill`, validated by `agent/oracle_validate.py:55`, promoted at `agent/oracle.py:137`); bank at `data/oracle/atoms.yaml`. Wired from `agent/pipeline.py:187` `_maybe_distill_and_validate`.
- **LLM routing** (`agent/llm.py:560` `call_llm_raw`): tiers anthropic / openrouter / ollama / claude-code (`agent/llm.py:300`) with `MODEL_FALLBACK` (`agent/llm.py:280`), driven by `models.json`; trace JSONL via `agent/trace.py:43` `TraceLogger` (`agent/trace.py:90` `log_llm_call`)

## Legend

| Shape / color | Meaning |
|---------------|---------|
| Blue rectangle | LLM call (INTENT / PLAN / LEARN / oracle re-rank / distill) |
| Grey rectangle | Deterministic step / gate (lint, interpret, verify) |
| Green ellipse | Storage (yaml / json / atoms) — the spec's "cylinder", rendered as a single-primitive ellipse |
| Yellow diamond | Branch / condition |
| Red rounded rectangle | Terminal outcome |
| Solid arrow | Control flow |
| Dashed arrow | Feedback / learning (LEARN, training loop, distill write-back) |

## Where to change what

| Module | Responsibility |
|--------|----------------|
| `main.py` | Harness driver; training loop (`TRAIN_MAX_CYCLES`) |
| `agent/orchestrator.py` | VM open, `/AGENTS.MD` read, pre-phase fact gathering |
| `agent/pipeline.py` | IR-only `run_pipeline` (INTENT → PLAN/lint/interpret/verify loop), `_ilearn`, distill wiring, `learn_from_grader` |
| `agent/reason.py` | INTENT + PLAN LLM phases (emit `IntentSpec` / `PlanIR`, never code) |
| `agent/interpreter.py` | Deterministic `interpret()` + `lint_security_first` |
| `agent/verify.py` | Deterministic VERIFY (I1/I3 invariants + success_criteria) |
| `agent/ir_models.py` | Plan-IR data model (`IntentSpec`, `PlanIR`, `Step`, `RowSet`, …) |
| `agent/oracle.py` + `agent/oracle_rank.py` + `agent/oracle_validate.py` | Atom retrieval (cosine → re-rank → inject) + distill→validate→promote |
| `agent/learned_store.py` | Per-task learned rules + `prephase_deep_read` + `last_run` |
| `agent/llm.py` + `agent/trace.py` + `models.json` | Provider routing, fallback, JSONL traces |
| `data/prompts/*.md` | Phase guides (general structural rules only — never task-specific) |
