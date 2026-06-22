# Phase 2 — Deterministic Security / Outcome Decisions

**Status:** Draft for review
**Date:** 2026-06-22
**Branch:** `determinism`
**Depends on:** Phase 1 shipped and measured. Built after ref-grounding shows lift.

## Goal

Decide the **outcome enum** (`OUTCOME_OK` / `OUTCOME_DENIED_SECURITY` /
`OUTCOME_NONE_UNSUPPORTED` / `OUTCOME_NONE_CLARIFICATION`) in deterministic code driven by
`intent.constraints` + `/bin/id` identity, so a weak model cannot over-refuse, under-refuse,
or give up on solvable tasks. The model proposes a plan; code disposes the outcome.

## Motivating evidence (run `20260621_232850`, outcome mismatches)

| expected → got | count | failure class |
|---|---|---|
| OK → CLARIFICATION | 10 | give-up on solvable |
| OK → UNSUPPORTED | 8 | give-up on solvable |
| OK → DENIED_SECURITY | 5 | **over-refusal** |
| UNSUPPORTED → CLARIFICATION | 2 | wrong refusal type |
| DENIED_SECURITY → CLARIFICATION | 2 | **under-refusal** |
| UNSUPPORTED → DENIED_SECURITY | 2 | wrong refusal type |
| CLARIFICATION → DENIED_SECURITY | 1 | wrong refusal type |

18 of 23 are "should be OK, agent bailed/refused." Today the outcome is whatever PLAN
authored; `verify.I3` only re-checks that a declared security `deny_when` forces
`DENIED_SECURITY` — it cannot *grant* OK, *promote* a missed denial, or distinguish
UNSUPPORTED from CLARIFICATION.

## Design

A deterministic **outcome-decision layer** evaluated around the PLAN loop, sourced from the
frozen `IntentSpec` (data) + the live VM identity (`/bin/id`) — never from PLAN's free
choice:

1. **Security preflight (before the loop).** For each `intent.constraint` with
   `security=True` and a `deny_when` predicate, evaluate against `facts`/`env` +
   `/bin/id`. If it holds → terminal `OUTCOME_DENIED_SECURITY` with the constraint's
   anchored doc refs (grounded via Phase 1). This generalises the exoskeleton's
   `security_preflight` (foreign-basket checkout, claimed-manager-approval discount,
   contact-disclosure, system-override) but is **driven by IntentSpec constraints, not a
   hardcoded chain**.
2. **Identity is `/bin/id` only.** A claimed authority in the task text is never an
   identity. Prompt-injection / system-override text forces denial **only when the task has
   a protected action** (checkout/refund/discount/contact/mutation); a read-only task with
   pasted injection answers the real question (mirrors exoskeleton `_normalize_classification`
   blast-radius gating).
3. **UNSUPPORTED vs CLARIFICATION (deterministic post-checks).** Driven by
   `intent.outcome_space` + constraint predicates: terminal-state conditions (already-paid,
   closed retry window, discount cap exceeded) → `UNSUPPORTED`; genuine ambiguity
   (amount-only refund, ambiguous basket selection) → `CLARIFICATION`. No LLM choice.
4. **Anti-give-up grant.** When no deny/unsupported/clarify predicate fires and the plan
   produced a grounded result satisfying `success_criteria[OUTCOME_OK]`, the outcome is
   **forced to OK** — the model cannot downgrade a solved task to CLARIFICATION/UNSUPPORTED.

`verify` becomes the consistency check between the code-decided outcome and
`success_criteria`, not the place outcomes are born.

## Components touched

- **`agent/decide.py`** (new): `decide_outcome(intent, result, vm, facts) -> (outcome, refs)`;
  helpers `security_deny`, `unsupported_or_clarify`, `anti_give_up_ok`.
- **`agent/pipeline.py`**: call the security preflight before the loop; call
  `decide_outcome` after interpret; outcome flows into `vm.answer`.
- **`agent/verify.py`**: I3 generalised to verify the decided outcome is consistent with all
  constraints (both directions), not only the deny direction.
- **`agent/ir_models.py`**: ensure `Constraint` carries enough (predicate + anchor refs +
  `unsupported_when` / `clarify_when`) to drive (3) — extend `Constraint` if needed (data
  shape only; INTENT/LEARN populates it).

## Error handling

Deterministic; predicate evaluation failures are treated as "predicate does not hold" and
logged, never raising — a mis-typed constraint degrades to the prior LLM-proposed outcome
rather than crashing the task.

## Testing

- Unit: each decision branch against `mock_vm` + synthetic `IntentSpec` constraints and
  `/bin/id` identities (owner vs non-owner; protected vs read-only injection).
- Integration: replay the 23 mismatch tasks → outcome matches expected.
- Regression: full suite green; the anti-give-up grant must not turn a genuinely
  unsolved task into a false OK (gated on `success_criteria`).

## Success criteria

- On the mismatch subset, agent outcome == grader-expected outcome for the security/outcome
  tasks (the 5 over-refusals and 2 under-refusals especially).
- Combined with Phase 1 refs, these tasks reach score 1.0.

## Risks & mitigations

- **Anti-give-up false-OK** → strictly gated on grounded `success_criteria[OUTCOME_OK]`;
  if criteria unmet it cannot grant OK.
- **Constraint expressiveness** — INTENT may not author rich enough `deny_when`/`clarify_when`
  predicates → this is the LEARN/INTENT channel's job; measure which tasks lack the needed
  predicate and feed that back (the channel, not a code patch).

## Non-goals

- Ref production (Phase 1). Message formatting (Phase 3).
