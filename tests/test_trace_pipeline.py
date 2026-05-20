"""Verify pipeline instruments TraceLogger at required points."""
import json
from unittest.mock import MagicMock, patch

from agent.pipeline import run_pipeline
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt
from agent.trace import TraceLogger, set_trace


def _mock_assemble(*_a, **_kw):
    return AssembledPrompt(unified_context="mocked-unified-context")


def _make_pre(db_schema="CREATE TABLE products(id INT, brand TEXT, type TEXT, sku TEXT)"):
    return PrephaseResult(agents_md_content="", agents_md_path="/AGENTS.MD", db_schema=db_schema, task_type="sql")


def _exec_ok(stdout='[{"count": 3}]'):
    r = MagicMock()
    r.stdout = stdout
    r.output = stdout
    return r


def _collect_trace(tmp_path, task_id="t01"):
    p = tmp_path / f"{task_id}.jsonl"
    t = TraceLogger(p, task_id)
    set_trace(t)
    return t, p


def _sdd_json():
    return json.dumps({
        "spec_goal": "count products by type",
        "success_criteria": ["result contains integer count"],
        "plan": ["filter by type", "count rows"],
        "actions": ["SELECT COUNT(*) FROM products WHERE type='X'"],
        "error_code": "",
    })


def _plan_json():
    return json.dumps({
        "approach": "single count query",
        "steps": ["filter products by type='X'", "return count"],
        "action": "SELECT COUNT(*) FROM products WHERE type='X'",
    })


def _answer_json():
    return json.dumps({
        "reasoning": "SQL returned 3",
        "message": "Found 3 products",
        "outcome": "OUTCOME_OK",
        "grounding_refs": [],
        "completed_steps": [],
    })


def test_llm_call_records_written_on_success(tmp_path):
    """Happy path: sdd + plan + answer llm_call records written."""
    t, p = _collect_trace(tmp_path)

    vm = MagicMock()
    vm.exec.return_value = _exec_ok()

    with patch("agent.pipeline.call_llm_raw", side_effect=[_sdd_json(), _plan_json(), _answer_json()]), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        run_pipeline(vm, "anthropic/claude-sonnet-4-6", "find X", _make_pre(), {})

    t.close()
    set_trace(None)

    records = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    llm_calls = [r for r in records if r["type"] == "llm_call"]
    phases = {r["phase"] for r in llm_calls}
    assert "sdd" in phases
    assert "answer" in phases
    for r in llm_calls:
        assert "system_sha256" in r
        assert "cycle" in r
        assert "duration_ms" in r


def test_sql_execute_record_written(tmp_path):
    """sql_execute record written on successful SQL action."""
    t, p = _collect_trace(tmp_path)

    vm = MagicMock()
    vm.exec.return_value = _exec_ok()

    with patch("agent.pipeline.call_llm_raw", side_effect=[_sdd_json(), _plan_json(), _answer_json()]), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        run_pipeline(vm, "anthropic/claude-sonnet-4-6", "find X", _make_pre(), {})

    t.close()
    set_trace(None)

    records = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    types = [r["type"] for r in records]
    assert "sql_execute" in types
    exec_r = next(r for r in records if r["type"] == "sql_execute")
    assert "duration_ms" in exec_r
    assert isinstance(exec_r["has_data"], bool)


def test_plan_phase_llm_call_recorded(tmp_path):
    """PLAN phase llm_call record written in new pipeline."""
    t, p = _collect_trace(tmp_path)

    vm = MagicMock()
    vm.exec.return_value = _exec_ok()

    with patch("agent.pipeline.call_llm_raw", side_effect=[_sdd_json(), _plan_json(), _answer_json()]), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        run_pipeline(vm, "anthropic/claude-sonnet-4-6", "find X", _make_pre(), {})

    t.close()
    set_trace(None)

    records = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    llm_calls = [r for r in records if r["type"] == "llm_call"]
    phases = {r["phase"] for r in llm_calls}
    assert "plan" in phases
