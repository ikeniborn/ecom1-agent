---
state: draft
created: 2026-05-20
review:
  plan_hash: cd50d2247dab23c8
  spec_hash: ce8d03e7f2c32050
  last_run: 2026-05-20
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: WARNING
      section: "### Component 1 — sdd.md fix"
      section_hash: 09d4c1574739c13d
      text: "Spec requires unit test for Component 1: mock SDD LLM response with natural-language action → verify pipeline raises/retries. Plan Task 1 has only grep verification (Step 2), no unit test step."
      verdict: fixed
      verdict_at: 2026-05-20
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "### Component 2 — CONSOLIDATE phase"
      section_hash: f7b2ba0724ab665b
      text: "Spec requires integration test: run t40 with LOG_LEVEL=DEBUG, confirm CONSOLIDATE fires and reduces active rule count. Not covered in any plan task."
      verdict: fixed
      verdict_at: 2026-05-20
---

# Learned Knowledge Consolidation + SDD Action Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix SDD natural-language action fallback and add CONSOLIDATE phase that merges redundant learned rules after each LEARN cycle.

**Architecture:** Two targeted changes — (1) add "Standard Unix tools" section to `data/prompts/sdd.md` so SDD emits `/bin/ls` instead of prose; (2) add `_run_consolidate()` in `agent/pipeline.py` called after every `_run_learn`, backed by a new `data/prompts/consolidate.md` guide and `ConsolidateOutput` Pydantic model.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, pytest, existing `_call_llm_phase` / `_apply_learn_diff` infrastructure.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `data/prompts/sdd.md` | Add Standard Unix tools section + strengthen action-format constraint |
| Modify | `agent/models.py` | Add `ConsolidationItem`, `ConsolidateOutput` |
| Modify | `agent/llm.py` | Add `"consolidate"` entry to `_PHASE_MODEL_MAP` |
| Modify | `agent/pipeline.py` | Add `MAX_TOKENS_CONSOLIDATE`, `_run_consolidate()`, wire calls after each `_run_learn` |
| Create | `data/prompts/consolidate.md` | CONSOLIDATE phase LLM guide |
| Modify | `.env.example` | Add `MODEL_CONSOLIDATE`, `MAX_TOKENS_CONSOLIDATE` |
| Modify | `CLAUDE.md` | Add new env vars to table |
| Modify | `tests/test_pipeline.py` | Add `_run_consolidate` unit tests, patch `load_learned_entries` in existing test with `task_id` |

---

### Task 1: Fix `data/prompts/sdd.md`

**Files:**
- Modify: `data/prompts/sdd.md`

- [ ] **Step 1: Add Standard Unix tools section after "Action Rules"**

Open `data/prompts/sdd.md`. After the `## Action Rules` block (line 23), insert:

```markdown
## Standard Unix tools (always available)

`/bin/ls`, `/bin/cat`, `/bin/tree`, `/bin/grep` are always available even if absent from `important_tools`.
Use them for filesystem operations without vault confirmation.

An action MUST be an executable string in one of these forms:
- SQL query: starts with `SELECT`
- File read: absolute path starting with `/` (no arguments)
- Exec: absolute path `/bin/<name>` or `/usr/<name>` followed by space-separated args

Never write a natural-language sentence as an action value.
If you cannot express the required operation as one of the forms above, set `actions` to `[]`.
```

The existing `## Action Rules` text stays unchanged. The new section is inserted between `## Action Rules` block and `## Prompt Injection` block.

- [ ] **Step 2: Write unit test — SDD natural-language action triggers pipeline retry**

Create `tests/test_sdd_action_fix.py`. Uses helpers from `tests/test_pipeline.py`:

```python
import json
from unittest.mock import MagicMock, patch

from agent.pipeline import run_pipeline
from tests.test_pipeline import (
    _make_pre, _mock_assemble, _seq_llm,
    _plan_json, _learn_json, _answer_json, _sdd_json,
)


def _nl_sdd_json():
    return json.dumps({
        "thoughts": "need to list files",
        "actions": ["List the payment record files in proc/payments/ directory,"],
        "sql": "",
        "answer": "",
    })


def test_pipeline_retries_when_sdd_emits_prose_action():
    """Natural-language action → exec fails → LEARN → retry with valid action → success."""
    vm = MagicMock()
    vm.exec.side_effect = [
        MagicMock(error="runtime tool not found", rows=[]),
        MagicMock(error="", rows=[["result"]]),
    ]
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([
             _nl_sdd_json(), _plan_json(), _learn_json(),
             _sdd_json(), _plan_json(), _answer_json(),
         ])), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None), \
         patch("agent.pipeline.load_learned_entries", return_value=[]):
        stats, _ = run_pipeline(vm, "model", "task", pre, {}, task_id="t99")

    assert stats["outcome"] != "OUTCOME_NONE_CLARIFICATION"
```

Run:
```bash
uv run pytest tests/test_sdd_action_fix.py -v
```
Expected: 1 test PASSES.

- [ ] **Step 3: Verify file looks correct**

Run:
```bash
grep -n "Standard Unix\|natural-language\|bin/ls" data/prompts/sdd.md
```
Expected: 3 matching lines appear.

- [ ] **Step 4: Commit**

```bash
git add data/prompts/sdd.md tests/test_sdd_action_fix.py
git commit -m "fix(sdd): add Standard Unix tools section, forbid natural-language actions"
```

---

### Task 2: Add Pydantic models to `agent/models.py`

**Files:**
- Modify: `agent/models.py`
- Test: `tests/test_models_consolidate.py` (new file)

- [ ] **Step 1: Write failing test**

Create `tests/test_models_consolidate.py`:

```python
from agent.models import ConsolidationItem, ConsolidateOutput


def test_consolidate_output_default_is_skip():
    out = ConsolidateOutput()
    assert out.skip is True
    assert out.consolidations == []
    assert out.skip_reason is None


def test_consolidation_item_fields():
    item = ConsolidationItem(
        deactivate=["r002", "r003"],
        merged_rule="use /bin/ls for directory listing",
        merged_reasoning="r002 and r003 are duplicates",
    )
    assert item.deactivate == ["r002", "r003"]
    assert "r002" in item.merged_reasoning


def test_consolidate_output_with_consolidations():
    out = ConsolidateOutput(
        skip=False,
        skip_reason=None,
        consolidations=[
            ConsolidationItem(
                deactivate=["r002", "r003"],
                merged_rule="merged rule content",
                merged_reasoning="r002 and r003 overlap",
            )
        ],
    )
    assert out.skip is False
    assert len(out.consolidations) == 1
    assert out.consolidations[0].deactivate == ["r002", "r003"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_models_consolidate.py -v
```
Expected: `ImportError: cannot import name 'ConsolidationItem'`

- [ ] **Step 3: Add models to `agent/models.py`**

Add after the `LearnOutput` class (after line 35):

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

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_models_consolidate.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/models.py tests/test_models_consolidate.py
git commit -m "feat(models): add ConsolidationItem and ConsolidateOutput"
```

---

### Task 3: Create `data/prompts/consolidate.md`

**Files:**
- Create: `data/prompts/consolidate.md`

- [ ] **Step 1: Create the prompt file**

Create `data/prompts/consolidate.md` with this exact content:

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

- [ ] **Step 2: Verify file created**

```bash
uv run python -c "from agent.prompt import load_prompt; p = load_prompt('consolidate'); assert p, 'empty'; print('OK', len(p), 'chars')"
```
Expected: `OK <N> chars`

- [ ] **Step 3: Commit**

```bash
git add data/prompts/consolidate.md
git commit -m "feat(prompts): add consolidate.md phase guide"
```

---

### Task 4: Add env config for CONSOLIDATE phase

**Files:**
- Modify: `agent/llm.py` (lines 67-73 — `_PHASE_MODEL_MAP`)
- Modify: `agent/pipeline.py` (lines 32-38 — `_PHASE_MAX_TOKENS`)

- [ ] **Step 1: Add `"consolidate"` to `_PHASE_MODEL_MAP` in `agent/llm.py`**

Current block (lines 67-73):
```python
_PHASE_MODEL_MAP: dict[str, str | None] = {
    "sdd":       os.environ.get("MODEL_SDD") or None,
    "plan":      os.environ.get("MODEL_PLAN") or None,
    "executor":  os.environ.get("MODEL_EXECUTOR") or None,
    "learn":     os.environ.get("MODEL_LEARN") or None,
    "assembler": os.environ.get("MODEL_ASSEMBLER") or None,
}
```

Replace with:
```python
_PHASE_MODEL_MAP: dict[str, str | None] = {
    "sdd":         os.environ.get("MODEL_SDD") or None,
    "plan":        os.environ.get("MODEL_PLAN") or None,
    "executor":    os.environ.get("MODEL_EXECUTOR") or None,
    "learn":       os.environ.get("MODEL_LEARN") or None,
    "assembler":   os.environ.get("MODEL_ASSEMBLER") or None,
    "consolidate": os.environ.get("MODEL_CONSOLIDATE") or None,
}
```

- [ ] **Step 2: Add `MAX_TOKENS_CONSOLIDATE` to `_PHASE_MAX_TOKENS` in `agent/pipeline.py`**

Current block (lines 32-38):
```python
_PHASE_MAX_TOKENS: dict[str, int] = {
    "sdd":       int(os.environ.get("MAX_TOKENS_SDD",       "8192")),
    "plan":      int(os.environ.get("MAX_TOKENS_PLAN",      "4096")),
    "learn":     int(os.environ.get("MAX_TOKENS_LEARN",     "2048")),
    "assembler": int(os.environ.get("MAX_TOKENS_ASSEMBLER", "4096")),
    "answer":    int(os.environ.get("MAX_TOKENS_ANSWER",    "4096")),
}
```

Replace with:
```python
_PHASE_MAX_TOKENS: dict[str, int] = {
    "sdd":         int(os.environ.get("MAX_TOKENS_SDD",         "8192")),
    "plan":        int(os.environ.get("MAX_TOKENS_PLAN",        "4096")),
    "learn":       int(os.environ.get("MAX_TOKENS_LEARN",       "2048")),
    "assembler":   int(os.environ.get("MAX_TOKENS_ASSEMBLER",   "4096")),
    "answer":      int(os.environ.get("MAX_TOKENS_ANSWER",      "4096")),
    "consolidate": int(os.environ.get("MAX_TOKENS_CONSOLIDATE", "2048")),
}
```

- [ ] **Step 3: Verify import still works**

```bash
uv run python -c "from agent.pipeline import run_pipeline; from agent.llm import _resolve_model_for_phase; print(_resolve_model_for_phase('consolidate', 'fallback'))"
```
Expected: prints `fallback` (env var not set).

- [ ] **Step 4: Commit**

```bash
git add agent/llm.py agent/pipeline.py
git commit -m "feat(config): add MODEL_CONSOLIDATE and MAX_TOKENS_CONSOLIDATE env vars"
```

---

### Task 5: Implement `_run_consolidate()` in `agent/pipeline.py`

**Files:**
- Modify: `agent/pipeline.py`
- Test: `tests/test_consolidate.py` (new file)

- [ ] **Step 1: Write failing tests**

Create `tests/test_consolidate.py`:

```python
import json
from unittest.mock import MagicMock, patch, call

from agent.pipeline import _run_consolidate


def _consolidate_skip_json():
    return json.dumps({
        "skip": True,
        "skip_reason": "all rules distinct",
        "consolidations": [],
    })


def _consolidate_merge_json(deactivate=None, merged_rule="merged content"):
    return json.dumps({
        "skip": False,
        "skip_reason": None,
        "consolidations": [
            {
                "deactivate": deactivate or ["r002", "r003"],
                "merged_rule": merged_rule,
                "merged_reasoning": "r002 and r003 are duplicates",
            }
        ],
    })


def _make_entry(eid, content, status="active"):
    return {"id": eid, "content": content, "status": status}


def test_run_consolidate_fewer_than_2_active_skips_llm():
    """With 1 active entry, no LLM call made."""
    entries = [_make_entry("r001", "only rule")]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw") as mock_llm:
        _run_consolidate("mocked-ctx", "model", {}, "t01", ["only rule"], cycle=1)

    mock_llm.assert_not_called()


def test_run_consolidate_zero_active_skips_llm():
    """With 0 active entries, no LLM call made."""
    entries = [_make_entry("r001", "rule", status="inactive")]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw") as mock_llm:
        _run_consolidate("mocked-ctx", "model", {}, "t01", [], cycle=1)

    mock_llm.assert_not_called()


def test_run_consolidate_skip_true_no_apply():
    """LLM returns skip=true → _apply_learn_diff not called, learn_ctx unchanged."""
    entries = [
        _make_entry("r002", "rule A"),
        _make_entry("r003", "rule B"),
    ]
    learn_ctx = ["rule A", "rule B"]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw", return_value=_consolidate_skip_json()), \
         patch("agent.pipeline._apply_learn_diff") as mock_apply:
        _run_consolidate("ctx", "model", {}, "t01", learn_ctx, cycle=1)

    mock_apply.assert_not_called()
    assert learn_ctx == ["rule A", "rule B"]


def test_run_consolidate_merges_rules():
    """LLM returns consolidation → _apply_learn_diff called, learn_ctx reduced."""
    entries = [
        _make_entry("r002", "rule A"),
        _make_entry("r003", "rule B"),
        _make_entry("r007", "rule C"),
    ]
    learn_ctx = ["rule A", "rule B", "rule C"]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw", return_value=_consolidate_merge_json(
             deactivate=["r002", "r003"], merged_rule="merged rule",
         )), \
         patch("agent.pipeline._apply_learn_diff") as mock_apply:
        _run_consolidate("ctx", "model", {}, "t01", learn_ctx, cycle=1)

    mock_apply.assert_called_once()
    call_args = mock_apply.call_args[0]
    assert call_args[0] == "t01"           # task_id
    assert call_args[1] == "merged rule"   # merged_rule
    assert call_args[3] == ["r002", "r003"]  # deactivate list
    # learn_ctx: rule A and rule B removed, merged rule added
    assert "rule A" not in learn_ctx
    assert "rule B" not in learn_ctx
    assert "merged rule" in learn_ctx
    assert "rule C" in learn_ctx           # untouched entry remains


def test_run_consolidate_empty_merged_rule_skips_item():
    """Consolidation item with empty merged_rule is silently skipped."""
    entries = [_make_entry("r001", "A"), _make_entry("r002", "B")]

    bad_json = json.dumps({
        "skip": False,
        "skip_reason": None,
        "consolidations": [{"deactivate": ["r001"], "merged_rule": "", "merged_reasoning": "bad"}],
    })

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw", return_value=bad_json), \
         patch("agent.pipeline._apply_learn_diff") as mock_apply:
        _run_consolidate("ctx", "model", {}, "t01", ["A", "B"], cycle=1)

    mock_apply.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_consolidate.py -v
```
Expected: `ImportError: cannot import name '_run_consolidate'`

- [ ] **Step 3: Implement `_run_consolidate()` in `agent/pipeline.py`**

Add the import at the top of `agent/pipeline.py` (line 22, after the existing models import):
```python
from .models import SddOutput, PlanOutput, ExecuteOutput, LearnOutput, AnswerOutput, ConsolidateOutput
```

Add the `_run_consolidate` function after `_run_learn` (before `run_pipeline`, around line 283):

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
        max_tokens=_PHASE_MAX_TOKENS["consolidate"], phase="consolidate", cycle=cycle,
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_consolidate.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_consolidate.py
git commit -m "feat(pipeline): implement _run_consolidate() with unit tests"
```

---

### Task 6: Wire `_run_consolidate` into `run_pipeline` + fix existing tests

**Files:**
- Modify: `agent/pipeline.py` (6 call sites of `_run_learn` — each followed by `continue`)
- Modify: `tests/test_pipeline.py` (patch `load_learned_entries` in `test_all_cycles_exhausted`)

- [ ] **Step 1: Add `_run_consolidate` call after each `_run_learn` in `run_pipeline`**

There are 6 places in `run_pipeline` where `_run_learn(...)` is called followed by `continue`. After each one, insert `_run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)`.

Pattern to apply 6 times (each call site looks slightly different but all end with `continue`):

**Call site 1** — SDD parse fail (around line 347-350):
```python
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type=sdd_err_type, cycle=cycle + 1, task_id=task_id)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
```

**Call site 2** — PLAN parse fail (around line 415-419):
```python
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="llm_fail" if not raw_plan else "semantic",
                           cycle=cycle + 1, task_id=task_id, sdd_out=sdd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
```

**Call site 3** — PLAN empty action (around line 424-428):
```python
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
```

**Call site 4** — EXECUTE fail (around line 449-453):
```python
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
```

**Call site 5** — EXECUTE empty result (around line 459-463):
```python
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="empty", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
```

**Call site 6** — ANSWER parse fail (around line 489-494):
```python
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
```

- [ ] **Step 2: Fix `test_all_cycles_exhausted` in `tests/test_pipeline.py`**

`test_all_cycles_exhausted` uses `task_id="t01"` which points to a real YAML file.
`_run_consolidate` calls `load_learned_entries(task_id)` — if real file has ≥2 active entries it would fire an extra LLM call, breaking the mock sequence.

Patch `load_learned_entries` to return `[]` in that test:

Current test (around lines 154-173):
```python
def test_all_cycles_exhausted():
    """All cycles fail → OUTCOME_NONE_CLARIFICATION."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result("")  # always empty
    pre = _make_pre()

    import agent.pipeline as pl
    max_cycles = pl._MAX_CYCLES

    call_seq = []
    for _ in range(max_cycles):
        call_seq.extend([_sdd_json(), _plan_json(), _learn_json()])

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm(call_seq)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        stats, eval_thread = run_pipeline(vm, "model", "task", pre, {}, task_id="t01")

    assert stats["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    assert eval_thread is None
```

Replace the `with patch(...)` block with:
```python
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm(call_seq)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None), \
         patch("agent.pipeline.load_learned_entries", return_value=[]):
        stats, eval_thread = run_pipeline(vm, "model", "task", pre, {}, task_id="t01")
```

- [ ] **Step 3: Run all existing pipeline tests**

```bash
uv run pytest tests/test_pipeline.py -v
```
Expected: all tests PASS (same count as before, no new failures).

- [ ] **Step 4: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): wire _run_consolidate after each _run_learn"
```

---

### Task 7: Update `.env.example` and `CLAUDE.md`

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add vars to `.env.example`**

In `.env.example`, after the `MODEL_ASSEMBLER=` line (line 22), add:
```
MODEL_CONSOLIDATE=                   # CONSOLIDATE phase model (defaults to MODEL)
```

In the `# ─── Phase Max Tokens ────` block, after `MAX_TOKENS_LEARN=2048` (line 28), add:
```
MAX_TOKENS_CONSOLIDATE=2048          # CONSOLIDATE phase response limit
```

- [ ] **Step 2: Add vars to `CLAUDE.md` env-var table**

In `CLAUDE.md`, find the env-var table. After the `MODEL_LEARN` row, add:
```
| `MODEL_CONSOLIDATE` | Override for CONSOLIDATE phase (defaults to `MODEL`) |
```

After the `MAX_TOKENS_LEARN` row, add:
```
| `MAX_TOKENS_CONSOLIDATE` | Max tokens for CONSOLIDATE phase response (default 2048) |
```

- [ ] **Step 3: Integration check — verify CONSOLIDATE fires on t40**

Run t40 with debug logging and check CONSOLIDATE output:

```bash
LOG_LEVEL=DEBUG TASKS=t40 uv run python main.py 2>&1 | grep -E "\[pipeline\] CONSOLIDATE|CONSOLIDATE phase"
```
Expected: at least one `[pipeline] CONSOLIDATE: N merge(s)` line appears after a LEARN cycle.
If t40 has <2 active rules (fresh run), trigger LEARN first by letting it fail one cycle.

- [ ] **Step 4: Run full test suite to confirm clean**

```bash
uv run pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: add MODEL_CONSOLIDATE and MAX_TOKENS_CONSOLIDATE to env docs"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|-----------------|------|
| Fix sdd.md — Standard Unix tools section | Task 1 |
| Fix sdd.md — action-format constraint | Task 1 |
| Unit test: prose SDD action triggers pipeline retry | Task 1 |
| `ConsolidationItem` + `ConsolidateOutput` models | Task 2 |
| `data/prompts/consolidate.md` | Task 3 |
| `MODEL_CONSOLIDATE` env routing | Task 4 |
| `MAX_TOKENS_CONSOLIDATE` | Task 4 |
| `_run_consolidate()` function | Task 5 |
| Call after every `_run_learn` | Task 6 |
| Unit test: 3 overlapping rules → `_apply_learn_diff` once, learn_ctx reduced | Task 5 |
| Unit test: 1 active rule → no LLM call | Task 5 |
| Regression: existing tests pass | Task 6 |
| Integration: CONSOLIDATE fires on t40 | Task 7 |
| `.env.example` + `CLAUDE.md` docs | Task 7 |

### Placeholder scan

No TBDs or "similar to Task N" references. All code blocks complete.

### Type consistency

- `ConsolidationItem` defined in Task 2, imported and used in Task 5.
- `_run_consolidate` signature defined in Task 5, wired in Task 6 with identical args.
- `_apply_learn_diff(task_id, rule_content, reasoning, deactivate, deactivate_reason)` — matches existing signature in `agent/prompt_assembler.py`.
- `_PHASE_MAX_TOKENS["consolidate"]` key added in Task 4 before used in Task 5.
