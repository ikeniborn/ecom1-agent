# Pipeline Phases

One INTENT call is frozen for the run; the cycle loop then runs PLAN → lint → interpret → verify, with LEARN between failing cycles.

INTENT and PLAN are the only per-cycle LLM calls (plus LEARN on failure); lint, interpret, and verify are deterministic (no LLM).

## INTENT

`reason.py:run_intent(facts, instruction)` — one LLM call (reason tier), system prompt `data/prompts/intent.md`. Produces `IntentSpec`. See [[data-models]].

`IntentSpec` fields: objective, desired_outcome, params, outcome_space, constraints, success_criteria, answer_shape, required_refs. Frozen for the whole run; retried up to `DESIGN_MAX_ATTEMPTS` on transient empty/parse failure. Hard failure → terminal `OUTCOME_NONE_CLARIFICATION` (no cycles run).

## PLAN

`reason.py:run_plan(intent, facts, learn_ctx, prev_error, oracle_atoms, observed)` — one LLM call per cycle (reason tier), system prompt `data/prompts/plan.md`. Produces `PlanIR`.

`PlanIR` parts: discovery, rowsets, compute, decision, ops, answer, custom_extract. PLAN sees all active learned rules + retrieved oracle atoms + the prior cycle's error and observed RPC outputs.

## lint

`interpreter.py:lint_security_first(plan)` — no LLM. Static security-first ordering check on the plan: a deny path must precede any mutating op. `PlanError` / `InterpretError` → `_ilearn` → next cycle. See [[security-lint]].

## plan-signature short-circuit

`pipeline.py:_plan_signature(plan)` over discovery + ops (SQL whitespace/case-normalized, other step args verbatim). Identical to the prior cycle → break with CLARIFICATION. This is the only anti-infinite-loop guard. See [[constraints]].

## interpret

`interpreter.py:interpret(plan, intent, vm, facts)` — no LLM. Executes the plan against the VM: resolve columns → run discovery + RPC ops → classify outcome → project `required_refs` → build `CapturedAnswer`. See [[vm-protocol]].

RPC steps dispatch via `getattr(vm, step.rpc.lower())`. `InterpretError` → `_ilearn` → retry (break if a mutation landed). A real-VM `Exception` → `_ilearn`, then retry only when the plan is read-only AND the error is retryable (`_is_retryable_vm_error`), else break.

## verify

`verify.py:verify(result, intent)` — no LLM, deterministic. Checks built-in invariants (I1 ref-grounding, I3 security re-check) + `IntentSpec.success_criteria`. See [[security-lint]].

Pass → `vm.answer()` once + `_persist_artifacts` + optional distill→validate→promote. Fail → `_ilearn(error + observed RPC outputs)` → next cycle (break if a mutation landed).

## LEARN

`pipeline.py:_ilearn()` wraps `_learn_consolidate_text()` (system prompt `data/prompts/ilearn.md`). Distils a `LearnConsolidateOutput` and writes a diff to `data/learned/{tid}.yaml` via `apply_learn_diff`.

It also mutates the in-session `learn_ctx` and persists `prephase_deep_read` hints. `learn_from_grader()` reuses the same call on grader feedback between training cycles.

## Outcomes

`vm.answer()` is called exactly once with one of:

- `OUTCOME_OK` — success (verify passed, captured outcome OK).
- `OUTCOME_NONE_UNSUPPORTED` / `OUTCOME_DENIED_SECURITY` — classified by interpret, emitted on a passing verify.
- `OUTCOME_NONE_CLARIFICATION` — terminal only: INTENT failure, identical-plan no-progress, or cycles exhausted.
