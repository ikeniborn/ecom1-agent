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
toggling the flag off on a `make task` subset, not by intuition.

**Load-bearing threshold (decision rule):** a subsystem is *load-bearing* iff toggling it
off drops **≥1 task** from pass→fail on the measured subset. Load-bearing → KEEP; drops
0 tasks → REMOVE. This is the quantified criterion behind every "decision required at
review" below — Oracle/LEARN are removed unless a measured 0→drop proves them load-bearing.

## Proposed classification

### REMOVE — unproven experiments (low risk, clear win)

| Subsystem | LOC / flag | Rationale |
|---|---|---|
| `ECOM_HARNESS_DISTILL` path (`harness.py`, `harness_validate.py`, `_maybe_harness_distill`) | ~240 LOC, default 0 | Never enabled in scoring runs; candidates are warn-only; no measured effect. |
| `ECOM_INVESTIGATE_DATA_PATHS` branch (`pipeline.py:129`, seed-probe in `investigate.py`) | flag default 0, UNPROVEN | A/B never showed lift; dead-by-default branch. Remove flag + branch, keep slim seed. |
| `cc_client.py` Claude-Code-CLI tier (`ECOM_CC_ENABLED`) | 396 LOC | Subprocess OAuth tier, unused in benchmark runs; large surface in `llm.py` routing. |
| `ECOM_ORACLE_DISTILL` / `ECOM_ORACLE_VALIDATE_INLINE` inline-grader round-trips | distill paths in `pipeline.py`, `oracle_validate.py` | Default off; live grader round-trips mid-run are expensive and unproven. |

### REMOVE / DEMOTE — core mechanisms that have not paid off (decision required at review)

| Subsystem | LOC | Rationale | Default proposal |
|---|---|---|---|
| **Oracle** (`oracle.py`, `oracle_atoms.py`, `oracle_rank.py`, `oracle_validate.py`, `promote.py`, `data/oracle/*`) | ~500 + data | 78 atoms, 5% score; reference 90% agent has no analogue; conflicts with "generic engines, not retrieved knowledge". | **Remove** retrieval-into-PLAN; archive `atoms.yaml`. |
| **Per-task LEARN as primary knowledge** (`learned_store.py`, `_ilearn`, `data/learned/*`) | 214 + 1310 rules | 84% of rules deactivated; primary-knowledge-via-prose conflicts with shifting gradable decisions into code. | **Prune** 1102 inactive rules now; **demote** LEARN to a thin diagnostic aid; revisit after Phase 1 measurement. |
| **Training loop** (`ECOM_TRAIN_MAX_CYCLES`, `learn_from_grader`, `main.py` outer loop) | outer loop + pipeline | Existence justified only by LEARN; 7-cycle grind still produced 5%. | **DEFER** removal until LEARN's fate is settled; do not delete in Phase 0. |

### KEEP — core skeleton (untouched by Phase 0)

`orchestrator.py` (slim seed path), INTENT (`reason.run_intent`), INVESTIGATE
(`investigate.py` minus data-paths), PLAN (`reason.run_plan`), `interpreter.py`,
`verify.py`, `ir_models.py`, `llm.py` (minus cc tier), `trace.py`, `learned_store.py`
(slimmed). These carry the INTENT→INVESTIGATE→PLAN→verify skeleton that Phases 1–3 extend.

## Execution plan

1. Land each REMOVE as its own commit; delete the subsystem's tests with it.
2. After each commit: `uv run pytest tests/ -q` green (retained suite).
3. Strip now-dead env vars from `CLAUDE.md`, `agent/CLAUDE.md`, `.env.example`.
4. Regenerate affected `docs/wiki/` pages via `iwiki:iwiki-ingest`; `/iwiki-lint` clean.
5. Archive removed data corpora (`data/oracle/`, inactive `data/learned` rules) under a
   `legacy/` tag or git history note — do not silently delete validated work.

## Success criteria

- `agent/` LOC reduced by **≥1000** (oracle ~500 + `cc_client` 396 + harness-distill ~240 +
  data-paths branch).
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
- **Hidden coupling** (e.g. `llm.py` routing assumes cc tier). → Tests green gate per commit
  catches breakage.
