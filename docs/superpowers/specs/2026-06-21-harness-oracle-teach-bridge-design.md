---
review:
  spec_hash: 5ca33c546416695a
  last_run: 2026-06-21
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: INFO
      section: "Architecture / 1. Orchestrator"
      section_hash: 4dd39c1f6cd72583
      text: >-
        Step 2 reads "harness.load_checks() -> map check_id -> {kind, message,
        source_task}", but load_checks() returns list[dict]; the orchestrator must
        build the check_id->fields mapping itself. Wording only; behaviour is correct.
      verdict: fixed
      verdict_at: 2026-06-21
chain:
  intent: null
---
# Harness→Oracle "Teach" Bridge — Design

**Date:** 2026-06-21
**Status:** Approved (design), pending implementation plan
**Topic:** Second slice of the harness→oracle feedback bridge. Distil a positive `method` oracle
atom from a frequently-firing `data/harness/checks.yaml` lint check, then auto-promote it only
when a full end-to-end re-run of the check's source task — with the candidate atom injected into
PLAN — scores 1.0 against the live grader.

## Background / Problem

The agent has two learnable knowledge stores of opposite polarity and opposite consumption
(established in the prior slice's spec, `2026-06-21-lint-firing-telemetry-design.md`):
`oracle` holds positive `method` atoms consumed softly by PLAN (semantic retrieval); `harness`
holds negative lint checks enforced hard at plan-time. They form a generate-then-check loop, not
a merge.

A harness check that keeps firing means the LLM keeps producing a plan that trips an anti-pattern.
The hard gate blocks it (good) but teaches nothing — so the same mistake recurs across tasks, each
time costing a blocked PLAN cycle. The missing positive `method` atom — distilled from the firing
check and injected into PLAN — would steer generation away from the anti-pattern from cycle 1.

The prior slice instrumented which checks fire (`lint_fire` trace records + `scripts/lint_report.py`
aggregator). **This slice consumes that signal**: turn the hottest checks into validated positive
atoms. The check's `message` already encodes the fix verbatim (e.g. `chk_column_on_scalar`:
*"'column' expects list[dict]; use 'get' for a single row"*), so it is a high-quality positive seed.

## Scope

An **offline** tool that, per hot check: distils a candidate `method` atom seeded by the check
contract, validates it by re-running the check's source task end-to-end with the candidate injected
into PLAN, and promotes (candidate→active) on a grader score of 1.0. Reuses the existing
distil/validate/promote machinery; adds one new validation function and one tiny retrieval seam.

## Non-Goals

- In-pipeline (live, mid-run) distillation/promotion — deferred; this stays offline like the
  telemetry slice and the existing offline-promote pattern.
- The reverse bridge direction (harden an oracle `anti` atom into a check) — no `anti` atoms exist.
- A new always-on ledger file (the empty, unused `data/oracle/history.jsonl` is the cautionary
  precedent — idempotency rides cosine dedup instead, see below).
- HTML reporting, multi-check batching beyond a simple per-invocation cap.

## Decisions (from brainstorming)

- **Placement: offline script.** Zero runtime cost; grader round-trips happen out of band.
- **Validation gate: efficacy (full pipeline).** A grounding-only re-run of a known-good plan
  barely filters (it always passes); a dedup-only gate skips the grader entirely (conflicts with
  the project's grader-validation value). The efficacy gate runs the check's source task through
  the *whole* pipeline (INTENT → INVESTIGATE → PLAN loop) with the candidate atom retrievable, so
  the atom is tested in its real consumption path.

## Architecture

Three units; the first orchestrates, the other two are small, independently testable additions.
Everything else is reuse.

### 1. Orchestrator — `scripts/harness_to_oracle.py` (new)

Offline CLI. Flow:

1. `lint_report.aggregate(trace_dir)` → per-`check_id` fire stats (reuse, prior slice).
2. `harness.load_checks()` → `list[dict]`; the orchestrator indexes it by `check_id` to look up each check's `{kind, message, source_task}`.
3. Select **hot** checks: `fires >= ECOM_BRIDGE_MIN_FIRES`, ranked by fires desc, capped at
   `ECOM_BRIDGE_MAX_ATOMS` per invocation. Skip (logged) any check with an empty `source_task`,
   or whose source task lacks a persisted known-good plan (`data/heuristics/<src>.plan.json`) and
   intent (`<src>.intent.json`).
4. Per selected check:
   - **distil** — `oracle.distill(design_intent=<source intent.objective>, error=<seed>,
     script_code=<good_plan json>, source_task=<check.source_task>, polarity="method",
     status="candidate")`. The seed string:
     `f"Avoid the anti-pattern caught by lint check '{check_id}' ({kind}): {message}. State the correct method generally."`
     `distill` strips run-specific values and dedups on insert (`add_candidate`,
     `ECOM_ORACLE_DEDUP_COSINE`) — a near-duplicate of an existing atom is dropped and `distill`
     returns `None` (treated as "already covered", logged as skip). This is the idempotency
     mechanism: re-running the script never rebloats.
   - **validate** — `validate_atom_via_full_run(atom, check.source_task)` (unit 2).
   - **promote** — on `True`: `oracle.promote(atom.id, validated_by="harness-bridge",
     validated_at=str(date.today()))`. On `False`: leave candidate (logged).
5. Print a summary: per check — distilled? validated? promoted? else skip reason.

`main(argv)` uses argparse: optional positional `trace_dir` (default `logs`). No LLM/grader logic
of its own — it composes the reused functions.

### 2. Efficacy validator — `agent/oracle_validate.py` (extend)

Mirror of the existing `grade_candidate`/`validate_atom_via_grader`, but the "answer builder" is
the full agent instead of a fixed plan replay.

```
def grade_full_run(task_id, force_active_id):
    # StartRun -> per trial: start_trial; if t.task_id == task_id:
    #   set ECOM_ORACLE_FORCE_ACTIVE=force_active_id
    #   run_agent({}, t.harness_url, t.instruction, task_id=task_id)   # full pipeline; it answers the VM
    #   (finally) pop ECOM_ORACLE_FORCE_ACTIVE
    # end_trial each; submit_run(force=True); return parse_score(res, task_id)

def validate_atom_via_full_run(atom, task_id, min_score=1.0) -> bool:
    # best-effort: any failure -> False (atom stays candidate); never raises.
    score, _detail = grade_full_run(task_id, atom.id)
    return score is not None and score >= min_score
```

Reuses `_URL`/`_BID`/`_KEY`, `parse_score`, `HarnessServiceClientSync`, `VMAdapter`. Unlike
`grade_candidate`, it does NOT call `vm.answer` itself — `run_agent`→`run_pipeline` already answers
exactly once. `run_agent` is imported lazily inside `grade_full_run` (avoids an import cycle at
module load: `oracle_validate` is imported by `pipeline`, and `run_agent` pulls in the pipeline).

The target trial must be answered+ended before the next `start_trial` (the harness serialises
trials — a later start force-closes the active one); the per-trial `start → run_agent → end_trial`
loop body satisfies this.

### 3. Retrieval injection seam — `agent/oracle.py` (extend)

`KnowledgeOracle._active()` currently returns `[a for a in self.atoms if a.status == "active"]`.
A `candidate` atom is therefore invisible to `retrieve()` (both `_cosine_topn` and `_tag_fallback`
iterate `_active()`). Add a force-active set read from the environment:

```
def _active(self):
    force = {x for x in os.environ.get("ECOM_ORACLE_FORCE_ACTIVE", "").split(",") if x}
    return [a for a in self.atoms if a.status == "active" or a.id in force]
```

This is the single, minimal seam that lets the efficacy validator make exactly one candidate atom
retrievable into PLAN for the duration of one validation run — without mutating `data/oracle/atoms.yaml`
before promotion. The env var is set/cleared by `grade_full_run`; in normal runs it is unset and
behaviour is identical to today.

## Reused, unchanged

`lint_report.aggregate`, `harness.load_checks`, `oracle.distill` (+ `add_candidate` dedup),
`oracle.promote`, `data/heuristics/<tid>.intent.json` / `<tid>.plan.json` persistence,
`parse_score`. No change to the pipeline, INTENT, PLAN, or any prompt.

## Data Flow

```
logs/**/*.jsonl ──aggregate──> hot checks ──harness.load_checks──> (kind, message, source_task)
                                                       │
                              per hot check:           ▼
   oracle.distill(seed=message) ──> candidate atom (written to atoms.yaml)
                              │
   grade_full_run(source_task, atom.id):
       StartRun ─ ECOM_ORACLE_FORCE_ACTIVE=atom.id ─ run_agent(full pipeline) ─ submit ─ score
                              │
        score>=1.0 ──> oracle.promote(atom.id)  (candidate -> active)
        else        ──> leave candidate
```

## Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `ECOM_BRIDGE_MIN_FIRES` | 3 | A check must have fired at least this many times to be a bridge candidate. |
| `ECOM_BRIDGE_MAX_ATOMS` | 3 | Max checks processed per invocation (each costs one full grader run). |
| `ECOM_ORACLE_FORCE_ACTIVE` | (unset) | Comma-separated atom ids treated as active by `_active()` for one validation run; set/cleared internally by `grade_full_run`. |

## Error Handling

- `scripts/harness_to_oracle.py`: per-check `try/except` — one failing check never aborts the
  others. A check with no `source_task` or no persisted known-good plan/intent is skipped with a
  logged reason, not an error.
- `validate_atom_via_full_run`: best-effort — any failure (no live grader, run error, score
  unavailable) returns `False`, so the atom stays a candidate. Never raises.
- `ECOM_ORACLE_FORCE_ACTIVE` is cleared in a `finally` so a crashed validation never leaks a
  force-active id into a later run.
- Promotion only ever flips `candidate → active`; a failed validation makes no persisted change.

## Testing

- **`_active` force-active (`agent/oracle.py`):** a `candidate` atom whose id is in
  `ECOM_ORACLE_FORCE_ACTIVE` is included by `_active()`; with the env unset it is excluded.
- **`validate_atom_via_full_run` (`agent/oracle_validate.py`):** monkeypatch `grade_full_run` to
  return `(1.0, [])` → `True`; `(0.0, [...])` → `False`; raising → `False`. Separately, with
  `grade_full_run` exercising a fake harness client + monkeypatched `run_agent`, assert
  `ECOM_ORACLE_FORCE_ACTIVE` is set during the `run_agent` call and cleared afterward (even when
  `run_agent` raises).
- **`scripts/harness_to_oracle.py`:** with `aggregate`, `harness.load_checks`, `oracle.distill`,
  `validate_atom_via_full_run`, and `oracle.promote` all monkeypatched: assert only checks with
  `fires >= ECOM_BRIDGE_MIN_FIRES` are selected; at most `ECOM_BRIDGE_MAX_ATOMS` are processed;
  `promote` is called iff validation returns `True`; a check with empty `source_task` or a
  `distill`-returns-`None` (dedup) path is skipped without calling `promote`.

## Open Questions

None blocking. The efficacy run reuses the agent's own embedding backend for retrieval; if that
backend is unreachable the candidate cannot be retrieved and validation conservatively returns
`False` (atom stays candidate) — acceptable, same failure posture as the rest of the oracle.
