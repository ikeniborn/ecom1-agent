# PHASE: LEARN + CONSOLIDATE (merged)

You diagnose a failed CODEGEN cycle and either produce a new corrective rule
or skip if the failure is already covered. You may also deactivate stale rules
that contradict the new one — this replaces the standalone CONSOLIDATE phase.

## Inputs

- `TASK` — original instruction
- `TOOL_PLAN` — DesignOutput JSON for this run (frozen — do not propose tool_plan changes)
- `ERROR` — error string (`lint:`, `fidelity:`, `codegen_llm_fail:`)
- `SCRIPT_CODE` — the failing CODEGEN output
- `EXISTING_RULES` — active rules from prior cycles in this and earlier runs

## Output format

Single JSON object — no prose, no markdown fences:

```json
{
  "rule_content": "<starts with Never|Always|Use|Do not|When|If|Prefer>",
  "agents_md_anchor": "<#section > entry> or null",
  "reasoning": "<diagnosis: verbatim error, root cause, failing fragment, rule linkage>",
  "deactivate_ids": ["rXXX"],
  "deactivate_reason": "<why these become obsolete> or null",
  "skip": false,
  "skip_reason": null
}
```

## Rules

- `rule_content` must describe a CODEGEN technique — how to translate `tool_plan` to script — not domain conclusions.
- `rule_content` must be task-agnostic — never embed literal task params (SKUs, brand names, dates).
- Skip (`skip: true`) only if the new rule is semantically identical to an existing one.
- Use `deactivate_ids` when the new rule strictly supersedes prior rules — set `deactivate_reason`.
- Length: `rule_content` ≥ 20 chars; must start with one of the listed lead verbs.
