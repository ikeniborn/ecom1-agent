# grounding

Deterministic reference-grounding (`agent/grounding.py`, 0 LLM). Re-derives the
authoritative `/proc` and `/docs` reference set for an answer from the VM + task text +
computed answer, **replacing** what the model declared. Runs in [[pipeline]] between
`interpret` and [[interpreter#verify() — the deterministic quality gate]]; the model's refs
become hints, code produces the enforced set
(the "muxx exoskeleton" pattern). Best-effort: `ground_refs` never raises — any single
resolution failure drops that one ref, a catastrophic failure returns the interpreter's
refs unchanged.

## ground_refs (orchestration)

`ground_refs(intent, answer, result, vm, task_text, docs_read=None) -> list[str]` is the
entry point. It starts from `answer.refs` (the [[interpreter]] projections, kept first),
adds VM-derived record refs and doc refs, dedups stable-order, and returns the merged set
that the caller writes back into `result.captured.refs`. The whole body is wrapped in one
`try/except` that returns the original `base` refs on any error, so grounding can never
break a cycle. Per-call caps (`ECOM_GROUND_TOKEN_CAP`, `ECOM_GROUND_RECORD_CAP`) bound RPC
fan-out. Identity for the ownership guard comes from `result.env["_facts"].identity`.

## Record refs

For each entity token from `extract_entity_tokens(task_text, answer.message)` (regex over
SKU/ID shapes like `STO-2R84BSHQ` and prefixed ids like `basket_12`), `resolve_record_path`
resolves a real `/proc/<table>/<id>.json` path in three generic stages: (1) an evidence
fast-path scanning `result.sql_results` + message + stringified `env` for a `/proc/...json`
already returned by the run; (2) `find`-by-id over `/proc`; (3) a generic SQL fallback —
`SELECT record_path FROM <t> WHERE record_path LIKE '%token%'` over table names parsed from
`facts.schema` (`_schema_tables_from`), gated by an SQL-safe-token guard. Every candidate is
`stat`-validated; unresolved tokens are dropped. `align_count` trims catalog refs to a
leading count for count-type answers (anti over-citation).

## Ownership guard

`ownership_safe(vm, record_path, identity)` is the Phase-1 conservative cross-customer
guard: a non-customer caller (no `customer_id`) is never blocked; a customer caller may cite
only public (no owner) or self-owned records — a record owned by another customer, or one
that cannot be read/parsed, is dropped (errs toward dropping a doubtful ref). The full
identity gate is deferred to a later phase. See [[interpreter#interpret() — executing the plan against the VM]]
for how enforced refs are projected from `intent.required_refs`.

## Doc refs

`canonical_doc_refs(docs_read, vm, intent, answer)` derives doc refs from the `/docs/*.md`
paths the [[investigate]] step actually read (accumulated into `brief.env["docs_read"]` by
`investigate._note_doc_read`). A recall-preserving relies-on filter narrows to docs the
answer relies on (basename stem in the message, or a declared `policy_doc` in
`intent.required_refs`) — but only when at least one read doc carries such a signal; with no
signal it keeps every read doc, so a single relevant doc is never dropped. Each kept doc is
`stat`-validated and case-corrected against the live tree.

## verify interaction

After grounding overwrites `result.captured.refs`,
[[interpreter#verify() — the deterministic quality gate]] enforces I1 presence-based on
every outcome: each resolved `intent.required_refs[outcome]` value must be ⊆ `answer.refs`,
plus a `$`-ref guard on all outcomes. Grounding supplies the values verify enforces, so an
under-declared record/doc ref that the model omitted is re-derived before the gate. The
success-path security backstop (`pipeline._ground_security_refs`) still runs post-verify and
composes cleanly (grounding never inserts the security policy ref itself).
