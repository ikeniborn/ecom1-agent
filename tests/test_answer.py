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
    """OSError from script → hard error error message returned."""
    vm = MagicMock()
    fs_script = CodegenOutput(
        script_path="data/heuristics/t01.py",
        script_code="raise OSError('Permission denied: /etc/passwd')",
        test_code="",
    )
    answer_out, err = _run_answer(vm, fs_script, "task")
    assert answer_out is None
    assert "filesystem" in err.lower() or "permission" in err.lower() or "hard error" in err.lower()
