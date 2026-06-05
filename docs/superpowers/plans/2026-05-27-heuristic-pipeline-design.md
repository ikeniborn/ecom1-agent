---
chain:
  intent: docs/superpowers/intents/2026-05-27-heuristic-pipeline-intent.md
  spec: docs/superpowers/specs/2026-05-27-heuristic-pipeline-design.md
review:
  plan_hash: "13fba8bf75330b19"
  spec_hash: "e236ecc26672c483"
  last_run: "2026-05-27"
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: dependencies
      severity: CRITICAL
      section: "Task 5: Implement _run_codegen()"
      section_hash: "1aebf3c9bb3907fd"
      text: "Task 5 Step 3 adds imports to pipeline.py but does NOT add load_last_run to 'from .prompt_assembler import ...' line. Task 8 Step 4 uses load_last_run(task_id) which will NameError at runtime."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-002
      phase: dependencies
      severity: CRITICAL
      section: "Task 6: Replace _run_answer()"
      section_hash: "d67383a3470b2727"
      text: "Task 6 Step 1 adds 'from agent.pipeline import _run_answer' at module level of tests/test_codegen.py before _run_answer exists. This causes ImportError on the whole file, breaking all Task 5 tests when test code is added in Step 1."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-003
      phase: dependencies
      severity: WARNING
      section: "Task 8: Wire fast path + CODEGEN/ANSWER into run_pipeline()"
      section_hash: "7815225472a0b527"
      text: "Fast path success returns hardcoded 'outcome': 'OUTCOME_OK' in stats dict regardless of actual script outcome (could be OUTCOME_DENIED_SECURITY). Stats will be inaccurate when script returns non-OK outcome."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-004
      phase: verifiability
      severity: WARNING
      section: "Task 9: Update .env.example and CLAUDE.md"
      section_hash: "57747f3fca4ae589"
      text: "Task 9 Step 2 says 'update the execution flow description to reference CODEGEN replacing EXECUTE, and add fast path description' without showing exact replacement text. No concrete expected output — cannot verify completion."
      verdict: fixed
      verdict_at: "2026-05-27"
---
# Heuristic-Driven Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-as-executor with LLM-as-heuristic-generator — pipeline generates a self-contained Python script (`data/heuristics/{task_id}.py`) that runs with zero LLM calls on repeat runs.

**Architecture:** Fast path checks for an existing valid heuristic and executes it directly (0 LLM calls). On first run or fast-path failure, the full cycle runs ASSEMBLE → IDD → SDD → PLAN → CODEGEN → ANSWER. CODEGEN replaces EXECUTE: LLM generates a Python script + mock test; ANSWER executes the script and calls `vm.answer()` directly without a further LLM call. LEARN passes the failed script to the LLM so next-cycle CODEGEN regenerates a better one.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, ast (stdlib), uv/pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `agent/models.py` | Modify | Add `CodegenOutput` model |
| `agent/prompt_assembler.py` | Modify | Extend `save_last_run` with `heuristic_valid` |
| `agent/llm.py` | Modify | Add `codegen` to `_PHASE_MODEL_MAP` |
| `agent/mock_vm.py` | Create | `MockVM` stub for CODEGEN mock-test execution |
| `agent/pipeline.py` | Modify | Fast path, `_run_codegen`, modified `_run_answer`, `_build_learn_user_msg` |
| `data/prompts/codegen.md` | Create | CODEGEN phase guide for LLM |
| `.env.example` | Modify | Add `MODEL_CODEGEN`, `MAX_TOKENS_CODEGEN`, `CODEGEN_LINT_RETRIES` |
| `CLAUDE.md` | Modify | Document new env vars and `data/heuristics/` dir |
| `tests/test_codegen.py` | Create | Tests for `_run_codegen` (lint loop, mock exec, success/failure paths) |
| `tests/test_mock_vm.py` | Create | Tests for `MockVM` |
| `tests/test_fast_path.py` | Create | Tests for fast path in `run_pipeline` |

---

## Task 1: Add `CodegenOutput` model + extend `save_last_run`

**Files:**
- Modify: `agent/models.py`
- Modify: `agent/prompt_assembler.py:59-90`
- Test: `tests/test_models.py` (extend existing), `tests/test_prompt_assembler.py` (extend existing)

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_models.py — add at bottom:
def test_codegen_output_model():
    from agent.models import CodegenOutput
    obj = CodegenOutput(
        script_path="data/heuristics/t01.py",
        script_code="_result = {'message': 'ok', 'outcome': 'OUTCOME_OK', 'refs': []}",
        test_code="assert True",
    )
    assert obj.script_path == "data/heuristics/t01.py"
    assert "OUTCOME_OK" in obj.script_code


# In tests/test_prompt_assembler.py — add at bottom:
def test_save_last_run_heuristic_valid(tmp_path, monkeypatch):
    from agent import prompt_assembler
    monkeypatch.setattr(prompt_assembler, "_LEARNED_DIR", tmp_path)
    prompt_assembler.save_last_run(
        task_id="t99",
        status="success",
        outcome="OUTCOME_OK",
        cycles_used=1,
        grounding_refs_count=2,
        heuristic_valid=True,
    )
    import yaml
    data = yaml.safe_load((tmp_path / "t99.yaml").read_text())
    assert data["last_run"]["heuristic_valid"] is True


def test_save_last_run_heuristic_valid_default_false(tmp_path, monkeypatch):
    from agent import prompt_assembler
    monkeypatch.setattr(prompt_assembler, "_LEARNED_DIR", tmp_path)
    prompt_assembler.save_last_run("t99", "failure", "OUTCOME_NONE_CLARIFICATION", 3)
    import yaml
    data = yaml.safe_load((tmp_path / "t99.yaml").read_text())
    assert data["last_run"]["heuristic_valid"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_models.py::test_codegen_output_model tests/test_prompt_assembler.py::test_save_last_run_heuristic_valid tests/test_prompt_assembler.py::test_save_last_run_heuristic_valid_default_false -v
```

Expected: FAIL — `ImportError: cannot import name 'CodegenOutput'` and `TypeError: unexpected keyword argument 'heuristic_valid'`

- [ ] **Step 3: Add `CodegenOutput` to `agent/models.py`**

Add after `AnswerOutput` class (after line 97):

```python
class CodegenOutput(BaseModel):
    script_path: str
    script_code: str
    test_code: str
```

- [ ] **Step 4: Extend `save_last_run` in `agent/prompt_assembler.py`**

Replace the function signature and `data["last_run"]` assignment:

```python
def save_last_run(
    task_id: str,
    status: str,
    outcome: str,
    cycles_used: int,
    grounding_refs_count: int = 0,
    heuristic_valid: bool = False,
) -> None:
    """Write last_run metadata to data/learned/{task_id}.yaml."""
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
    data["task_id"] = task_id
    data["last_run"] = {
        "status": status,
        "outcome": outcome,
        "cycles_used": cycles_used,
        "grounding_refs_count": grounding_refs_count,
        "heuristic_valid": heuristic_valid,
        "date": str(date.today()),
    }
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_models.py::test_codegen_output_model tests/test_prompt_assembler.py::test_save_last_run_heuristic_valid tests/test_prompt_assembler.py::test_save_last_run_heuristic_valid_default_false -v
```

Expected: PASS

- [ ] **Step 6: Run full test suite to check no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all previously passing tests still pass

- [ ] **Step 7: Commit**

```bash
git add agent/models.py agent/prompt_assembler.py tests/test_models.py tests/test_prompt_assembler.py
git commit -m "feat(models): add CodegenOutput; extend save_last_run with heuristic_valid"
```

---

## Task 2: Add `codegen` to `_PHASE_MODEL_MAP` in `llm.py`

**Files:**
- Modify: `agent/llm.py:67-75`
- Test: `tests/test_llm_module.py` (extend existing)

- [ ] **Step 1: Write failing test**

```python
# In tests/test_llm_module.py — add at bottom:
def test_resolve_codegen_phase_uses_model_codegen(monkeypatch):
    import os
    monkeypatch.setenv("MODEL_CODEGEN", "anthropic/claude-haiku-4-5-20251001")
    # Re-import to pick up new env var value
    import importlib
    import agent.llm as llm_mod
    importlib.reload(llm_mod)
    result = llm_mod._resolve_model_for_phase("codegen", "anthropic/claude-sonnet-4-6")
    assert result == "anthropic/claude-haiku-4-5-20251001"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm_module.py::test_resolve_codegen_phase_uses_model_codegen -v
```

Expected: FAIL — returns default model, not `MODEL_CODEGEN`

- [ ] **Step 3: Add `codegen` to `_PHASE_MODEL_MAP` in `agent/llm.py`**

Replace lines 67–75:

```python
_PHASE_MODEL_MAP: dict[str, str | None] = {
    "idd":         os.environ.get("MODEL_IDD") or None,
    "sdd":         os.environ.get("MODEL_SDD") or None,
    "plan":        os.environ.get("MODEL_PLAN") or None,
    "codegen":     os.environ.get("MODEL_CODEGEN") or None,
    "executor":    os.environ.get("MODEL_EXECUTOR") or None,
    "learn":       os.environ.get("MODEL_LEARN") or None,
    "assembler":   os.environ.get("MODEL_ASSEMBLER") or None,
    "consolidate": os.environ.get("MODEL_CONSOLIDATE") or None,
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_llm_module.py::test_resolve_codegen_phase_uses_model_codegen -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/llm.py tests/test_llm_module.py
git commit -m "feat(llm): add codegen phase to model routing map"
```

---

## Task 3: Create `MockVM`

**Files:**
- Create: `agent/mock_vm.py`
- Create: `tests/test_mock_vm.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mock_vm.py
import pytest
from agent.mock_vm import MockVM


def test_mock_vm_exec_returns_rows_from_params():
    vm = MockVM(
        extracted_params={"order_id": "ord_123", "customer_id": "cust_456"},
        schema_digest="orders(id, customer_id, total)\ncustomers(id, name)",
    )
    result = vm.exec(type("R", (), {"path": "/bin/sql", "args": ["SELECT * FROM orders"]})())
    assert result is not None
    assert hasattr(result, "stdout")
    # stdout contains JSON with at least one row
    import json
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)


def test_mock_vm_read_returns_content():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.read(type("R", (), {"path": "/proc/orders/ord_001.json"})())
    assert result is not None
    assert hasattr(result, "content")
    assert isinstance(result.content, str)


def test_mock_vm_search_returns_matches():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.search(type("R", (), {"root": "/", "pattern": "order", "limit": 5})())
    assert hasattr(result, "matches")


def test_mock_vm_find_returns_nodes():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.find(type("R", (), {"root": "/", "name": "*.json", "limit": 5})())
    assert hasattr(result, "nodes")


def test_mock_vm_list_returns_entries():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.list(type("R", (), {"path": "/proc"})())
    assert hasattr(result, "entries")


def test_mock_vm_tree_returns_string():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.tree(type("R", (), {"root": "/", "level": 2})())
    assert result is not None


def test_mock_vm_answer_raises():
    vm = MockVM(extracted_params={}, schema_digest="")
    with pytest.raises(RuntimeError, match="vm.answer\\(\\) must not be called"):
        vm.answer(object())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_mock_vm.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agent.mock_vm'`

- [ ] **Step 3: Create `agent/mock_vm.py`**

```python
"""MockVM — stub for EcomRuntimeClientSync used in CODEGEN mock tests."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _ExecResult:
    stdout: str = ""
    stderr: str = ""


@dataclass
class _ReadResult:
    content: str = ""


@dataclass
class _Match:
    path: str
    line: int
    line_text: str


@dataclass
class _SearchResult:
    matches: list[_Match] = field(default_factory=list)


@dataclass
class _Node:
    path: str


@dataclass
class _FindResult:
    nodes: list[_Node] = field(default_factory=list)


@dataclass
class _Entry:
    name: str


@dataclass
class _ListResult:
    entries: list[_Entry] = field(default_factory=list)


class MockVM:
    """Stub for EcomRuntimeClientSync. Returns synthesized data for CODEGEN mock tests.

    Never raises on exec/read/search/etc. — always returns structurally valid responses
    with data synthesized from extracted_params and schema_digest.
    """

    def __init__(self, extracted_params: dict, schema_digest: str) -> None:
        self._params = extracted_params
        self._schema = schema_digest

    def exec(self, req: Any) -> _ExecResult:
        rows = [dict(self._params)] if self._params else [{"id": "mock_001", "value": "mock"}]
        return _ExecResult(stdout=json.dumps(rows))

    def read(self, req: Any) -> _ReadResult:
        path = getattr(req, "path", "/mock/path")
        content = json.dumps({**self._params, "_mock_path": path})
        return _ReadResult(content=content)

    def search(self, req: Any) -> _SearchResult:
        pattern = getattr(req, "pattern", "")
        return _SearchResult(matches=[
            _Match(path="/mock/result.json", line=1, line_text=f"mock match for {pattern}")
        ])

    def find(self, req: Any) -> _FindResult:
        return _FindResult(nodes=[_Node(path="/mock/found.json")])

    def list(self, req: Any) -> _ListResult:
        return _ListResult(entries=[_Entry(name="mock_entry")])

    def tree(self, req: Any) -> str:
        return 'name: "mock_dir" NODE_KIND_DIR\n  name: "mock_file.json" NODE_KIND_FILE'

    def answer(self, req: Any) -> None:
        raise RuntimeError("vm.answer() must not be called from heuristic script")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_mock_vm.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/mock_vm.py tests/test_mock_vm.py
git commit -m "feat(mock_vm): add MockVM stub for CODEGEN mock test execution"
```

---

## Task 4: Create `data/prompts/codegen.md`

**Files:**
- Create: `data/prompts/codegen.md`
- Test: `tests/test_prompt_loader.py` (extend existing)

- [ ] **Step 1: Write failing test**

```python
# In tests/test_prompt_loader.py — add at bottom:
def test_codegen_prompt_exists():
    from agent.prompt import load_prompt
    content = load_prompt("codegen")
    assert content, "codegen.md prompt must exist and be non-empty"
    assert "CODEGEN" in content or "script" in content.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_prompt_loader.py::test_codegen_prompt_exists -v
```

Expected: FAIL — returns empty string (file not found)

- [ ] **Step 3: Create `data/prompts/codegen.md`**

```markdown
# PHASE: CODEGEN

You generate a self-contained Python script that solves a task using a VM interface.

## Output format

Respond with a single JSON object:
```json
{
  "script": "# complete python script...",
  "test": "# mock test script..."
}
```

## Script requirements

The script receives two injected variables:
- `vm` — VM interface with methods: `exec(req)`, `read(req)`, `search(req)`, `find(req)`, `list(req)`, `tree(req)`
- `task_text: str` — the original task text

The script MUST:
1. Parse task-specific parameters from `task_text` using regex or string parsing
2. Use `vm` methods to retrieve data
3. Compute the final answer using Python (loops, aggregation, filtering, regex, etc.)
4. Write the complete result to `_result`:

```python
_result = {
    "message": "...",         # human-readable answer
    "outcome": "OUTCOME_OK",  # one of: OUTCOME_OK | OUTCOME_DENIED_SECURITY | OUTCOME_NONE_UNSUPPORTED | OUTCOME_NONE_CLARIFICATION
    "refs": ["/proc/..."]     # grounding refs (file paths read)
}
```

5. Include `if __name__ == "__main__": pass` guard at the bottom
6. NEVER call `vm.answer()`
7. NEVER access filesystem outside `data/`
8. NEVER make network calls

Use `vm.exec` for SQL queries:
```python
from bitgn.vm.ecom.ecom_pb2 import ExecRequest
result = vm.exec(ExecRequest(path="/bin/sql", args=["SELECT ..."]))
import json
rows = json.loads(result.stdout)
```

Use `vm.read` for file reads:
```python
from bitgn.vm.ecom.ecom_pb2 import ReadRequest
result = vm.read(ReadRequest(path="/proc/orders/ord_001.json"))
data = json.loads(result.content)
```

## Test script requirements

The test script:
1. Imports MockVM (injected as `vm`) — same interface as real VM
2. Calls the script logic (import or inline)
3. Asserts `_result` is not None
4. Asserts `_result["outcome"]` is a valid outcome code
5. Asserts `_result["message"]` is non-empty
6. Does NOT assert exact values — mock data is synthetic

## Outcome codes

- `OUTCOME_OK` — task completed successfully with data
- `OUTCOME_DENIED_SECURITY` — request violates security policy
- `OUTCOME_NONE_UNSUPPORTED` — operation not supported
- `OUTCOME_NONE_CLARIFICATION` — insufficient data to answer

## Quality

The script must handle the full task autonomously. Use the LEARNED rules, SCHEMA, and SUCCESS_CRITERIA from unified_context to ensure the script produces a correct, well-formatted answer.
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_prompt_loader.py::test_codegen_prompt_exists -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/prompts/codegen.md tests/test_prompt_loader.py
git commit -m "feat(prompts): add CODEGEN phase guide"
```

---

## Task 5: Implement `_run_codegen()` in `pipeline.py`

**Files:**
- Modify: `agent/pipeline.py`
- Create: `tests/test_codegen.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_codegen.py
import ast
from unittest.mock import patch, MagicMock
import pytest

from agent.pipeline import _run_codegen
from agent.models import IddOutput, SddOutput, PlanOutput, CodegenOutput
from agent.prephase import PrephaseResult


def _make_idd(extracted_params=None):
    return IddOutput(
        intent_objective="Count orders",
        reformulated_task="How many orders?",
        intent_type="read",
        extracted_params=extracted_params or {"status": "paid"},
        success_criteria=["result is a positive integer"],
        decision="proceed",
    )


def _make_sdd():
    return SddOutput(
        spec_goal="count orders",
        success_criteria=["positive integer"],
        plan=["query orders"],
        actions=["SELECT COUNT(*) FROM orders"],
    )


def _make_plan():
    return PlanOutput(
        approach="sql count",
        steps=["run count query"],
        action="SELECT COUNT(*) FROM orders",
    )


def _make_pre(schema_digest=None):
    return PrephaseResult(
        agents_md_content="AGENTS",
        agents_md_path="/AGENTS.MD",
        db_schema="CREATE TABLE orders(id INT, status TEXT)",
        task_type="sql",
        schema_digest=schema_digest or {},
    )


_GOOD_SCRIPT = '''
import json
from bitgn.vm.ecom.ecom_pb2 import ExecRequest
result = vm.exec(ExecRequest(path="/bin/sql", args=["SELECT COUNT(*) FROM orders"]))
rows = json.loads(result.stdout)
_result = {"message": "3 orders found", "outcome": "OUTCOME_OK", "refs": []}

if __name__ == "__main__":
    pass
'''

_GOOD_TEST = '''
import json
result = vm.exec(None)
rows = json.loads(result.stdout)
assert _result is not None
assert _result["outcome"] in ("OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION", "OUTCOME_DENIED_SECURITY", "OUTCOME_NONE_UNSUPPORTED")
assert _result["message"]
'''

_GOOD_LLM_RESPONSE = f'{{"script": {repr(_GOOD_SCRIPT)}, "test": {repr(_GOOD_TEST)}}}'


def test_run_codegen_success():
    """LLM returns valid script+test → CodegenOutput written to data/heuristics/"""
    import json
    idd_out = _make_idd()
    sdd_out = _make_sdd()
    plan_out = _make_plan()
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", return_value=_GOOD_LLM_RESPONSE), \
         patch("agent.pipeline.Path") as mock_path_cls:
        mock_dir = MagicMock()
        mock_file = MagicMock()
        mock_path_cls.return_value = mock_dir
        mock_dir.__truediv__ = MagicMock(return_value=mock_file)

        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="How many orders?",
            task_id="t01",
            idd_out=idd_out,
            sdd_out=sdd_out,
            plan_out=plan_out,
            pre=pre,
            cycle=1,
        )

    assert err == "", f"Unexpected error: {err}"
    assert result is not None
    assert isinstance(result, CodegenOutput)
    assert result.script_path == "data/heuristics/t01.py"
    assert "OUTCOME_OK" in result.script_code


def test_run_codegen_lint_failure_retries_then_fails():
    """LLM returns invalid Python syntax → retries CODEGEN_LINT_RETRIES times → returns error."""
    bad_response = '{"script": "def broken(", "test": "assert True"}'
    idd_out = _make_idd()

    with patch("agent.pipeline.call_llm_raw", return_value=bad_response), \
         patch.dict("os.environ", {"CODEGEN_LINT_RETRIES": "2"}):
        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="How many orders?",
            task_id="t01",
            idd_out=idd_out,
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
        )

    assert result is None
    assert "lint failed" in err.lower()


def test_run_codegen_mock_test_exception_returns_error():
    """Script passes lint but mock test raises → returns error."""
    bad_test = '{"script": ' + repr(_GOOD_SCRIPT) + ', "test": "raise ValueError(\\"mock test failed\\")"}'

    idd_out = _make_idd()

    with patch("agent.pipeline.call_llm_raw", return_value=bad_test):
        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="How many orders?",
            task_id="t01",
            idd_out=idd_out,
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
        )

    assert result is None
    assert "mock test" in err.lower() or "valueerror" in err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_codegen.py -v
```

Expected: FAIL — `ImportError: cannot import name '_run_codegen' from 'agent.pipeline'`

- [ ] **Step 3: Add imports and constants to `agent/pipeline.py`**

Add to the imports section at the top of `pipeline.py` (after existing imports):

```python
import ast
from pathlib import Path

from .mock_vm import MockVM
from .models import IddOutput, SddOutput, PlanOutput, ExecuteOutput, LearnOutput, AnswerOutput, ConsolidateOutput, CodegenOutput
from .prompt_assembler import assemble_prompt, load_learned_ctx, load_learned_entries, load_last_run, _apply_learn_diff, save_last_run
```

Note: `Path` is already used if already imported — check first; add only if missing. The `from .prompt_assembler import ...` line already exists at line 29 — replace it entirely with the line above (adds `load_last_run`). Add these constants after `_PHASE_MAX_TOKENS`:

```python
_CODEGEN_MAX_TOKENS = int(os.environ.get("MAX_TOKENS_CODEGEN", "8192"))
_CODEGEN_LINT_RETRIES = int(os.environ.get("CODEGEN_LINT_RETRIES", "3"))
```

- [ ] **Step 4: Add `_run_codegen()` to `agent/pipeline.py`**

Add after `_run_execute()` function (after line ~420):

```python
def _run_codegen(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    task_id: str,
    idd_out: "IddOutput",
    sdd_out: "SddOutput",
    plan_out: "PlanOutput",
    pre: "PrephaseResult",
    cycle: int,
) -> "tuple[CodegenOutput | None, str]":
    """CODEGEN phase: LLM generates heuristic script + mock test. Returns (CodegenOutput, error)."""
    codegen_model = _resolve_model_for_phase("codegen", model)
    codegen_guide = load_prompt("codegen") or "# PHASE: codegen"

    import json as _json

    # Build user message with all context CODEGEN needs
    user_parts = [
        f"TASK: {task_text}",
        f"TASK_ID: {task_id}",
        f"REFORMULATED_TASK: {idd_out.reformulated_task}",
        f"INTENT_TYPE: {idd_out.intent_type}",
    ]
    if idd_out.extracted_params:
        user_parts.append(f"EXTRACTED_PARAMS: {_json.dumps(idd_out.extracted_params)}")
    if idd_out.success_criteria:
        user_parts.append("SUCCESS_CRITERIA:\n" + "\n".join(f"  - {c}" for c in idd_out.success_criteria))
    user_parts.append(f"SDD_GOAL: {sdd_out.spec_goal}")
    user_parts.append(f"PLAN_ACTION: {plan_out.action}")
    user_msg = "\n\n".join(user_parts)

    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": codegen_guide, "cache_control": {"type": "ephemeral"}},
    ]

    lint_error: str | None = None
    script_code = ""
    test_code = ""

    for attempt in range(_CODEGEN_LINT_RETRIES):
        if lint_error:
            retry_msg = f"{user_msg}\n\nPREVIOUS_LINT_ERROR: {lint_error}\nFix the syntax error and regenerate."
        else:
            retry_msg = user_msg

        tok_info: dict = {}
        raw = call_llm_raw(system, retry_msg, codegen_model, cfg,
                           max_tokens=_CODEGEN_MAX_TOKENS, token_out=tok_info)
        if not raw:
            lint_error = "LLM returned empty response"
            continue

        extracted = _extract_json_from_text(raw)
        if not isinstance(extracted, dict):
            lint_error = f"Could not parse JSON from LLM response: {raw[:200]}"
            continue

        script_code = extracted.get("script", "")
        test_code = extracted.get("test", "")

        lint_error = None
        for label, code in [("script", script_code), ("test", test_code)]:
            try:
                ast.parse(code)
            except SyntaxError as e:
                lint_error = f"{label} syntax error: {e}"
                break

        if lint_error is None:
            break

    if lint_error:
        return None, f"CODEGEN lint failed after {_CODEGEN_LINT_RETRIES} attempts: {lint_error}"

    # Mock test execution
    mock_vm = MockVM(
        extracted_params=idd_out.extracted_params,
        schema_digest=pre.schema_digest if isinstance(pre.schema_digest, str) else str(pre.schema_digest),
    )
    exec_globals: dict = {"vm": mock_vm, "task_text": task_text, "_result": None}
    try:
        exec(compile(test_code, f"{task_id}_test.py", "exec"), exec_globals)
    except Exception as e:
        return None, f"CODEGEN mock test failed: {e}"

    # Persist script
    heuristics_dir = Path("data/heuristics")
    heuristics_dir.mkdir(exist_ok=True)
    script_path = f"data/heuristics/{task_id}.py"
    (heuristics_dir / f"{task_id}.py").write_text(script_code, encoding="utf-8")
    (heuristics_dir / f"{task_id}_test.py").write_text(test_code, encoding="utf-8")

    return CodegenOutput(script_path=script_path, script_code=script_code, test_code=test_code), ""
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_codegen.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_codegen.py
git commit -m "feat(pipeline): add _run_codegen with lint-fix loop and mock test execution"
```

---

## Task 6: Replace `_run_answer()` — no LLM, exec script directly

**Files:**
- Modify: `agent/pipeline.py` — add `_run_answer()` as standalone function after `_run_codegen()`
- Create: `tests/test_answer.py` — separate file to avoid module-level import conflict with `tests/test_codegen.py`

- [ ] **Step 1: Write failing tests**

Create new file `tests/test_answer.py`:

```python
# tests/test_answer.py
from unittest.mock import MagicMock

from agent.pipeline import _run_answer
from agent.models import CodegenOutput


def _make_codegen_out(script_code=None):
    code = script_code or '''
_result = {"message": "3 orders found", "outcome": "OUTCOME_OK", "refs": ["/proc/orders/ord_1.json"]}

if __name__ == "__main__":
    pass
'''
    return CodegenOutput(
        script_path="data/heuristics/t01.py",
        script_code=code,
        test_code="assert True",
    )


def test_run_answer_success():
    vm = MagicMock()
    codegen_out = _make_codegen_out()
    answer_out, err = _run_answer(vm, codegen_out, "How many orders?")
    assert err == ""
    assert answer_out is not None
    assert answer_out.outcome == "OUTCOME_OK"
    assert "3 orders" in answer_out.message
    vm.answer.assert_called_once()


def test_run_answer_script_runtime_error():
    vm = MagicMock()
    bad_script = CodegenOutput(
        script_path="data/heuristics/t01.py",
        script_code="raise RuntimeError('boom')",
        test_code="",
    )
    answer_out, err = _run_answer(vm, bad_script, "task")
    assert answer_out is None
    assert "runtime error" in err.lower() or "boom" in err.lower()


def test_run_answer_no_result_set():
    vm = MagicMock()
    no_result_script = CodegenOutput(
        script_path="data/heuristics/t01.py",
        script_code="x = 1  # forgot to set _result",
        test_code="",
    )
    answer_out, err = _run_answer(vm, no_result_script, "task")
    assert answer_out is None
    assert "_result" in err


def test_run_answer_invalid_outcome_code():
    vm = MagicMock()
    bad_outcome = CodegenOutput(
        script_path="data/heuristics/t01.py",
        script_code='_result = {"message": "ok", "outcome": "BOGUS_CODE", "refs": []}',
        test_code="",
    )
    answer_out, err = _run_answer(vm, bad_outcome, "task")
    assert answer_out is None
    assert "outcome" in err.lower()


def test_run_answer_fs_access_outside_data_is_hard_error():
    """OSError/PermissionError from script → hard error, not routed to LEARN."""
    vm = MagicMock()
    fs_script = CodegenOutput(
        script_path="data/heuristics/t01.py",
        script_code="open('/etc/passwd')",
        test_code="",
    )
    answer_out, err = _run_answer(vm, fs_script, "task")
    assert answer_out is None
    assert "filesystem" in err.lower() or "permission" in err.lower() or "hard error" in err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_answer.py -v
```

Expected: FAIL — `ImportError: cannot import name '_run_answer' from 'agent.pipeline'`

- [ ] **Step 3: Add `_run_answer()` as a standalone function in `agent/pipeline.py`**

Add after `_run_codegen()`:

```python
def _run_answer(
    vm,
    codegen_out: "CodegenOutput",
    task_text: str,
) -> "tuple[AnswerOutput | None, str]":
    """ANSWER phase: exec heuristic script, call vm.answer(). No LLM call."""
    exec_globals: dict = {"vm": vm, "task_text": task_text, "_result": None}
    try:
        exec(compile(codegen_out.script_code, codegen_out.script_path, "exec"), exec_globals)
    except (OSError, PermissionError) as e:
        return None, f"Script filesystem hard error (not routed to LEARN): {e}"
    except Exception as e:
        return None, f"Script runtime error: {e}"

    raw_result = exec_globals.get("_result")
    if not raw_result or not isinstance(raw_result, dict):
        return None, "Script did not set _result"
    if "outcome" not in raw_result or "message" not in raw_result:
        return None, "Script _result missing required fields: outcome, message"
    if raw_result["outcome"] not in OUTCOME_BY_NAME:
        return None, f"Unknown outcome code in _result: {raw_result['outcome']!r}"

    try:
        vm.answer(AnswerRequest(
            message=raw_result["message"],
            outcome=OUTCOME_BY_NAME[raw_result["outcome"]],
            refs=raw_result.get("refs", []),
        ))
    except Exception as e:
        return None, f"vm.answer() error: {e}"

    return AnswerOutput(
        reasoning="",
        message=raw_result["message"],
        outcome=raw_result["outcome"],
        grounding_refs=raw_result.get("refs", []),
        completed_steps=[],
    ), ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_answer.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_answer.py
git commit -m "feat(pipeline): add _run_answer that executes heuristic script without LLM"
```

---

## Task 7: Extend `_build_learn_user_msg()` with `heuristic_code`

**Files:**
- Modify: `agent/pipeline.py:239-270`
- Test: `tests/test_pipeline.py` (extend existing)

- [ ] **Step 1: Write failing test**

```python
# In tests/test_pipeline.py — add at bottom:
def test_build_learn_user_msg_includes_heuristic_code():
    from agent.pipeline import _build_learn_user_msg
    msg = _build_learn_user_msg(
        task_text="How many orders?",
        error="Script runtime error: KeyError",
        error_type="semantic",
        existing_entries=[],
        heuristic_code="_result = {'message': 'bad', 'outcome': 'OUTCOME_OK', 'refs': []}",
    )
    assert "HEURISTIC_CODE" in msg
    assert "KeyError" in msg
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_pipeline.py::test_build_learn_user_msg_includes_heuristic_code -v
```

Expected: FAIL — `TypeError: _build_learn_user_msg() got unexpected keyword argument 'heuristic_code'`

- [ ] **Step 3: Add `heuristic_code` parameter to `_build_learn_user_msg()` in `agent/pipeline.py`**

Replace the function signature (line 239) and add the `heuristic_code` block before `return`:

```python
def _build_learn_user_msg(
    task_text: str,
    error: str,
    error_type: str,
    existing_entries: list[dict],
    sdd_out=None,
    plan_out=None,
    answer_out=None,
    idd_out: "IddOutput | None" = None,
    heuristic_code: str | None = None,
) -> str:
    parts = [
        f"TASK: {task_text}",
        f"ERROR: {error}",
        f"ERROR_TYPE: {error_type}",
    ]
    if idd_out and idd_out.stop_rules:
        parts.append("STOP_RULES:\n" + "\n".join(f"  - {r}" for r in idd_out.stop_rules))
    if sdd_out is not None:
        parts.append(f"SDD_OUTPUT:\n{sdd_out.model_dump_json(indent=2)}")
    if plan_out is not None:
        parts.append(f"PLAN_OUTPUT:\n{plan_out.model_dump_json(indent=2)}")
    if answer_out is not None:
        parts.append(f"ANSWER_OUTPUT:\n{answer_out.model_dump_json(indent=2)}")
    if heuristic_code:
        parts.append(f"HEURISTIC_CODE:\n```python\n{heuristic_code[:3000]}\n```")
    if existing_entries:
        rules_lines = "\n".join(
            f"  - id: {e['id']}\n    content: {e['content']!r}"
            for e in existing_entries
            if e.get("status") == "active"
        )
        if rules_lines:
            parts.append(f"EXISTING_RULES:\n{rules_lines}")
    return "\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_pipeline.py::test_build_learn_user_msg_includes_heuristic_code -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all previously passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): pass heuristic_code to _build_learn_user_msg for targeted LEARN"
```

---

## Task 8: Wire fast path + CODEGEN/ANSWER into `run_pipeline()`

This is the largest change. We replace the EXECUTE + BATCH EXECUTE + ANSWER LLM blocks with CODEGEN → ANSWER. We also add the fast path check at the start of `run_pipeline()`.

**Files:**
- Modify: `agent/pipeline.py:538-1034`
- Create: `tests/test_fast_path.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fast_path.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.pipeline import run_pipeline
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt


def _make_pre():
    return PrephaseResult(
        agents_md_content="AGENTS",
        agents_md_path="/AGENTS.MD",
        db_schema="CREATE TABLE orders(id INT, status TEXT)",
        task_type="sql",
    )


def _mock_assemble(*_a, **_kw):
    return AssembledPrompt(unified_context="mocked-context")


_VALID_SCRIPT = """
_result = {"message": "3 orders", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
"""


def test_fast_path_skips_llm_when_heuristic_valid(tmp_path):
    """Fast path: existing script + heuristic_valid=True → 0 LLM calls, vm.answer called."""
    vm = MagicMock()
    pre = _make_pre()
    task_id = "t_fp_01"

    # Create heuristic file
    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)
    (heur_dir / f"{task_id}.py").write_text(_VALID_SCRIPT)

    last_run_data = {
        "task_id": task_id,
        "last_run": {"status": "success", "outcome": "OUTCOME_OK", "cycles_used": 1,
                     "grounding_refs_count": 0, "heuristic_valid": True, "date": "2026-05-27"},
        "entries": [],
    }
    import yaml
    learned_dir = tmp_path / "data" / "learned"
    learned_dir.mkdir(parents=True)
    (learned_dir / f"{task_id}.yaml").write_text(
        yaml.dump(last_run_data, allow_unicode=True)
    )

    with patch("agent.pipeline.call_llm_raw") as mock_llm, \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir), \
         patch("agent.pipeline.Path") as mock_path_cls:

        # Make Path("data/heuristics/{task_id}.py") resolve to our tmp file
        def path_side_effect(p):
            if "heuristics" in str(p):
                return heur_dir / Path(p).name
            return Path(p)
        mock_path_cls.side_effect = path_side_effect

        stats, _ = run_pipeline(
            vm=vm,
            model="anthropic/claude-sonnet-4-6",
            task_text="How many orders?",
            pre=pre,
            cfg={},
            task_id=task_id,
        )

    mock_llm.assert_not_called()
    vm.answer.assert_called_once()
    call_args = vm.answer.call_args[0][0]
    assert call_args.message == "3 orders"
    # Stats dict carries real outcome from script
    assert stats["outcome"] == "OUTCOME_OK"


def test_fast_path_failure_falls_through_to_full_path(tmp_path):
    """Fast path script raises → fall through to full path immediately (same run)."""
    vm = MagicMock()
    pre = _make_pre()
    task_id = "t_fp_02"

    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)
    # Broken script
    (heur_dir / f"{task_id}.py").write_text("raise RuntimeError('broken')")

    last_run_data = {
        "task_id": task_id,
        "last_run": {"status": "success", "outcome": "OUTCOME_OK", "cycles_used": 1,
                     "grounding_refs_count": 0, "heuristic_valid": True, "date": "2026-05-27"},
        "entries": [],
    }
    import yaml
    learned_dir = tmp_path / "data" / "learned"
    learned_dir.mkdir(parents=True)
    (learned_dir / f"{task_id}.yaml").write_text(
        yaml.dump(last_run_data, allow_unicode=True)
    )

    def _idd_json():
        return json.dumps({
            "intent_objective": "count", "reformulated_task": "How many orders?",
            "intent_type": "read", "extracted_params": {}, "success_criteria": ["positive int"],
            "stop_rules": [], "health_metrics": [], "decision": "proceed",
            "stop_code": "", "stop_message": "", "stop_refs": [], "reasoning": "",
        })

    def _sdd_json():
        return json.dumps({
            "spec_goal": "count", "success_criteria": ["positive int"],
            "plan": ["query"], "actions": ["SELECT COUNT(*) FROM orders"], "error_code": "",
        })

    def _plan_json():
        return json.dumps({"approach": "count", "steps": ["run query"],
                           "action": "SELECT COUNT(*) FROM orders"})

    _GOOD_SCRIPT_FULL = '''
_result = {"message": "5 orders", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
'''
    _CODEGEN_JSON = json.dumps({"script": _GOOD_SCRIPT_FULL, "test": "assert True"})

    llm_seq = iter([_idd_json(), _sdd_json(), _plan_json(), _CODEGEN_JSON])

    with patch("agent.pipeline.call_llm_raw", side_effect=lambda *a, **kw: next(llm_seq)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir), \
         patch("agent.pipeline.Path") as mock_path_cls:

        def path_side_effect(p):
            if "heuristics" in str(p):
                return heur_dir / Path(p).name
            return Path(p)
        mock_path_cls.side_effect = path_side_effect

        stats, _ = run_pipeline(
            vm=vm,
            model="anthropic/claude-sonnet-4-6",
            task_text="How many orders?",
            pre=pre,
            cfg={},
            task_id=task_id,
        )

    # Full path ran — LLM was called (IDD + SDD + PLAN + CODEGEN = 4 calls)
    assert vm.answer.call_count >= 1


def test_fast_path_not_eligible_when_heuristic_invalid(tmp_path):
    """heuristic_valid=False → skip fast path, run full pipeline."""
    vm = MagicMock()
    pre = _make_pre()
    task_id = "t_fp_03"

    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)
    (heur_dir / f"{task_id}.py").write_text(_VALID_SCRIPT)

    last_run_data = {
        "task_id": task_id,
        "last_run": {"status": "failure", "outcome": "OUTCOME_NONE_CLARIFICATION",
                     "cycles_used": 3, "grounding_refs_count": 0,
                     "heuristic_valid": False, "date": "2026-05-27"},
        "entries": [],
    }
    import yaml
    learned_dir = tmp_path / "data" / "learned"
    learned_dir.mkdir(parents=True)
    (learned_dir / f"{task_id}.yaml").write_text(
        yaml.dump(last_run_data, allow_unicode=True)
    )

    llm_calls: list[str] = []

    def _tracking_llm(*a, **kw):
        llm_calls.append("called")
        return json.dumps({
            "intent_objective": "x", "reformulated_task": "y", "intent_type": "read",
            "extracted_params": {}, "success_criteria": ["z"], "stop_rules": [],
            "health_metrics": [], "decision": "hard_stop",
            "stop_code": "OUTCOME_NONE_CLARIFICATION",
            "stop_message": "not enough data", "stop_refs": [], "reasoning": "",
        })

    with patch("agent.pipeline.call_llm_raw", side_effect=_tracking_llm), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir):

        run_pipeline(
            vm=vm, model="anthropic/claude-sonnet-4-6",
            task_text="How many orders?", pre=pre, cfg={}, task_id=task_id,
        )

    assert len(llm_calls) > 0, "Full path should have run LLM calls"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_fast_path.py -v
```

Expected: FAIL — fast path logic not yet present in `run_pipeline`

- [ ] **Step 3: Add fast path helper `_run_fast_path()` to `agent/pipeline.py`**

Add before `run_pipeline()`:

```python
def _run_fast_path(
    vm,
    task_id: str,
    task_text: str,
) -> "tuple[bool, str, str]":
    """Execute existing heuristic script. Returns (ok, error_string, outcome_str)."""
    script_path = Path("data") / "heuristics" / f"{task_id}.py"
    try:
        script_code = script_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"fast path read error: {e}", ""

    exec_globals: dict = {"vm": vm, "task_text": task_text, "_result": None}
    try:
        exec(compile(script_code, str(script_path), "exec"), exec_globals)
    except (OSError, PermissionError) as e:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path filesystem error: {e}", ""
    except Exception as e:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path script error: {e}", ""

    raw_result = exec_globals.get("_result")
    if not raw_result or "outcome" not in raw_result or "message" not in raw_result:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, "fast path: script did not produce valid _result", ""

    if raw_result["outcome"] not in OUTCOME_BY_NAME:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path: unknown outcome {raw_result['outcome']!r}", ""

    script_outcome = raw_result["outcome"]
    try:
        vm.answer(AnswerRequest(
            message=raw_result["message"],
            outcome=OUTCOME_BY_NAME[script_outcome],
            refs=raw_result.get("refs", []),
        ))
    except Exception as e:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path vm.answer error: {e}", ""

    save_last_run(task_id, status="success", outcome=script_outcome,
                  cycles_used=0, heuristic_valid=True)
    return True, "", script_outcome
```

- [ ] **Step 4: Modify `run_pipeline()` — add fast path check at start**

In `run_pipeline()`, after the `learn_ctx` / `sgr_trace` initialization block (before the `try:` / `for cycle in range(...)` loop), add:

```python
    # ── FAST PATH ─────────────────────────────────────────────────────────────
    if task_id:
        last_run_record = load_last_run(task_id)
        _heuristic_script = Path("data") / "heuristics" / f"{task_id}.py"
        _fast_eligible = (
            last_run_record is not None
            and last_run_record.get("heuristic_valid") is True
            and _heuristic_script.exists()
        )
        if _fast_eligible:
            print(f"{CLI_BLUE}[pipeline] fast path: {task_id}{CLI_CLR}")
            _fp_ok, _fp_err, _fp_outcome = _run_fast_path(vm, task_id, task_text)
            if _fp_ok:
                return {
                    "outcome": _fp_outcome,
                    "cycles_used": 0,
                    "grounding_refs_count": 0,
                    "step_facts": ["fast path: 0 LLM calls"],
                    "done_ops": [],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_elapsed_ms": 0,
                }, None
            # Fast path failed → fall through to full path
            last_error = _fp_err
            print(f"{CLI_YELLOW}[pipeline] fast path failed: {_fp_err} — falling through to full path{CLI_CLR}")
```

- [ ] **Step 5: Replace EXECUTE + BATCH EXECUTE + ANSWER LLM blocks in cycle loop**

In the cycle loop, find the comment `# ── EXECUTE ───────────` (around line 774) and replace everything from that comment through the end of the ANSWER block (the `break` after `success = True`, line ~987) with:

```python
            # ── CODEGEN ──────────────────────────────────────────────────────
            _t0 = time.monotonic()
            codegen_out, codegen_error = _run_codegen(
                unified_context=unified_context,
                model=model,
                cfg=cfg,
                task_text=task_text,
                task_id=task_id,
                idd_out=idd_out,
                sdd_out=sdd_out,
                plan_out=plan_out,
                pre=pre,
                cycle=cycle + 1,
            )
            _dur = int((time.monotonic() - _t0) * 1000)

            if codegen_error or codegen_out is None:
                err = codegen_error or "CODEGEN returned None"
                print(f"{CLI_YELLOW}[pipeline] CODEGEN failed: {err}{CLI_CLR}")
                last_error = err
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            print(f"{CLI_BLUE}[pipeline] CODEGEN ok: {codegen_out.script_path}{CLI_CLR}")

            # ── ANSWER ────────────────────────────────────────────────────────
            answer_out, answer_error = _run_answer(vm, codegen_out, task_text)

            if answer_error or answer_out is None:
                err = answer_error or "ANSWER returned None"
                # Hard filesystem errors are not routed to LEARN
                if "hard error" in (err or "").lower() or "filesystem" in (err or "").lower():
                    print(f"{CLI_RED}[pipeline] ANSWER filesystem hard error: {err}{CLI_CLR}")
                    last_error = err
                    break
                print(f"{CLI_YELLOW}[pipeline] ANSWER failed: {err}{CLI_CLR}")
                last_error = err
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out,
                           heuristic_code=codegen_out.script_code if codegen_out else None)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            # ── SUCCESS ───────────────────────────────────────────────────────
            outcome = answer_out.outcome
            print(f"{CLI_GREEN}[pipeline] ANSWER: {outcome} — {answer_out.message[:100]}{CLI_CLR}")

            final_grounding_refs_count = len(answer_out.grounding_refs)
            if task_id:
                print(f"{CLI_BLUE}[pipeline] SUCCESS: {len(learn_ctx)} active rules in data/learned/{task_id}.yaml{CLI_CLR}")
            success = True
            break
```

Also update `save_last_run` call at end of `run_pipeline()` to pass `heuristic_valid`:

```python
        save_last_run(
            task_id=task_id,
            status=last_run_status,
            outcome=outcome,
            cycles_used=cycles_used,
            grounding_refs_count=final_grounding_refs_count,
            heuristic_valid=success and outcome in _SUCCESSFUL_OUTCOMES,
        )
```

And update the `_run_learn` calls throughout the cycle loop to pass `heuristic_code=None` (they already don't pass it, so no change needed — default is `None`).

- [ ] **Step 6: Run fast path tests**

```bash
uv run pytest tests/test_fast_path.py -v
```

Expected: PASS (all 3 tests)

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all previously passing tests still pass. If existing `test_pipeline.py` tests fail due to removed EXECUTE/BATCH/ANSWER-LLM blocks, update them to use CODEGEN-based LLM sequence:

Old `test_happy_path` LLM sequence: `[_idd_json(), _sdd_json(), _plan_json(), _answer_json()]`

New sequence (CODEGEN replaces EXECUTE+ANSWER-LLM):
```python
_GOOD_SCRIPT = '''
_result = {"message": "<YES> 3 found", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog/ABC-001.json"]}
if __name__ == "__main__":
    pass
'''
_codegen_json = json.dumps({"script": _GOOD_SCRIPT, "test": "assert True"})
# New sequence: IDD, SDD, PLAN, CODEGEN
call_seq = [_idd_json(), _sdd_json(), _plan_json(), _codegen_json]
```

Remove `vm.exec` setup from test (no SQL executed directly anymore). Update `vm.answer.assert_called_once()` assertion — still valid.

- [ ] **Step 8: Commit**

```bash
git add agent/pipeline.py tests/test_fast_path.py tests/test_pipeline.py
git commit -m "feat(pipeline): wire fast path + CODEGEN/ANSWER into run_pipeline; remove EXECUTE/BATCH/ANSWER-LLM"
```

---

## Task 9: Update `.env.example` and `CLAUDE.md`

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add new env vars to `.env.example`**

After the `MODEL_CONSOLIDATE` line in the `# ─── Phase Models ───` section, add:

```
MODEL_CODEGEN=                       # CODEGEN phase model (defaults to MODEL)
```

After the `MAX_TOKENS_IDD` line in the `# ─── Phase Max Tokens ───` section, add:

```
MAX_TOKENS_CODEGEN=8192              # CODEGEN phase response limit
CODEGEN_LINT_RETRIES=3               # max AST lint retry attempts before LEARN
```

- [ ] **Step 2: Update `CLAUDE.md` env vars table**

In the `## Environment Variables` table, add three rows:

```
| `MODEL_CODEGEN` | Override for CODEGEN phase (defaults to `MODEL`) |
| `MAX_TOKENS_CODEGEN` | Max tokens for CODEGEN phase response (default 8192) |
| `CODEGEN_LINT_RETRIES` | Max AST lint retry attempts in CODEGEN before LEARN (default 3) |
```

In the `## Key Data Files` table, add:

```
| `data/heuristics/{task_id}.py` | Generated heuristic script; fast path executes this |
| `data/heuristics/{task_id}_test.py` | Mock test generated alongside script (debug only) |
```

In `CLAUDE.md` `## Architecture`, replace the `**Execution flow per task:**` block (lines starting with `2. pipeline.py:run_pipeline()`) with:

```
**Execution flow per task:**
1. `prephase.py:run_prephase()` — fetches `/AGENTS.MD` (vault rules), reads `.schema` + PRAGMA, builds `schema_digest` and `agents_md_index`
2. `pipeline.py:run_pipeline()` — fast path check, then main loop (max `MAX_STEPS` cycles):
   - **FAST PATH** (if `data/heuristics/{task_id}.py` exists and `last_run.heuristic_valid==True`) → exec script → `vm.answer()` — 0 LLM calls; on failure falls through to full path immediately
   - **ASSEMBLE** → `prompt_assembler.py:assemble_prompt()` — 1 LLM call builds `unified_context` from learned knowledge, vault, and schema
   - **IDD** → LLM call → `IddOutput` (intent, extracted_params, success_criteria)
   - **SDD** → LLM call with `[unified_context, sdd_guide]` → `json_extract.py` → `SddOutput`
   - **PLAN** → LLM call → `PlanOutput` (primary action anchor)
   - **CODEGEN** → LLM call with `[unified_context, codegen_guide]` → generates `data/heuristics/{task_id}.py` (self-contained Python script); internal lint-fix loop (ast.parse) + MockVM test execution
   - **ANSWER** → exec heuristic script → `vm.answer()` — no LLM call; script produces complete answer
   - On any phase failure: **LEARN** → LLM with `[unified_context, learn_guide]` → appends rule to `learn_ctx` → next cycle (LEARN receives failed script as `heuristic_code`)
   - On success: marks in-session learn entries active; they persist in `data/learned/{task_id}.yaml`; sets `heuristic_valid=True` in `last_run`
   - On all cycles exhausted: entries written incrementally; last `data/heuristics/{task_id}.py` preserved
```

- [ ] **Step 3: Run full test suite one final time**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: document new CODEGEN env vars and data/heuristics/ directory"
```
