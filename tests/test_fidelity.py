import textwrap

import pytest

from agent.fidelity import (
    generate_fidelity_test,
    exec_fidelity_in_subprocess,
    FidelityResult,
)
from agent.models import (
    DesignOutput, ToolOp, AgentsMdRef, AnswerTemplate,
)


def _design():
    return DesignOutput(
        intent="count baskets",
        params={"store_id": "S001"},
        success_criteria=["cnt >= 0"],
        discovery=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": [".schema baskets"]}, bind="schema")],
        ops=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, bind="rows")],
        agents_md_constraints=[AgentsMdRef(anchor="#baskets > store_scope", rule="filter store_id")],
        answer_template=AnswerTemplate(message="{rows[0][cnt]} baskets", outcome="OUTCOME_OK", refs=[]),
        outcome_override=None,
    )


def test_generate_is_deterministic():
    d = _design()
    a = generate_fidelity_test(d, "t_fp")
    b = generate_fidelity_test(d, "t_fp")
    assert a == b


def test_generated_module_contains_expected_calls():
    d = _design()
    src = generate_fidelity_test(d, "t_fp")
    assert "EXPECTED_CALLS" in src
    assert "Exec" in src
    assert "/bin/sql" in src
    assert ".schema baskets" in src
    assert "Answer" in src


def test_subprocess_pass_path():
    """Script that emits EXPECTED_CALLS exactly -> passes."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            vm.exec(path="/bin/sql", args=[".schema baskets"])
            vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
            vm.answer(message="0 baskets", outcome="OUTCOME_OK", refs=[])
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=30)
    assert isinstance(result, FidelityResult)
    assert result.passed, f"unexpected fail: {result.error}"


def test_subprocess_fail_extra_call():
    """Script that calls an extra RPC -> fails the gate."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            vm.exec(path="/bin/sql", args=[".schema baskets"])
            vm.tree(root="/", level=1)
            vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
            vm.answer(message="0", outcome="OUTCOME_OK", refs=[])
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=30)
    assert not result.passed
    assert "Tree" in (result.error or "") or "drift" in (result.error or "")


def test_subprocess_fail_missing_discovery():
    """Skipped discovery op -> fails the gate."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
            vm.answer(message="0", outcome="OUTCOME_OK", refs=[])
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=30)
    assert not result.passed


def test_subprocess_timeout():
    """Infinite loop -> killed by timeout, reported as failure."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            while True:
                pass
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=2)
    assert not result.passed
    assert "timeout" in (result.error or "").lower()
