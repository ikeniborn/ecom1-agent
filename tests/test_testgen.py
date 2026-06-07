import json
from unittest.mock import patch

import pytest

from agent.models import AgentsMdRef, AnswerTemplate, DesignOutput
from agent.testgen import TestGenError as _TestGenError
from agent.testgen import run_test_gen


def _design() -> DesignOutput:
    return DesignOutput(
        intent="count baskets in store",
        params={"store_id": "$agent_store_id"},
        success_criteria=["rows non-empty", "answer references catalog path"],
        discovery=[],
        ops=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT COUNT(*) FROM baskets"]}}],
        agents_md_constraints=[AgentsMdRef(anchor="#yes-no", rule="include <YES>/<NO> tokens")],
        answer_template=AnswerTemplate(message="{cnt} baskets", outcome="OUTCOME_OK", refs=["$path"]),
    )


_GOOD_TEST_JSON = json.dumps({
    "reasoning": "aggregate count, OK outcome, refs required",
    "sql_tests": "def test_sql(results):\n    assert results, 'no results'\n",
    "answer_tests": "def test_answer(sql_results, answer):\n    assert answer['outcome'] == 'OUTCOME_OK'\n    assert answer['message']\n",
})


def test_happy_path_returns_test_spec():
    with patch("agent.pipeline.call_llm_raw", return_value=_GOOD_TEST_JSON):
        out = run_test_gen(_design(), "How many baskets?")
    assert "def test_sql" in out.sql_tests
    assert "def test_answer" in out.answer_tests
    assert out.reasoning


def test_user_msg_carries_intent_and_constraints():
    captured = {}

    def _fake(system, user_msg, model, cfg, **kw):
        captured["user_msg"] = user_msg
        return _GOOD_TEST_JSON

    with patch("agent.pipeline.call_llm_raw", side_effect=_fake):
        run_test_gen(_design(), "How many baskets?")
    msg = captured["user_msg"]
    assert msg.startswith("INTENT:")
    assert "count baskets in store" in msg
    assert "include <YES>/<NO> tokens" in msg          # agents_md_constraints reach the tests
    assert "answer references catalog path" in msg      # success_criteria reach the tests
    assert "INSTRUCTION:" in msg


def test_empty_response_raises():
    with patch("agent.pipeline.call_llm_raw", return_value=""):
        with pytest.raises(_TestGenError):
            run_test_gen(_design(), "x")


def test_unparseable_response_raises():
    with patch("agent.pipeline.call_llm_raw", return_value="not json"):
        with pytest.raises(_TestGenError):
            run_test_gen(_design(), "x")
