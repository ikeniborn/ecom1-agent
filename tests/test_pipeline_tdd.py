import json
import os
from unittest.mock import MagicMock, patch
import pytest
from agent.pipeline import run_pipeline
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt


def _mock_assemble(*args, **kwargs):
    return AssembledPrompt(unified_context="mocked-unified-context")


def _make_pre():
    return PrephaseResult(
        agents_md_content="AGENTS",
        db_schema="CREATE TABLE products(id INT, sku TEXT, path TEXT)",
        task_type="sql",
    )


def _sdd_json():
    return json.dumps({
        "reasoning": "r",
        "spec": "return count",
        "plan": [{"type": "sql", "description": "count", "query": "SELECT COUNT(*) FROM products"}],
        "agents_md_refs": [],
    })


def _test_gen_json():
    return json.dumps({
        "reasoning": "r",
        "sql_tests": "def test_sql(results):\n    assert results\n",
        "answer_tests": "def test_answer(sql_results, answer):\n    assert answer['outcome'] == 'OUTCOME_OK'\n",
    })


def _answer_json():
    return json.dumps({
        "reasoning": "r",
        "message": "3 found",
        "outcome": "OUTCOME_OK",
        "grounding_refs": [],
        "completed_steps": [],
    })


def test_test_gen_mandatory_called(tmp_path):
    """TEST_GEN LLM call MUST occur even without SDD_ENABLED env var."""
    vm = MagicMock()
    vm.exec.return_value = MagicMock(stdout='[{"count": 3}]')
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    call_seq = iter([_sdd_json(), _test_gen_json(), _answer_json()])
    calls = []

    def fake_llm(system, user_msg, model, cfg, **kw):
        calls.append(user_msg)
        return next(call_seq)

    with patch("agent.pipeline.call_llm_raw", side_effect=fake_llm), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._RULES_DIR", rules_dir), \
         patch("agent.pipeline.load_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", return_value=None), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        stats, _ = run_pipeline(vm, "model", "count products", _make_pre(), {})

    # 3 LLM calls: SDD, TEST_GEN, ANSWER
    assert len(calls) == 3, f"Expected 3 LLM calls (SDD+TEST_GEN+ANSWER), got {len(calls)}"
    assert stats["outcome"] == "OUTCOME_OK"


def test_sdd_enabled_flag_true_by_default(tmp_path):
    """_SDD_ENABLED must be True by default (no env var)."""
    import agent.pipeline as pl
    assert pl._SDD_ENABLED is True
