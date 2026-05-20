# Consolidate Phase

Review active learned rules and eliminate redundancy.

/no_think

## Input

ACTIVE_RULES — list of {id, content} for all currently active rules.

## Task

Find groups of rules that:
1. Are semantically identical (duplicates) — same failure, same fix
2. Overlap — rule A is a strict subset of rule B
3. Contradict — rules require incompatible actions for the same situation

For each group: produce one merged_rule. Take the content of the rule with the highest numeric id
as the base; extend it to cover the full scope of all rules in the group.

Skip (output skip: true) when all active rules are distinct and non-contradictory.

## Output (JSON only, first character must be {)

{
  "skip": true,
  "skip_reason": "<why no consolidation needed, or null>",
  "consolidations": []
}

or when consolidation is needed:

{
  "skip": false,
  "skip_reason": null,
  "consolidations": [
    {
      "deactivate": ["r002", "r003"],
      "merged_rule": "<content derived from highest-id rule, extended to cover all>",
      "merged_reasoning": "<which ids merged, what was redundant>"
    }
  ]
}
