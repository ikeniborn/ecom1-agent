# Harness

The lint-registry harness is the learnable plan-time check layer introduced in F8. It sits between PLAN emission and `interpret()`, providing a closed set of code-backed check handlers dispatched over a data-driven catalogue. See [[interpreter#lint — registry-driven lint dispatcher]] for the call site, [[pipeline]] for integration, and [[data-files#Harness Check Catalogue]] for the on-disk spec format.

## Overview

The design separates two axes: **kind** (code, rare change) and **instance** (data, learnable). A `kind` is a pure Python handler `(plan, spec) -> list[str]`; an instance is a check-spec entry in `data/harness/checks.yaml` declaring which kind to invoke and any kind-specific parameters. Adding a new *kind* requires a deliberate code change to `agent/harness.py`; adding new *instances* of an existing kind is a data promotion — the catalogue grows without touching Python.

## Check Kinds (handlers)

Five handlers are registered in `_HANDLERS` (`harness.py:129`). All are pure: they never raise and never call `vm.answer`.

- **`security_first`** — delegates to `lint_security_first(plan)` from `interpreter.py` (single source of truth), converts its raise into a violation list. H3 invariant: every `OUTCOME_DENIED_SECURITY` branch must precede all non-denied branches.
- **`primitive_contract`** — detects a list-consuming primitive fed from a scalar/dict producer. Configured by `prim`, `arg_index`, and `forbid_source` (a list of primitive names whose output type is scalar or dict, e.g. `first`, `get`). Catches the `first`→`column` mismatch class at plan time.
- **`primitive_exists`** — flags any `compute` step whose `prim` name is absent from the `PRIMITIVES` registry.
- **`primitive_arity`** — flags any `compute` step whose `args` count does not match the primitive's required positional arity (via `inspect.signature`).
- **`sql_stdin`** — flags an `Exec /bin/sql` step that still carries SQL in `args` with an empty `stdin` after the pre-lint repair. In practice this should never fire after [[interpreter#repair_sql_stdin]] runs, but acts as a safety net.

## Load / Save / handler_for

`load_checks(path=None) -> list[dict]` reads `data/harness/checks.yaml`; a missing or corrupt file returns `[]` (lint degrades to a no-op, never crashes). `save_checks(checks, path=None)` writes the catalogue atomically (via `p.write_text`). `handler_for(kind)` returns the pure handler or `None`; an unknown kind is skipped with a logged warning by `lint()` — the caller never errors on a novel kind. See [[data-files#Harness Check Catalogue]].

## Check Status and Severity

Each spec entry in the catalogue carries `status` (`active` | `candidate` | `inactive`) and `severity` (`error` | `warn`). The `lint()` dispatcher in `interpreter.py` applies the following logic: an `active` + `error` violation raises `InterpretError` (blocking); a `candidate` or `warn`-severity violation logs only. `inactive` entries are skipped entirely. This makes it safe to promote a new check incrementally.

## F8b: distill → validate → promote

When `ECOM_HARNESS_DISTILL=1` (default `0`), `_maybe_harness_distill(plan, error, task_id)` fires after an F1-class compute contract failure in `pipeline.py`. It calls `harness.distill(plan, error, source_task)`, which issues one reason-tier LLM call to propose a `candidate` check-spec generalising the failing step. The candidate must reference an existing kind in `_HANDLERS`; an unknown kind or a duplicate `id` is rejected and returns `None`.

When `ECOM_HARNESS_VALIDATE_INLINE=1` (default `1`, effective only with `ECOM_HARNESS_DISTILL=1`), `harness_validate.validate_check_via_grader(candidate, failing_plan, good_plan)` is called immediately. It is promotable only if the handler flags `failing_plan` AND does not flag `good_plan` (the last persisted successful `PlanIR` for the task from `data/heuristics/{task_id}.plan.json`). On success, `harness.promote(check_id)` flips the spec to `active` and the check takes effect in all subsequent cycles. Without `ECOM_HARNESS_VALIDATE_INLINE`, the candidate stays in the catalogue at `candidate` status for an offline promote. `_maybe_harness_distill` never raises — any exception is logged and swallowed. See [[pipeline#answer-once and harness distill]].

## harness_validate.py

`agent/harness_validate.py` is the validation gate for candidate check-specs (mirroring `oracle_validate.py`). `validate_check_via_grader(check, failing_plan, good_plan) -> bool` resolves the handler via `harness.handler_for(check["kind"])`, runs it against both plans, and returns `True` only when the handler flags the bad plan and does not flag the good one. No live grader round-trip is needed for structural checks — unlike oracle atoms, checks are evaluated purely over the `PlanIR` structure. See [[oracle]] for the parallel oracle validation pattern.
