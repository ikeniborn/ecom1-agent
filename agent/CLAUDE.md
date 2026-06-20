# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Authoritative CLAUDE.md is `../CLAUDE.md` (repo root). This file covers agent-package internals.**

## Commands

```bash
uv sync                                          # install all deps
uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline_interpreted.py -v   # single test file

LOG_LEVEL=DEBUG uv run python main.py           # full LLM response logging
```

Key env vars (authoritative table is the root `../CLAUDE.md`):
- `ECOM_MODEL` — primary LLM (e.g. `anthropic/claude-sonnet-4-6`)
- `ECOM_MODEL_REASON` / `ECOM_MODEL_FAST` — model tiers (see routing below)
- `ECOM_INTERPRETER_MAX_STEPS` — interpreter cycle ceiling (default 6)
- `ECOM_INVESTIGATE_ENABLED` / `ECOM_INVESTIGATE_MAX_STEPS` / `ECOM_INVESTIGATE_ORACLE_K` / `ECOM_MODEL_INVESTIGATE` — INVESTIGATE phase controls (see root `../CLAUDE.md`)

## Agent Package Architecture

Entry: `orchestrator.py:run_agent()` → opens VM, reads `/AGENTS.MD` inline, gathers
pre-phase facts → `pipeline.py:run_pipeline()`. There is **one** pipeline: the
deterministic Plan-IR interpreter.

**Per-task execution flow:**

1. **INTENT** (`reason.py:run_intent(facts, instruction, learn_ctx=...)`) — 1 LLM call
   (reason tier), frozen for the run, retried on transient empty/parse failure. System
   prompt: `intent.md`. Receives the run's active `learn_ctx` (same rules PLAN sees) so a
   learned rule can shape `required_refs`/`success_criteria`/`outcome_space`. Output:
   `IntentSpec` (objective, desired_outcome, params, outcome_space, constraints,
   success_criteria, answer_shape, required_refs). Hard failure → terminal
   `OUTCOME_NONE_CLARIFICATION`.
2. **INVESTIGATE** (`investigate.py:investigate(vm, intent, seed, oracle)`, fast tier,
   `ECOM_INVESTIGATE_ENABLED=1`) — called once after INTENT, before the loop. Runs a
   bounded read-only ReAct loop (`ECOM_INVESTIGATE_MAX_STEPS` steps) fetching doc bodies,
   listings, and table samples on demand; per-step oracle retrieval uses
   `ECOM_INVESTIGATE_ORACLE_K`. Read-only gate: `investigate.is_readonly(tool, args)` — mutations
   are never dispatched here (they stay in the plan's `ops`). Stops on sufficiency (all
   `intent.required_refs` groundable from `env`) or step budget. Escalates from fast to
   reason tier on a deterministic stall (empty result or repeated tool signature). Per-step
   errors become lessons; hard failure falls back to the slim seed facts. Returns a `Brief`
   (step-notes + bound `env`); `render_brief(brief)` is injected into every PLAN cycle via
   `run_plan(..., brief_block=...)`. When `ECOM_INVESTIGATE_ENABLED=0`, this step is skipped
   and the pipeline uses the legacy eager gather + whole-instruction oracle dump.
3. **LOOP** (`cycle = 1..INTERPRETER_MAX_STEPS`):
   - **PLAN** (`reason.py:run_plan(intent, brief_block, learn_ctx, prev_error, oracle_atoms, observed)`)
     — LLM call (reason tier), system prompt `plan.md` → `PlanIR`
     (discovery, rowsets, compute, decision, ops, answer, custom_extract).
   - **lint** (`interpreter.py:lint_security_first(plan)`) — no LLM. On `PlanError` /
     `InterpretError` → `_ilearn` → next cycle.
   - **plan-signature short-circuit** — `_plan_signature(plan)` over discovery+ops (SQL
     whitespace/case-normalised, other step args verbatim); identical to the prior cycle →
     break with CLARIFICATION (no-progress guard).
   - **interpret** (`interpreter.py:interpret(plan, intent, vm, facts)`) — no LLM; runs the
     plan against the VM. `InterpretError` → `_ilearn` → retry (break if a mutation landed).
     A real-VM `Exception` → `_ilearn`, then retry only when the plan is read-only AND the
     error is retryable (`_is_retryable_vm_error`), else break.
   - **verify** (`verify.py:verify(result, intent)`) — no LLM, deterministic. Checks
     `success_criteria` and required refs.
     - Pass → `vm.answer(...)` once, `_persist_artifacts(intent, plan)`, optional
       distill→validate→promote, return success metrics.
     - Fail → `_ilearn(prev_error + observed RPC outputs)` → next cycle (break if a mutation
       landed).
4. Loop exhaust / no-progress → terminal `OUTCOME_NONE_CLARIFICATION`.

`vm.answer` is called **exactly once** per task. The quality gate is `verify()`
(deterministic) — there is no LLM-graded answer check.

**LEARN seam** (`pipeline.py`): `_ilearn(...)` wraps `_learn_consolidate_text(...)`, the
message-building core driven by the rendered `IntentSpec` (plan_context) and `PlanIR`
(artifact). It writes a diff to `data/learned/{tid}.yaml` via `apply_learn_diff`, mutates the
in-session `learn_ctx`, and persists any `prephase_deep_read` hints. Single surface — PLAN
sees all active rules.

**Persistence** (`learned_store.py`):
- `load_entries(tid)` — active entries only (single surface)
- `apply_learn_diff(tid, LearnConsolidateOutput)` — write/deactivate
- `save_last_run(tid, status, outcome, cycles_used)`
- `_persist_artifacts` writes `data/heuristics/{tid}.intent.json` + `{tid}.plan.json`,
  consumed by `learn_from_grader` in training mode.

**Pydantic models:**
- `models.py`: `LearnConsolidateOutput` (rule_content?, agents_md_anchor?, reasoning,
  deactivate_ids, deactivate_reason?, skip, skip_reason?, prephase_deep_read),
  `AnswerOutput` (message, outcome, grounding_refs).
- `ir_models.py`: `IntentSpec` / `PlanIR` and their parts — `PredExpr`, `Constraint`,
  `RefSpec`, `AnswerShape` (IntentSpec); `Step`, `RowSet`, `ComputeStep`, `DecisionTree`,
  `GuardedOp`, `AnswerTemplateIR`, `CustomExtract` (PlanIR).

**Model routing** (`llm.py`): two axes.
- *Provider transport* by `ECOM_MODEL` prefix: `anthropic/` → Anthropic SDK (prompt caching via
  `cache_control` blocks); `openrouter/` → OpenRouter (OpenAI-compatible); bare name /
  `ollama/` → local Ollama; `ECOM_CC_ENABLED=1` / `claude-code/` → `cc_client.py` subprocess.
- *Per-phase model* via `_resolve_model_for_phase(phase, MODEL)`: `ECOM_MODEL_<PHASE>` → tier env
  (`ECOM_MODEL_REASON` / `ECOM_MODEL_FAST` / `ECOM_MODEL_EMBED`) → `ECOM_MODEL`. Reason-tier phases (INTENT, PLAN,
  iLEARN, distill) → `ECOM_MODEL_REASON`; fast-tier (DOC_SELECT, oracle rerank, INVESTIGATE) → `ECOM_MODEL_FAST`;
  embeddings → `ECOM_MODEL_EMBED`. **`ECOM_MODEL_REASON` is the catch-all** for any phase not explicitly
  fast-tier (including unlisted phases). Reason tier → `think=on`; fast tier → `think=off`. INVESTIGATE
  router/digest steps run fast-tier and escalate to reason tier on a deterministic stall.

Transient errors (503, rate-limit, timeout) retry with exponential backoff before falling
through to the next provider tier, then `ECOM_MODEL_FALLBACK`.

**Prompt loading** (`prompt.py`):
- `load_prompt(name)` — reads `data/prompts/{name}.md`; returns `""` if missing
- Phase guides live in `data/prompts/{intent,plan,ilearn,learn,compact}.md`

**Trace logging** (`trace.py`): thread-local `TraceLogger` writes structured JSONL. Attach
with `set_trace(logger)`; read with `get_trace()`. `set_cycle(n)` stamps the active cycle.

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools take priority over reads
- `_plan_signature` / identical-plan short-circuit in `pipeline.py` is the anti-infinite-loop guard
- INTENT is frozen for the run and reads the active `learn_ctx` snapshot loaded before it;
  in-loop `learn_ctx` updates (iLEARN) only affect subsequent PLAN cycles, not INTENT
- Answer refs: enforced refs are projected from `intent.required_refs[outcome]`; the selected
  answer template's authored `refs` add best-effort CONDITIONAL grounding (a `$ref` that
  resolves to nothing is dropped, not refused) — `interpreter._resolve_authored_refs`
- System prompt blocks are passed as `list[dict]` (Anthropic multi-block format):
  `[{"type":"text","text":guide,"cache_control":{"type":"ephemeral"}}]` — agent-relevant VM
  API surface is inline in `data/prompts/{intent,plan}.md`; `docs/proto-api-reference.md` is
  repo-side reference only and is not injected
- `verify()` is the sole pre-answer quality gate and is deterministic (no LLM)
