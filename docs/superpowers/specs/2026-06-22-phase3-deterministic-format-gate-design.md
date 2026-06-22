---
review:
  spec_hash: f9ae40e6efa6d116
  last_run: 2026-06-22
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: Design
      section_hash: null
      text: >-
        Count format has no resolution source/DoD. Goal states the pattern as
        `count: %d`, but Design says count → "substitute into the task's exact
        `%d`/format string" with no stated source for that string (unlike money's
        format_eur or boolean's AGENTS.MD-parsed tokens).
      verdict: open
      verdict_at: null
    - id: F-002
      phase: clarity
      severity: INFO
      section: Error handling
      section_hash: null
      text: >-
        Term "Best-effort" is vague-flagged but self-defined on the same line
        ("never raises: a formatting failure returns the original message"), so DoD
        is present. INFO only.
      verdict: open
      verdict_at: null
chain:
  intent: null
---

# Phase 3 — Deterministic Output-Format Gate

**Status:** Draft for review
**Date:** 2026-06-22
**Branch:** `determinism`
**Depends on:** Phases 1–2 shipped. Built last; smallest surface.

## Goal

Guarantee `answer.message` matches the exact format contract deterministically, so the model
never has to hold a regex. Patterns: `EUR %d.%02d`, `<YES>`/`<NO>`, `count: %d`, and the
tenant's `/AGENTS.MD` yes/no tokens. The model proposes content; code shapes the surface.

## Motivating evidence (run `20260621_232850`)

- `verify fail: success_criteria[OUTCOME_OK][0] failed: {'op': 'regex_match',
  'lhs': '$answer.msg', 'rhs': '^EUR \\d+\\.\\d{2}$'}` — the value was right, the surface
  string was not.
- Tasks whose `score_detail` is `Answer should contain '<YES>'` / `'<NO>'` (e.g. t04, t06,
  t07, t08) — boolean answers emitted in the wrong token form.

The format contract is an *observable the grader scores separately*; today it depends on the
LLM emitting the exact string.

## Design

A deterministic **format gate** applied to `answer.message` just before `vm.answer`,
**after** the outcome decision (Phase 2) and refs (Phase 1):

1. **Typed formatters (code).** When `intent.answer_shape` declares a typed shape, render the
   computed value with the matching formatter:
   - money → `format_eur(value)` → `"EUR %d.%02d"`;
   - boolean → the tenant's yes/no tokens parsed from `/AGENTS.MD` (`<YES>`/`<NO>` or custom);
   - count → substitute the computed integer into the **exact format string declared by
     `intent.answer_shape`** (which echoes the instruction's required format clause — the
     same string the `success_criteria` regex validates against); no other source;
   - table/quote → exact TSV per `answer_shape`.
   These overwrite the model's message — format never depends on the model.
2. **Gate guards (mirror exoskeleton `answer_formatter`).**
   - **Preserve non-OK messages** — a denial/clarification message passes through unchanged.
   - **Already-exact short-circuit** — if the message already equals the required token /
     matches the required regex, leave it.
   - **Normalise-only** — the gate may reshape but never corrupt; empty/failed formatting
     falls back to the original message; a wrongly-prepended `OUTCOME_*` prefix is stripped.
3. **AGENTS.MD tokens** are read from the per-trial `/AGENTS.MD` (already loaded by the
   orchestrator) so custom yes/no tokens are honoured.

## Components touched

- **`agent/format_gate.py`** (new): `format_answer(message, intent, answer_shape, agents_md)
  -> str` + `format_eur`, `bool_tokens`, `already_exact`.
- **`agent/pipeline.py`**: apply `format_answer` to `answer.message` immediately before
  `vm.answer`.
- **`agent/interpreter.py`**: ensure the typed computed value (not just the rendered string)
  is available to the gate (carry the raw value alongside the message slot).

## Error handling

Best-effort, never raises: a formatting failure returns the original message. Non-OK
outcomes are never reshaped.

## Testing

- Unit: `format_eur` rounding/locale; bool-token resolution from a synthetic `/AGENTS.MD`;
  already-exact short-circuit; non-OK preserve.
- Integration: replay money/boolean/count tasks (t04, t06, t07, t08, and the `EUR` regex
  task) → message matches the `success_criteria` regex.
- Regression: full suite green; the gate must not alter any message that already passed.

## Success criteria

- Format-class `verify fail` / `Answer should contain` feedback eliminated on the affected
  tasks.
- No regression on tasks whose message already matched.

## Risks & mitigations

- **Wrong shape inference** (gate reshapes a free-text answer it shouldn't) → gate only fires
  when `answer_shape` declares a typed shape; free-text passes through.
- **Locale/rounding** on money → single `format_eur` helper, unit-tested for half-up vs
  truncation against the grader's expectation.

## Non-goals

- Ref production (Phase 1), outcome decisions (Phase 2).
- No LLM reformat call in the default path — typed formatters are pure code; an optional
  fast-tier reshape for residual free-text answers is a future extension, not this phase.
