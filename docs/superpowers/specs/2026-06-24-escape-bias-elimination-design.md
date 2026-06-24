---
chain:
  intent: null
review:
  spec_hash: de80843a2502353f
  last_run: 2026-06-24
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: INFO
      section: "## Success criteria"
      section_hash: fd8064800467ada4
      text: >-
        "PLAN input tokens per call drop materially" (and the Phase-3 verify
        line) uses the vague term "materially" without a numeric threshold.
        A criterion exists in spirit (the associated token-count regression
        test) but no explicit target (e.g. a % or absolute drop) is stated.
      verdict: fixed
      verdict_at: 2026-06-24
---

# Escape-bias elimination — deterministic resolve, grounded denial, lean structured PLAN

**Date:** 2026-06-24
**Branch:** `determinism`
**Scope:** `agent/{investigate,interpreter,decide,verify,reason,pipeline,llm,learned_store}.py` + a new
resolution helper. **No task-specific prompt rules** (project rule: knowledge flows through code
mechanisms / LEARN, never task-specific prose in `data/prompts/*`).

## Problem

A full `deepseek-v4-flash` run on this branch (`logs/20260624_194401`, 45/54 tasks traced
before a network hang froze the run) shows a pathological **escape-outcome bias** in the
submitted outcomes:

| Outcome | n | % |
|---|---|---|
| `OUTCOME_NONE_UNSUPPORTED` | 24 | 53% |
| `OUTCOME_DENIED_SECURITY` | 10 | 22% |
| `OUTCOME_OK` | 7 | 16% |
| `OUTCOME_NONE_CLARIFICATION` | 4 | 9% |

**75% of tasks terminate in an escape outcome** (gave up / refused) rather than computing an
answer. (These are *submitted* outcomes, not grader scores — `SubmitRun` never ran because the
process hung; see Phase 5. The distribution is decisive on its own and is model-independent:
the same give-up/deny behaviour is reported on Opus. Note the deepseek-flash *score* baseline is
~3.64%, not the 32% of a stronger model — do not frame this as a regression-vs-32%.)

The give-up messages cluster into buckets:

- **B1 — entity-resolve give-up → UNSUPPORTED** (~14: t01,t03,t04,t08,t13,t17,t18,t19,t20,
  t32,t33,t52,t53). "product/store not found" for an entity the task *presumes exists*. The
  deterministic exact-equality SQL does not match the seeded data (value formatting such as
  `volume='8'` vs seeded `'8 l'`, case, whitespace, unit suffix, synonym).
- **B2 — ungrounded denial → DENIED_SECURITY** (~10: t14,t25,t26,t30,t31,t37,t42,t43,t46,t54).
  PLAN emits a security denial with no holding `deny_when`. `verify` catches it (I3 reverse,
  **19 spurious-over-refusal verify-fails in one run**) but PLAN re-emits the same denial →
  the cycle loop never converges. (Some denials may be legitimate — those have a holding
  predicate and must be preserved.)
- **B3 — answer/outcome mismatch + template leak** (~3: t05/t07 computed `<NO>` with a SKU but
  tagged the outcome `UNSUPPORTED`; t53 leaked raw IR pseudo-code into the message —
  "...is compute absolute difference between current_total_cents and old_t...").
- **B4 — input capture** (~2: t45/t47). INTENT dropped the pasted price-list rows; PLAN had no
  params → give up.
- **B5 — reliability**. No enforced hard timeout: one blocked socket froze the whole run for
  53 min (t51/t53/t55 hung mid-cycle), killing `SubmitRun` and all scores. Cycle non-convergence
  also burns budget (t52: 329 s / 4 cycles / 33.8k output tokens).

## Root cause

A single escape-outcome bias produced by three reinforcing mechanisms, amplified by a bloated
prompt and missing timeouts:

1. **Brittle deterministic matching + unverified resolution.** `investigate.sufficient()`
   (`agent/investigate.py:159`) skips every required_ref whose grounding is "PLAN's
   responsibility" (`g is None`, e.g. a `record_path` resolved from a `$source`). So the key
   entity's resolution is **nobody's verified responsibility** before the answer is computed:
   the investigator punts to PLAN, PLAN writes exact-match SQL blind to the actual value
   formats, gets 0 rows, and reads "0 rows" as "does not exist" → `UNSUPPORTED`.
   `decide.py` already has an `anti_give_up_ok` rung, but it cannot help — with the entity
   unresolved there is nothing to compute an OK answer from.
2. **Denial as a safe default.** When unsure, the model emits `DENIED_SECURITY`. The pipeline
   rejects it in `verify` (reactive) instead of rewriting it in `decide` (proactive), so the
   correction loop re-emits the same denial.
3. **Non-converging correction.** iLEARN distills *plumbing* lessons (get-vs-column,
   ExecResponse unwrapping, ref naming) and accumulates **contradictory** rules
   (t20: r001 "branch to UNSUPPORTED on empty" ↔ r006 same, vs the inventory rule "return OK
   with 0") — the loop oscillates and exhausts the cycle budget. Each retry digests a large,
   unstructured PLAN prompt (~5.2k input tokens: anti-patterns + INTENT spec + facts + an
   ~8k-char `CREATE INDEX` schema **dump** that is pure noise + brief + step-lessons + learned
   rules + oracle atoms), degrading a weak model's structured output further.

## Phased approach

One spec, five phases in priority order. Each is independently testable and shippable. Phase 5
(timeout) lands first in implementation order despite low bucket-count, because without it no
clean scored measurement is possible.

### Phase 1 — Resolve-or-prove (bucket B1, ~14 tasks; highest leverage)

Make key-entity resolution a **verified, deterministic** step that runs before PLAN and proves
existence (or proves genuine absence) instead of guessing.

- **Normalized resolution probe** (new helper, e.g. `agent/resolve.py`): given the entity
  descriptors INTENT already extracts (brand / series / model / property key-values), resolve
  candidate `product_sku` / `record_path` with **progressive relaxation**, all general data
  hygiene (no task-specific values):
  1. exact equality;
  2. normalized equality — `trim`, case-fold, collapse internal whitespace, and unit-suffix
     normalization on `property_value_text` (`'8 l'`↔`'8'`, `'1000 ml'`↔`'1000'`, `'900 mm'`↔
     `'900'`) applied symmetrically to query literal and column;
  3. token-subset `LIKE` on `product_name` / descriptor tokens as a last resort.
  Bind the first non-empty candidate set into `Brief.env` (real SKU + record_path) so PLAN
  builds its aggregation against a *known-resolving* entity.
- **`investigate.sufficient()` no longer punts.** A required_ref whose source is a
  `record_path` for a key entity must be **actually resolved** by the probe; if unresolved,
  sufficiency is false → an extra probe/relaxation step runs (within the step budget) before
  the investigator may stop.
- **No "0 rows ⇒ does not exist" for a presumed-existing entity.** When
  `intent.desired_outcome == OUTCOME_OK` and `required_refs[OK]` includes a key-entity
  `record_path`, an empty resolve must not short-circuit to `UNSUPPORTED`; it triggers the
  relaxation ladder first. `UNSUPPORTED` is permitted only after the ladder is exhausted.

**Verify:** unit tests for `resolve.py` on synthetic rows with formatting/case/unit-suffix
skew (assert relaxation finds the row exact-match misses); a pipeline test that an OK-task with
a format-skewed product no longer submits `UNSUPPORTED`; trace check on t20 → resolves the
Milwaukee SKU and computes a count.

### Phase 2 — No ungrounded denial (bucket B2, ~10 tasks)

Move spurious-denial correction from reactive (`verify` reject → loop) to proactive
(`decide` rewrite → proceed).

- In `decide.decide_outcome`, a PLAN-authored `OUTCOME_DENIED_SECURITY` is **downgraded** to
  the next viable outcome from the ladder when **no** declared security `deny_when` holds in
  env. Denials backed by a holding predicate are preserved unchanged (legitimate guest/role
  denials must still deny).
- Net effect: the loop no longer spins on a denial `verify` would only reject; the spurious
  case is resolved in one pass. `verify`'s I3-reverse check stays as a backstop.

**Verify:** test that a PLAN emitting DENIED with no holding `deny_when` is rewritten (not
looped) and proceeds to compute; test that a genuine guest-privileged-op denial (holding
`deny_when`) is preserved. Trace check on a B2 task → single cycle, no spurious-denial verify-
fail.

### Phase 3 — Prompt diet + structured-output chain (bucket B3 + quality multiplier)

Shrink and structure the reasoning prompt so a weak model emits a correct plan reliably.

- **Drop the schema-index dump.** Replace the `CREATE INDEX …` block in the INTENT/PLAN
  pre-phase facts with a compact `table(col, col, …)` list (names only). General; large input
  reduction.
- **Fixed PLAN prompt skeleton.** Stable section order, minimal, deduplicated; learned rules
  and oracle atoms in clearly delimited, capped blocks.
- **Decompose the monolithic PLAN emit into a short structured-output chain** with a brief CoT
  scaffold per step: `resolve-spec` (consumes Phase-1 candidates) → `compute-spec` →
  `answer-spec`, each a tiny validated schema. Evaluate replacing the ReAct INVESTIGATE loop
  with a **deterministic probe sequence** (router LLM only where a branch genuinely needs it).
  *This is the largest/riskiest item; the implementation plan will spike a minimal first cut and
  gate it behind a flag for A/B before defaulting on.*
- **No unrendered template in the message** (fixes t53): the interpreter/format-gate must
  detect an unresolved answer template and route to the next cycle (or a safe default), never
  emit raw IR text.
- **Computed-answer ⇒ non-escape outcome** (fixes t05/t07): when a typed answer value was
  computed, `decide` must not tag `UNSUPPORTED`.

**Verify:** assert the PLAN prompt no longer contains `CREATE INDEX`; token-count regression —
PLAN-call input tokens drop **≥25%** vs the current ~3,080-token user message (the `CREATE INDEX`
dump alone is ~8k chars ≈ 2k tokens); test that an unresolved template never reaches
`vm.answer`; A/B the structured chain vs monolith on the task set (OK-rate, tokens, cycles).

### Phase 4 — LEARN hygiene (anti-regression)

Stop the correction loop from re-bloating and self-contradicting.

- **Contradiction detector** in `apply_learn_diff` / distillation: a new rule that gives
  outcome guidance opposite to an active rule deactivates the loser (or is refused), instead of
  stacking both.
- **Semantics-not-plumbing distillation:** on an empty-resolve failure, iLEARN distills a
  data-semantics lesson ("sample real property values; relax the match") — a general iLEARN
  improvement, not a task-specific rule.
- **Enforce + dedup the active cap:** `ECOM_LEARN_MAX_ACTIVE` strictly enforced; near-duplicate
  active rules collapsed (mirror the oracle dedup-cosine idea at the rule level).

**Verify:** test that adding a contradicting rule deactivates the prior; test the active count
never exceeds the cap; replay t20's learned history → no r001↔r006 oscillation.

### Phase 5 — Reliability (lands first in impl order)

- **Hard timeout on every network call** — LLM providers, the Ollama embedding endpoint
  (oracle), and BitGN harness RPCs. Audit each path; the 53-min hang implies at least one path
  ignores `ECOM_LLM_HTTP_READ_TIMEOUT_S`.
- **Per-task wall-clock budget.** On exceed → terminate that task with a terminal outcome so
  the run proceeds and `SubmitRun` still produces scores. One task must never freeze the run.

**Verify:** inject a hanging endpoint in a test → the task fails fast with a terminal outcome
and the run completes; a full run completes end-to-end and emits the `ИТОГО` table.

## Out of scope

- Model selection / swap (goal is to lift deepseek-flash via logic, not a stronger model).
- Task-specific rules in `data/prompts/*` (forbidden by project rule).
- The pre-existing orphan-vector accumulation in the oracle vec cache.
- B4 input-capture (t45/t47) beyond what the Phase-3 prompt restructure incidentally fixes;
  if it persists it gets its own follow-up spec.

## Verification (overall)

1. Land Phase 5 (timeout) → a full deepseek-flash run completes and emits grader scores
   (current state: cannot, it hangs).
2. Land Phase 1 → clean scored re-run; measure OK-rate delta vs the escape distribution above.
   Expectation: the bulk of B1's ~14 `UNSUPPORTED` give-ups convert toward OK.
3. Phases 2–4 → incremental scored re-runs, each measured independently.

## Success criteria

- A full deepseek-flash run completes without hanging and produces grader scores.
- The submitted-outcome distribution shifts decisively away from escape outcomes: the B1
  "not found" give-ups and B2 spurious denials are largely eliminated (legitimate denials
  preserved).
- PLAN input tokens per call drop **≥25%** (vs the current ~3,080-token user message) after the
  schema-dump removal.
- No new task-specific prompt rules introduced; all behaviour change is in code mechanisms.
- Existing tests stay green; new per-phase tests pass.
