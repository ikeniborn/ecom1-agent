# Security & Lint

The IR interpreter enforces security and answer-grounding deterministically — no LLM and no separate SQL gate. (The legacy `schema_gate.py` / `sql_security.py` modules remain in the tree but are no longer wired into the pipeline.)

## lint_security_first

`interpreter.py:lint_security_first(plan)` runs before interpret each cycle (no LLM). See [[pipeline-phases]].

Static check that the plan's security branch ordering is correct in `decision` / `ops`: a deny path must be reachable before any mutating op. Violations raise `PlanError` / `InterpretError`, routing to LEARN.

## verify invariants

`verify.py:verify(result, intent)` is the sole pre-answer quality gate (deterministic, 0 LLM):

- **I1 — ref grounding.** An `OUTCOME_OK` answer must carry exactly the required refs for its outcome (`intent.required_refs[outcome]`); unresolved or wrong-count refs fail.
- **I3 — security re-check.** Each security `Constraint.deny_when` (`PredExpr`) is re-evaluated from the frozen `IntentSpec` against the runtime env; if a deny predicate holds, verify fails (defense in depth — interpret already applied it).
- **success_criteria.** Every `PredExpr` in `intent.success_criteria` must hold over env + answer.

Pass → `vm.answer()` once. Fail → `_ilearn` with observed RPC outputs → next cycle.

## Security ref grounding

`pipeline.py:_ground_security_refs()` guarantees an `OUTCOME_DENIED_SECURITY` answer cites `/docs/security.md` (per AGENTS.MD: an applied policy doc must appear in refs, even for refusals).

## Anti-infinite-loop

`pipeline.py:_plan_signature(plan)` over discovery + ops (SQL whitespace/case-normalized, other args verbatim). See [[constraints]].

Two consecutive identical signatures ⇒ no progress ⇒ break with CLARIFICATION. The cycle ceiling (`INTERPRETER_MAX_STEPS`) bounds A↔B oscillation. This replaces the legacy `check_retry_loop()` guard.
