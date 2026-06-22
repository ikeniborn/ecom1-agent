# Harness

The lint-registry harness is the learnable plan-time check layer introduced in F8. It sits between PLAN emission and `interpret()`, providing a closed set of code-backed check handlers dispatched over a data-driven catalogue. See [[interpreter#lint — registry-driven lint dispatcher]] for the call site, [[pipeline]] for integration, and [[data-files#Harness Check Catalogue]] for the on-disk spec format.

## Overview

The design separates two axes: **kind** (code, rare change) and **instance** (data, learnable). A `kind` is a pure Python handler `(plan, spec) -> list[str]`; an instance is a check-spec entry in `data/harness/checks.yaml` declaring which kind to invoke and any kind-specific parameters. Adding a new *kind* requires a deliberate code change to `agent/harness.py`; adding new *instances* of an existing kind is a data promotion — the catalogue grows without touching Python.

## Check Kinds (handlers)

Seven handlers are registered in `_HANDLERS` (`harness.py:169`). All are pure: they never raise and never call `vm.answer`.

- **`security_first`** — delegates to `lint_security_first(plan)` from `interpreter.py` (single source of truth), converts its raise into a violation list. H3 invariant: every `OUTCOME_DENIED_SECURITY` branch must precede all non-denied branches.
- **`primitive_contract`** — detects a list-consuming primitive fed from a scalar/dict producer. Configured by `prim`, `arg_index`, and `forbid_source` (a list of primitive names whose output type is scalar or dict, e.g. `first`, `get`). Catches the `first`→`column` mismatch class at plan time.
- **`primitive_exists`** — flags any `compute` step whose `prim` name is absent from the `PRIMITIVES` registry.
- **`primitive_arity`** — flags any `compute` step whose `args` count does not match the primitive's required positional arity (via `inspect.signature`).
- **`sql_stdin`** — flags an `Exec /bin/sql` step that still carries SQL in `args` with an empty `stdin` after the pre-lint repair. In practice this should never fire after [[interpreter#repair_sql_stdin]] runs, but acts as a safety net.
- **`sql_exact_match`** — flags a `/bin/sql` query that compares a product text attribute (`brand`, `series`, `model`, `product_name`) with raw `=` while never normalising it (`lower(trim(...))`). A generic anti-pattern guard for catalogue matching over re-seeded data, not a per-task rule.
- **`compute_on_raw_discovery_bind`** — flags a list-consuming primitive (`concat`, `column`, `sum_col`, `count`, `dedupe`, `filter_rows`, `all_true`, `any_true`, `first`) that consumes a RAW discovery RPC bind (which is not iterable rows) instead of a `rowsets`-parsed binding. Complements `primitive_contract`, which only sees compute→compute producers.

## Load / handler_for

`load_checks(path=None) -> list[dict]` reads `data/harness/checks.yaml`; a missing or corrupt file returns `[]` (lint degrades to a no-op, never crashes). `handler_for(kind)` returns the pure handler or `None`; an unknown kind is skipped with a logged warning by the dispatcher — the caller never errors on a novel kind, and adding a new kind is a deliberate code change. See [[data-files#Harness Check Catalogue]].

## Check Status and Severity

Each spec entry in the catalogue carries `status` (`active` | `candidate` | `inactive`) and `severity` (`error` | `warn`). The `lint()` dispatcher in `interpreter.py` applies the following logic: an `active` + `error` violation raises `InterpretError` (blocking); a `candidate` or `warn`-severity violation logs only. `inactive` entries are skipped entirely. This makes it safe to promote a new check incrementally.

## Removed in Phase 0: in-pipeline check distillation

The earlier `ECOM_HARNESS_DISTILL` / `ECOM_HARNESS_VALIDATE_INLINE` path — where `pipeline._maybe_harness_distill` distilled a candidate check-spec after a compute-contract failure and `harness_validate.validate_check_via_grader` promoted it inline — was removed in the Phase 0 legacy cleanup. `agent/harness.py` is now the lint engine only: handlers + the catalogue loader, with no `distill`/`promote`/`save_checks` functions and no `harness_validate.py` module. The catalogue grows by hand-seeding or the offline teach bridge below, not by an in-run distill. The `data/harness/checks.yaml` schema still carries `candidate`/`active` status so a hand-added or bridge-added check can be staged warn-only before promotion.

## Teach bridge to the oracle

A repeatedly-firing check signals a recurring PLAN mistake worth teaching against positively. The offline `scripts/harness_to_oracle.py` bridge selects hot checks from lint telemetry and distils each into a validated `method` atom in the oracle bank, turning a negative lint signal into positive PLAN guidance. See [[harness-to-oracle]].
