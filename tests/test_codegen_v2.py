import json
from unittest.mock import patch

import pytest

from agent.codegen_v2 import run_codegen, CodegenError
from agent.models import (
    DesignOutput, ToolOp, AgentsMdRef, AnswerTemplate, CodegenOutput,
)


def _design():
    return DesignOutput(
        intent="count baskets",
        params={"store_id": "$agent_store_id"},
        success_criteria=["rows non-empty"],
        discovery=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": [".schema baskets"]}, bind="schema")],
        ops=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, bind="rows")],
        agents_md_constraints=[AgentsMdRef(anchor="#baskets > store_scope", rule="filter store_id")],
        answer_template=AnswerTemplate(message="{rows[0][cnt]} baskets", outcome="OUTCOME_OK", refs=[]),
        outcome_override=None,
    )


_GOOD_SCRIPT = '''
def run(vm, params):
    vm.exec(path="/bin/sql", args=[".schema baskets"])
    rows = vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
    vm.answer(message="0 baskets", outcome="OUTCOME_OK", refs=[])
'''


def test_happy_path_returns_codegen_output():
    payload = json.dumps({"script_code": _GOOD_SCRIPT})
    with patch("agent.codegen_v2.call_llm_raw", return_value=payload):
        out = run_codegen(_design(), learn_ctx=[], prev_error=None)
    assert isinstance(out, CodegenOutput)
    assert "def run(vm, params)" in out.script_code


def test_learn_ctx_passed_in_user_msg():
    captured = {}

    def _fake_llm(system, user_msg, *a, **kw):
        captured["user_msg"] = user_msg
        return json.dumps({"script_code": _GOOD_SCRIPT})

    with patch("agent.codegen_v2.call_llm_raw", side_effect=_fake_llm):
        run_codegen(_design(), learn_ctx=["Never hardcode SKUs"], prev_error=None)
    assert "Never hardcode SKUs" in captured["user_msg"]


def test_prev_error_appended():
    captured = {}

    def _fake_llm(system, user_msg, *a, **kw):
        captured["user_msg"] = user_msg
        return json.dumps({"script_code": _GOOD_SCRIPT})

    with patch("agent.codegen_v2.call_llm_raw", side_effect=_fake_llm):
        run_codegen(_design(), learn_ctx=[], prev_error="lint: invalid syntax")
    assert "lint: invalid syntax" in captured["user_msg"]


def test_unparseable_raises_codegen_error():
    with patch("agent.codegen_v2.call_llm_raw", return_value="<not json>"):
        with pytest.raises(CodegenError):
            run_codegen(_design(), learn_ctx=[], prev_error=None)
