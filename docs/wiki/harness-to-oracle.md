# Harness → Oracle Teach Bridge

`scripts/harness_to_oracle.py` is an offline bridge that converts frequently-firing lint checks into validated positive oracle method-atoms. Per hot check it distils a candidate `method` atom seeded by the check's contract, validates it with a full grader round-trip, and promotes it on a score of 1.0. It reuses the existing oracle distil/validate/promote machinery, so grader round-trips happen out of band rather than during a production run. See [[harness]], [[oracle]].

## Why it exists

The lint registry ([[harness]]) accumulates anti-pattern checks that block bad plans, but a repeatedly-firing check signals a recurring mistake PLAN keeps making. The bridge turns that negative signal into positive guidance: a `method` atom in the oracle bank ([[oracle#Atom Model]]) that steers PLAN toward the correct approach before the mistake is even attempted. Hot checks (many fires) are the highest-value teaching targets.

## Hot-check selection

`select_hot_checks(stats, checks, min_fires, max_atoms)` (`harness_to_oracle.py:29`) keeps checks that fired at least `min_fires` times, ranks them by fire count descending, and caps the result at `max_atoms`. `stats` is the `lint_report.aggregate` map (`check_id -> {fires, ...}`); `checks` is `harness.load_checks()`. A `check_id` present in `stats` but absent from the catalogue is ignored. See [[harness#Load / handler_for]].

## Per-check bridge

`bridge_one(check, oracle, validate_fn=validate_atom_via_full_run)` (`harness_to_oracle.py:56`) runs distil → validate → promote for ONE hot check and returns a one-line outcome string; it never raises. It seeds `oracle.distill` with the check's `kind` and `message` plus an instruction to "state the correct method generally", producing a `candidate` `method` atom. On `validate_fn` success it calls `oracle.promote(..., validated_by="harness-bridge")`. Outcomes: `PROMOTED`, `candidate` (validation < 1.0), `skip` (no artifacts / distil produced nothing / already bridged). See [[oracle#Distill]], [[oracle#Promote (Inline)]].

## Source artifacts

`_source_artifacts(source_task)` (`harness_to_oracle.py:41`) returns `(objective, good_plan_json)` for the check's `source_task`, read from `data/heuristics/{source_task}.intent.json` (objective) and `{source_task}.plan.json` (the known-good `PlanIR`). When either persisted artifact is missing it returns `(None, None)` and `bridge_one` skips the check — distil needs a real objective and a working plan to generalise from. See [[data-files#Persisted Heuristics (`data/heuristics/*.json`)]].

## Validation via full run

The default `validate_fn` is `oracle_validate.validate_atom_via_full_run`, the efficacy gate that re-runs the source task end-to-end with the candidate atom force-active in PLAN and checks the real grader score. This is why the bridge is offline-only: each candidate costs a live grader round-trip. A failed or unavailable validation leaves the atom a `candidate`; only a grader score of 1.0 promotes it to `active`. See [[oracle#Inline Validation via Grader]].

## CLI and env knobs

`main(argv)` (`harness_to_oracle.py:82`) takes an optional `trace_dir` (default `logs`) scanned recursively for `*.jsonl` lint-fire telemetry, aggregates it, selects hot checks, and bridges each. Two env knobs tune selection: `ECOM_BRIDGE_MIN_FIRES` (default 3, the hotness threshold) and `ECOM_BRIDGE_MAX_ATOMS` (default 3, the per-run promotion cap). Run with `uv run python scripts/harness_to_oracle.py [trace_dir]`.

## Tests

`tests/test_harness_to_oracle.py` covers selection and routing with no live grader: threshold/rank/cap in `select_hot_checks` (orphan check excluded), and `bridge_one` across its four outcomes — promote on validation, leave-candidate on failed validation, skip on missing source artifacts, and skip-already-bridged when dedup returns an `active` atom. A `_FakeOracle` and an injected `validate_fn` isolate the orchestration from the oracle machinery.
