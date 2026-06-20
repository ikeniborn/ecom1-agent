# Pipeline

The deterministic Plan-IR pipeline in `agent/pipeline.py`. One pipeline per task: INTENT freezes the goal, then a bounded loop emits a `PlanIR`, lints it, interprets it against the VM, verifies the result, and answers exactly once — or terminates in CLARIFICATION. No LLM grades the answer; `verify()` is the only gate. See [[architecture]] for the surrounding harness.

## run_pipeline

`run_pipeline(vm, instruction, task_id, agents_md_text, facts)` (`pipeline.py:214`) is the per-task entry. It loads active LEARN rules via `load_entries(task_id)`, retrieves oracle atoms, runs frozen INTENT, then loops PLAN→lint→interpret→verify. It calls `vm.answer` exactly once and returns a metrics dict (`cycles_used`, `outcome`, `status`, token counts). See [[vm]] and [[learning]].

## INTENT — run_intent

`run_intent(facts, instruction, token_out=None, learn_ctx=None)` (`reason.py:60`) makes one reason-tier LLM call with the `intent.md` system prompt and the pre-phase facts block, parsing the JSON reply into an `IntentSpec` (objective, desired_outcome, params, outcome_space, constraints, success_criteria, answer_shape, required_refs). It is frozen for the whole run.

**Learned rules in INTENT:** `pipeline.run_pipeline` passes the run's pre-loaded `learn_ctx` snapshot to `run_intent`. INTENT injects a `LEARNED_RULES (active)` block (same `_format_entry` used by `run_plan`) so that a learned rule can shape `required_refs`, `success_criteria`, or `outcome_space`. WHY: `required_refs` (the sole driver of enforced answer-ref projection) is INTENT's output, but INTENT previously received no learned context — so no LEARN rule could fix a missing grounding ref. In-loop `_ilearn` updates still write to `learn_ctx` in place but are consumed only by subsequent PLAN calls, not by the frozen INTENT. See [[interpreter#Answer-ref assembly]] for how `required_refs` drives ref enforcement, and [[llm]].

## INTENT retry and hard failure

INTENT is retried up to `_DESIGN_MAX_ATTEMPTS` (env `ECOM_DESIGN_MAX_ATTEMPTS`, default 3) times on transient empty/parse failure — `IntentError` is caught and the attempt re-run (`pipeline.py:244`). If `intent` is still `None` after all attempts, the run records `save_last_run(..., "OUTCOME_NONE_CLARIFICATION", 0)`, emits one terminal CLARIFICATION, and returns with `cycles_used: 0`.

## PLAN — run_plan

`run_plan(intent, facts, learn_ctx, prev_error, oracle_atoms, observed)` (`reason.py:77`) is the reason-tier LLM call inside the loop. Its user message assembles the oracle block, the `IntentSpec` JSON, the facts block, active LEARNED_RULES, prior OBSERVED_RPC_OUTPUTS, and any PREVIOUS_ERROR. It returns a `PlanIR` (discovery, rowsets, compute, decision, ops, answer, custom_extract). An empty LLM body raises `PlanEmptyError` (a `PlanError` subclass, `reason.py`) — distinguished from a substantive parse/validation `PlanError` so the loop can handle a transient empty cheaply (see [[pipeline#Empty-PLAN handling]]). See [[oracle]].

## Tiered pre-phase facts

`_facts_block(facts, tier)` (`reason.py:40`) injects facts per phase. INTENT (`tier="intent"`) gets `agents_md_inventory`, `schema`, `identity`, `docs_inventory`, and `policies`; PLAN (`tier="plan"`) gets the thin set only (drops `policies`, `sample_rows`, `target_records`, `path_listings`, and the full `agents_md`). The thinned PLAN block shrinks the prompt and pushes heavy data to on-demand IR `discovery`. `agents_md_inventory` is a compact, 0-LLM tool/catalog list rendered by `render_inventory` (`agent/agents_md_parser.py`) instead of re-injecting the verbose AGENTS.MD. With `ECOM_LOG_LEVEL=DEBUG`, `run_plan` prints the assembled PLAN prompt size.

## PLAN IR auto-repair (pre-lint)

`_repair_plan_dict(obj)` (`reason.py`) runs in `run_plan` after JSON parse and before `PlanIR(**obj)`, deterministically (no LLM). It maps common predicate-op synonyms to canonical names (`neq`/`!=`→`ne`, `==`→`eq`, `gte`/`=>`→`ge`, `lte`/`=<`→`le`) via `_repair_ops`, and strips unknown keys from each answer branch (`_ANSWER_KEYS = {message, outcome, refs}`). Unmappable ops are left untouched and still raise at construction (→ `PlanError` → iLEARN), so invalid IR is never silently accepted. The allowed op spellings and `AnswerTemplateIR` shape are documented structurally in `plan.md`. See [[data-files]].

## The cycle loop and INTERPRETER_MAX_STEPS

The loop runs `cycle = 1..INTERPRETER_MAX_STEPS` (`_IMAX_STEPS`, env `ECOM_INTERPRETER_MAX_STEPS`, default 6; `pipeline.py:260`). Each cycle: PLAN → `repair_sql_stdin` → `lint` (registry dispatcher) → plan-signature check → `interpret` → `verify`. `set_cycle(cycle)` stamps the trace. Exhausting the loop without a passing verify falls through to terminal CLARIFICATION.

## Pre-lint repair and lint

`repair_sql_stdin(plan)` runs first, normalising any `/bin/sql` Exec step that delivers SQL via `args` (nondeterministic) to deliver it via `stdin` (reliable channel) instead. After repair, the registry dispatcher `interpreter.lint(plan)` runs — no LLM. A substantive `PlanError` (unparseable/invalid PLAN response) or `InterpretError` raised by lint is caught: `last_error` is set, `_ilearn` fires with the plan JSON, and the loop `continue`s to the next cycle. The empty-body case (`PlanEmptyError`) is caught by a separate handler ordered first — it does NOT fire `_ilearn` (see [[pipeline#Empty-PLAN handling]]). See [[interpreter#lint — registry-driven lint dispatcher]] and [[harness]].

## Empty-PLAN handling

An empty PLAN body (`PlanEmptyError`, raised by `run_plan` when the LLM returns no content — e.g. a `think=on` model starving its visible output, or an endpoint read-timeout) is caught by a dedicated handler ordered before the generic `(PlanError, InterpretError)` catch (`pipeline.py`). Because an empty body carries nothing to learn from, it skips `_ilearn` entirely (which would be a wasted LLM call that emits no rule) and retries the cycle cheaply. A running `empty_streak` counter breaks the loop to terminal CLARIFICATION once it reaches `_EMPTY_PLAN_MAX` (env `ECOM_EMPTY_PLAN_MAX`, default 2) consecutive empties, so a persistently-empty model does not silently burn the whole `ECOM_INTERPRETER_MAX_STEPS` budget on `PLAN + iLEARN` pairs. A single transient empty followed by a valid plan resets the streak and the task proceeds normally.

## Plan signature and no-progress guard

`_plan_signature(plan)` (`pipeline.py:29`) builds a per-step identity over `discovery + ops`: SQL Exec steps include both `args` and `stdin` content (whitespace/case-normalised and sorted), so a before/after `repair_sql_stdin` that only moves SQL from args to stdin produces the same signature. Every other step contributes its rpc plus verbatim sorted args, so re-planning a changed Read/List path is not mistaken for stalling. If a cycle's signature equals the previous one, the loop breaks with CLARIFICATION. It is consecutive-only — A↔B oscillation is bounded by the cycle ceiling, not caught here.

**Same-error guard (complements the signature guard).** When iLEARN keeps *changing* the plan each cycle (signatures differ, so the no-progress guard never fires) but the interpret/verify error is *identical* every cycle, the model is stuck. `_stuck_on_same_error(err)` tracks the consecutive count of the normalised (`_norm_err`, 120-char) error across the plan-error, interpret-error, real-VM-retry, and verify-fail branches; once it reaches `_SAME_ERROR_MAX` (env `ECOM_SAME_ERROR_MAX`, default 3) the loop breaks to CLARIFICATION instead of burning the rest of `ECOM_INTERPRETER_MAX_STEPS` on PLAN+iLEARN pairs. Canonical trigger: an OK answer whose required `record_path` ref the SQL never SELECTs — refused identically each cycle (observed t38 burning all 6 cycles + ~73k tokens).

## Interpret

`interpret(plan, intent, vm, facts)` (`pipeline.py:284`) executes the plan against the VM, no LLM. An `InterpretError` triggers `_ilearn` then retry, but breaks if the error carries `mutation_landed`. A raw VM `Exception` triggers `_ilearn`, then retries only when the plan is read-only AND the message is retryable per `_is_retryable_vm_error` (missing path/record or network transient); a mutating plan, or a non-retryable error, breaks. See [[interpreter]].

## Verify and answer-once

`verify(result, intent)` (`pipeline.py:308`) is the sole deterministic quality gate (no LLM), checking `success_criteria` and required refs. `success_criteria` is keyed by outcome (`dict[str, list[PredExpr]]`); verify applies only `success_criteria.get(ans.outcome, [])`, so a valid negative outcome (e.g. `OUTCOME_NONE_UNSUPPORTED`) with no criteria for it passes — still gated by `outcome_space`. On pass: `_ground_security_refs` ensures a DENIED_SECURITY answer cites `/docs/security.md`, `answer_once(...)` submits via vm.answer (message capped at 800 chars), artifacts persist, distill runs, and the run returns. On fail: `_ilearn` fires with observed RPC outputs, or breaks if a mutation already landed. See [[interpreter#verify() — the deterministic quality gate]].

**answer-once idempotency guard (F4):** `_make_answer_once(vm)` (`pipeline.py:250`) returns a closure that tracks whether `vm.answer` has already been called. The first call submits; subsequent calls are suppressed no-ops (logging a yellow warning). Both the success path and all terminal exits share the same `answer_once` closure, so a success followed by a loop-exhaust terminal can never double-submit. This eliminates the "answer already provided" dead-end that previously required a separate `_terminal_clarification` helper.

## _ilearn retry seam

`_ilearn(task_id, learn_ctx, intent, plan_text, error, observed)` (`pipeline.py:155`) is the between-cycle LEARN seam for the interpreted path. It calls `_learn_consolidate_text` with the IR-framed `ilearn.md` prompt and `surface="ir"`, passing the rendered `IntentSpec` as context and `PlanIR` as artifact. It writes a diff to `data/learned/{tid}.yaml`, mutates `learn_ctx` in place, and persists any `prephase_deep_read` hints. See [[learning]].

## Distill → validate → promote

On a passing verify, `_maybe_distill_and_validate(intent, plan, task_id, note)` (`pipeline.py:187`) runs only when `ORACLE_ENABLED!=0` and `ECOM_ORACLE_DISTILL=1`. It calls `oracle.distill(...)` to generalise the working `PlanIR` into a candidate atom. When `ECOM_ORACLE_VALIDATE_INLINE=1`, `validate_atom_via_grader` re-runs against the live grader and `oracle.promote(...)` fires on improvement. It never raises. See [[oracle]].

## Persisted artifacts

`_persist_artifacts(task_id, intent, plan)` (`pipeline.py:167`) writes `data/heuristics/{tid}.intent.json` and `{tid}.plan.json` on the success path. These rendered `IntentSpec` / `PlanIR` JSON files are the seam consumed by `learn_from_grader` in training mode. See [[data-files]].

## End-of-run self-fill

`distill_from_grader(task_id, score, score_detail)` (`pipeline.py`) self-fills the oracle bank from the score SubmitRun already returned — not a live grader round-trip (distinct from `ECOM_ORACLE_VALIDATE_INLINE`). A pass (`score >= 1.0`) distills a `method` atom, a fail an `anti_pattern` atom, both written `status="active"`. It is gated only by `ECOM_ORACLE_ENABLED`, reads the persisted `IntentSpec`+`PlanIR`, no-ops when artifacts are absent, and never raises. `main.py` calls it once per task (pass and fail) in the score loop, before the fail-only `learn_from_grader`. Because it is gated only by `ECOM_ORACLE_ENABLED` (default on), it adds one distill LLM call per task. See [[oracle#End-of-run self-fill (distill_from_grader)]].

## learn_from_grader training path

`learn_from_grader(task_id, score_detail)` (`pipeline.py:339`) is the post-trial seam: the pipeline never sees grader feedback during a run (the score arrives only on SubmitRun). It loads the persisted `{tid}.intent.json` + `{tid}.plan.json`, frames the grader feedback as the error, and reuses the same IR-framed `_learn_consolidate_text` LEARN call. Returns False if persisted state is missing. See [[learning]].

## LLM call budget

Each cycle costs one PLAN call, plus one `_ilearn` LEARN call when the cycle fails. Best happy path is 2 calls (INTENT + 1 PLAN); a hard INTENT stop is 1 call; the worst case is `1 + 2·INTERPRETER_MAX_STEPS`. Interpret and verify make no LLM calls. See [[llm]].

## answer-once and harness distill

After a verify failure, `_maybe_harness_distill(plan, error, task_id)` (`pipeline.py:285`) fires when `ECOM_HARNESS_DISTILL=1` (default `0`) and the error string indicates an F1-class compute contract failure (`"compute step"` or `"custom_extract"` in the message). It calls `harness.distill(...)` to propose a candidate check-spec, then optionally validates and promotes it inline. It never raises. See [[harness#F8b: distill → validate → promote]].

## Terminal OUTCOME_NONE_CLARIFICATION

The terminal exit calls `answer_once(message, "OUTCOME_NONE_CLARIFICATION", [])` — the same idempotency-guarded closure used on the success path, so there is no separate `_terminal_clarification` helper. It fires when INTENT cannot be built, when `_plan_signature` short-circuits on no progress, or when the cycle loop exhausts. `save_last_run` records the failure with the cycles used before the terminal answer.
