# tests/test_codegen.py
import ast
from unittest.mock import patch, MagicMock
import pytest

from agent.pipeline import _run_codegen, _detect_hardcoded_params
from agent.models import IddOutput, SddOutput, PlanOutput, CodegenOutput
from agent.prephase import PrephaseResult


def test_detect_hardcoded_params_catches_task_token():
    """Token from task_text that appears as a string literal in script → detected."""
    script = '''
_result = {"message": "found Heco brand", "outcome": "OUTCOME_OK", "refs": []}
sql = "SELECT * FROM products WHERE brand = 'Heco'"
'''
    reason = _detect_hardcoded_params(script, "Find products for brand Heco")
    assert reason is not None, "Should detect 'Heco' hardcoded from task_text"
    assert "Heco" in reason


def test_detect_hardcoded_params_ignores_stopwords():
    """SQL keywords and short words not in task_text are not flagged."""
    script = '''
import csv, io
from bitgn.vm.ecom.ecom_pb2 import ExecRequest
result = vm.exec(ExecRequest(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM orders"]))
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
count = int(rows[0]["cnt"]) if rows else 0
_result = {"message": f"{count} orders", "outcome": "OUTCOME_OK", "refs": []}
'''
    reason = _detect_hardcoded_params(script, "How many orders?")
    assert reason is None, f"Should not detect false positives, but got: {reason}"


def test_detect_hardcoded_params_ignores_short_tokens():
    """Tokens shorter than 4 chars are not checked."""
    script = '_result = {"message": "ok", "outcome": "OUTCOME_OK", "refs": []}'
    reason = _detect_hardcoded_params(script, "ok id")
    assert reason is None


def test_detect_hardcoded_params_returns_none_on_syntax_error():
    """Broken script (SyntaxError) → returns None, not raises."""
    reason = _detect_hardcoded_params("def broken(", "find brand Sony")
    assert reason is None


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
import csv, io
from bitgn.vm.ecom.ecom_pb2 import ExecRequest
result = vm.exec(ExecRequest(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM orders"]))
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
count = int(rows[0]["cnt"]) if rows else 0
_result = {"message": f"{count} orders found", "outcome": "OUTCOME_OK", "refs": []}

if __name__ == "__main__":
    pass
'''

_GOOD_TEST = '''
import csv, io
result = vm.exec(None)
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
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
    """LLM returns invalid Python syntax → retries _CODEGEN_LINT_RETRIES times → returns error."""
    bad_response = '{"script": "def broken(", "test": "assert True"}'
    idd_out = _make_idd()

    import agent.pipeline as pipeline_mod
    with patch("agent.pipeline.call_llm_raw", return_value=bad_response) as mock_llm, \
         patch.object(pipeline_mod, "_CODEGEN_LINT_RETRIES", 2):
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
    assert mock_llm.call_count == 2  # exactly 2 retries as patched


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


_HARDCODED_SCRIPT = '''
import csv, io
from bitgn.vm.ecom.ecom_pb2 import ExecRequest
result = vm.exec(ExecRequest(path="/bin/sql", args=["SELECT * FROM products WHERE brand = 'Heco'"]))
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
_result = {"message": f"{len(rows)} Heco products", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
'''

_HARDCODED_LLM_RESPONSE = (
    '{"script": ' + repr(_HARDCODED_SCRIPT) + ', "test": ' + repr(_GOOD_TEST) + '}'
)


def test_run_codegen_detects_hardcoded_params_returns_prefixed_error():
    """Script hardcodes brand from task_text → all retries fail → HARDCODED_PARAMS: prefix in error."""
    import agent.pipeline as pipeline_mod
    with patch("agent.pipeline.call_llm_raw", return_value=_HARDCODED_LLM_RESPONSE), \
         patch.object(pipeline_mod, "_CODEGEN_LINT_RETRIES", 2):
        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="Find products for brand Heco",
            task_id="t01",
            idd_out=_make_idd(extracted_params={"brand": "Heco"}),
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
        )
    assert err.startswith("HARDCODED_PARAMS:"), f"Expected HARDCODED_PARAMS: prefix, got: {err!r}"
    assert result is not None, "Should return partial CodegenOutput for LEARN to inspect"
    assert result.script_code == _HARDCODED_SCRIPT


_CRASH_ON_MUTATED_SCRIPT = '''
import re, csv, io
from bitgn.vm.ecom.ecom_pb2 import ExecRequest

_prices = {"Heco": 100, "Sony": 200}
brand_m = re.search(r"brand\\s+(\\S+)", task_text, re.I)
brand = brand_m.group(1) if brand_m else "Heco"
price = _prices[brand]

result = vm.exec(ExecRequest(path="/bin/sql", args=[f"SELECT * FROM products WHERE brand = '{brand}'"]))
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
_result = {"message": f"Price: {price}", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
'''

_CRASH_LLM_RESPONSE = (
    '{"script": ' + repr(_CRASH_ON_MUTATED_SCRIPT) + ', "test": ' + repr(_GOOD_TEST) + '}'
)


def test_run_codegen_dual_run_crash_returns_hardcoded_prefix():
    """Script passes AST hardcode check but crashes on mutated task_text → HARDCODED_PARAMS:."""
    import agent.pipeline as pipeline_mod
    with patch("agent.pipeline.call_llm_raw", return_value=_CRASH_LLM_RESPONSE), \
         patch.object(pipeline_mod, "_CODEGEN_LINT_RETRIES", 2):
        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="Get price for brand Heco",
            task_id="t01",
            idd_out=_make_idd(extracted_params={"brand": "Heco"}),
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
        )
    assert err.startswith("HARDCODED_PARAMS:"), f"Expected HARDCODED_PARAMS: prefix, got: {err!r}"
