"""Verify pipeline instruments TraceLogger at all required points."""
import json
from unittest.mock import MagicMock, patch
import pytest

from agent.pipeline import run_pipeline
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt
from agent.trace import TraceLogger, set_trace


def _mock_assemble(*args, **kwargs):
    return AssembledPrompt(unified_context="mocked-unified-context")


def _make_pre(db_schema="CREATE TABLE products(id INT, brand TEXT, type TEXT, sku TEXT)"):
    return PrephaseResult(agents_md_content="", agents_md_path="/AGENTS.MD", db_schema=db_schema, task_type="sql")


def _exec_ok(stdout="sku,path\nHeco-001,/proc/catalog/Heco-001.json"):
    r = MagicMock()
    r.stdout = stdout
    return r


@pytest.fixture(autouse=True)
def reset_caches():
    import agent.pipeline
    agent.pipeline._rules_loader_cache = None
    agent.pipeline._security_gates_cache = None
    yield
    agent.pipeline._rules_loader_cache = None
    agent.pipeline._security_gates_cache = None


def _collect_trace_records(tmp_path, task_id="t01"):
    p = tmp_path / f"{task_id}.jsonl"
    t = TraceLogger(p, task_id)
    set_trace(t)
    return t, p


def _sdd_json():
    return json.dumps({
        "reasoning": "ok",
        "spec": "return products",
        "plan": [{"type": "sql", "description": "fetch", "query": "SELECT brand FROM products WHERE type='X'"}],
        "agents_md_refs": [],
    })


def _test_gen_json():
    return json.dumps({
        "reasoning": "r",
        "sql_tests": "def test_sql(results):\n    assert results\n",
        "answer_tests": "def test_answer(sql_results, answer):\n    pass\n",
    })


def _answer_json():
    return json.dumps({
        "reasoning": "ok",
        "message": "Found Heco",
        "outcome": "OUTCOME_OK",
        "grounding_refs": [],
        "completed_steps": [],
    })


def test_llm_call_records_written_on_success(tmp_path):
    """Happy path: sdd + answer llm_call records written."""
    t, p = _collect_trace_records(tmp_path)

    vm = MagicMock()
    vm.exec.return_value = _exec_ok()

    with patch("agent.pipeline.call_llm_raw", side_effect=[_sdd_json(), _test_gen_json(), _answer_json()]), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._get_rules_loader"), \
         patch("agent.pipeline._get_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", return_value=None), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        run_pipeline(vm, "anthropic/claude-sonnet-4-6", "find X", _make_pre(), {})

    t.close()
    set_trace(None)

    records = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    types = [r["type"] for r in records]
    assert "llm_call" in types
    llm_calls = [r for r in records if r["type"] == "llm_call"]
    phases = {r["phase"] for r in llm_calls}
    assert "sdd" in phases
    assert "answer" in phases
    for r in llm_calls:
        assert "system_sha256" in r
        assert "cycle" in r
        assert "duration_ms" in r


def test_gate_check_records_written(tmp_path):
    """gate_check record for schema gate written every cycle."""
    t, p = _collect_trace_records(tmp_path)

    vm = MagicMock()
    vm.exec.return_value = _exec_ok()

    with patch("agent.pipeline.call_llm_raw", side_effect=[_sdd_json(), _test_gen_json(), _answer_json()]), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._get_rules_loader"), \
         patch("agent.pipeline._get_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", return_value=None), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        run_pipeline(vm, "anthropic/claude-sonnet-4-6", "find X", _make_pre(), {})

    t.close()
    set_trace(None)

    records = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    gate_records = [r for r in records if r["type"] == "gate_check"]
    gate_types = {r["gate_type"] for r in gate_records}
    assert "schema" in gate_types


def test_sql_validate_and_execute_records(tmp_path):
    """sql_validate + sql_execute records written on successful cycle."""
    t, p = _collect_trace_records(tmp_path)

    vm = MagicMock()
    vm.exec.return_value = _exec_ok()

    with patch("agent.pipeline.call_llm_raw", side_effect=[_sdd_json(), _test_gen_json(), _answer_json()]), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._get_rules_loader"), \
         patch("agent.pipeline._get_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", return_value=None), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        run_pipeline(vm, "anthropic/claude-sonnet-4-6", "find X", _make_pre(), {})

    t.close()
    set_trace(None)

    records = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    types = [r["type"] for r in records]
    assert "sql_validate" in types
    assert "sql_execute" in types
    exec_r = next(r for r in records if r["type"] == "sql_execute")
    assert "duration_ms" in exec_r
    assert isinstance(exec_r["has_data"], bool)
