# Learn Context Compaction Design

**Date:** 2026-05-17  
**Status:** Approved

## Problem

`learn_ctx` accumulates rules without consolidation. Each `_run_learn` call appends one new rule. After multiple failed cycles on the same task (e.g. t21: 10 cycles), the list contains:

- Semantically duplicate rules (same point, different wording)
- Task-specific IDs embedded in "general" rules (`basket_115`, `cust_022`)
- Redundant signal — assembler LLM wastes tokens on duplicated content

## Solution

Extend the LEARN phase to produce `compacted_ctx` alongside the new rule. The LEARN LLM — which already sees the full `learn_ctx` in its user message — deduplicates and generalizes the list in the same call, replacing concrete IDs with placeholders.

## Data Flow

```
_run_learn() called on failure
  ↓
LEARN LLM (MODEL_LEARN) → LearnOutput
  {
    reasoning, conclusion, agents_md_anchor,   ← unchanged
    rule_content,                               ← new rule (unchanged)
    compacted_ctx: ["rule1", "rule2", ...]      ← NEW: deduplicated + generalized list
  }
  ↓
if compacted_ctx is not None and len > 0:
    learn_ctx[:] = compacted_ctx   ← in-place replace (includes new rule)
else:
    learn_ctx.append(rule_content) ← fallback: original behavior
  ↓
save_learned_ctx(task_id, learn_ctx)  ← clean list to disk
```

## Components

### `data/prompts/learn.md` — extend output format

Add compaction section:

- If `EXISTING_RULES` is non-empty: merge semantically similar rules into one canonical rule; generalize task-specific IDs (`basket_115` → `<basket_id>`, `cust_022` → `<customer_id>`, any concrete numeric/string ID → typed placeholder); keep distinct failure patterns separate (do not collapse different root causes)
- `compacted_ctx` must include the new `rule_content` already merged in
- If `EXISTING_RULES` is empty: `compacted_ctx` = `[rule_content]`
- Output: JSON array of strings

New output format:
```json
{
  "reasoning": "<diagnosis>",
  "conclusion": "<one-sentence summary>",
  "rule_content": "<new rule text>",
  "compacted_ctx": ["<merged rule 1>", "<merged rule 2>"],
  "agents_md_anchor": null
}
```

### `agent/models.py`

```python
class LearnOutput(BaseModel):
    rule_content: str
    agents_md_anchor: str | None = None
    reasoning: str = ""
    conclusion: str = ""
    compacted_ctx: list[str] | None = None  # NEW
```

### `agent/pipeline.py` — `_run_learn()`

Replace the final append block:

```python
# After learn_out is parsed:
compacted = learn_out.compacted_ctx
if compacted and len(compacted) > 0 and all(isinstance(r, str) for r in compacted):
    learn_ctx[:] = compacted
    print(f"[pipeline] LEARN: compacted to {len(learn_ctx)} rules")
else:
    learn_ctx.append(learn_out.rule_content)
    print(f"[pipeline] LEARN: rule added (total={len(learn_ctx)})")

if task_id:
    save_learned_ctx(task_id, learn_ctx)
```

## Edge Cases

| Case | Behavior |
|------|----------|
| `compacted_ctx = []` | Ignore, fallback to `append` |
| `compacted_ctx` fails Pydantic validation | Field is `None`, fallback to `append` |
| First cycle (learn_ctx was empty before append) | LLM produces `compacted_ctx = [rule_content]` |
| LLM omits `compacted_ctx` field | Field is `None`, fallback to `append` |
| LLM collapses all rules into 1 | Accepted — if semantically equivalent |

## Files Changed

| File | Change |
|------|--------|
| `data/prompts/learn.md` | Add compaction section + `compacted_ctx` to output format |
| `agent/models.py` | Add `compacted_ctx: list[str] \| None = None` to `LearnOutput` |
| `agent/pipeline.py` | Update `_run_learn` to use `compacted_ctx` if valid |

## What Does NOT Change

- `MODEL_LEARN` — same model, no new env var
- `assemble_prompt` — unchanged
- `save_learned_ctx` / `load_learned_ctx` — unchanged (list[str] format preserved)
- LEARN phase LLM call structure — same call, extended output schema
