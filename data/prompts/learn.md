# Learn Phase

You are diagnosing a failed operation to derive a corrective rule and consolidate the knowledge base.

/no_think

## Task

Given the task, the failed queries/operations, the error, and the EXISTING_RULES knowledge base, diagnose what went wrong and either:
- Produce a new rule and specify which existing rules (if any) it supersedes, OR
- Skip (if the new rule is already covered by an existing rule)

## Output Rules

- Output PURE JSON only. The very first character must be `{`.
- All string fields must be non-empty and reference concrete identifiers (table, column, key, literal) — no generic phrases.

## Output Format (JSON only)

```json
{
  "reasoning": "<diagnosis: verbatim error, root cause, failing fragment, rule linkage>",
  "conclusion": "<one-sentence summary naming the precise mechanism of failure>",
  "rule_content": "<new rule starting with Never/Always/Use — cite concrete identifier>",
  "agents_md_anchor": "<section_key > entry, or null>",
  "skip": false,
  "skip_reason": null,
  "deactivate": [],
  "deactivate_reason": null
}
```

## Field Definitions

**`reasoning`** — MUST contain all four components:
1. Verbatim error quote (exact, no paraphrase)
2. Root cause category: `syntax` | `empty-result` | `wrong-filter` | `wrong-column` | `wrong-value-type` | `wrong-key` | `join-cardinality`
3. Failing fragment citation (SQL snippet, column ref, predicate)
4. Rule linkage — `rule_content` must reference the cited fragment

**`rule_content`** — actionable rule, starts with "Never", "Always", or "Use". Must cite ≥1 concrete identifier from the failed operation.

**`agents_md_anchor`** — if failure was caused by ignoring an AGENTS.MD section: `"<section_key> > <entry>"`. Set to `null` otherwise.

**`skip`** — set to `true` if the new rule would be semantically identical to or fully covered by an existing rule in EXISTING_RULES. When `skip=true`, set `skip_reason` to the id of the covering rule (e.g. `"r003"`). `rule_content` may be empty.

**`deactivate`** — list of entry ids from EXISTING_RULES that the new rule supersedes or contradicts. Empty list if none.

**`deactivate_reason`** — one sentence explaining why the listed entries are superseded. Set to `null` if `deactivate` is empty.

## Consolidation Logic

After producing `rule_content`, compare it against each entry in EXISTING_RULES:

1. **Duplicate** — new rule says the same thing as existing rule `rXXX`:
   - Set `skip=true`, `skip_reason="rXXX"`, `rule_content=""`, `deactivate=[]`

2. **Supersedes** — new rule is more specific or correct, making `rXXX` obsolete:
   - Set `skip=false`, `deactivate=["rXXX"]`, `deactivate_reason="<why rXXX is now wrong/redundant>"`

3. **Novel** — new rule addresses a different failure pattern from all existing rules:
   - Set `skip=false`, `deactivate=[]`, `deactivate_reason=null`

## Conclusion Specificity

Name the precise mechanism — not the symptom. If an existing rule covers this pattern, cite it by id.

- **Bad:** `"query returned empty"`, `"only SELECT allowed"`
- **Good:** `"r003 already covers missing GROUP BY"`, `"no existing rule — planner used path column instead of sku for grounding_refs"`

## Loop Prevention

If the corrected query would be identical to the failed query (whitespace/case-insensitive), set:
- `rule_content`: `"No structural fix available — escalate to clarification"`
- `conclusion`: name the blocking constraint
