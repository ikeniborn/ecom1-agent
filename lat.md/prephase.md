# Prephase

`orchestrator.py:gather_prephase_facts()` hydrates `PrePhaseFacts` before the pipeline loop. Every step is best-effort.

A failure marks that field `empty` / `error(...)` and never aborts the task. A per-field `status` map records `ok` / `empty` / `error(...)`.

## Gathered Facts

In order:

1. **schema** — `.schema` + table names. DDL and names are uncapped.
2. **sample_rows** — relevance-gated `LIMIT` sample per table (`PREPHASE_SAMPLE_ROWS`, row byte cap `PREPHASE_SAMPLE_ROW_CHARS`). Tables not relevant to the instruction are skipped and logged — no silent truncation.
3. **identity** — `/bin/id` parsed into `runtime_identity`; `kind` derived (customer / employee / …). A customer `cust_*` value is surfaced as `customer_id` so role-aware deny predicates are robust.
4. **docs_inventory** — `/docs` listing.
5. **policies** — `/docs/security.md` + path-named docs from the instruction / AGENTS.MD (`PREPHASE_PATH_LITERALS` cap), plus entity-token `Search` enrichment over `/docs`.

## Learned deep-read

`load_prephase_deep_read(task_id)` returns table names / literal paths a prior run's LEARN flagged via `prephase_deep_read`.

Paths (`/…`) are read eagerly; bare names join the sample-table set. This lets the agent eagerly fetch context it learned it needed last run.

## Consumption

`PrePhaseFacts` is passed to `run_pipeline()` as `facts` and threaded into INTENT, PLAN, and interpret. See [[pipeline-phases]].

The agent-relevant VM API surface is inlined in `data/prompts/{intent,plan}.md` — there is no separate prompt-assembly LLM call (the legacy `prompt_assembler.py` was removed).
