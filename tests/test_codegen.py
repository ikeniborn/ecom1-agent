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


def test_run_codegen_success(tmp_path):
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
