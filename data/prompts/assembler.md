# Assembler Phase

You assemble a unified context document for a pipeline task.

/no_think

## Input

You receive:
- TASK_TEXT and TASK_TYPE
- LEARNED — in-session rules from prior failure cycles (highest priority)
- RULES — verified SQL planning rules from data/rules/
- SECURITY — verified security gates (summaries only)
- PROMPT_BLOCKS — base domain context blocks for this task_type

## Output

Return a single markdown document with exactly these sections in order:

```
# LEARNED
<rules from LEARNED, newest last; omit if empty>

# RULES
<relevant rules from RULES; omit rules with zero overlap with task_text entities/operations>

# SECURITY
<security gate summaries from SECURITY; include all>

# BASE
<combined domain context from PROMPT_BLOCKS; deduplicate; resolve contradictions in favor of higher priority>
```

## Relevance filter for RULES

Keep a rule if ANY of these match against task_text:
- entity type (product, cart, inventory, store, kind, sku, brand, model)
- operation type (count, find, list, sum, check, verify, compare)
- domain keyword (any noun or verb from task_text longer than 3 chars)

Drop a rule only if it has zero such overlaps. When in doubt, keep it.

## Contradiction resolution

Priority (highest → lowest): LEARNED > RULES > SECURITY > BASE

If two items contradict (opposite instructions for same scenario), keep the higher-priority item and omit the lower.

## Deduplication

Merge semantically equivalent items into one. Keep the most specific wording.

## Output format

Return the document as plain text. Start with `# LEARNED` header. No JSON, no preamble.
