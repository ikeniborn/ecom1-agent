---
review:
  spec_hash: 47f7f6d60c12ccda
  last_run: 2026-06-22
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: CRITICAL
      section: "Success criteria"
      section_hash: 460777eb55df545e
      text: >-
        The guaranteed ">=1000 LOC" success criterion counts oracle ~500 LOC,
        but Oracle removal is explicitly "decision required at review" in the
        REMOVE/DEMOTE table (may be kept if load-bearing). Without oracle the
        firm REMOVE items (cc_client 396 + harness-distill 240 + data-paths
        branch) sum to ~636 < 1000, so the headline acceptance gate is
        contingent on an undecided removal. Contradiction between Success
        criteria and the decision-gated classification.
      verdict: fixed
      verdict_at: 2026-06-22
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "Proposed classification / Non-goals"
      section_hash: f270b6237e748042
      text: >-
        REMOVE/DEMOTE proposes "demote LEARN to a thin diagnostic aid" as a
        Phase 0 action, while Non-goals states "defer the structural decision to
        post-Phase-1 measurement". Demotion is itself a structural change ->
        tension between "demote now" and "defer the structural decision".
      verdict: fixed
      verdict_at: 2026-06-22
    - id: F-003
      phase: clarity
      severity: WARNING
      section: "Proposed classification"
      section_hash: f270b6237e748042
      text: >-
        "Demote LEARN to a thin diagnostic aid" has no DoD/acceptance criterion:
        what "thin" means or how completion is verified is undefined.
      verdict: fixed
      verdict_at: 2026-06-22
    - id: F-004
      phase: clarity
      severity: WARNING
      section: "Audit methodology"
      section_hash: acea6f69608a2b7a
      text: >-
        The load-bearing decision relies on toggling flags off on "a make task
        subset" / "the measured subset", but which tasks comprise the subset is
        never defined. Every KEEP/REMOVE verdict depends on an unspecified,
        non-reproducible subset.
      verdict: fixed
      verdict_at: 2026-06-22
chain:
  intent: null
---

# Phase 0 — Current-Implementation Audit & Legacy Removal

**Status:** Draft for review
**Date:** 2026-06-22
**Branch:** `determinism` (off `heuristics`)
**Build order:** Phase 0 → Phase 1 (ref-grounding) → measure → Phase 2 → Phase 3

## Goal

Shrink and de-risk `agent/` before the determinism refactor. Audit every subsystem,
remove approaches that have not moved the benchmark and carry ongoing maintenance cost,
and land a leaner, fully-understood baseline. Phase 0 changes are **subtractive only** —
no new behaviour, no new deterministic stages (those are Phases 1–3).

## Motivating evidence (measured 2026-06-22)

- **Completed run `20260621_232850` (55 tasks, `deepseek-v4-flash:cloud`):**
  `OUTCOME_OK = 3/55 = 5%`. Outcome mix: CLARIFICATION 21, DENIED_SECURITY 18,
  UNSUPPORTED 12, OK 3. (An earlier baseline was ~32%.) The current learning/oracle
  apparatus is not delivering.
- **`agent/` = 6403 LOC.** Largest: `llm.py` 756, `orchestrator.py` 721, `pipeline.py`
  617, `trace.py` 586, `investigate.py` 400, `cc_client.py` 396, `interpreter.py` 390.
- **LEARN store: 1310 distilled rules across 55 files; 208 active, 1102 (84%) deactivated.**
  The per-task LEARN loop over-produces; deactivated rules are pure accretion.
- **Oracle: 78 atoms (all `active`); ~500 LOC** across `oracle.py`, `oracle_validate.py`,
  `oracle_atoms.py`, `oracle_rank.py`, `promote.py` plus distill paths in `pipeline.py`.
- **Default-off / unproven flags:** `ECOM_ORACLE_DISTILL=0`, `ECOM_HARNESS_DISTILL=0`,
  `ECOM_INVESTIGATE_DATA_PATHS=0` (recorded UNPROVEN).
- **Reference (`muxx/bitgn-ecom1-exoskeleton`, ~90% on lighter models)** has no
  oracle/LEARN equivalent: domain knowledge lives in generic deterministic engines, not in
  a retrieved atom bank or per-task prose rules. This is the direction Phases 1–3 take.

## Audit methodology

For each subsystem, record a row: **(LOC, flag default, call sites, run-data effect,
conflict with the determinism thesis)** → classify **KEEP / REMOVE / DEFER**.

"Run-data effect" = does the subsystem demonstrably flip any task from fail→pass in the two
most recent runs (`logs/20260621_232850_*`, `logs/20260622_063422_*`)? Measured by
toggling the flag off on the **measured subset** (defined below), not by intuition.

**Measured subset (frozen, reproducible):** the union of — (a) every task that reached
`OUTCOME_OK` in either reference run (the pass-set Phase 0 must not regress), and (b) every
task whose trace in those runs shows the subsystem actually firing (oracle atom injected,
LEARN rule applied, or the flag-gated branch entered). Set (b) is where the subsystem could
plausibly be load-bearing. The exact task ids of (a)∪(b) per subsystem are pinned in that
subsystem's removal-commit message, so the toggle-off measurement is reproducible.

**Load-bearing threshold (decision rule):** a subsystem is *load-bearing* iff toggling it
off drops **≥1 task** from pass→fail on the measured subset. Load-bearing → KEEP; drops
0 tasks → REMOVE. This is the quantified criterion behind every "decision required at
review" below — Oracle/LEARN are removed unless a measured 0→drop proves them load-bearing.

## Proposed classification

### REMOVE — unproven experiments (low risk, clear win)

| Subsystem | LOC / flag | Rationale |
|---|---|---|
| `ECOM_HARNESS_DISTILL` path (distill block of `harness.py`, all of `harness_validate.py`, `_maybe_harness_distill`/`_load_good_plan` in `pipeline.py`) | ~104 LOC, default 0 | Never enabled in scoring runs; candidates warn-only; no measured effect. **Lint enforcement (`load_checks`/`handler_for`/`_HANDLERS`) STAYS in `harness.py` — `interpreter.lint()` depends on it; only the distill block is removed.** |
| `ECOM_INVESTIGATE_DATA_PATHS` branch (`pipeline.py:129`, seed-probe in `investigate.py`) | flag default 0, UNPROVEN | A/B never showed lift; dead-by-default branch. Remove flag + branch, keep slim seed. |
| `ECOM_ORACLE_DISTILL` / `ECOM_ORACLE_VALIDATE_INLINE` inline-grader round-trips | distill paths in `pipeline.py` only; `oracle_validate.py` KEPT (offline `harness_to_oracle` bridge uses it) | Default off; live grader round-trips mid-run are expensive and unproven. |

### REMOVE / DEMOTE — core mechanisms that have not paid off (decision required at review)

| Subsystem | LOC | Rationale | Default proposal |
|---|---|---|---|
| **Oracle** (`oracle.py`, `oracle_atoms.py`, `oracle_rank.py`, `oracle_validate.py`, `promote.py`, `data/oracle/*`) | ~500 + data | 78 atoms, 5% score; reference 90% agent has no analogue; conflicts with "generic engines, not retrieved knowledge". | **Remove** retrieval-into-PLAN; archive `atoms.yaml`. |
| **Per-task LEARN as primary knowledge** (`learned_store.py`, `_ilearn`, `data/learned/*`) | 214 + 1310 rules | 84% of rules deactivated; primary-knowledge-via-prose conflicts with shifting gradable decisions into code. | **Prune** 1102 inactive rules now — subtractive, no behaviour change. **Defer** any structural demotion of LEARN's role to post-Phase-1 (see Non-goals); Phase 0 does not redefine LEARN. |
| **Training loop** (`ECOM_TRAIN_MAX_CYCLES`, `learn_from_grader`, `main.py` outer loop) | outer loop + pipeline | Existence justified only by LEARN; 7-cycle grind still produced 5%. | **DEFER** removal until LEARN's fate is settled; do not delete in Phase 0. |

### KEEP — core skeleton (untouched by Phase 0)

`orchestrator.py` (slim seed path), INTENT (`reason.run_intent`), INVESTIGATE
(`investigate.py` minus data-paths), PLAN (`reason.run_plan`), `interpreter.py`,
`harness.py` lint block (`load_checks`/`handler_for`/`_HANDLERS`), `verify.py`,
`ir_models.py`, `llm.py` **incl. the Claude-Code-CLI tier** — `cc_client.py` is KEPT
(a separate benchmark-passing LLM tier; explicitly NOT removed), `trace.py`,
`learned_store.py` (slimmed). These carry the INTENT→INVESTIGATE→PLAN→verify skeleton
that Phases 1–3 extend.

## Execution plan

1. Land each REMOVE as its own commit; delete the subsystem's tests with it.
2. After each commit: `uv run pytest tests/ -q` green (retained suite).
3. Strip now-dead env vars from `CLAUDE.md`, `agent/CLAUDE.md`, `.env.example`.
4. Regenerate affected `docs/wiki/` pages via `iwiki:iwiki-ingest`; `/iwiki-lint` clean.
5. Archive removed data corpora (`data/oracle/`, inactive `data/learned` rules) under a
   `legacy/` tag or git history note — do not silently delete validated work.

## Success criteria

- **No numeric LOC headline.** Phase 0 removes the three unproven experiments
  (harness-distill, data-paths branch, oracle-distill paths) and prunes inactive LEARN
  rules; `cc_client.py` is KEPT (separate benchmark-passing tier). Firm `agent/` removal is
  ~150–240 LOC; the actual reduction is **reported after the run, not promised up front**.
- **Oracle stays decision-gated.** Removing Oracle retrieval-into-PLAN (~500 LOC) is measured
  against the load-bearing threshold and removed only on a 0-drop result — tracked as its own
  decision, not part of any Phase 0 LOC commitment.
- All retained tests pass.
- A clean `make task` subset run reproduces the pre-removal pass-count **exactly** (Δtasks =
  0) — Phase 0 removes weight, it must not by itself drop a task. Any task that regresses on
  a removal proves that subsystem load-bearing (per the threshold above) → revert that one
  removal, document why.

## Non-goals

- No new deterministic stages (Phases 1–3).
- No prompt edits.
- No final verdict on LEARN/training architecture — Phase 0 prunes the dead 84% and defers
  the structural decision to post-Phase-1 measurement.

## Risks & mitigations

- **Oracle/LEARN currently carry a few tasks.** → Toggle-off subset measurement before
  deletion; keep `heuristics` branch as the revert point.
- **Hidden coupling** (e.g. removing the harness distill block must not break `interpreter.lint()`,
  which depends on the retained `harness.py` lint handlers). → Tests green gate per commit
  catches breakage.
