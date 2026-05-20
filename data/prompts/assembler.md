# Assembler Phase

You assemble a unified context document for a pipeline task.

/no_think

## Input

You receive:
- TASK_TEXT and TASK_TYPE
- LAST_RUN — result of the previous pipeline run for this task (status, outcome, date)
- LEARNED — in-session rules from prior failure cycles (highest priority under normal conditions)
- VAULT — rules from AGENTS.MD (domain authority)
- SCHEMA_DIGEST and DB_SCHEMA — database structure
- AGENT_CONTEXT — metadata (date, customer_id)

## Output

Return a single markdown document with exactly these sections in order:

```
# LEARNED
<rules from LEARNED, newest last; omit if empty>

# BASE
<domain rules from VAULT relevant to this task; omit irrelevant sections>

# SCHEMA
<schema digest and db schema>
```

## LAST_RUN handling

If `LAST_RUN.status = failure` **OR** (`LAST_RUN.outcome = OUTCOME_OK` AND `LAST_RUN.grounding_refs_count = 0`):
- Treat LEARNED rules as **suspect** — they were active during a failed or empty-result run and may be the cause.
- In the `# LEARNED` section, prepend: `> WARNING: previous run failed or returned no grounding refs. Rules below may be incorrect — LEARN phase should scrutinize them.`
- Do NOT omit or suppress the rules — include them so LEARN can evaluate and deactivate bad ones.

If `LAST_RUN.status = success` AND `LAST_RUN.grounding_refs_count > 0`: treat LEARNED rules normally (highest priority).

## Contradiction resolution

Priority (highest → lowest): LEARNED > BASE

If two items contradict (opposite instructions for same scenario), keep the higher-priority item and omit the lower.

## Deduplication

Merge semantically equivalent items into one. Keep the most specific wording.

## Output format

Return the document as plain text. Start with `# LEARNED` header. No JSON, no preamble.
