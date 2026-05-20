---
review:
  spec_hash: 890bd787f960ec4f
  last_run: "2026-05-19"
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "### Fix 2: Prompt output to optimized/"
      section_hash: b67833ace8ab350c
      text: "_PROMPTS_OPTIMIZED_DIR используется без определения — нет инициализации в спеке"
      verdict: fixed
      verdict_at: "2026-05-19"
    - id: F-002
      phase: clarity
      severity: INFO
      section: "### Fix 1 / ### Fix 2"
      section_hash: f75e2a8bb798f9c5
      text: "Номера строк с ~ — приблизительные ссылки без DoD для локации"
      verdict: fixed
      verdict_at: "2026-05-19"
---
# Design: Fix propose_optimizations.py — nested eval fields + prompt output dir

## Problem

Two bugs in `scripts/propose_optimizations.py`:

1. **No candidates found** — `_flatten_recs` and item list comprehensions read `entry.get("rule_optimization")` at top level. Actual data lives at `entry["evaluator"]["rule_optimization"]`. 25 eval_log entries have evaluator data (14 rule, 4 security, 19 prompt recs) — all invisible to the script.

2. **Prompt writes bypass review** — `_rewrite_prompt_file` overwrites `data/prompts/<target>.md` directly. User wants to review before applying. Output should go to `data/prompts/optimized/<target>.md`.

## Solution

Minimal patch — two independent fixes, no architectural changes.

### Fix 1: Nested field access

Six substitutions in `propose_optimizations.py`:

**`_flatten_recs` (locate by function name):**
```python
# before
if entry.get(channel, []):

# after
ev = entry.get("evaluator") or {}
if ev.get(channel, []):
```

**Three list comprehensions in `main()` (locate by `entry.get("rule_optimization"`):**
```python
# before
for rec in entry.get("rule_optimization", [])
for rec in entry.get("security_optimization", [])
for rec in entry.get("prompt_optimization", [])

# after
for rec in (entry.get("evaluator") or {}).get("rule_optimization", [])
for rec in (entry.get("evaluator") or {}).get("security_optimization", [])
for rec in (entry.get("evaluator") or {}).get("prompt_optimization", [])
```

### Fix 2: Prompt output to optimized/

Replace the `_rewrite_prompt_file` call in the prompt loop with append-to-optimized logic.

Add at module level (near other `_PROMPTS_*` constants):
```python
_PROMPTS_OPTIMIZED_DIR = Path("data/prompts/optimized")
```
`_PROMPTS_OPTIMIZED_DIR.mkdir(parents=True, exist_ok=True)` called once in `main()` before the prompt loop.

**New helper function:**
```python
def _append_optimized_prompt(target: str, content: str) -> None:
    dest = _PROMPTS_OPTIMIZED_DIR / target
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    sep = "\n\n" if existing else ""
    dest.write_text(existing + sep + content, encoding="utf-8")
    print(f"[propose] appended to optimized/{target}")
```

**Prompt loop in `main()` (locate by `for raw_rec, entry, all_hashes in prompt_clusters`):**

`_synthesize_prompt_patch` already runs for routing and returns `{target_file, content}` (markdown section with `## heading`). Reuse `patch_result["content"]` directly — no second LLM call needed.

Before writing, run `_check_contradiction` against `rules_md + security_md + content of existing optimized/<target>.md` to block conflicts with already-staged sections and with rules/security.

```python
for raw_rec, entry, all_hashes in prompt_clusters:
    patch_result = _synthesize_prompt_patch(raw_rec, prompts_md, model, cfg)
    if patch_result is None:
        new_processed.update(all_hashes)
        print("  → skip (null/vague)")
        continue
    target = patch_result["target_file"]
    content = patch_result["content"]
    # Check against rules + security + already-staged optimized content
    optimized_existing = ""
    opt_path = _PROMPTS_OPTIMIZED_DIR / target
    if opt_path.exists():
        optimized_existing = opt_path.read_text(encoding="utf-8")
    combined_existing = "\n\n".join(filter(None, [rules_md, security_md, optimized_existing]))
    conflict = _check_contradiction(content, combined_existing, model, cfg)
    if conflict:
        print(f"  → skip (contradiction: {conflict})")
        new_processed.update(all_hashes)
        continue
    if dry_run:
        print(f"  → [DRY RUN] optimized/{target}: {content[:200]}")
    else:
        _append_optimized_prompt(target, content)
        new_processed.update(all_hashes)
        written += 1
```

`target_to_recs` grouping dict and `_rewrite_prompt_file` call are removed from `main()`. `_rewrite_prompt_file` function itself stays in file (not deleted — may have test coverage).

## Tests

Three new test cases in `tests/test_propose_optimizations.py`:

1. `test_flatten_recs_reads_from_evaluator_nested` — entry with top-level empty + `evaluator.rule_optimization` populated → `_flatten_recs` returns entry
2. `test_prompt_writes_to_optimized_dir` — mock `_synthesize_prompt_patch` returns `{target_file, content}` → file written to `data/prompts/optimized/`, not `data/prompts/`
3. `test_prompt_append_not_overwrite` — two runs → `optimized/<target>.md` contains both sections

## Not changed

- `_rewrite_prompt_file` stays in file, not called from `main()`
- `_synthesize_prompt_patch` logic unchanged
- `target_to_recs` grouping removed (no longer needed — each cluster writes immediately)
- All existing rule/security pipeline unchanged
