"""Phase 3 integration: format_answer reshapes the OK message BEFORE verify, so a
format-class success_criterion passes and the canonical surface is what vm.answer gets."""
import json
from unittest.mock import MagicMock, patch
import pytest

from agent.pipeline import run_pipeline


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        return next(it)
    return _next


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    from agent import learned_store
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")   # skip the ReAct phase in tests
    monkeypatch.setenv("ECOM_ORACLE_ENABLED", "0")  # skip oracle retrieval
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


# A plan that reads a single value via SQL and authors a money message off the skeleton.
_PLAN_MONEY = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 12.5 AS amt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "EUR {row0.amt}", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})
_PLAN_COUNT = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 9 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "there are {row0.cnt}", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})
_PLAN_BOOL = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 'FK' AS sku"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "SKU: {row0.sku} not present", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})


def test_money_message_reshaped_before_verify():
    intent = json.dumps({
        "objective": "price diff", "desired_outcome": "money", "params": {},
        "outcome_space": ["OUTCOME_OK"], "constraints": [],
        "success_criteria": {"OUTCOME_OK": [
            {"op": "regex_match", "lhs": "$answer.message", "rhs": r"^EUR \d+\.\d{2}$"}]},
        "answer_shape": {"msg_skeleton": "EUR {row0.amt}"}, "required_refs": {},
    })
    learn = json.dumps({"rule_content": "", "reasoning": "", "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "amt\n12.5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_MONEY, learn)):
        m = run_pipeline(vm, instruction="price diff", task_id="t_money",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"
    assert m["answer_message"] == "EUR 12.50"


def test_count_message_reshaped_to_skeleton_format():
    intent = json.dumps({
        "objective": "count", "desired_outcome": "count", "params": {},
        "outcome_space": ["OUTCOME_OK"], "constraints": [],
        "success_criteria": {"OUTCOME_OK": [
            {"op": "regex_match", "lhs": "$answer.message", "rhs": r"^qty=\d+$"}]},
        "answer_shape": {"msg_skeleton": "qty=%d"}, "required_refs": {},
    })
    learn = json.dumps({"rule_content": "", "reasoning": "", "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n9"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_COUNT, learn)):
        m = run_pipeline(vm, instruction="how many", task_id="t_count",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["answer_message"] == "qty=9"


def test_boolean_message_gets_canonical_token():
    intent = json.dumps({
        "objective": "exists", "desired_outcome": "boolean", "params": {},
        "outcome_space": ["OUTCOME_OK"], "constraints": [],
        "success_criteria": {"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]},
        "answer_shape": {"msg_skeleton": "<NO> (SKU: {sku})"}, "required_refs": {},
    })
    learn = json.dumps({"rule_content": "", "reasoning": "", "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "sku\nFK"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_BOOL, learn)):
        m = run_pipeline(vm, instruction="does it exist", task_id="t_bool",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["answer_message"].startswith("<NO> ")
    assert m["outcome"] == "OUTCOME_OK"
