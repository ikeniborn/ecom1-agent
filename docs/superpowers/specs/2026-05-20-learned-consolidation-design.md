---
state: draft
created: 2026-05-20
review:
  spec_hash: ce8d03e7f2c32050
  last_run: 2026-05-20
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "## Testing"
      section_hash: 01ba4719c80b6fe9
      text: "Component 1 (sdd.md fix) has no dedicated test or acceptance criterion. Testing section covers only CONSOLIDATE phase. No test verifies SDD no longer emits natural-language action values after the prompt change."
      verdict: fixed
      verdict_at: 2026-05-20
---

# Spec: Learned Knowledge Consolidation + SDD Action Fix

## Problem

Two related issues in the learned-knowledge pipeline:

1. **SDD generates natural-language actions.** `sdd.md` forbids inventing binary paths not in
   `important_tools`. When no listing tool appears in the vault, SDD falls back to prose like
   `"List the payment record files in proc/payments/ directory,"`. The executor splits on whitespace,
   tries `vm.exec(path="List", ...)`, and fails with `runtime tool not found`.

2. **Learned rules accumulate without consolidation.** Each LEARN cycle appends a rule. The LLM
   only deactivates superseded rules when it recognises the overlap at write time. It routinely
   misses partial overlaps. After 14 cycles for t40, 13 active rules include three overlapping
   "table discovery" rules (r002, r003, r007) and three separate "proc/payments/ fallback" rules
   (r008, r010, r012), diluting LLM attention and risking implicit contradictions.

## Solution Overview

Two targeted changes, no pipeline hardcoding:

1. **Fix `data/prompts/sdd.md`** — add a "Standard tools" section that explicitly permits common
   Unix binaries (`/bin/ls`, `/bin/cat`, `/bin/tree`, `/bin/grep`) and strengthens the action-format
   constraint.

2. **CONSOLIDATE phase** — a new LLM pass that runs after every successful LEARN. It reviews all
   active rules, merges duplicates/overlaps into a single rule (priority: highest rule id), and
   deactivates the source rules. Implemented as `data/prompts/consolidate.md` + `ConsolidateOutput`
   model + `_run_consolidate()` called from `run_pipeline`.

Merged rules get new monotonic IDs (`_next_entry_id`). Deactivated rules are marked `inactive`
with `deactivated_reason`. No structural gates, no hardcoded regex.

## Component 1 — `data/prompts/sdd.md` changes

Add after the existing "Action Rules" section:

```markdown
## Standard Unix tools (always available)

/bin/ls, /bin/cat, /bin/tree, /bin/grep are always available even if absent from important_tools.
Use them for filesystem operations without vault confirmation.

An action MUST be an executable string in one of these forms:
- SQL query: starts with SELECT
- File read: absolute path starting with / (no arguments)
- Exec: absolute path /bin/<name> or /usr/<name> followed by space-separated args

Never write a natural-language sentence as an action value.
If you cannot express the required operation as one of the forms above, set actions to [].
```

This gives SDD a positive instruction ("use /bin/ls") instead of only a negative one
("don't invent paths"), eliminating the natural-language fallback.

## Component 2 — CONSOLIDATE phase

### 2a. `data/prompts/consolidate.md`

```markdown
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
```

### 2b. Pydantic models (`agent/models.py`)

```python
class ConsolidationItem(BaseModel):
    deactivate: list[str]
    merged_rule: str
    merged_reasoning: str

class ConsolidateOutput(BaseModel):
    skip: bool = True
    skip_reason: str | None = None
    consolidations: list[ConsolidationItem] = []
```

### 2c. `_run_consolidate()` in `agent/pipeline.py`

```python
def _run_consolidate(
    unified_context: str,
    model: str,
    cfg: dict,
    task_id: str,
    learn_ctx: list[str],
    cycle: int,
) -> None:
    entries = load_learned_entries(task_id)
    active = [e for e in entries if e.get("status") == "active"]
    if len(active) < 2:
        return
    consolidate_model = _resolve_model_for_phase("consolidate", model)
    consolidate_guide = load_prompt("consolidate") or "# PHASE: consolidate"
    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": consolidate_guide, "cache_control": {"type": "ephemeral"}},
    ]
    rules_lines = "\n".join(
        f"  - id: {e['id']}\n    content: {e['content']!r}"
        for e in active
    )
    user_msg = f"ACTIVE_RULES:\n{rules_lines}"
    out, _, _ = _call_llm_phase(
        system, user_msg, consolidate_model, cfg, ConsolidateOutput,
        max_tokens=2048, phase="consolidate", cycle=cycle,
    )
    if not out or out.skip:
        return
    for item in out.consolidations:
        if not item.merged_rule or not item.deactivate:
            continue
        _apply_learn_diff(
            task_id,
            item.merged_rule,
            item.merged_reasoning,
            item.deactivate,
            "Consolidated: " + ", ".join(item.deactivate),
        )
        deactivate_contents = {
            e["content"] for e in active if e.get("id") in item.deactivate
        }
        learn_ctx[:] = [r for r in learn_ctx if r not in deactivate_contents]
        learn_ctx.append(item.merged_rule)
    print(f"[pipeline] CONSOLIDATE: {len(out.consolidations)} merge(s), active={len(learn_ctx)}")
```

### 2d. Pipeline call site (`run_pipeline`)

After every `_run_learn(...)` call, unconditionally call `_run_consolidate`. The function
short-circuits when fewer than 2 active rules exist or when LLM returns `skip: true`.
No change to `_run_learn` signature needed.

```python
_run_learn(unified_context, model, cfg, task_text, error,
           sgr_trace, learn_ctx, pre.agents_md_index,
           error_type=..., cycle=cycle + 1, task_id=task_id, ...)
_run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
```

### 2e. `_resolve_model_for_phase` — add "consolidate"

`"consolidate"` resolves via `MODEL_CONSOLIDATE` env var, defaulting to `MODEL`. Add to
`.env.example` and `CLAUDE.md` env-var table.

## Data flow for t40 after fix

Expected outcome running CONSOLIDATE on t40's 13 active rules:

| Group | Input | After |
|-------|-------|-------|
| Table discovery | r002, r003, r007 | 1 merged rule (base: r007) |
| /bin/sql ordering | r007, r010 | covered by merged rule above |
| Fallback hierarchy | r008, r010, r012 | 1 merged rule (base: r012) |
| Distinct rules | r004, r005, r006, r009, r011, r013, r014 | unchanged |

Result: ~9 active rules instead of 13.

## Testing

### Component 1 — sdd.md fix

- Unit test: mock SDD LLM response containing a natural-language action value (e.g.
  `"List the payment record files in proc/payments/ directory,"`) → verify pipeline raises or
  retries (schema gate / validate phase rejects non-executable action).
- Acceptance criterion: after the prompt change, SDD prompt mock returning the same natural-language
  sentence must be replaced by either `[]` or `/bin/ls proc/payments/` in the parsed `SddOutput`.

### Component 2 — CONSOLIDATE phase

- Unit test `_run_consolidate` with mock `load_learned_entries` returning 3 overlapping rules →
  verify `_apply_learn_diff` called once, `learn_ctx` reduced.
- Unit test `_run_consolidate` with 1 active rule → verify returns immediately (no LLM call).
- Integration: run t40 with `LOG_LEVEL=DEBUG`, confirm CONSOLIDATE fires after LEARN and reduces
  active rule count.
- Regression: run existing tests in `tests/test_pipeline.py` — no new failures.

## Out of scope

- Retroactive consolidation of existing `.yaml` files (manual cleanup, not automated).
- CONSOLIDATE on success path (only fires after LEARN).
- Cross-task consolidation.
