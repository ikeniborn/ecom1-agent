---
review:
  spec_hash: 34f0b1003895d215
  last_run: 2026-06-17
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings: []
chain:
  intent: docs/superpowers/intents/2026-06-16-prephase-ondemand-and-loop-fixes-intent.md
---
# Design: Prephase on-demand fetching + loop/oracle fixes

**Date:** 2026-06-17
**Status:** draft
**Intent:** [docs/superpowers/intents/2026-06-16-prephase-ondemand-and-loop-fixes-intent.md](../intents/2026-06-16-prephase-ondemand-and-loop-fixes-intent.md)

## Overview

The deterministic Plan-IR pipeline loops to `OUTCOME_NONE_CLARIFICATION` on
solvable tasks (`t01` proven across two runs). Three compounding causes — a
prephase that over- and under-fetches, an inert oracle, and cycles burned on
IR-syntax + an asymmetric verify gate. This design fixes all three in one pass
by splitting fact injection per phase, moving heavy data to PLAN-driven
on-demand `discovery`, and making the oracle self-fill with polarity.

The five work blocks (A–E) are independent enough to land and verify separately,
but share one acceptance run (`t01`).

## Acceptance (from intent)

Carried verbatim from the approved intent doc.

**Desired Outcomes:**
- `t01` returns `OUTCOME_OK` on a real `make task TASKS='t01'` run (product found
  via format-robust lookup), verified by running the code — not by tests.
- PLAN addresses the correct tools and catalog paths up front, derived from
  AGENTS.MD, without the full document being injected into every cycle.
- Prephase no longer dumps all facts up front; the PLAN prompt for `t01` is
  measurably smaller than the 27–29 K baseline. Real data (sample rows, docs,
  records) is fetched portionally via PLAN `discovery` steps.
- The oracle bank is non-empty and injects ≥1 relevant atom on a matching task.
- A valid `OUTCOME_NONE_UNSUPPORTED` answer can pass verify when that is the
  correct outcome (verify accepts the negative branch, not only the positive).
- IR-syntax errors no longer silently burn cycles to exhaustion.

**Done when:** `t01` returns `OUTCOME_OK` on a real `make task TASKS='t01'` run,
AND a spot-check of ≥2 previously-passing tasks still passes, AND the PLAN prompt
size for `t01` is measurably smaller than the 27–29 K baseline.

**Hard constraints (fixed):** no functional tests (verify by running real code);
never patch `data/prompts/` for task-specific fixes (generic structural rules are
allowed); `verify()` stays deterministic; `vm.answer` exactly once; no
re-seed-fragile hardcoded values.

## Architecture

One sentence: INTENT gets full facts (one frozen call); PLAN gets thin facts plus
on-demand `discovery` and oracle atoms; the oracle self-fills from the grader
result at the end of each run.

```
INTENT(full facts, frozen)
  └─ loop[ PLAN(thin facts + oracle[method+anti_pattern] + observed)
            → auto-repair → lint → interpret(discovery probes fetch data)
            → verify(criteria for the chosen outcome) → answer | iLEARN(observed) ]
  └─ end-of-run: grader score → distill an atom carrying polarity
```

The per-cycle cost driver is PLAN (it repeats). Front-loading facts onto the
single INTENT call and thinning PLAN is the main context-drift lever.

## Components

### Block A — thin prephase + AGENTS.MD tool/catalog inventory

**Files:** `agent/agents_md_parser.py` (revive), `agent/reason.py` (`_facts_block`),
`agent/orchestrator.py` (`gather_prephase_facts`, `PrePhaseFacts`).

- Revive `parse_agents_md(content) -> dict[section, lines]` (currently dead) and
  add a thin renderer that produces a compact **tool/catalog inventory**:
  available tools/RPCs + catalog/dir paths (e.g. `proc/catalog`, `proc/stores`,
  `proc/employees`, `docs`). Deterministic, 0 LLM, computed once per task.
- `_facts_block` gains a `tier` parameter (`"intent"` | `"plan"`):
  - **INTENT tier (one frozen call):** inventory + schema DDL + identity +
    `docs_inventory` + a compact security deny-rules summary (so INTENT can fill
    `constraints` / `deny_when` correctly).
  - **PLAN tier (repeated):** **thin** — inventory + schema names/DDL + identity
    + `docs_inventory` (path list). **Dropped from upfront injection:**
    `sample_rows`, full `policies` text, `target_records` bodies. PLAN fetches
    these via `discovery` on demand.
- The verbose policy glossary is no longer injected wholesale; the compact
  security deny-rules stay where security matters (INTENT tier).

**Interface contract:** `_facts_block(facts, tier="plan")`. `run_intent` calls
with `tier="intent"`, `run_plan` with `tier="plan"`. Existing callers default to
`"plan"` (thin).

**Target:** PLAN prompt for `t01` drops from ~28 K to < ~10 K chars.

### Block B — probe-then-refine (format-robust lookup)

**Files:** `data/oracle/atoms.yaml` (seed atom); no interpreter change.

- Mechanism reuses the existing loop: a PLAN `discovery` step can probe
  (`SELECT DISTINCT property_value_text …` or a small sample of the target
  table). `interpret` runs it; observed RPC output already flows back to the next
  PLAN call via the `observed` argument (`reason.py:run_plan`). The next cycle
  writes a format-correct filter. **No new phase, no new interpreter machinery.**
- The knowledge is a seeded oracle **method atom**: "an exact-equality lookup
  that returns 0 rows usually means the literal does not match the stored format
  — probe DISTINCT values or sample the table, then refine with a normalized /
  case-insensitive comparison before concluding the product is not carried."
- This atom is generic (method, not a task value) → re-seed-safe.

### Block C — oracle self-filling + polarity

**Files:** `agent/oracle_atoms.py` (`Atom` model), `agent/oracle.py` (`distill`),
`agent/pipeline.py` (`learn_from_grader` seam), `agent/reason.py` /
`oracle_atoms.build_oracle_block` (render).

- Extend `Atom` with `polarity: "method" | "anti_pattern"` (default `"method"`,
  back-compatible with existing/seed atoms).
- Distill on **both** outcomes at the `learn_from_grader` / training-cycle
  boundary ("end-of-run" signal — the grader score):
  - **pass (score = 1.0):** distill the working knowledge as an **effective
    method** atom (active).
  - **fail (score < 1.0):** distill the failure cause as an **anti-pattern**
    atom (active) — retrieved next run to steer away from the mistake.
- `build_oracle_block` renders methods under an "apply" heading and anti-patterns
  under an "avoid" heading so PLAN reads polarity unambiguously.
- **Bootstrap seed:** `atoms.yaml` is hand-seeded with the probe-then-refine
  method (Block B) plus 1–2 generic methods. Hand-authored atoms are trusted
  (verified by authorship).
- `ORACLE_VALIDATE_INLINE=0` stays the default — no live grader round-trips
  during a normal run (live grader = the intent's escalate condition).

### Block D — verify keyed-by-outcome

**Files:** `agent/ir_models.py` (`IntentSpec.success_criteria`),
`agent/verify.py`, `data/prompts/intent.md`, `agent/pipeline.py`
(`{tid}.intent.json` loader).

- Change `IntentSpec.success_criteria` from `list[PredExpr]` to
  `dict[str, list[PredExpr]]` keyed by outcome — mirroring the existing
  `required_refs` shape.
- `verify` applies only `intent.success_criteria.get(ans.outcome, [])`. A valid
  negative outcome (e.g. `OUTCOME_NONE_UNSUPPORTED`) is then gated by I2
  (in `outcome_space`) and its own criteria (typically none), so it can pass.
- `intent.md` documents the keyed shape (structural output-format rule —
  allowed).
- **Migration:** the persisted-artifact loader accepts both shapes — a bare list
  is treated as `{"OUTCOME_OK": [...]}`.

### Block E — IR-syntax: prompt + deterministic auto-repair

**Files:** `data/prompts/plan.md`, `agent/reason.py` (`run_plan`).

The normalizer runs on the raw parsed `dict` in `run_plan`, **before**
`PlanIR(**obj)` — invalid ops raise at pydantic construction, so the repair must
precede validation (not run as a post-construction pass).

- `plan.md` explicitly lists the allowed predicate ops (`LEAF_OPS` +
  `BOOL_OPS`) and the `AnswerTemplateIR` shape (`{message, outcome, refs}` only;
  message placeholders resolve from `env`, never from extra answer fields).
  Structural rules — allowed.
- A deterministic pre-lint normalizer maps common op synonyms
  (`neq`→`ne`, `!=`→`ne`, `==`→`eq`, `gte`→`ge`, `lte`→`le`) and strips unknown
  keys from `answer.*` branches, then validation runs. This turns two of `t01`'s
  four wasted cycles into valid plans.

## Data flow (per task)

1. `gather_prephase_facts` builds facts incl. the AGENTS.MD inventory.
2. INTENT (full-tier facts, frozen) → `IntentSpec` with `success_criteria` keyed
   by outcome.
3. Loop: PLAN (thin-tier facts + retrieved oracle atoms [method + anti_pattern] +
   `observed`) → auto-repair → lint → `interpret` (discovery probes fetch the
   data on demand) → `verify` (criteria for the chosen outcome) → `answer` once,
   or `iLEARN` with observed outputs → next cycle.
4. End-of-run: grader score → `distill` an atom with polarity (method on pass,
   anti-pattern on fail) into `atoms.yaml`.

## Error handling

- Auto-repair is best-effort: unknown ops it can't map fall through to the
  existing `PlanError` → `iLEARN` path (no silent acceptance of invalid IR).
- Thin PLAN facts never drop identity or security deny-rules from INTENT; the
  `verify` I3 security re-check stays independent (defense in depth).
- Distill failures (LLM returns no atom) are non-fatal — the run result is
  unchanged; the bank simply doesn't grow that cycle.
- Anti-pattern accumulation is bounded by `ORACLE_FLOOR` (cosine floor) and
  `ORACLE_K` (injection cap) — noise can't flood PLAN.

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Security regression from thinning policies | INTENT keeps compact deny-rules; `verify` I3 re-check is independent of prephase injection |
| Probe adds +1 cycle | Within `INTERPRETER_MAX_STEPS=6`; user accepted the cost |
| `success_criteria` schema change breaks persisted `intent.json` | Loader accepts both shapes (bare list → `OUTCOME_OK`) |
| Anti-pattern atoms add retrieval noise | Bounded by `ORACLE_FLOOR` + `ORACLE_K` |
| Auto-repair masks model misunderstanding | Pair it with the explicit `plan.md` op/shape list so the model also learns the correct form |

## Out of scope

- New pipeline phase (intent constraint: reuse IR `discovery`).
- LLM-graded answer checking (`verify` stays deterministic).
- Live per-atom grader validation during normal runs (escalate-gated).
- Cheaper read-only probe re-plan (skip LEARN LLM on a pure probe cycle) — noted
  as a possible later optimization, not in this design.

## Verification plan (no functional tests)

- `make task TASKS='t01'` → expect `OUTCOME_OK`; inspect the trace to confirm
  the product is found via probe-then-refine.
- Capture the PLAN prompt char/token size before vs after (intent Health Metric).
- Spot-check ≥2 previously-passing tasks for no regression.
- Confirm `atoms.yaml` is non-empty and ≥1 atom is injected into PLAN (trace).
- `LLM-call count` for `t01` reported before/after (tracked, not gated).
