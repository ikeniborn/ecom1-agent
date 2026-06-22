# Phase 0 — Oracle Load-Bearing Measurement & Δtasks=0 Verification

**Date:** 2026-06-22
**Branch:** `determinism`
**Plan:** `docs/superpowers/plans/2026-06-22-phase0-legacy-removal.md` (Tasks 7 & 8)
**Model:** `deepseek-v4-flash:cloud`

## Scope of this measurement

A **bounded** subset of **3 tasks — `t01`, `t38`, `t54`** — was run (operator-chosen),
not the full reference OK-set. The verdicts below are scoped to this subset and are NOT a
full load-bearing measurement. `t01`/`t38`/`t54` are all hard, historically-failing tasks
(see `data/learned/` history and prior reports); none of them passes on the current model.

## Runs

| Run | Config | Log dir |
|---|---|---|
| A | Oracle ON (default, post-removal HEAD) | `logs/20260622_190926_deepseek-v4-flash-cloud` |
| B | Oracle OFF (`ECOM_ORACLE_ENABLED=0`) | `logs/20260622_191402_deepseek-v4-flash-cloud` |

### Run A — Oracle ON (also serves as the post-removal baseline for Δtasks)

| Task | Score | Outcome |
|---|---|---|
| t01 | 0.00 | expected OUTCOME_OK, got OUTCOME_NONE_UNSUPPORTED |
| t38 | 0.00 | expected OUTCOME_OK, got OUTCOME_DENIED_SECURITY |
| t54 | 0.00 | answer missing required reference `/docs/security.md` (OUTCOME_DENIED_SECURITY) |

**P_on = ∅** (0/3 pass).

### Run B — Oracle OFF

| Task | Score | Outcome |
|---|---|---|
| t01 | 0.00 | expected OUTCOME_OK, got OUTCOME_NONE_UNSUPPORTED |
| t38 | 0.00 | expected OUTCOME_OK, got OUTCOME_DENIED_SECURITY |
| t54 | 0.00 | expected OUTCOME_OK, got OUTCOME_DENIED_SECURITY |

**P_off = ∅** (0/3 pass).

## Task 7 — Oracle load-bearing verdict (on this subset)

`dropped = P_on \ P_off = ∅` → **0 tasks dropped pass→fail** when Oracle retrieval was
toggled off.

Per the spec's load-bearing threshold ("*load-bearing iff toggling it off drops ≥1 task
pass→fail on the measured subset*"), Oracle is **NOT load-bearing on {t01, t38, t54}**.
This is vacuously true here: no task in the subset passes with Oracle ON, so there is no
pass for Oracle to be carrying.

**This does NOT authorize Oracle removal.** The subset is 3 already-failing tasks, not the
reference OK-set. A defensible Oracle-removal decision requires the same ON/OFF measurement
over the tasks that actually reach `OUTCOME_OK` in the reference runs (the set Oracle could
plausibly be carrying). That fuller measurement is deferred. Recommendation: before removing
Oracle retrieval, run `ECOM_ORACLE_ENABLED=0` against the reference OK-set and confirm
0 pass→fail drops there.

## Task 8 — Δtasks = 0 verification (Phase 0 dropped no task)

Pre-removal reference outcomes for the subset (from `logs/20260621_232850_*` /
`logs/20260622_063422_*`): `t01` FAIL (0.00), `t38` FAIL (0.00), `t54` FAIL (0.00).

Post-removal (Run A, Oracle ON, current HEAD): `t01` FAIL, `t38` FAIL, `t54` FAIL.

Pass-count: **pre = 0, post = 0 → Δtasks = 0** on the subset. No task regressed from
pass→fail across the Phase 0 removals. (Per-task *outcome labels* vary run-to-run — e.g.
`t38` reads NONE_UNSUPPORTED in reference vs DENIED_SECURITY now — because the benchmark
re-seeds data every StartRun and the model is non-deterministic; the pass/fail bit is the
stable signal, and it is unchanged.)

## Supporting Phase 0 facts (Task 8, non-benchmark)

- **`agent/` LOC: 6403 → 6186 = −217** across the six Phase 0 commits (`dffb9bc^..HEAD`).
  `cc_client.py` (396 LOC) was intentionally KEPT (separate benchmark-passing tier); the
  largest remaining removable block (Oracle retrieval, ~500 LOC) is pending the Task 7
  decision above.
- **Skeleton intact:** `interpreter.lint()` is still wired to the retained harness lint
  engine (`harness.load_checks` / `harness.handler_for` / `_HANDLERS`); all agent modules
  import cleanly. INTENT→INVESTIGATE→PLAN→verify is unchanged.
- **Retained suite:** green on the targeted, non-live-VM test files run per commit (the full
  `pytest tests/` cannot complete in this environment — several tests block on a live
  VM/grader; this is environmental, not a Phase 0 regression).

## Commits (Phase 0)

```
5498ee4 docs(wiki): regenerate pages after Phase 0 legacy removal
f40d4be docs: strip env vars for removed harness/oracle-distill + data-paths paths
21f0d81 test(learn): cover prune_file dry-run + write-once idempotence
5e49c12 chore(learn): prune inactive rules from data/learned/*.yaml
03db1bb refactor(investigate): remove unproven data-paths seed/probe branch
e886443 refactor(pipeline): remove in-pipeline oracle-distill round-trips
dffb9bc refactor(harness): remove unproven harness-distill path, keep lint engine
```
