# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                          # install all deps
uv run python main.py                            # run all benchmark tasks
make task TASKS='t01,t03'                        # run specific tasks

uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline_interpreted.py -v      # single file
uv run pytest tests/test_pipeline_interpreted.py::test_name -v  # single test

make proto                                       # rebuild protobuf stubs (requires buf)
```

## Environment Variables

Copy `.env.example` → `.env` (single source for config AND credentials; gitignored via `**/.env`). Core vars:

| Var | Purpose |
|-----|---------|
| `ECOM_MODEL` | Primary LLM (`anthropic/claude-sonnet-4-6`, `openrouter/…`, `ollama/…`, or bare Ollama name) |
| `ECOM_MODEL_FALLBACK` | Fallback model after primary exhausts all tiers |
| `ECOM_MODEL_REASON` | Reason-tier model (INTENT/PLAN/iLEARN/distill). **Catch-all** for any phase not explicitly fast-tier — including unlisted phases. Defaults to `ECOM_MODEL`. |
| `ECOM_MODEL_FAST` | Fast-tier model (DOC_SELECT/oracle rerank). Defaults to `ECOM_MODEL`. |
| `ECOM_MODEL_LEARN` | Per-phase override for LEARN (defaults to its tier → `ECOM_MODEL`) |
| `ECOM_MAX_TOKENS_INTENT` | Max tokens for INTENT phase response (default 4096) |
| `ECOM_MAX_TOKENS_PLAN` | Max tokens for PLAN phase response (default 8192) |
| `ECOM_MAX_TOKENS_LEARN` | Max tokens for LEARN/iLEARN phase response (default 2048) |
| `ECOM_LEARN_MAX_ACTIVE` | Cap on **active content-rules per task** in `data/learned/{tid}.yaml` (default 3). `apply_learn_diff` deactivates the oldest UNPINNED rules beyond the cap; a rule with `pinned: true` is exempt. Guards against iLEARN re-bloat (one rule appended per failing cycle → rule-overload → PLAN non-convergence). |
| `ECOM_INTERPRETER_MAX_STEPS` | Plan-IR interpreter cycle ceiling (default 6) |
| `ECOM_LOG_LEVEL=DEBUG` | Full LLM response logging |
| `ECOM_OLLAMA_BASE_URL` | Ollama endpoint (default `http://localhost:11434/v1`) |
| `ECOM_CC_ENABLED=1` | Enable Claude Code CLI tier (iclaude subprocess, OAuth) |
| `ECOM_LLM_HTTP_READ_TIMEOUT_S` | HTTP read timeout in seconds (default 180) |
| `ECOM_TRAIN_MAX_CYCLES` | Per-task training cycles (default 1 = no training). Each cycle is a fresh `StartRun → SubmitRun`; failing tasks (score < 1.0) get a LEARN rule distilled from grader feedback via `pipeline.learn_from_grader`, then re-run next cycle. Loop exits early when all targeted tasks reach score ≥ 1.0. |
| `ECOM_ORACLE_ENABLED` | Knowledge-oracle master toggle; `0` → pipeline behaves as before (default 1) |
| `ECOM_MODEL_EMBED` | Embedding model id for oracle retrieval (key into `models.json`, default `nomic-embed-text`); endpoint is `ECOM_OLLAMA_BASE_URL` |
| `ECOM_ORACLE_TOPN` | Stage-1 cosine candidate count (default 10) |
| `ECOM_ORACLE_K` | Final atoms injected into PLAN after re-rank (default 4) |
| `ECOM_ORACLE_FLOOR` | Minimum cosine similarity for a retrieved atom to be injected; below-floor atoms discarded (default 0.5) |
| `ECOM_MODEL_RANK` | Model for stage-2 re-rank; falls back to `ECOM_MODEL` |
| `ECOM_ORACLE_RANK_ENABLED` | `0` → skip LLM re-rank, use cosine top-k (default 1) |
| `ECOM_ORACLE_DEDUP_COSINE` | Cosine ≥ this ⇒ two atoms are duplicates (default 0.92). Used by `oracle.prune()` (collapse near-duplicate active atoms; drop unvalidated candidates) and `add_candidate` dedup-on-insert (anti-rebloat). Lower → more aggressive collapse. |
| `ECOM_PREPHASE_PATH_LITERALS` | Cap on path literals extracted from the instruction text (default 3); learned deep-read paths are probed in addition |
| `ECOM_PREPHASE_LISTING_BYTES` | Byte cap on a rendered dir listing; overflow → `… +N skipped` (default 4096) |
| `ECOM_PREPHASE_SAMPLE_ROWS` | `LIMIT` per sampled table — Tier-2 (default 3) |
| `ECOM_PREPHASE_SAMPLE_ROW_CHARS` | Per-row byte cap — Tier-2 safety rail (default 400) |
| `ECOM_INVESTIGATE_ENABLED` | Master toggle for the read-only INVESTIGATE phase. `1` (default) → slim pre-phase seed (identity + schema names + doc paths only) + step-wise investigator builds the PLAN brief; `0` → eager pre-phase gather + legacy whole-instruction oracle dump, investigator skipped (exact pre-feature baseline). |
| `ECOM_INVESTIGATE_MAX_STEPS` | Step budget for the investigator ReAct loop (default 6). |
| `ECOM_INVESTIGATE_ORACLE_K` | Oracle atoms retrieved per investigator step, scoped to the step goal (default 2). |
| `ECOM_MODEL_INVESTIGATE` | Per-phase model override for INVESTIGATE (defaults to its tier → `ECOM_MODEL_FAST`). Router/digest steps run on the FAST tier and escalate to REASON on a deterministic stall. |

Credentials (`ECOM_ANTHROPIC_API_KEY`, `ECOM_OPENROUTER_API_KEY`, `ECOM_OLLAMA_API_KEY`, `ECOM_BITGN_API_KEY`) live in `.env` (single source; gitignored). There is no separate `.secrets` file. The agent reads `ECOM_`-prefixed keys ONLY — a stray system `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` can never leak into a call.

**Model-tier resolution** (`llm.py:_resolve_model_for_phase`): per phase, `ECOM_MODEL_<PHASE>` → tier env (`ECOM_MODEL_REASON` / `ECOM_MODEL_FAST` / `ECOM_MODEL_EMBED`) → `ECOM_MODEL`. Reason-tier phases (INTENT, PLAN, iLEARN, distill) map to `ECOM_MODEL_REASON`; fast-tier phases (DOC_SELECT, oracle rerank, INVESTIGATE) to `ECOM_MODEL_FAST`; embeddings to `ECOM_MODEL_EMBED`. **`ECOM_MODEL_REASON` is the catch-all** — any phase not explicitly fast-tier, including unlisted phases, resolves through it. With only `ECOM_MODEL` set, every phase resolves to `ECOM_MODEL` (back-compatible). The reason tier requests `think=on`; the fast tier `think=off`. INVESTIGATE router/digest steps run on the fast tier and escalate to the reason tier (`think=on`) on a deterministic stall (empty result or repeated tool signature).

## Architecture

Entry point: `main.py` → BitGN harness → `agent/orchestrator.py:run_agent()`

There is **one** pipeline: the deterministic Plan-IR interpreter. Per task — INTENT → INVESTIGATE (read-only ReAct → Brief) → loop[PLAN(brief) → lint → interpret → ground-refs → verify → answer-once] → CLARIFICATION. No DESIGN, CODEGEN, fidelity, or TEST-GEN; the quality gate is `verify()` (deterministic, no LLM).

**Execution flow per task:**
1. `orchestrator.py:run_agent()` — opens VM, reads `/AGENTS.MD` directly, gathers pre-phase facts. When `ECOM_INVESTIGATE_ENABLED=1` (default): slim seed only (identity + schema names + doc paths; no bodies/samples/listings/records). When `=0`: eager gather (DOC_SELECT [fast tier] + schema + identity + listings) exactly as before. Calls `run_pipeline`.
2. `pipeline.py:run_pipeline(vm, instruction, task_id, agents_md_text, facts)`:
   - **INTENT** (`reason.py:run_intent`, reason tier) — 1 LLM call, frozen for the run, retried on transient empty/parse failure (`ECOM_DESIGN_MAX_ATTEMPTS`). Input `[facts, instruction, learn_ctx]` — INTENT receives the same active learned rules PLAN does, so a learned rule can shape `required_refs`/`success_criteria`/`outcome_space` (the channel for making a missing grounding ref learnable). Output: `IntentSpec` (`objective`, `desired_outcome`, `params`, `outcome_space`, `constraints`, `success_criteria`, `answer_shape`, `required_refs`). On hard failure → terminal `OUTCOME_NONE_CLARIFICATION`.
   - **INVESTIGATE** (`investigate.py`, fast tier, `ECOM_INVESTIGATE_ENABLED=1`) — called ONCE after INTENT and before the loop: `investigate(vm, intent, seed=facts, oracle=...)`. Runs a bounded read-only ReAct loop (up to `ECOM_INVESTIGATE_MAX_STEPS` steps) fetching doc bodies, listings, and table samples on demand. All steps are read-only (`investigate.is_readonly` gate; mutations stay in the plan's `ops`). Stops on sufficiency (every `intent.required_refs` for the desired outcome groundable from `env`) or step budget. Escalates from fast to reason tier on a deterministic stall (empty result or repeated tool signature). Per-step errors become lessons; pipeline falls back to the slim seed on hard failure. Returns a compact `Brief` (step-notes + bound `env`); `render_brief(brief)` is threaded into every PLAN cycle via `run_plan(..., brief_block=...)`. On a successful run, the investigator's step-lessons enrich the distill note (`pipeline._brief_lessons_text`) fed into the existing `_maybe_distill_and_validate` path. When `ECOM_INVESTIGATE_ENABLED=0`, this step is skipped and the pipeline restores the legacy whole-instruction oracle dump.
   - **LOOP** — `cycle = 1..INTERPRETER_MAX_STEPS`:
     - **PLAN** (`reason.py:run_plan`, reason tier) — LLM call; input `[intent, brief_block, learn_ctx, prev_error?, oracle_atoms, observed?]`. Output: `PlanIR` (`discovery`, `rowsets`, `compute`, `decision`, `ops`, `answer`, `custom_extract`).
     - **lint** — `interpreter.lint_security_first(plan)` (no LLM). On `PlanError`/`InterpretError` → `_ilearn` → next cycle.
     - **plan-signature short-circuit** — `_plan_signature(plan)` over discovery+ops (SQL normalised, other args verbatim); identical to prior cycle → break with CLARIFICATION (no-progress guard).
     - **interpret** — `interpreter.interpret(plan, intent, vm, facts)` (no LLM) executes the plan against the VM. `InterpretError` → `_ilearn` → retry (break if a mutation landed); a real-VM `Exception` → `_ilearn`, then retry only when the plan is read-only AND the error is retryable (`_is_retryable_vm_error`), else break.
     - **ground-refs** — `grounding.ground_refs(intent, result.captured, result, vm, instruction, docs_read=brief.env["docs_read"])` (no LLM, best-effort, never raises) re-derives the authoritative reference set from the VM + task text + computed answer and **overwrites** `result.captured.refs` before verify. Record refs: entity-token → evidence-scan/`find`/generic-SQL-fallback → `stat`-validate, with a conservative cross-customer ownership guard. Doc refs: the `/docs/*.md` the investigator read (`docs_read`), narrowed by a recall-preserving relies-on filter and case-corrected. The model's declared refs become hints; code produces the enforced set (`agent/grounding.py`).
     - **verify** — `verify.verify(result, intent)` (no LLM, deterministic) checks `success_criteria`/refs. I1 is presence-based on **every** outcome: each resolved `intent.required_refs[outcome]` value must be ⊆ `answer.refs`, plus a `$`-ref guard on all outcomes. Pass → `vm.answer(...)` once, `_persist_artifacts`, return. Fail → `_ilearn` (with observed RPC outputs) → next cycle (break if a mutation landed).
   - On loop exhaust / no-progress → terminal `OUTCOME_NONE_CLARIFICATION`.
   - On success — pipeline persists `data/heuristics/{tid}.intent.json` AND `data/heuristics/{tid}.plan.json`. Both are consumed by `pipeline.learn_from_grader` between training cycles to distil grader feedback into a LEARN rule without re-running INTENT/PLAN.
3. `learned_store.py` — `load_entries(tid)` (active only, single surface), `apply_learn_diff(tid, LearnConsolidateOutput)`, `save_last_run(tid, status, outcome, cycles_used)`.

`vm.answer` is called **exactly once** per task (the success path or one terminal CLARIFICATION).

**Training mode** (`TRAIN_MAX_CYCLES > 1`): `main.py` wraps the StartRun/SubmitRun pass in an outer loop. After each SubmitRun, tasks with `score < 1.0` get `pipeline.learn_from_grader(task_id, score_detail)` — loads the persisted `IntentSpec` + `PlanIR` and runs the same IR-framed `_learn_consolidate_text` LEARN call used in-pipeline. Next cycle a fresh StartRun targets only failing tasks; non-targets get `EndTrial` immediately. Successive cycles' trace files are named `{tid}.c{N}.jsonl`.

**LLM call budget:** 1 (INTENT hard-stop) / 2 (best happy path: INTENT + 1 PLAN) / `1 + 2·INTERPRETER_MAX_STEPS` worst (each failing cycle costs PLAN + iLEARN).

**LLM provider routing** (`llm.py`): provider prefix determines transport — `anthropic/` → Anthropic SDK; `openrouter/` → OpenRouter; `ollama/` or bare name → local Ollama; `claude-code` → CC CLI subprocess. All tiers tried in order per `models.json` before falling through to `ECOM_MODEL_FALLBACK`. (Per-phase *model* selection is the tier resolution documented above.)

**Protobuf layer:** `bitgn/` = generated stubs for harness + ECOM + PCM services. Source protos in `proto/`. Regenerate with `make proto`.

## Key Data Files

| Path | Purpose |
|------|---------|
| `data/prompts/*.md` | Phase guides: `intent`, `plan`, `ilearn`, `learn`, `compact` |
| `data/learned/{task_id}.yaml` | Per-task active+inactive LearnConsolidate rules; `last_run` carries `status/outcome/cycles_used/date` only (no `heuristic_valid`, no `schema_hash`) |
| `data/heuristics/{task_id}.intent.json` | Persisted `IntentSpec` from the last run; consumed by `learn_from_grader` in training mode. |
| `data/heuristics/{task_id}.plan.json` | Persisted `PlanIR` from the last run; consumed by `learn_from_grader` in training mode. |
| `models.json` | Per-model provider hints and Ollama options (e.g. `num_ctx`) |
| `data/oracle/atoms.yaml` | Validated general knowledge atoms; retrieved semantically into PLAN by `agent/oracle.py` |

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools (write/delete) take priority over reads to avoid spurious tool calls
- `_plan_signature` / identical-plan short-circuit in `pipeline.py` is the anti-infinite-loop guard (replaces the legacy SQL-multiset retry guard)
- `verify()` is the only quality gate before `vm.answer` — it is deterministic; there is no LLM-graded answer check
- `agent/CLAUDE.md` covers agent-package internals and mirrors this file's architecture section

## Prompt Engineering Rules

**System prompts (`data/prompts/*.md`) contain only general structural rules.**

- Allowed: action forms, output format, SQL constraints, generic decision patterns
- Forbidden: task-specific domain rules, per-task-type heuristics, scenario-specific sequences

Phase guides live in `data/prompts/{intent,plan,ilearn,learn,compact}.md`.
All task-specific knowledge must flow through the LEARN mechanism into `data/learned/{task_id}.yaml`.
Never patch `data/prompts/` to fix a task failure — fix the LEARN trigger or learned rule instead.
