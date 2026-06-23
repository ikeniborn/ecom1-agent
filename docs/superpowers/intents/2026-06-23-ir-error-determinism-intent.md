---
review:
  intent_hash: 1a3b0cb0496b31d0
  last_run: 2026-06-23
  phases:
    structure:    { status: passed }
    completeness: { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
    alignment:    { status: passed }   # advisory — вне CRITICAL-gate
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: Desired Outcomes
      section_hash: d77690d0e2bc853b
      text: >-
        DO1 embeds the implementation mechanism ("a pre-interpret lint raises ... → iLEARN
        → next cycle re-plans with an absolute path") inside the outcome. An observable
        anchor is present ("t01 stops giving up at cycle 1"), so not CRITICAL, but the
        outcome is not stated purely at the observation level.
      verdict: fixed
      verdict_at: 2026-06-23
    - id: F-002
      phase: clarity
      severity: WARNING
      section: Desired Outcomes
      section_hash: d77690d0e2bc853b
      text: >-
        DO2 embeds the implementation mechanism ("verify hard-fails → iLEARN forces
        resolve-before-cite") inside the outcome. An observable anchor is present ("t50
        stops citing a record it never bound"), so not CRITICAL, but the outcome leaks
        the mechanism rather than staying observation-level.
      verdict: fixed
      verdict_at: 2026-06-23
    - id: F-003
      phase: clarity
      severity: WARNING
      section: Stop Rules
      section_hash: 25a7f012eaca7377
      text: >-
        The `Done when:` criterion opens with "A1/A2/B implemented" — implementation-act
        phrasing. It is conjoined with measurable gates (159 tests + full pytest green,
        observable benchmark outcome shift on t01/t50), which carry the criterion and keep
        it from being CRITICAL; the leading implementation-act clause is still advisory.
      verdict: fixed
      verdict_at: 2026-06-23
---

# Intent: IR error→outcome determinism (exoskeleton continuation)

**Date:** 2026-06-23
**Status:** approved

## Objective

A benchmark run of t01/t10/t38/t50 on the `determinism` branch scored 25% (only t10
passed). The three deterministic phases (P1 grounding, P2 decide, P3 format-gate) are
correctly built and fire, but they are post-LLM gates: they enforce what the LLM plan
declares. With a weak primary model (`deepseek-v4-flash:cloud`) the failures are upstream
of the engines, and two of them are silent:

- **t01** — PLAN emitted a discovery step `list path="."`. The relative path raised a VM
  error (`invalid path: must be absolute`) that is NOT in `_RETRYABLE_VM_ERROR_PATTERNS`,
  so the cycle broke to a terminal NONE outcome at cycle 1 with no iLEARN — a malformed
  literal path became a terminal give-up instead of a learnable re-plan.
- **t50** — `required_refs[OUTCOME_DENIED_SECURITY]` declared a `record_path`
  `$basket.record_path`, but the discovery never bound `$basket`. `verify.py` resolves the
  ref to `None`, drops it silently (the unresolved list `_missing_src` is discarded), and
  I1 passes vacuously. The grader then fails the answer for the missing
  `/proc/baskets/basket_019.json` record reference.
- The pipeline's terminal/break path hardcodes `OUTCOME_NONE_CLARIFICATION`, which may be
  outside a task's `outcome_space` — the exact "defaulting to an invalid outcome" failure
  that learned rule **r008** asks the model to prevent, and which the model ignores.

Make error→outcome deterministic at the IR layer: a malformed IR or an unresolved required
reference must become a precise iLEARN signal or a valid in-space outcome — never a silent
wrong answer. This is a continuation of the muxx exoskeleton pattern (model proposes, code
disposes), not a structured-output change.

## Desired Outcomes

- t01 no longer terminates at cycle 1 on a malformed relative path — a step carrying a
  relative literal `path`/`root` gets a further cycle and can reach a grounded answer
  instead of a terminal give-up.
- No answer reaches `vm.answer` while a DECLARED required `record_path` is unbound — for any
  outcome (including a denial), an answer that should cite a record it never resolved is no
  longer submitted (t50 no longer answers with the basket record missing).
- Every terminal / give-up answer carries an outcome that is in the task's `outcome_space`
  — never an outcome the task does not declare.

## Health Metrics

- The 159 determinism unit tests (`test_format_gate` / `test_decide` / `test_grounding` +
  `test_pipeline_decide` / `test_pipeline_grounding` / `test_investigate_doc_grounding`)
  stay green.
- t10 and every currently-passing benchmark task show no regression — the new A2 hard-fail
  and B precedence introduce no new failures.
- The happy-path LLM call budget (INTENT + 1 PLAN) is unchanged — the new gates add no
  cycles when the plan is well-formed.
- The full `pytest tests/` suite stays green (except the known stale `t09`-replay red noted
  in project memory, which predates this work).

## Strategic Context

- Interacts with: `agent/interpreter.py` (lint + answer assembly), `agent/verify.py`
  (the I1 ref-grounding gate), `agent/pipeline.py` (terminal/break outcome selection and
  the retryable-error classification). Reads from the frozen `IntentSpec`
  (`outcome_space`, `required_refs`) and `PlanIR` (`discovery`, `ops`).
- Priority trade-off: **trust / correctness over speed** — spending one extra iLEARN cycle
  to surface a precise signal is preferred to answering fast and wrong.

## Constraints

### Steering (behavioral guidance)

- Exoskeleton style: the new gates raise / hard-fail as an explicit iLEARN signal — they do
  not silently drop, repair, or mask. (A1/A2/B are intentionally NOT best-effort
  pass-through; that is the point.)
- Mirror existing precedence: B's negative-outcome ordering matches
  `decide.unsupported_or_clarify` (UNSUPPORTED outranks CLARIFICATION) so decide ↔ pipeline
  never diverge.

### Hard (architectural enforcement)

- No task-specific knowledge in `data/prompts/*.md` — all task knowledge flows through the
  LEARN mechanism. These fixes are code-side determinism, not prompt patches.
- B adds NO new IR surface — it derives the outcome from the existing `intent.outcome_space`,
  no new `IntentSpec`/`PlanIR` field.
- Surgical changes only: A2 reuses the already-computed `_missing_src` at `verify.py:39`;
  A1 mirrors the existing `lint_security_first` structural-lint shape; every changed line
  traces to one of the three components.
- `vm.answer` is still called exactly once per task; `verify()` remains the sole
  deterministic pre-answer quality gate (no LLM-graded check is added).

## Autonomy Zones

- **Full autonomy** (reversible, low risk): implement A1/A2/B + unit tests, run
  `pytest tests/`, run the real benchmark on t01/t10/t38/t50 — all on the
  `dev/ir-error-determinism` branch (fully reversible).
- **Guarded**: none.
- **Proposal-first**: none during implementation.
- **No autonomy (HUMAN CHECKPOINT)**: opening the PR into `determinism` — pause for human
  review before the PR.

> These zones OVERRIDE subagent-driven-development's "don't pause" default: halt before the
> PR for human review.

## Stop Rules

- **Halt if:** any of the 159 determinism unit tests, or any previously-passing benchmark
  task, regresses and the cause is not understood.
- **Escalate if:** the A2 hard-fail or B precedence drives a previously-passing task into an
  iLEARN loop (no convergence within `INTERPRETER_MAX_STEPS`) — that is an intent-compliance
  defect, return to spec, do not mask it.
- **Done when:** all 159 determinism tests + full `pytest tests/` green; a real benchmark
  run shows t01 and t50 no longer fail via the diagnosed mechanisms (relative-path terminal
  / silent record-ref drop) — an observable outcome shift, or a precise evidenced
  explanation why a remaining gap is upstream — AND t10 + the other tasks show no new
  failures.
