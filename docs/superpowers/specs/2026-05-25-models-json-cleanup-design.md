---
review:
  spec_hash: 48f36818658b03a8
  last_run: 2026-05-25
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  section_hashes:
    Problem:                  8052566ba0797f1e
    Goals:                    9e14b89c85d0fe7c
    Scope_what_changes:       02592f2b6545142a
    Scope_what_not_change:    86f1002b8cd3c368
    Validation:               0e44a7f519491ae0
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: Scope_what_changes
      section_hash: 02592f2b6545142a
      text: ".env.example CC comment update — clarified: only MODEL_IDD= added, no versioned key update needed"
      verdict: fixed
      verdict_at: 2026-05-25
---
# Design: models.json Cleanup & Inline Profiles

Date: 2026-05-25

## Problem

`models.json` has accumulated dead configuration that is never read by any code:
- `_profiles` mechanism partially broken: `cc_options` strings never resolved → CC effort/timeout/exclude_dynamic silently ignored
- `thinking_budget` defined but never consumed by `llm.py`
- `ollama_options_think/longContext/coder/classifier/evaluator` variants never resolved or read
- `anthropic/claude-opus-4.6` references a non-existent Anthropic model
- `anthropic/claude-opus-4.7` missing from `_ANTHROPIC_MODEL_MAP` → API receives `"claude-opus-4.7"` (dot) instead of `"claude-opus-4-7"` (dash) → 404
- `claude-code/*` keys carry version suffixes; CC aliases (`haiku`, `sonnet`, `opus`) are version-agnostic

## Goals

1. Remove all dead config (nothing unreachable by code)
2. Fix `cc_options` silent discard bug by inlining dicts
3. Fix `claude-opus-4.7` model ID mapping
4. Standardize CC model keys to versionless aliases
5. Add `MODEL_IDD` to `.env.example`

## Scope — what changes

### models.json

**Remove entirely:**
- `_profiles` section
- `_ollama_tuning_rationale` section
- `anthropic/claude-opus-4.6` entry

**Remove from every model entry:**
- `thinking_budget` (all Anthropic entries)
- `ollama_options_think`, `ollama_options_longContext`, `ollama_options_coder`, `ollama_options_classifier`, `ollama_options_evaluator` (all Ollama entries)
- `cc_options_classifier` (all CC entries)

**Inline `ollama_options`:** replace string `"default"` with dict directly in each Ollama model entry.
Valid params confirmed via litellm Ollama provider: `num_ctx`, `temperature`, `seed`, `repeat_penalty`, `repeat_last_n`, `top_k`, `top_p`.

Default inline value (same as former `default` profile):
```json
{
  "num_ctx": 16384,
  "temperature": 0.35,
  "seed": 1,
  "repeat_penalty": 1.3,
  "repeat_last_n": 256,
  "top_k": 30,
  "top_p": 0.9
}
```

**Inline `cc_options`:** replace string references with dicts directly. Fixes the silent discard bug in `cc_client.py` (`isinstance(cc_opts, str) → cc_opts = {}`).

**Rename CC keys:**
- `claude-code/haiku-4.5` → `claude-code/haiku`
- `claude-code/sonnet-4.6` → `claude-code/sonnet`
- `claude-code/opus-4.7` → `claude-code/opus`

### llm.py

Add missing mapping and remove stale mapping in `_ANTHROPIC_MODEL_MAP` (line ~562):
```python
# Remove:
"claude-opus-4.6": "claude-opus-4-6",
# Add:
"claude-opus-4.7": "claude-opus-4-7",
```

### main.py

Remove `_profiles` variable and the resolve loop (lines 113–118):
```python
# DELETE:
_profiles: dict[str, dict] = _raw.get("_profiles", {})
...
for _cfg in MODEL_CONFIGS.values():
    for _fname in ("ollama_options", "ollama_options_classifier", "ollama_options_evaluator"):
        if isinstance(_cfg.get(_fname), str):
            _cfg[_fname] = _profiles.get(_cfg[_fname], {})
```

`MODEL_CONFIGS` line simplifies to single dict comprehension (already correct without profiles).

### .env.example

Add `MODEL_IDD=` to Phase Models section (between `MODEL_SDD=` and `MODEL_PLAN=`).

## Scope — what does NOT change

- All `agent/*.py` LLM routing logic — no changes
- Ollama cloud model keys (`:cloud` suffix stays)
- OpenRouter section — no changes
- `ollama_think` flag mechanism — stays
- `_fields` and `_section_*` comment keys — stays

## Validation

After changes:
1. `python -c "import json; d=json.load(open('models.json')); assert '_profiles' not in d"` — no profiles key
2. `grep -n "thinking_budget\|ollama_options_think\|cc_options_classifier" models.json` — no matches
3. `grep "claude-code/haiku-4.5\|claude-code/sonnet-4.6\|claude-code/opus-4.7" models.json` — no matches
4. `python -c "from agent.llm import get_anthropic_model_id; assert get_anthropic_model_id('anthropic/claude-opus-4.7') == 'claude-opus-4-7'"` — mapping correct
5. Existing tests pass: `uv run pytest tests/ -v`
