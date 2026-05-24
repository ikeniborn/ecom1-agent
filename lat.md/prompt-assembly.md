# Prompt Assembly

`prompt_assembler.py:assemble_prompt()` runs once per pipeline cycle, producing `unified_context` via an LLM call. Every subsequent phase (IDD, SDD, PLAN, ANSWER) receives this as system context.

## Sources

Sources assembled in priority order (highest first):

1. **LEARNED** — active entries from `data/learned/{task_id}.yaml` + in-session `learn_ctx`
2. **VAULT** — `/AGENTS.MD` content fetched during prephase
3. **SCHEMA_DIGEST** — formatted table/column/FK/key info from `_format_schema_digest()`
4. **DB_SCHEMA** — raw `.schema` output for full DDL context
5. **AGENT_CONTEXT** — `runtime_identity`, `agent_store_id`, `current_date`
6. **LAST_RUN** — status/outcome/cycles from previous run (helps assembler weight risky rules)

## Assembler LLM Call

Serializes sources → calls assembler LLM → produces `unified_context` with `# LEARNED` and `# BASE` sections.

`_build_sources()` serializes all sources as plain text. Assembler model configurable via `MODEL_ASSEMBLER`. Falls back to raw sources string if LLM call fails.

## Learned Entry Storage

Three functions manage learned entries: `load_learned_ctx()` reads active-only; `load_learned_entries()` reads all; `_apply_learn_diff()` writes incrementally.

Deduplication of in-session rules uses `dict.fromkeys()` to preserve order. LEARN and CONSOLIDATE both call `_apply_learn_diff()` — one writes new entries, other deactivates merged ones.

## Last Run Metadata

`save_last_run()` writes `last_run` block to YAML after each pipeline run. `load_last_run()` reads it for next run's assembler context.

Allows assembler to know if prior run used too many cycles or failed, and weight learned rules accordingly.
