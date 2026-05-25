---
review:
  plan_hash: 12ae1639af245683
  spec_hash: 48f36818658b03a8
  last_run: 2026-05-25
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  section_hashes:
    File_Map:  b62d574e0db88f28
    Task_1:    1cbfabacb37dd690
    Task_2:    750d64d65051edfb
    Task_3:    bd634e272a490876
    Task_4:    197b3447c87be39e
    Task_5:    1492fe8d6fb82470
    Task_6:    58683164406538f3
  findings:
    - id: F-001
      phase: verifiability
      severity: WARNING
      section: Task_5
      section_hash: 1492fe8d6fb82470
      text: "Task 5 Step 1 has no verification command — missing grep/cat to confirm MODEL_IDD= was added"
      verdict: fixed
      verdict_at: 2026-05-25
    - id: F-002
      phase: verifiability
      severity: WARNING
      section: Task_4
      section_hash: 197b3447c87be39e
      text: "Task 4 Step 2 uses importlib.util.spec_from_file_location which never loads code — always prints 'syntax ok'; use python -m py_compile main.py instead"
      verdict: fixed
      verdict_at: 2026-05-25
---
# models.json Cleanup & Inline Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all dead config from `models.json`, fix `cc_options` silent discard bug by inlining dicts, fix `claude-opus-4.7` model ID mapping, standardize CC keys to versionless aliases.

**Architecture:** Four files change: `models.json` (major cleanup + inline), `agent/llm.py` (one line swap in `_ANTHROPIC_MODEL_MAP`), `main.py` (remove `_profiles` load + resolve loop), `.env.example` (add `MODEL_IDD=`). No logic changes — data cleanup only.

**Tech Stack:** Python 3.11+, pytest, uv

---

## File Map

| File | Change |
|------|--------|
| `tests/test_models_json_cleanup.py` | **Create** — TDD tests for all spec requirements |
| `models.json` | **Modify** — remove dead keys, inline dicts, rename CC keys |
| `agent/llm.py:561-566` | **Modify** — swap `claude-opus-4.6` → `claude-opus-4.7` in `_ANTHROPIC_MODEL_MAP` |
| `main.py:113-118` | **Modify** — remove `_profiles` var + resolve loop |
| `.env.example:18` | **Modify** — add `MODEL_IDD=` between `MODEL_SDD=` and `MODEL_PLAN=` |

---

## Task 1: Write Failing Tests

**Files:**
- Create: `tests/test_models_json_cleanup.py`

- [ ] **Step 1: Write the test file**

```python
import json
from pathlib import Path

import pytest

_MODELS = json.loads((Path(__file__).parent.parent / "models.json").read_text())


def test_no_profiles_section():
    assert "_profiles" not in _MODELS


def test_no_ollama_tuning_rationale():
    assert "_ollama_tuning_rationale" not in _MODELS


def test_no_dead_anthropic_opus46():
    assert "anthropic/claude-opus-4.6" not in _MODELS


def test_no_thinking_budget():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        assert "thinking_budget" not in cfg, f"{key} still has thinking_budget"


def test_no_ollama_variant_keys():
    dead = (
        "ollama_options_think",
        "ollama_options_longContext",
        "ollama_options_coder",
        "ollama_options_classifier",
        "ollama_options_evaluator",
    )
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        for dead_key in dead:
            assert dead_key not in cfg, f"{key} still has {dead_key}"


def test_no_cc_options_classifier():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        assert "cc_options_classifier" not in cfg, f"{key} still has cc_options_classifier"


def test_ollama_options_are_dicts():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        if "ollama_options" in cfg:
            assert isinstance(cfg["ollama_options"], dict), (
                f"{key}.ollama_options is a string, should be inlined dict"
            )


def test_cc_options_are_dicts():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        if "cc_options" in cfg:
            assert isinstance(cfg["cc_options"], dict), (
                f"{key}.cc_options is a string, should be inlined dict"
            )


def test_cc_keys_versionless():
    assert "claude-code/haiku" in _MODELS
    assert "claude-code/sonnet" in _MODELS
    assert "claude-code/opus" in _MODELS
    assert "claude-code/haiku-4.5" not in _MODELS
    assert "claude-code/sonnet-4.6" not in _MODELS
    assert "claude-code/opus-4.7" not in _MODELS


def test_anthropic_opus47_mapping():
    from agent.llm import get_anthropic_model_id
    assert get_anthropic_model_id("anthropic/claude-opus-4.7") == "claude-opus-4-7"


def test_anthropic_opus46_mapping_removed():
    from agent.llm import _ANTHROPIC_MODEL_MAP
    assert "claude-opus-4.6" not in _ANTHROPIC_MODEL_MAP
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_models_json_cleanup.py -v
```

Expected: all 12 tests FAIL (models.json not cleaned yet, llm.py not patched).

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_models_json_cleanup.py
git commit -m "test(models): add failing tests for models.json cleanup spec"
```

---

## Task 2: Clean Up models.json

**Files:**
- Modify: `models.json`

- [ ] **Step 1: Replace models.json with cleaned version**

Write the full file (replace entirely — there are many scattered changes):

```json
{
  "_comment": "Model capability configs. Key = model ID as used in env vars. Loaded by main.py at startup.",
  "_fields": {
    "provider": "Explicit provider: 'anthropic' | 'openrouter' | 'ollama'. If omitted, inferred from model name (name:tag → ollama, anthropic/... or claude → anthropic, else openrouter).",
    "max_completion_tokens": "Max tokens the model may generate per step",
    "response_format_hint": "Hint for OpenRouter tier: 'json_object' or 'json_schema'",
    "ollama_think": "Enable <think> blocks for Ollama models that support it",
    "ollama_options": "Ollama-specific options passed via extra_body.options (e.g. {num_ctx: 16384})",
    "seed": "Random seed for reproducible sampling (Ollama only); fixes the RNG state so identical prompt+seed always produces identical output. Use with temperature=0 for full determinism (classifier), or with low temperature to stabilize code generation (coder)",
    "cc_model": "Model alias passed as --model to iclaude CLI (e.g. 'haiku', 'sonnet', 'opus'). Provider='claude-code' only.",
    "cc_options": "Inline dict. Recognised keys: cc_effort (low|medium|high|xhigh|max), cc_timeout_s (int), cc_fallback_model (string → --fallback-model), cc_exclude_dynamic (bool → --exclude-dynamic-system-prompt-sections, improves cross-run prompt-cache reuse), cc_json_schema (raw JSON schema → --json-schema, used by classifier). --bare is intentionally NOT exposed (it breaks OAuth auth).",
    "ctx_window": "Context window size in tokens (input limit). Used by _compact_log for token-aware compaction threshold."
  },
  "_section_ollama_cloud": "--- Ollama cloud endpoint (OLLAMA_BASE_URL=https://your-cloud/v1) ---",
  "qwen3.5:cloud": {
    "provider": "ollama",
    "max_completion_tokens": 16000,
    "ollama_think": true,
    "ollama_options": {
      "num_ctx": 16384,
      "temperature": 0.35,
      "seed": 1,
      "repeat_penalty": 1.3,
      "repeat_last_n": 256,
      "top_k": 30,
      "top_p": 0.9
    },
    "ctx_window": 16384
  },
  "qwen3-coder-next:cloud": {
    "provider": "ollama",
    "max_completion_tokens": 16000,
    "ollama_think": false,
    "ollama_options": {
      "num_ctx": 16384,
      "temperature": 0.35,
      "seed": 1,
      "repeat_penalty": 1.3,
      "repeat_last_n": 256,
      "top_k": 30,
      "top_p": 0.9
    },
    "ctx_window": 16384
  },
  "qwen3.5:397b-cloud": {
    "provider": "ollama",
    "max_completion_tokens": 16000,
    "ollama_think": true,
    "ollama_options": {
      "num_ctx": 16384,
      "temperature": 0.35,
      "seed": 1,
      "repeat_penalty": 1.3,
      "repeat_last_n": 256,
      "top_k": 30,
      "top_p": 0.9
    },
    "ctx_window": 16384
  },
  "deepseek-v4-flash:cloud": {
    "provider": "ollama",
    "max_completion_tokens": 16000,
    "ollama_think": true,
    "ollama_options": {
      "num_ctx": 16384,
      "temperature": 0.35,
      "seed": 1,
      "repeat_penalty": 1.3,
      "repeat_last_n": 256,
      "top_k": 30,
      "top_p": 0.9
    },
    "ctx_window": 16384
  },
  "kimi-k2.6:cloud": {
    "provider": "ollama",
    "max_completion_tokens": 16000,
    "ollama_think": false,
    "ollama_options": {
      "num_ctx": 16384,
      "temperature": 0.35,
      "seed": 1,
      "repeat_penalty": 1.3,
      "repeat_last_n": 256,
      "top_k": 30,
      "top_p": 0.9
    },
    "ctx_window": 16384
  },
  "deepseek-v4-pro:cloud": {
    "provider": "ollama",
    "max_completion_tokens": 16000,
    "ollama_think": true,
    "ollama_options": {
      "num_ctx": 16384,
      "temperature": 0.35,
      "seed": 1,
      "repeat_penalty": 1.3,
      "repeat_last_n": 256,
      "top_k": 30,
      "top_p": 0.9
    },
    "ctx_window": 16384
  },
  "_section_anthropic": "--- Anthropic SDK ---",
  "anthropic/claude-haiku-4.5": {
    "provider": "anthropic",
    "max_completion_tokens": 16384,
    "response_format_hint": "json_object",
    "ctx_window": 200000
  },
  "anthropic/claude-sonnet-4.6": {
    "provider": "anthropic",
    "max_completion_tokens": 16384,
    "response_format_hint": "json_object",
    "ctx_window": 200000
  },
  "anthropic/claude-opus-4.7": {
    "provider": "anthropic",
    "max_completion_tokens": 16384,
    "response_format_hint": "json_object",
    "ctx_window": 200000
  },
  "_section_openrouter": "--- OpenRouter ---",
  "qwen/qwen3.5-9b": {
    "provider": "openrouter",
    "max_completion_tokens": 16000,
    "response_format_hint": "json_object",
    "temperature": 0.35,
    "ctx_window": 131072
  },
  "meta-llama/llama-3.3-70b-instruct": {
    "provider": "openrouter",
    "max_completion_tokens": 16000,
    "response_format_hint": "json_object",
    "temperature": 0.35,
    "ctx_window": 131072
  },
  "_section_claude_code": "--- Claude Code CLI (iclaude subprocess, OAuth) ---",
  "claude-code/haiku": {
    "provider": "claude-code",
    "cc_model": "haiku",
    "cc_options": {
      "cc_effort": "low",
      "cc_timeout_s": 120,
      "cc_exclude_dynamic": true
    },
    "max_completion_tokens": 16384,
    "response_format_hint": "json_object",
    "ctx_window": 200000
  },
  "claude-code/sonnet": {
    "provider": "claude-code",
    "cc_model": "sonnet",
    "cc_options": {
      "cc_effort": "medium",
      "cc_timeout_s": 180,
      "cc_exclude_dynamic": true
    },
    "max_completion_tokens": 16384,
    "response_format_hint": "json_object",
    "ctx_window": 200000
  },
  "claude-code/opus": {
    "provider": "claude-code",
    "cc_model": "opus",
    "cc_options": {
      "cc_effort": "high",
      "cc_timeout_s": 240,
      "cc_exclude_dynamic": true
    },
    "max_completion_tokens": 16384,
    "response_format_hint": "json_object",
    "ctx_window": 200000
  }
}
```

- [ ] **Step 2: Validate JSON is valid**

```bash
python -c "import json; json.load(open('models.json')); print('JSON valid')"
```

Expected: `JSON valid`

- [ ] **Step 3: Run spec validation checks**

```bash
python -c "import json; d=json.load(open('models.json')); assert '_profiles' not in d; print('ok: no _profiles')"
grep -n "thinking_budget\|ollama_options_think\|cc_options_classifier" models.json && echo "FAIL: dead keys found" || echo "ok: no dead keys"
grep "claude-code/haiku-4.5\|claude-code/sonnet-4.6\|claude-code/opus-4.7" models.json && echo "FAIL: versioned CC keys found" || echo "ok: CC keys clean"
```

Expected: all three commands print `ok`.

---

## Task 3: Fix llm.py Anthropic Model Map

**Files:**
- Modify: `agent/llm.py:561-566`

- [ ] **Step 1: Replace the stale mapping**

In `agent/llm.py` at lines 561–566, change `_ANTHROPIC_MODEL_MAP` from:

```python
_ANTHROPIC_MODEL_MAP = {
    "claude-haiku-4.5": "claude-haiku-4-5-20251001",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
    "claude-sonnet-4.6": "claude-sonnet-4-6",
    "claude-opus-4.6": "claude-opus-4-6",
}
```

to:

```python
_ANTHROPIC_MODEL_MAP = {
    "claude-haiku-4.5": "claude-haiku-4-5-20251001",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
    "claude-sonnet-4.6": "claude-sonnet-4-6",
    "claude-opus-4.7": "claude-opus-4-7",
}
```

- [ ] **Step 2: Verify mapping**

```bash
python -c "from agent.llm import get_anthropic_model_id; assert get_anthropic_model_id('anthropic/claude-opus-4.7') == 'claude-opus-4-7'; print('ok')"
```

Expected: `ok`

---

## Task 4: Remove _profiles Loader from main.py

**Files:**
- Modify: `main.py:111-118`

- [ ] **Step 1: Remove `_profiles` and the resolve loop**

In `main.py`, the current block at lines 111–118:

```python
_MODELS_JSON = Path(__file__).parent / "models.json"
_raw = json.loads(_MODELS_JSON.read_text())
_profiles: dict[str, dict] = _raw.get("_profiles", {})
MODEL_CONFIGS: dict[str, dict] = {k: v for k, v in _raw.items() if not k.startswith("_")}
for _cfg in MODEL_CONFIGS.values():
    for _fname in ("ollama_options", "ollama_options_classifier", "ollama_options_evaluator"):
        if isinstance(_cfg.get(_fname), str):
            _cfg[_fname] = _profiles.get(_cfg[_fname], {})
```

Replace with:

```python
_MODELS_JSON = Path(__file__).parent / "models.json"
_raw = json.loads(_MODELS_JSON.read_text())
MODEL_CONFIGS: dict[str, dict] = {k: v for k, v in _raw.items() if not k.startswith("_")}
```

- [ ] **Step 2: Verify main.py syntax**

```bash
python -m py_compile main.py && echo "syntax ok"
```

Expected: `syntax ok`

---

## Task 5: Add MODEL_IDD to .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add MODEL_IDD= line**

In `.env.example`, the Phase Models section currently reads:

```
MODEL_SDD=                           # SDD phase model (defaults to MODEL)
MODEL_PLAN=                          # PLAN phase model (defaults to MODEL)
```

Insert `MODEL_IDD=` between them:

```
MODEL_SDD=                           # SDD phase model (defaults to MODEL)
MODEL_IDD=                           # IDD phase model (defaults to MODEL)
MODEL_PLAN=                          # PLAN phase model (defaults to MODEL)
```

- [ ] **Step 2: Verify MODEL_IDD= added**

```bash
grep "MODEL_IDD" .env.example
```

Expected: `MODEL_IDD=                           # IDD phase model (defaults to MODEL)`

---

## Task 6: Run All Tests & Final Validation

- [ ] **Step 1: Run the cleanup tests**

```bash
uv run pytest tests/test_models_json_cleanup.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS (no regressions).

- [ ] **Step 3: Run spec validation commands**

```bash
python -c "import json; d=json.load(open('models.json')); assert '_profiles' not in d; print('ok: no _profiles')"
grep -n "thinking_budget\|ollama_options_think\|cc_options_classifier" models.json && echo "FAIL" || echo "ok: no dead keys"
grep "claude-code/haiku-4.5\|claude-code/sonnet-4.6\|claude-code/opus-4.7" models.json && echo "FAIL" || echo "ok: CC keys clean"
python -c "from agent.llm import get_anthropic_model_id; assert get_anthropic_model_id('anthropic/claude-opus-4.7') == 'claude-opus-4-7'; print('ok: opus-4.7 mapped')"
```

Expected: all four print `ok`.

- [ ] **Step 4: Commit**

```bash
git add models.json agent/llm.py main.py .env.example tests/test_models_json_cleanup.py
git commit -m "refactor(models): clean up dead config, inline profiles, fix opus-4.7 mapping"
```
