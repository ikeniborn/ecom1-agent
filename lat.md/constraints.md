# Constraints and Invariants

Non-obvious rules that are load-bearing in the current implementation. Violating any of these causes silent failures or infinite loops.

## JSON Extraction Priority

Mutation tool types (write/delete) take priority over reads in `json_extract.py`.

Reversing this ordering causes spurious read tool calls to shadow mutation tools, producing wrong execution.

## Anti-Infinite-Loop Guard

`check_retry_loop()` in `sql_security.py` blocks any action matching a prior cycle's action set.

Checked before EXECUTE every cycle. This is the only mechanism preventing identical query retry — no other guard exists.

## Schema Gate Rules

`schema_gate.py` enforces three checks before EXECUTE: unknown table, unknown qualified column, double-key JOIN.

1. **Unknown table** — not in `schema_digest` fails; pragma_* and system tables exempt
2. **Unknown qualified column** — `alias.column` not in schema fails; unqualified columns pass
3. **Double-key JOIN on product_properties** — two `key=` conditions requires separate EXISTS subqueries

Literal check fires only when literal appears in `task_text` — prevents blocking discovery queries.

## LEARN Rule Validation

`_apply_learn_diff()` rejects rules shorter than 20 chars or not starting with action prefixes.

Valid starts: `("never", "always", "use", "do not", "when", "if", "prefer")`. Prevents placeholder content polluting the knowledge base.

## Prompt Engineering Boundary

`data/prompts/*.md` contain only structural rules. Task-specific rules must flow through LEARN.

Allowed in prompts: output format, action forms, SQL constraints, generic patterns. Forbidden: task-specific heuristics. Patching prompts to fix task failures is explicitly wrong — fix the LEARN trigger instead.

## System Prompt Block Format

Multi-block system format: `[{"type":"text","text":unified_context}, {"type":"text","text":guide,"cache_control":{"type":"ephemeral"}}]`.

Guide block carries `cache_control` for caching. Swapping block order breaks cache hit rates.

## Exec Action Empty Result

`/bin/` tool actions may legitimately return empty output on success.

Only data-returning types (sql, read, search, list, find, tree) gate on empty result to trigger LEARN. Exec-type actions skip the empty check.

## Discount Issuer Injection

When `pre.agent_id` contains `emp_\d+`, pipeline appends employee ID to `/bin/discount` commands.

Positional arg is ISSUER_ID. Commands without it are rejected by VM — injection is automatic.

## Store Filter Injection

When `pre.agent_store_id` is set and action is SQL touching `baskets`, pipeline injects store filter.

Injects `AND b.store_id = '{agent_store_id}'` before GROUP BY / ORDER BY / LIMIT. Prevents cross-store data access even when SQL is otherwise correct.
