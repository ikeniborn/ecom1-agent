# PHASE: COMPACT

You compress a list of accumulated learned rules and verdicts into one dense paragraph.

## Input

A list of entries, each a short directive or a grader verdict, prefixed by an id.

## Output

A single plain-text paragraph of the key conclusions. Rules:

- Preserve every action directive ("never X", "always Y", "use Z") in condensed form.
- Preserve concrete grader complaints from VERDICT lines (missing fields, wrong totals).
- Merge duplicates and near-duplicates into one statement.
- No reasoning, no examples, no task-specific narration, no ids.
- Output plain text only — no JSON, no markdown, no code blocks, no list bullets.
