# Schema Validation

Two components validate SQL before it reaches the VM: `schema_gate.py` (structural analysis) and `sql_security.py` (anti-loop and security guards).

## Schema Gate

`schema_gate.py:check_schema_compliance()` runs static analysis via sqlglot. Returns first error or None.

Parses query and checks three conditions in sequence: unknown table, unknown qualified column, double-key JOIN on `product_properties`.

### Unknown Table Check

Validates all table references against `schema_digest`. Empty digest skips this check.

Exempt: `sqlite_schema`, `sqlite_master`, names starting with `pragma_`.

### Unknown Qualified Column Check

Validates `alias.column` references against known columns for the resolved table.

Unqualified columns skipped (DB engine catches those). Unknown aliases skipped. System table queries exempt.

### Double-Key JOIN Check

Detects JOIN on `product_properties` with >1 `key=` condition in WHERE scope.

This pattern produces wrong results. Correct pattern: separate EXISTS subqueries per key.

### System Table Exemption

When query references `sqlite_schema`, `sqlite_master`, or `pragma_*`, literal and JOIN checks are skipped.

These queries do DDL discovery — their literals are table names, not data values.

### Literal Check

Fires when literal value appears in `task_text`. Literals in LIKE/ILike predicates are exempt (discovery queries).

## SQL Security Guards

`sql_security.py` provides standalone guards called by pipeline at specific checkpoints.

- `check_retry_loop()` — blocks identical action set repeated across cycles
- `check_sql_queries()` — applies regex + structural gates from config
- `check_path_access()` — blocks path prefix access
- `check_where_literals()` — blocks WHERE literals not traceable to task_text
- `check_grounding_refs()` — blocks refs not present in SQL result SKUs
- `check_learn_output()` — blocks stale replay and placeholder rule content

## Schema Digest

`prephase.py:_build_schema_digest()` queries PRAGMA for each known table and top 20 property keys.

Also queries `product_properties.key` value type breakdown (text vs number). Feeds schema_gate and is serialized into `unified_context`. Dynamic expansion via `merge_schema_from_sqlite_results()` parses CREATE TABLE DDL from `sqlite_schema` queries.
