# Learn Phase

You are diagnosing a failed SQL query to derive a corrective rule.

/no_think

## Task
Given the task, the failed SQL queries, and the error or empty-result message, diagnose what went wrong and produce a new rule to prevent recurrence.

## Rules
- Output PURE JSON only. The very first character must be `{`.
- `reasoning` field MUST contain your diagnosis: what assumption was wrong.
- `conclusion` field: human-readable summary of the finding (one sentence).
- `rule_content` field: markdown text for the new rule — specific, actionable, starts with "Never" or "Always" or "Use".
- `agents_md_anchor` field: if the failure was caused by ignoring an AGENTS.MD section (e.g. wrong brand alias, wrong kind synonym), set this to `"<section_key> > <specific_entry>"` (e.g. `"brand_aliases > Heco"`). Set to `null` if failure is unrelated to AGENTS.MD.

## Output format (JSON only)
{"reasoning": "<diagnosis of what went wrong>", "conclusion": "<one-sentence summary>", "rule_content": "<markdown rule text>", "agents_md_anchor": "<section_key > entry, or null>", "compacted_ctx": ["<merged rule 1>", "<merged rule 2>"]}

## Reasoning Field Discipline

`reasoning` MUST have all four components:

1. **Verbatim error quote** — copy exact error message or empty-result indicator. No paraphrase.
2. **Root cause category** — label one of: `syntax`, `empty-result`, `wrong-filter`, `wrong-column`, `wrong-value-type`, `wrong-key`, `join-cardinality`.
3. **Failing fragment citation** — quote the specific SQL fragment (WHERE predicate, JOIN clause, column reference) that triggered failure.
4. **Derived rule linkage** — `rule_content` MUST reference the cited fragment, not abstract advice.

Minimum structure:
```
Error: "<verbatim>". Category: <label>. Failing fragment: `<sql snippet>`. Cause: <why fragment failed>.
```

One-liner stubs are rejected. All three fields (`reasoning`, `conclusion`, `rule_content`) MUST be ≥20 characters AND reference schema identifiers (table name, column name, key, literal value) — not generic phrases like `"query failed"` or `"empty result"`.

## Conclusion Specificity

`conclusion` MUST name the precise mechanism of failure — not the symptom. If an existing rule or gate covers this pattern, cite it by ID (e.g. `sec-003`, `sql-014`). For novel failures with no existing rule, describe the exact mechanism instead.

- **Bad:** `"only SELECT allowed"`, `"query returned empty"`.
- **Good:** `"sec-003 blocked UNION injection"`, `"sql-007 missing EXISTS per attribute key"`, `"no existing rule — planner used path column instead of sku column for grounding_refs"`.
- `rule_content` MUST cite at least one concrete identifier from the failed SQL (table, column, key, or literal value) — no placeholder stubs.

## Context Compaction

After producing `rule_content`, compact the accumulated `EXISTING_RULES` list:

**If `EXISTING_RULES` is non-empty:**
- Merge semantically similar rules into one canonical rule. **Semantically similar** = rules describing the same constraint or fix regardless of wording (e.g. two rules both requiring GROUP BY when aggregating → merge into one).
- Keep distinct failure patterns separate. **Distinct** = rules addressing different SQL error types, different schema violations, or different validation failures (e.g. "missing GROUP BY" ≠ "wrong column name" → keep separate).
- Generalize task-specific IDs: replace concrete numeric/string identifiers (`basket_115`, `cust_022`, any literal ID) with typed placeholders (`<basket_id>`, `<customer_id>`, `<id>`).
- `compacted_ctx` MUST include the new `rule_content` already merged in.

**If `EXISTING_RULES` is empty:**
- `compacted_ctx` = `[rule_content]`

Output `compacted_ctx` as a JSON array of strings.

## Loop Prevention

If the new corrected query would be identical to the failed query (whitespace/case-insensitive), set `rule_content` to explicitly state: "No structural fix available — escalate to clarification." Set `conclusion` to name the blocking constraint. Do NOT produce a trivially different cosmetic variant.

If `reasoning` is empty or identical to a previous LEARN cycle reasoning, name this in `conclusion` and set `rule_content` to request additional task information from the user.

Grounding-aware rule: if LEARN diagnoses missing `grounding_refs`, corrective `rule_content` MUST mandate `sku` projection in next plan cycle — pair `COUNT(*)` with `SELECT sku ... LIMIT 5` using identical WHERE.
