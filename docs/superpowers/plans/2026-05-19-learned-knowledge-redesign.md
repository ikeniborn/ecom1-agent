# Learned Knowledge Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `data/rules/` + `data/security/` with a permanent per-task knowledge base in `data/learned/{task_id}.yaml` with LLM-driven dedup/consolidation on every rule addition.

**Architecture:** Each task gets a permanent YAML file of knowledge entries with `active`/`inactive` status. On every LEARN phase call, existing active entries are passed to the LLM alongside the new rule; the LLM returns a diff (`deactivate[]` + `skip` flag) applied atomically to the file and in-memory `learn_ctx`. Rules/security YAML directories are deleted; eval_log and the offline optimizer are removed.

**Tech Stack:** Python, PyYAML, Pydantic, pytest; files in `agent/`, `tests/`, `data/`, `scripts/`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `agent/prompt_assembler.py` | Modify | New YAML schema: `load_learned_ctx`, `load_learned_entries`, `_next_entry_id`, `_apply_learn_diff`; remove `save_learned_ctx`, `clear_learned_ctx`; remove RULES/SECURITY/PROMPT_BLOCKS from `_build_sources` |
| `agent/models.py` | Modify | Extend `LearnOutput`: add `deactivate`, `deactivate_reason`, `skip`, `skip_reason`; remove `compacted_ctx`; remove `PipelineEvalOutput` |
| `agent/pipeline.py` | Modify | Remove `_rules_loader_cache`, `_security_gates_cache`, `load_security_gates`, `clear_learned_ctx`, eval/evaluator block; update `_build_learn_user_msg` + `_run_learn`; update `run_pipeline` |
| `agent/sql_security.py` | Modify | `check_retry_loop` becomes standalone (no `security_gates` param); remove `load_security_gates` |
| `tests/test_learned_storage.py` | Create | Tests for new storage functions: `load_learned_ctx`, `load_learned_entries`, `_apply_learn_diff` |
| `tests/conftest.py` | Modify | Remove `_rules_loader_cache`/`_security_gates_cache` resets and `_EVAL_ENABLED` setup |
| `tests/test_pipeline.py` | Modify | Remove `load_security_gates` patches; update `_run_learn` mock calls |
| `tests/test_pipeline_models.py` | Modify | Update `LearnOutput` tests for new fields |
| `tests/test_prompt_assembler.py` | Modify | Update for new learned schema, remove RULES/SECURITY patches |
| `agent/rules_loader.py` | Delete | No longer used |
| `agent/evaluator.py` | Delete | No longer used |
| `agent/knowledge_loader.py` | Delete | No longer used (was only for propose_optimizations) |
| `scripts/propose_optimizations.py` | Delete | Replaced by in-pipeline consolidation |
| `scripts/migrate_learned.py` | Create | One-time migration from flat list to new schema |
| `tests/test_propose_optimizations.py` | Delete | Module deleted |
| `tests/test_rules_loader.py` | Delete | Module deleted |
| `tests/test_knowledge_loader.py` | Delete | Module deleted |
| `tests/test_evaluator.py` | Delete | Module deleted |
| `data/rules/` | Delete dir | Replaced by per-task data/learned/ |
| `data/security/` | Delete dir | Gates removed; retry-loop guard hardcoded |
| `data/eval_log.jsonl` | Delete | No longer written |
| `data/.eval_optimizations_processed` | Delete | No longer needed |
| `data/prompts/pipeline_evaluator.md` | Delete | Evaluator removed |
| `data/prompts/learn.md` | Modify | Add consolidation fields: `deactivate`, `deactivate_reason`, `skip`, `skip_reason` |
| `data/prompts/assembler.md` | Modify | Remove RULES/SECURITY/PROMPT_BLOCKS; update section list |
| `data/prompts/sdd.md` | Modify | Remove ECOM/SQL-specific hints |
| `data/prompts/tdd.md` | Modify | Remove task-specific references |
| `data/prompts/answer.md` | Modify | Remove task-specific references |
| `.env.example` | Modify | Remove `EVAL_ENABLED`, `MODEL_EVALUATOR` |
| `CLAUDE.md` | Modify | Update env vars table, architecture section |

---

## Task 1: New learned YAML storage — tests

**Files:**
- Create: `tests/test_learned_storage.py`

- [ ] **Step 1: Write failing tests for new storage functions**

```python
# tests/test_learned_storage.py
import yaml
import pytest
from unittest.mock import patch
from pathlib import Path


def _write_new_schema(path: Path, entries: list[dict]) -> None:
    path.write_text(
        yaml.dump({"task_id": path.stem, "entries": entries}, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def test_load_learned_ctx_returns_only_active(tmp_path):
    from agent.prompt_assembler import load_learned_ctx
    _write_new_schema(tmp_path / "t01.yaml", [
        {"id": "r001", "content": "Always SELECT sku", "status": "active", "source": "learn",
         "created": "2026-05-19", "reasoning": "needed", "deactivated_reason": None},
        {"id": "r002", "content": "Old rule", "status": "inactive", "source": "learn",
         "created": "2026-05-18", "reasoning": "old", "deactivated_reason": "superseded"},
    ])
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        ctx = load_learned_ctx("t01")
    assert ctx == ["Always SELECT sku"]
    assert "Old rule" not in ctx


def test_load_learned_ctx_empty_file(tmp_path):
    from agent.prompt_assembler import load_learned_ctx
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        assert load_learned_ctx("t01") == []


def test_load_learned_ctx_no_task_id(tmp_path):
    from agent.prompt_assembler import load_learned_ctx
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        assert load_learned_ctx("") == []


def test_load_learned_entries_returns_all(tmp_path):
    from agent.prompt_assembler import load_learned_entries
    _write_new_schema(tmp_path / "t01.yaml", [
        {"id": "r001", "content": "rule 1", "status": "active", "source": "learn",
         "created": "2026-05-19", "reasoning": "", "deactivated_reason": None},
        {"id": "r002", "content": "rule 2", "status": "inactive", "source": "learn",
         "created": "2026-05-18", "reasoning": "", "deactivated_reason": "old"},
    ])
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        entries = load_learned_entries("t01")
    assert len(entries) == 2
    assert entries[0]["id"] == "r001"
    assert entries[1]["status"] == "inactive"


def test_apply_learn_diff_adds_first_entry(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_ctx, load_learned_entries
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Always SELECT sku", "sku needed", [], None)
        entries = load_learned_entries("t01")
        assert len(entries) == 1
        assert entries[0]["id"] == "r001"
        assert entries[0]["status"] == "active"
        assert entries[0]["source"] == "learn"
        assert load_learned_ctx("t01") == ["Always SELECT sku"]


def test_apply_learn_diff_deactivates_entries(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_ctx
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Rule 1", "reason 1", [], None)
        _apply_learn_diff("t01", "Rule 2", "reason 2", ["r001"], "superseded by rule 2")
        ctx = load_learned_ctx("t01")
    assert ctx == ["Rule 2"]


def test_apply_learn_diff_id_monotonic(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_entries
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Rule 1", "r1", [], None)
        _apply_learn_diff("t01", "Rule 2", "r2", [], None)
        _apply_learn_diff("t01", "Rule 3", "r3", [], None)
        entries = load_learned_entries("t01")
    assert [e["id"] for e in entries] == ["r001", "r002", "r003"]


def test_apply_learn_diff_deactivated_ids_stay_in_file(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_entries
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Old rule", "old reason", [], None)
        _apply_learn_diff("t01", "New rule", "new reason", ["r001"], "superseded")
        entries = load_learned_entries("t01")
    assert len(entries) == 2
    assert entries[0]["status"] == "inactive"
    assert entries[0]["deactivated_reason"] == "superseded"
    assert entries[1]["status"] == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_learned_storage.py -v
```
Expected: FAIL with `ImportError` or `AttributeError` — `load_learned_entries`, `_apply_learn_diff` not yet defined.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_learned_storage.py
git commit -m "test: add failing tests for new learned storage schema"
```

---

## Task 2: New learned YAML storage — implementation

**Files:**
- Modify: `agent/prompt_assembler.py`

- [ ] **Step 1: Replace storage functions in `agent/prompt_assembler.py`**

Replace the three existing functions (`load_learned_ctx`, `save_learned_ctx`, `clear_learned_ctx`) with the new implementation. The section to replace spans lines 25–56.

```python
def load_learned_ctx(task_id: str) -> list[str]:
    """Return content of active entries from data/learned/{task_id}.yaml."""
    entries = load_learned_entries(task_id)
    return [e["content"] for e in entries if e.get("status") == "active"]


def load_learned_entries(task_id: str) -> list[dict]:
    """Return all entries (active + inactive) from data/learned/{task_id}.yaml."""
    if not task_id:
        return []
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        return list(data.get("entries", []))
    except Exception:
        return []


def _next_entry_id(entries: list[dict]) -> str:
    """Generate next monotonic id rNNN (never reuses existing ids)."""
    used: set[int] = set()
    for e in entries:
        eid = e.get("id", "")
        if isinstance(eid, str) and eid.startswith("r") and eid[1:].isdigit():
            used.add(int(eid[1:]))
    return f"r{(max(used, default=0) + 1):03d}"


def _apply_learn_diff(
    task_id: str,
    rule_content: str,
    reasoning: str,
    deactivate: list[str],
    deactivate_reason: str | None,
    source: str = "learn",
) -> None:
    """Append new rule entry and deactivate specified entries in data/learned/{task_id}.yaml."""
    if not task_id:
        return
    from datetime import date
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    else:
        data = {}
    entries: list[dict] = list(data.get("entries", []))
    for entry in entries:
        if entry.get("id") in deactivate:
            entry["status"] = "inactive"
            entry["deactivated_reason"] = deactivate_reason or "Deactivated by consolidation"
    entries.append({
        "id": _next_entry_id(entries),
        "content": rule_content,
        "status": "active",
        "source": source,
        "created": str(date.today()),
        "reasoning": reasoning,
        "deactivated_reason": None,
    })
    path.write_text(
        yaml.dump({"task_id": task_id, "entries": entries}, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
```

Also update the `assemble_prompt` function: remove the `persisted = load_learned_ctx(task_id)` + merge line, since `learn_ctx` already reflects the persisted state (updated incrementally by `_apply_learn_diff`). Replace lines 118–119 with:

```python
def assemble_prompt(...) -> AssembledPrompt:
    """Call LLM assembler to produce unified_context from all sources."""
    assembler_guide = load_prompt("assembler")
    sources = _build_sources(task_text, task_type, prephase_result, learn_ctx)
    ...
```

- [ ] **Step 2: Run storage tests**

```bash
uv run pytest tests/test_learned_storage.py -v
```
Expected: all PASS.

- [ ] **Step 3: Run full test suite to catch regressions**

```bash
uv run python -m pytest tests/ -v 2>&1 | tail -30
```
Expected: existing tests may fail on `save_learned_ctx`/`clear_learned_ctx` — note them, fix in Task 7.

- [ ] **Step 4: Commit**

```bash
git add agent/prompt_assembler.py
git commit -m "feat: new learned YAML schema with _apply_learn_diff and load_learned_entries"
```

---

## Task 3: Extend LearnOutput model

**Files:**
- Modify: `agent/models.py`
- Modify: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pipeline_models.py`:

```python
def test_learn_output_new_fields_defaults():
    obj = LearnOutput(
        reasoning="diagnosis",
        conclusion="summary",
        rule_content="Always use sku",
    )
    assert obj.deactivate == []
    assert obj.deactivate_reason is None
    assert obj.skip is False
    assert obj.skip_reason is None


def test_learn_output_skip_flag():
    obj = LearnOutput(
        reasoning="already covered",
        conclusion="rule exists",
        rule_content="",
        skip=True,
        skip_reason="Duplicate of r002",
    )
    assert obj.skip is True
    assert obj.skip_reason == "Duplicate of r002"


def test_learn_output_deactivate_list():
    obj = LearnOutput(
        reasoning="new rule supersedes old",
        conclusion="updated",
        rule_content="Use LIKE not equality",
        deactivate=["r001", "r003"],
        deactivate_reason="Superseded by more specific rule",
    )
    assert obj.deactivate == ["r001", "r003"]
    assert obj.deactivate_reason == "Superseded by more specific rule"


def test_learn_output_no_compacted_ctx():
    # compacted_ctx removed — verify it's not accepted
    import pydantic
    with pytest.raises((pydantic.ValidationError, TypeError)):
        LearnOutput(
            reasoning="r", conclusion="c", rule_content="x",
            compacted_ctx=["rule 1"],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_pipeline_models.py::test_learn_output_new_fields_defaults tests/test_pipeline_models.py::test_learn_output_skip_flag tests/test_pipeline_models.py::test_learn_output_deactivate_list tests/test_pipeline_models.py::test_learn_output_no_compacted_ctx -v
```
Expected: FAIL — new fields don't exist yet.

- [ ] **Step 3: Update `LearnOutput` in `agent/models.py`**

Replace the `LearnOutput` class:

```python
class LearnOutput(BaseModel):
    reasoning: str
    conclusion: str
    rule_content: str
    agents_md_anchor: str | None = None
    deactivate: list[str] = []
    deactivate_reason: str | None = None
    skip: bool = False
    skip_reason: str | None = None
```

Also remove `PipelineEvalOutput` from `models.py` (it's only used by `evaluator.py` which will be deleted). Remove lines 66–76.

- [ ] **Step 4: Run model tests**

```bash
uv run pytest tests/test_pipeline_models.py -v
```
Expected: all PASS (including the `compacted_ctx` test that verifies removal).

- [ ] **Step 5: Commit**

```bash
git add agent/models.py tests/test_pipeline_models.py
git commit -m "feat: extend LearnOutput with deactivate/skip fields, remove compacted_ctx and PipelineEvalOutput"
```

---

## Task 4: Standalone `check_retry_loop`

**Files:**
- Modify: `agent/sql_security.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_sql_security.py` (find the test file):

```python
def test_check_retry_loop_standalone_blocks_duplicate():
    from agent.sql_security import check_retry_loop
    queries = ["SELECT COUNT(*) FROM products"]
    prior = [frozenset(queries)]
    result = check_retry_loop(queries, prior)
    assert result is not None
    assert "identical" in result.lower() or "loop" in result.lower()


def test_check_retry_loop_standalone_allows_new():
    from agent.sql_security import check_retry_loop
    queries = ["SELECT COUNT(*) FROM products"]
    result = check_retry_loop(queries, [])
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sql_security.py::test_check_retry_loop_standalone_blocks_duplicate tests/test_sql_security.py::test_check_retry_loop_standalone_allows_new -v
```
Expected: FAIL — `check_retry_loop` requires 3 args including `security_gates`.

- [ ] **Step 3: Update `check_retry_loop` in `agent/sql_security.py`**

Replace:
```python
def check_retry_loop(
    queries: list[str],
    prior_query_sets: list[frozenset],
    security_gates: list[dict],
) -> str | None:
    """Block identical query retry without Learn mutation (sec-073)."""
    for gate in security_gates:
        if gate.get("check") != "no_identical_query_retry_without_learn_mutation":
            continue
        if frozenset(queries) in prior_query_sets:
            return f"[{gate['id']}] {gate['message']}"
    return None
```

With:
```python
def check_retry_loop(
    queries: list[str],
    prior_query_sets: list[frozenset],
) -> str | None:
    """Block identical query retry — anti-infinite-loop guard."""
    if frozenset(queries) in prior_query_sets:
        return "Identical query set detected — infinite loop prevention"
    return None
```

- [ ] **Step 4: Run security tests**

```bash
uv run pytest tests/test_sql_security.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/sql_security.py tests/test_sql_security.py
git commit -m "feat: make check_retry_loop standalone (no security_gates param)"
```

---

## Task 5: Update `_run_learn` in `pipeline.py`

**Files:**
- Modify: `agent/pipeline.py`

- [ ] **Step 1: Update `_build_learn_user_msg` signature and body**

Replace the existing `_build_learn_user_msg` (lines 172–178):

```python
def _build_learn_user_msg(
    task_text: str,
    queries: list[str],
    error: str,
    error_type: str,
    existing_entries: list[dict],
) -> str:
    base = (
        f"TASK: {task_text}\n"
        f"FAILED QUERIES: {json.dumps(queries)}\n"
        f"ERROR: {error}\n"
        f"ERROR_TYPE: {error_type}"
    )
    if existing_entries:
        rules_lines = "\n".join(
            f"  - id: {e['id']}\n    content: {e['content']!r}"
            for e in existing_entries
            if e.get("status") == "active"
        )
        if rules_lines:
            base += f"\n\nEXISTING_RULES:\n{rules_lines}"
    return base
```

- [ ] **Step 2: Update `_run_learn` function (lines 248–305)**

Replace the entire `_run_learn` function:

```python
def _run_learn(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    queries: list[str],
    error: str,
    sgr_trace: list[dict],
    learn_ctx: list[str],
    agents_md_index: dict,
    error_type: str = "semantic",
    cycle: int = 0,
    task_id: str = "",
) -> None:
    learn_model = _resolve_model_for_phase("learn", model)
    learn_guide = load_prompt("learn") or "# PHASE: learn"
    learn_system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": learn_guide, "cache_control": {"type": "ephemeral"}},
    ]
    existing_entries = load_learned_entries(task_id) if task_id else []
    learn_user = _build_learn_user_msg(task_text, queries, error, error_type, existing_entries)
    learn_out, sgr_learn, _ = _call_llm_phase(
        learn_system, learn_user, learn_model, cfg, LearnOutput,
        max_tokens=2048, phase="learn", cycle=cycle,
    )
    sgr_learn["error_type"] = error_type
    sgr_trace.append(sgr_learn)
    if not learn_out or error_type == "llm_fail":
        return
    if learn_out.skip:
        print(f"{CLI_BLUE}[pipeline] LEARN: skipped ({learn_out.skip_reason}){CLI_CLR}")
        return
    anchor = learn_out.agents_md_anchor
    if anchor:
        anchor_section = anchor.split(">")[0].strip()
        if anchor_section in agents_md_index:
            anchor_lines = agents_md_index[anchor_section]
            vault_rule = f"[{anchor_section}]\n" + "\n".join(anchor_lines)
            if task_id:
                _apply_learn_diff(task_id, vault_rule, f"anchor:{anchor}", [], None, source="learn")
            learn_ctx.append(vault_rule)
            print(f"{CLI_BLUE}[pipeline] LEARN: anchor={anchor!r}, vault rule added{CLI_CLR}")
            return
    # Apply diff
    if task_id:
        _apply_learn_diff(
            task_id,
            learn_out.rule_content,
            learn_out.reasoning,
            learn_out.deactivate,
            learn_out.deactivate_reason,
            source="learn",
        )
    # Update in-memory learn_ctx: remove deactivated, append new
    if learn_out.deactivate:
        deactivate_contents = {
            e["content"] for e in existing_entries
            if e.get("id") in learn_out.deactivate
        }
        learn_ctx[:] = [r for r in learn_ctx if r not in deactivate_contents]
    learn_ctx.append(learn_out.rule_content)
    print(f"{CLI_BLUE}[pipeline] LEARN: rule added, deactivated={learn_out.deactivate} (total active={len(learn_ctx)}){CLI_CLR}")
```

- [ ] **Step 3: Update the import line in `pipeline.py`**

Replace line 27:
```python
from .prompt_assembler import assemble_prompt, load_learned_ctx, save_learned_ctx, clear_learned_ctx
```
With:
```python
from .prompt_assembler import assemble_prompt, load_learned_ctx, load_learned_entries, _apply_learn_diff
```

- [ ] **Step 4: Update all `_run_learn` call sites in `run_pipeline` to remove `prior_learn_hashes` param**

Find all 6 `_run_learn(...)` calls in `run_pipeline` and remove the `prior_learn_hashes=prior_learn_hashes` argument from each. Also remove `prior_learn_hashes: set[str] = set()` initialization.

- [ ] **Step 5: Run tests (expecting failures due to other pipeline changes still pending)**

```bash
uv run pytest tests/test_pipeline.py -v 2>&1 | head -40
```

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py
git commit -m "feat: update _run_learn to use _apply_learn_diff and EXISTING_RULES in user message"
```

---

## Task 6: Update `run_pipeline` — remove security gates and evaluator

**Files:**
- Modify: `agent/pipeline.py`

- [ ] **Step 1: Update the import block at the top of `pipeline.py`**

Remove from lines 28–34:
```python
from .rules_loader import RulesLoader, _RULES_DIR
```
```python
from .sql_security import (
    check_path_access, load_security_gates,
    check_grounding_refs, check_learn_output,
    check_retry_loop, make_json_hash,
)
```

Replace with:
```python
from .sql_security import check_path_access, check_grounding_refs, check_retry_loop
```

- [ ] **Step 2: Remove module-level caches and their getter functions (lines 61–76)**

Delete:
```python
_rules_loader_cache: "RulesLoader | None" = None
_security_gates_cache: "list[dict] | None" = None

def _get_rules_loader() -> RulesLoader: ...
def _get_security_gates() -> list[dict]: ...
```

Also remove:
```python
_EVAL_ENABLED = os.environ.get("EVAL_ENABLED", "0") == "1"
_EVAL_LOG = Path(__file__).parent.parent / "data" / "eval_log.jsonl"
```

- [ ] **Step 3: Update `run_pipeline` signature and body**

Remove `injected_security_gates` param from signature.

At the start of `run_pipeline`, remove:
```python
rules_loader = _get_rules_loader()
security_gates = _get_security_gates() + (injected_security_gates or [])
```

In the retry-loop guard call, update to standalone signature:
```python
retry_err = check_retry_loop(sql_queries, prior_query_sets)
```

Remove path-access calls that depend on security_gates:
- `execute_error = check_path_access(_exec_path, security_gates)` → delete (SQL always allowed)
- `path_err = check_path_access(op_path, security_gates)` → delete (exec always allowed)

Remove `check_grounding_refs` call (returns None without gates — remove the block):
```python
ref_err = check_grounding_refs(...)
if ref_err:
    print(...)
```

- [ ] **Step 4: Remove success block eval_log and clear_learned_ctx calls**

In the SUCCESS block, remove:
```python
_append_eval_log(task_id, task_text, task_type, pre, sgr_trace, learn_ctx, cycles_used, outcome, None)
if task_id and learn_ctx:
    print(f"[pipeline] learn_ctx ({len(learn_ctx)} rules) moved to eval_log, data/learned/{task_id}.yaml cleared")
clear_learned_ctx(task_id)
```

Add a simple success log:
```python
if task_id:
    print(f"{CLI_BLUE}[pipeline] SUCCESS: {len(learn_ctx)} active rules in data/learned/{task_id}.yaml{CLI_CLR}")
```

- [ ] **Step 5: Remove evaluator block (lines 762–796) and `_run_evaluator_safe` / `_append_eval_log` functions**

Delete the entire evaluator thread launch block and both functions `_append_eval_log` and `_run_evaluator_safe`.

Update return value to remove `eval_thread`:
```python
    stats = {
        "outcome": outcome,
        "cycles_used": cycles_used,
        "step_facts": [f"pipeline cycles={cycles_used}"],
        "done_ops": [],
        "input_tokens": total_in_tok,
        "output_tokens": total_out_tok,
        "total_elapsed_ms": 0,
    }
    return stats, None
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_pipeline.py -v 2>&1 | head -50
```

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline.py
git commit -m "feat: remove security gates, eval_log, evaluator from run_pipeline"
```

---

## Task 7: Update `_build_sources` in `prompt_assembler.py`

**Files:**
- Modify: `agent/prompt_assembler.py`

- [ ] **Step 1: Remove unused imports from `prompt_assembler.py`**

Remove from top of file:
```python
from .prompt import load_prompt, load_task_blocks
from .rules_loader import RulesLoader
from .sql_security import load_security_gates
```

Replace with:
```python
from .prompt import load_prompt
```

Also remove:
```python
_RULES_DIR = Path(__file__).parent.parent / "data" / "rules"
_SECURITY_DIR = Path(__file__).parent.parent / "data" / "security"
```

- [ ] **Step 2: Replace `_build_sources` body**

Replace the entire `_build_sources` function:

```python
def _build_sources(
    task_text: str,
    task_type: str,
    prephase_result: PrephaseResult,
    learn_ctx: list[str],
) -> str:
    parts: list[str] = []
    parts.append(f"TASK_TEXT: {task_text}")
    parts.append(f"TASK_TYPE: {task_type}")
    if learn_ctx:
        parts.append("## LEARNED (highest priority)\n" + "\n".join(f"- {r}" for r in learn_ctx))
    pre = prephase_result
    if pre.agents_md_content:
        parts.append(f"## VAULT\n{pre.agents_md_content}")
    if pre.schema_digest:
        parts.append(f"## SCHEMA_DIGEST\n{_format_schema_digest(pre.schema_digest)}")
    if pre.db_schema:
        parts.append(f"## DB_SCHEMA\n{pre.db_schema}")
    meta: list[str] = []
    if pre.current_date:
        meta.append(f"date: {pre.current_date}")
    if pre.agent_id:
        meta.append(f"customer_id: {pre.agent_id}")
    if meta:
        parts.append("## AGENT_CONTEXT\n" + "\n".join(meta))
    return "\n\n".join(parts)
```

- [ ] **Step 3: Run assembler tests**

```bash
uv run pytest tests/test_prompt_assembler.py -v
```

- [ ] **Step 4: Commit**

```bash
git add agent/prompt_assembler.py
git commit -m "feat: remove RULES/SECURITY/PROMPT_BLOCKS from assembler _build_sources"
```

---

## Task 8: Fix tests — conftest + test_pipeline + test_prompt_assembler

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_prompt_assembler.py`

- [ ] **Step 1: Update `tests/conftest.py`**

Replace entire file:

```python
"""Reset module-level caches between tests."""
import pytest
import agent.pipeline


@pytest.fixture(autouse=True)
def reset_pipeline_caches():
    agent.pipeline._SDD_ENABLED = True
    yield
    agent.pipeline._SDD_ENABLED = True
```

- [ ] **Step 2: Remove `load_security_gates` patches from `tests/test_pipeline.py`**

In every test that has `patch("agent.pipeline.load_security_gates", return_value=[])`, remove that patch line. There are 7 occurrences at lines 75, 106, 145, 181, 221, 245, 264. Also remove `patch("agent.pipeline._RULES_DIR", rules_dir)` and `rules_dir.mkdir()` setup.

Also remove any `injected_security_gates` argument from `run_pipeline` calls in tests.

- [ ] **Step 3: Update `tests/test_prompt_assembler.py`**

Replace the `test_assemble_returns_assembled_prompt` test and similar tests that patch `_RULES_DIR`/`_SECURITY_DIR`:

```python
def test_assemble_returns_assembled_prompt(tmp_path):
    pre = _make_pre()
    fake_unified = "# LEARNED\n\n# BASE\nbase"

    with patch("agent.prompt_assembler.call_llm_raw", return_value=fake_unified), \
         patch("agent.prompt_assembler._LEARNED_DIR", tmp_path / "learned"):
        (tmp_path / "learned").mkdir()
        result = assemble_prompt(
            task_text="find products with sku ABC",
            task_type="sql",
            prephase_result=pre,
            learn_ctx=["Never use ILIKE"],
            model="test-model",
            cfg={},
        )

    assert isinstance(result, AssembledPrompt)
    assert result.unified_context == fake_unified
```

Update `test_assemble_loads_learned_ctx_from_file` to use new schema format:

```python
def test_assemble_includes_learn_ctx_in_sources(tmp_path):
    pre = _make_pre()
    captured_sources = []

    def _capture_llm(system, user_msg, *args, **kwargs):
        captured_sources.append(user_msg)
        return "unified"

    with patch("agent.prompt_assembler.call_llm_raw", side_effect=_capture_llm), \
         patch("agent.prompt_assembler._LEARNED_DIR", tmp_path / "learned"):
        (tmp_path / "learned").mkdir()
        assemble_prompt(
            task_text="find skus",
            task_type="sql",
            prephase_result=pre,
            learn_ctx=["Always SELECT sku"],
            model="m",
            cfg={},
        )

    assert "Always SELECT sku" in captured_sources[0]
    assert "## LEARNED" in captured_sources[0]
```

- [ ] **Step 4: Run full test suite**

```bash
uv run python -m pytest tests/ -v 2>&1 | tail -40
```
Expected: most tests pass; failures in test files for deleted modules will be addressed in Task 9.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_pipeline.py tests/test_prompt_assembler.py
git commit -m "test: update conftest and pipeline tests for new architecture"
```

---

## Task 9: Delete unused modules and test files

**Files:**
- Delete: `agent/rules_loader.py`
- Delete: `agent/evaluator.py`
- Delete: `agent/knowledge_loader.py`
- Delete: `tests/test_propose_optimizations.py`
- Delete: `tests/test_rules_loader.py`
- Delete: `tests/test_knowledge_loader.py`
- Delete: `tests/test_evaluator.py`
- Delete: `scripts/propose_optimizations.py`

- [ ] **Step 1: Delete agent modules**

```bash
rm agent/rules_loader.py agent/evaluator.py agent/knowledge_loader.py
```

- [ ] **Step 2: Delete test files for deleted modules**

```bash
rm tests/test_propose_optimizations.py tests/test_rules_loader.py tests/test_knowledge_loader.py tests/test_evaluator.py
```

- [ ] **Step 3: Delete the optimization script**

```bash
rm scripts/propose_optimizations.py
```

- [ ] **Step 4: Run tests to confirm no lingering imports**

```bash
uv run python -m pytest tests/ -v 2>&1 | tail -30
```
Expected: remaining tests pass; no ImportError for deleted modules.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: delete rules_loader, evaluator, knowledge_loader, propose_optimizations and their tests"
```

---

## Task 10: Delete data artifacts

**Files:**
- Delete: `data/rules/` directory
- Delete: `data/security/` directory
- Delete: `data/eval_log.jsonl`
- Delete: `data/.eval_optimizations_processed`
- Delete: `data/prompts/pipeline_evaluator.md`

- [ ] **Step 1: Delete data directories and files**

```bash
rm -rf data/rules/ data/security/
rm -f data/eval_log.jsonl data/.eval_optimizations_processed
rm -f data/prompts/pipeline_evaluator.md
```

- [ ] **Step 2: Run tests to verify no test depends on deleted files**

```bash
uv run python -m pytest tests/ -v 2>&1 | grep -E "FAIL|ERROR|PASS" | tail -20
```
Expected: no new failures.

- [ ] **Step 3: Run also test_data_files.py to check**

```bash
uv run pytest tests/test_data_files.py -v
```
Expected: if it checks for data/rules or data/security files, update the test or delete references.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete data/rules, data/security, eval_log.jsonl and pipeline_evaluator.md"
```

---

## Task 11: Migration script

**Files:**
- Create: `scripts/migrate_learned.py`

- [ ] **Step 1: Write the migration script**

```python
#!/usr/bin/env python3
"""One-time migration: convert flat list data/learned/{task_id}.yaml to new entry schema.

Run once before the first pipeline run after deploying the learned knowledge redesign.
Safe to run multiple times — skips files already in new schema format.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

_LEARNED_DIR = Path(__file__).parent.parent / "data" / "learned"


def _migrate_file(path: Path) -> bool:
    """Return True if migrated, False if already in new format or skipped."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  SKIP {path.name}: parse error: {e}")
        return False

    if not isinstance(data, dict):
        print(f"  SKIP {path.name}: not a dict")
        return False

    # Already in new format
    if "entries" in data:
        print(f"  SKIP {path.name}: already migrated")
        return False

    task_id = data.get("task_id", path.stem)
    old_ctx: list[str] = data.get("learn_ctx", [])

    today = str(date.today())
    entries = [
        {
            "id": f"r{i + 1:03d}",
            "content": rule,
            "status": "active",
            "source": "learn",
            "created": today,
            "reasoning": "",
            "deactivated_reason": None,
        }
        for i, rule in enumerate(old_ctx)
        if isinstance(rule, str) and rule.strip()
    ]

    new_data = {"task_id": task_id, "entries": entries}
    path.write_text(
        yaml.dump(new_data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"  MIGRATED {path.name}: {len(entries)} entries")
    return True


def main() -> None:
    if not _LEARNED_DIR.exists():
        print(f"No learned directory at {_LEARNED_DIR} — nothing to migrate.")
        return

    files = sorted(_LEARNED_DIR.glob("*.yaml"))
    if not files:
        print("No .yaml files in data/learned/ — nothing to migrate.")
        return

    print(f"Migrating {len(files)} file(s) in {_LEARNED_DIR}:")
    migrated = sum(_migrate_file(f) for f in files)
    print(f"\nDone: {migrated}/{len(files)} file(s) migrated.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable and run dry test**

```bash
chmod +x scripts/migrate_learned.py
uv run python scripts/migrate_learned.py
```
Expected: migrates any remaining flat-format files in `data/learned/`.

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_learned.py
git commit -m "feat: add migrate_learned.py one-time migration script"
```

---

## Task 12: Update `data/prompts/learn.md`

**Files:**
- Modify: `data/prompts/learn.md`

- [ ] **Step 1: Rewrite `learn.md` to include consolidation fields**

Replace the entire file content:

```markdown
# Learn Phase

You are diagnosing a failed operation to derive a corrective rule and consolidate the knowledge base.

/no_think

## Task

Given the task, the failed queries/operations, the error, and the EXISTING_RULES knowledge base, diagnose what went wrong and either:
- Produce a new rule and specify which existing rules (if any) it supersedes, OR
- Skip (if the new rule is already covered by an existing rule)

## Output Rules

- Output PURE JSON only. The very first character must be `{`.
- All string fields must be non-empty and reference concrete identifiers (table, column, key, literal) — no generic phrases.

## Output Format (JSON only)

```json
{
  "reasoning": "<diagnosis: verbatim error, root cause, failing fragment, rule linkage>",
  "conclusion": "<one-sentence summary naming the precise mechanism of failure>",
  "rule_content": "<new rule starting with Never/Always/Use — cite concrete identifier>",
  "agents_md_anchor": "<section_key > entry, or null>",
  "skip": false,
  "skip_reason": null,
  "deactivate": [],
  "deactivate_reason": null
}
```

## Field Definitions

**`reasoning`** — MUST contain all four components:
1. Verbatim error quote (exact, no paraphrase)
2. Root cause category: `syntax` | `empty-result` | `wrong-filter` | `wrong-column` | `wrong-value-type` | `wrong-key` | `join-cardinality`
3. Failing fragment citation (SQL snippet, column ref, predicate)
4. Rule linkage — `rule_content` must reference the cited fragment

**`rule_content`** — actionable rule, starts with "Never", "Always", or "Use". Must cite ≥1 concrete identifier from the failed operation.

**`agents_md_anchor`** — if failure was caused by ignoring an AGENTS.MD section: `"<section_key> > <entry>"`. Set to `null` otherwise.

**`skip`** — set to `true` if the new rule would be semantically identical to or fully covered by an existing rule in EXISTING_RULES. When `skip=true`, set `skip_reason` to the id of the covering rule (e.g. `"r003"`). `rule_content` may be empty.

**`deactivate`** — list of entry ids from EXISTING_RULES that the new rule supersedes or contradicts. Empty list if none.

**`deactivate_reason`** — one sentence explaining why the listed entries are superseded. Set to `null` if `deactivate` is empty.

## Consolidation Logic

After producing `rule_content`, compare it against each entry in EXISTING_RULES:

1. **Duplicate** — new rule says the same thing as existing rule `rXXX`:
   - Set `skip=true`, `skip_reason="rXXX"`, `rule_content=""`, `deactivate=[]`

2. **Supersedes** — new rule is more specific or correct, making `rXXX` obsolete:
   - Set `skip=false`, `deactivate=["rXXX"]`, `deactivate_reason="<why rXXX is now wrong/redundant>"`

3. **Novel** — new rule addresses a different failure pattern from all existing rules:
   - Set `skip=false`, `deactivate=[]`, `deactivate_reason=null`

## Conclusion Specificity

Name the precise mechanism — not the symptom. If an existing rule covers this pattern, cite it by id.

- **Bad:** `"query returned empty"`, `"only SELECT allowed"`
- **Good:** `"r003 already covers missing GROUP BY"`, `"no existing rule — planner used path column instead of sku for grounding_refs"`

## Loop Prevention

If the corrected query would be identical to the failed query (whitespace/case-insensitive), set:
- `rule_content`: `"No structural fix available — escalate to clarification"`
- `conclusion`: name the blocking constraint
```

- [ ] **Step 2: Verify learn.md has no domain-specific content**

```bash
grep -iE "sku|ecom|product|grounding_refs|sql-[0-9]+|sec-[0-9]+" data/prompts/learn.md
```
Expected: no matches (all domain-specific removed; generic "sku" reference removed, grounding_refs removed).

- [ ] **Step 3: Commit**

```bash
git add data/prompts/learn.md
git commit -m "feat: update learn.md with consolidation logic (deactivate/skip fields)"
```

---

## Task 13: Update `assembler.md` and clean remaining prompts

**Files:**
- Modify: `data/prompts/assembler.md`
- Modify: `data/prompts/sdd.md`
- Modify: `data/prompts/tdd.md`
- Modify: `data/prompts/answer.md`

- [ ] **Step 1: Update `assembler.md`**

Replace the Input and Output sections. Remove all references to RULES, SECURITY, PROMPT_BLOCKS. The input now has only: TASK_TEXT, TASK_TYPE, LEARNED, VAULT, SCHEMA_DIGEST, DB_SCHEMA, AGENT_CONTEXT.

Replace the "## Input" section:
```markdown
## Input

You receive:
- TASK_TEXT and TASK_TYPE
- LEARNED — in-session rules from prior failure cycles (highest priority)
- VAULT — rules from AGENTS.MD (domain authority)
- SCHEMA_DIGEST and DB_SCHEMA — database structure
- AGENT_CONTEXT — metadata (date, customer_id)
```

Replace the "## Output" section's section list:
```markdown
## Output

Return a single markdown document with exactly these sections in order:

```
# LEARNED
<rules from LEARNED, newest last; omit if empty>

# BASE
<domain rules from VAULT relevant to this task; omit irrelevant sections>

# SCHEMA
<schema digest and db schema>
```
```

Remove the priority statement that references RULES/SECURITY.

- [ ] **Step 2: Clean `sdd.md`**

Remove or replace all ECOM/SQL-specific content. DoD: `grep -iE "sku|ecom|product\.name|grounding_refs|inventory|lawn|mower|basket|checkout|discount|voucher|3ds|payment" data/prompts/sdd.md` returns no matches.

Keep only: role description, plan step types (sql/read/compute/exec), output format, agents_md_refs rules, general restrictions.

Remove sections: "Exec Tool Restriction" examples with `/bin/discount` and `/bin/payments` (or generalize to describe exec type without ECOM-specific binaries).

- [ ] **Step 3: Clean `tdd.md`**

Verify and remove any domain-specific SQL examples or ECOM table names. DoD: `grep -iE "sku|ecom|product|inventory|basket" data/prompts/tdd.md` returns no matches.

- [ ] **Step 4: Clean `answer.md`**

Verify and remove any domain-specific examples. DoD: `grep -iE "sku|ecom|product\.name|grounding_refs" data/prompts/answer.md` returns no matches.

- [ ] **Step 5: Run DoD checks**

```bash
grep -iE "sku|ecom|product\.name|grounding_refs|inventory" data/prompts/sdd.md && echo "FAIL sdd" || echo "PASS sdd"
grep -iE "sku|ecom|product|inventory|basket" data/prompts/tdd.md && echo "FAIL tdd" || echo "PASS tdd"
grep -iE "sku|ecom|product\.name|grounding_refs" data/prompts/answer.md && echo "FAIL answer" || echo "PASS answer"
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add data/prompts/assembler.md data/prompts/sdd.md data/prompts/tdd.md data/prompts/answer.md
git commit -m "feat: update assembler.md, clean sdd/tdd/answer prompts of domain-specific content"
```

---

## Task 14: Update `.env.example` and `CLAUDE.md`

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`
- Possibly modify: `agent/CLAUDE.md`

- [ ] **Step 1: Remove `EVAL_ENABLED` and `MODEL_EVALUATOR` from `.env.example`**

Delete the "Evaluator" section block:
```
# ─── Evaluator ──────────────────────────────────────────────────────────────
EVAL_ENABLED=0                       # 1 = запускать evaluator после каждой задачи, пишет data/eval_log.jsonl
MODEL_EVALUATOR=                     # модель для evaluator (напр. anthropic/claude-haiku-4-5); если пусто — evaluator не запускается
```

- [ ] **Step 2: Update `CLAUDE.md` env vars table**

Remove rows:
```
| `MODEL_EVALUATOR` | LLM for evaluation scoring; if unset evaluator is disabled |
| `EVAL_ENABLED=1` | Run evaluator after each successful task |
```

Update architecture description: remove references to `eval_log`, evaluator, `propose_optimizations.py`, `data/rules/*.yaml`, `data/security/*.yaml`.

Update the "Key Data Files" table: remove `data/rules/*.yaml`, `data/security/*.yaml`, `data/eval_log.jsonl` rows. Update `data/learned/{task_id}.yaml` description to: "Permanent per-task knowledge base; entries have active/inactive status; never deleted".

Update "Notable Constraints": remove `_rules_loader_cache`, `_security_gates_cache` mentions.

Also update `agent/CLAUDE.md`: remove references to `clear_learned_ctx`, `save_learned_ctx`, `data/rules/*.yaml`, `data/security/*.yaml`, evaluator.

- [ ] **Step 3: Commit**

```bash
git add .env.example CLAUDE.md agent/CLAUDE.md
git commit -m "docs: update CLAUDE.md and .env.example — remove eval, rules, security references"
```

---

## Task 15: Final verification

- [ ] **Step 1: Run full test suite**

```bash
uv run python -m pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 2: Run migration script on actual data**

```bash
uv run python scripts/migrate_learned.py
```
Expected: migrates any remaining flat-format files.

- [ ] **Step 3: Verify learned files are in new format**

```bash
python3 -c "
import yaml, glob
for f in glob.glob('data/learned/*.yaml'):
    d = yaml.safe_load(open(f))
    assert 'entries' in d, f'{f} not migrated'
    print(f'{f}: {len(d[\"entries\"])} entries')
print('All files in new format.')
"
```

- [ ] **Step 4: Verify no references to deleted modules remain**

```bash
grep -r "rules_loader\|evaluator\|knowledge_loader\|propose_optimizations\|eval_log\|EVAL_ENABLED\|MODEL_EVALUATOR\|load_security_gates\|save_learned_ctx\|clear_learned_ctx" agent/ tests/ --include="*.py" | grep -v "^Binary"
```
Expected: no output.

- [ ] **Step 5: Verify DoD for deleted data directories**

```bash
test -d data/rules && echo "FAIL: data/rules still exists" || echo "PASS: data/rules deleted"
test -d data/security && echo "FAIL: data/security still exists" || echo "PASS: data/security deleted"
test -f data/eval_log.jsonl && echo "FAIL: eval_log.jsonl still exists" || echo "PASS: deleted"
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: learned knowledge redesign complete — permanent per-task knowledge base"
```
