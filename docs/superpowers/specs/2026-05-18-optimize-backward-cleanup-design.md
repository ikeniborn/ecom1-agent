---
review:
  spec_hash: 80f0fb05d3940705
  last_run: 2026-05-18
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  section_hashes:
    Problem: f126af32d58c6f3c
    Solution: a2f95784b55c65ff
    Part1: fec945c1ea59eb4b
    Part2: 3439fe8bca109b7f
    ContradictionCheck: 35a9788beac19b46
    DataFlow: 07f20095da7395d8
    FilesChanged: b58f0ff2d53ac4f4
    OutOfScope: 47f998399109a9ef
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: Part2
      section_hash: 3439fe8bca109b7f
      text: "_synthesize_prompt_patch → None для rec в кластере: хеши не помечаются processed в новой grouped-архитектуре. Спек не определяет это поведение — риск повторной обработки при следующем запуске."
      verdict: fixed
      verdict_at: 2026-05-18
---

# Design: propose_optimizations — backward cleanup & prompt rewrite

**Date:** 2026-05-18  
**Scope:** `scripts/propose_optimizations.py`, `agent/knowledge_loader.py`

## Problem

Two gaps in the current optimization pipeline:

1. **No backward cleanup for rules/security.** `_check_contradiction` rejects new content that conflicts with existing, but never disables existing items that become contradictory once new ones are written. Over time, `data/rules/` and `data/security/` accumulate stale or conflicting entries.

2. **Prompts are append-only.** `_write_prompt` appends new sections to `data/prompts/*.md`. There is no mechanism to remove superseded or contradictory prompt instructions. Files grow stale.

## Solution: Inline Backward Cleanup (Approach A)

### Part 1 — Rules/Security: soft-disable superseded items

After writing any new rule or security gate, run one LLM call to identify existing items now superseded or contradicted by the new one. Set `verified: false` on those YAML files.

**New functions in `propose_optimizations.py`:**

```python
def _find_superseded(new_content: str, existing_md: str, model: str, cfg: dict) -> list[str]:
    """One LLM call. Returns list of IDs from existing_md that new_content supersedes or contradicts.
    System prompt asks for JSON array of IDs e.g. ["sql-015"]. Returns [] on failure."""

def _soft_disable(rule_id: str, directory: Path) -> bool:
    """Finds the YAML file with matching id field, sets verified: false.
    Returns True if found and patched, False if not found."""
```

**Call site** — immediately after `_write_rule()` / `_write_security()`:

```python
dest = _write_rule(num, content, entry, raw_rec)
superseded = _find_superseded(content, rules_md, model, cfg)
for sid in superseded:
    if _soft_disable(sid, _RULES_DIR):
        print(f"  → disabled {sid} (superseded)")
rules_md = knowledge_loader.existing_rules_text()  # refreshes, excludes disabled
```

`existing_rules_text()` already filters `verified: true` only → disabled items disappear from context on next synthesis call within the same run.

**dry-run:** `_find_superseded` still runs (read-only LLM call), prints what would be disabled. No YAML files touched.

### Part 2 — Prompts: full file rewrite per target

Replace the append-only `_write_prompt` with a full LLM-driven rewrite. All new recommendations for a given target file are grouped, then one LLM call rewrites the entire file: new recommendations take priority, duplicates and contradictions are removed.

**New function:**

```python
def _rewrite_prompt_file(
    target: str,
    new_recs: list[str],
    model: str,
    cfg: dict,
) -> str | None:
    """Reads data/prompts/<target> (empty string if missing).
    LLM rewrites entire file incorporating new_recs with priority.
    Returns complete rewritten content, or None on failure."""
```

LLM system prompt: rewrite the prompt file incorporating new recommendations (which take priority), remove duplicates and contradictions, return only the complete file content with no commentary.

**Pipeline change in `main()`:**

Replace the current per-cluster `_write_prompt` loop with:

1. Collect `target_file → [(raw_rec, all_hashes)]` from `prompt_clusters` using `_synthesize_prompt_patch` to determine target (its `content` field is discarded). If `_synthesize_prompt_patch` returns `None` for a rec — mark its hashes processed immediately (`new_processed.update(all_hashes)`) and skip it, same as the old per-cluster loop.
2. For each target, call `_rewrite_prompt_file(target, recs, model, cfg)`.
3. Write result to `data/prompts/<target>` directly.
4. Refresh `prompts_md` after each file written.

**Removed:** `_write_prompt` function. `_PROMPTS_OPTIMIZED_DIR` no longer used for writes (directory kept for backward compat but empty going forward).

**dry-run:** prints rewritten content preview, no file written.

### Contradiction check interaction

`_check_contradiction` (guards new content against existing) is **kept unchanged**. The new `_find_superseded` is its inverse: given newly written content, finds what existing items it makes obsolete. The two checks serve different purposes and both run.

## Data flow after changes

```
write new rule/gate
  → _find_superseded(new_content, existing_md) → [ids]
  → _soft_disable(id, dir) for each id
  → refresh existing_md

cluster prompt recs
  → group by target_file via _synthesize_prompt_patch
  → _rewrite_prompt_file(target, all_recs_for_target) → full content
  → write data/prompts/<target>
  → refresh prompts_md
```

## Files changed

| File | Change |
|------|--------|
| `scripts/propose_optimizations.py` | Add `_find_superseded`, `_soft_disable`, `_rewrite_prompt_file`; update `main()` prompt loop; remove `_write_prompt` |
| `agent/knowledge_loader.py` | No changes required (already filters `verified: true`) |

## Out of scope

- Periodic full-audit pass (`--audit` flag) — not needed for now; inline cleanup covers new writes.
- Cross-channel conflict detection (rule vs prompt) — not addressed; rules and prompts serve different roles.
- `_PROMPTS_OPTIMIZED_DIR` removal — keep directory, just stop writing to it.
