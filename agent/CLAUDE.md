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
   and the pipeline uses the legacy eager gather. The whole-instruction oracle retrieval into
   PLAN (`oracle.retrieve(instruction)` → `oracle_atoms`) runs in **both** modes — not gated
   by this toggle.
2.5. **SECURITY PREFLIGHT** (`decide.py:security_preflight`, no LLM) — between INTENT and
   the loop (in fact right after the INTENT-None guard and **before** INVESTIGATE, so a
   clear deny does not spend the ReAct budget): a facts/identity-driven terminal
   `OUTCOME_DENIED_SECURITY` when a security constraint's `deny_when` holds pre-plan.
   Answers once (`cycles_used=0`) and skips the loop (and any mutation) entirely.
3. **LOOP** (`cycle = 1..INTERPRETER_MAX_STEPS`):
   - **PLAN** (`reason.py:run_plan(intent, brief_block, learn_ctx, prev_error, oracle_atoms, observed)`)
     — LLM call (reason tier), system prompt `plan.md` → `PlanIR`
     (discovery, rowsets, compute, decision, ops, answer, custom_extract).
   - **lint** (`interpreter.py:lint_security_first(plan)`) — no LLM. On `PlanError` /
     `InterpretError` → `_ilearn` → next cycle. `interpret()` also runs
     `lint_paths_absolute(plan)` immediately after: a literal relative `path`/`root` arg in
     any discovery/ops step (non-`$ref`, non-`/`-prefixed) raises `InterpretError` → routed
     to iLEARN instead of dead-ending at the VM's "must be absolute" error (A1).
   - **plan-signature short-circuit** — `_plan_signature(plan)` over discovery+ops (SQL
     whitespace/case-normalised, other step args verbatim); identical to the prior cycle →
     break with CLARIFICATION (no-progress guard).
   - **interpret** (`interpreter.py:interpret(plan, intent, vm, facts)`) — no LLM; runs the
     plan against the VM. `InterpretError` → `_ilearn` → retry (break if a mutation landed).
     A real-VM `Exception` → `_ilearn`, then retry only when the plan is read-only AND the
     error is retryable (`_is_retryable_vm_error`), else break. `CapturedAnswer` also carries
     the typed `value`/`rows` (resolved from `answer_shape`) for the format-gate to render from.
   - **ground-refs** (`grounding.py:ground_refs(...)`) — no LLM, best-effort (never raises).
     Re-derives the authoritative reference set from the VM + task text + computed answer and
     **overwrites** `result.captured.refs` before verify. Record refs: entity-token →
     evidence-scan/`find`/generic-SQL-fallback → `stat`-validate (+ conservative cross-customer
     ownership guard). Doc refs: investigator `docs_read` (`brief.env["docs_read"]`), narrowed
     by a recall-preserving relies-on filter and case-corrected. Model refs are hints; code
     produces the enforced set.
   - **decide-outcome** (`decide.py:decide_outcome(intent, result, vm, facts)`) — no LLM.
     Overwrites the PLAN-authored `result.captured.outcome`/`refs` via the ladder
     `security_deny > unsupported_or_clarify > anti_give_up_ok > plan-outcome`, sourced
     from the frozen IntentSpec constraints + `/bin/id` identity. Runs BEFORE verify, so
     verify is a consistency gate, not where outcomes are born.
   - **format-gate** (`format_gate.py:format_answer(message, intent, answer_shape, agents_md,
     *, outcome, value, rows)`) — no LLM, best-effort. Overwrites `result.captured.message`
     with the exact surface contract per `intent.answer_shape` (money → `format_eur`;
     boolean → `<YES>`/`<NO>` or `/AGENTS.MD` tokens; count → skeleton format; table/quote →
     TSV). Runs BEFORE verify so the format-class success_criteria regex passes on the
     canonical string. Non-OK outcomes and free-text shapes pass through unchanged.
   - **verify** (`verify.py:verify(result, intent)`) — no LLM, deterministic. I1 is
     presence-based on **every** outcome (each resolved `required_refs[outcome]` value ⊆
     `answer.refs`, plus a `$`-ref guard). I1 also hard-fails (returns `(False, reason)`)
     when a declared required `record_path` source did not resolve (`missing_src` non-empty)
     on any outcome — the unresolved source is no longer silently discarded
     (A2: "resolve-before-cite"). Checks `success_criteria` and required refs.
     - Pass → `vm.answer(...)` once, `_persist_artifacts(intent, plan)`,
       return success metrics.
     - Fail → `_ilearn(prev_error + observed RPC outputs)` → next cycle (break if a mutation
       landed).
4. Loop exhaust / no-progress → terminal outcome selected from `intent.outcome_space` by
   precedence via `negative_outcome_by_precedence` (e.g. `OUTCOME_NONE_UNSUPPORTED` outranks
   `OUTCOME_NONE_CLARIFICATION`); falls back to the literal `OUTCOME_NONE_CLARIFICATION` only
   when the space declares neither (B). The INTENT-None hard-stop is exempt (fires before
   `intent` exists and always emits `OUTCOME_NONE_CLARIFICATION`).

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
  `RefSpec`, `AnswerShape` (IntentSpec; `msg_skeleton` + optional `kind`/`columns`/`rows_from`
  for the format-gate); `Step`, `RowSet`, `ComputeStep`, `DecisionTree`,
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
