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
4. **Same spec_goal, different actions** — multiple rules prescribe different action sequences for identical `spec_goal`. Even if the rules aren't contradictory, keep only the most recent (highest id) and deactivate older ones. Rationale: if a newer rule supersedes the approach, the older rule adds noise and may confuse the agent.

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

## Example: same-spec_goal consolidation

Rules r014, r015, r018 all address spec_goal "Confirm whether Kai Möller is the store manager at PowerTool Linz Hauptplatz":
- r014: "Always list /proc/employees/ first"
- r015: "Never use search:Kai Möller"
- r018: "Read /proc/stores/store_linz_hauptplatz.json"

These are not contradictory but they overlap. Merge into one rule using highest-id (r018) as base.

Result (JSON output the model should produce):

    {
      "skip": false,
      "consolidations": [{
        "deactivate": ["r014", "r015"],
        "merged_rule": "For spec_goal '...Kai Möller...': read /proc/stores/store_linz_hauptplatz.json directly (do not use search:Kai Möller; do not list /proc/employees/ unless store file lacks employee reference).",
        "merged_reasoning": "r014+r015+r018 all address same spec_goal; r018 subsumes with corrections"
      }]
    }
