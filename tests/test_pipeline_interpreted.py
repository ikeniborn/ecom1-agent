# tests/test_pipeline_interpreted.py
import json
from unittest.mock import MagicMock, patch
import pytest

from agent.pipeline import run_pipeline
from agent.mock_vm_spy import fixture_key


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        return next(it)
    return _next


_INTENT = json.dumps({
    "objective": "count", "desired_outcome": "int", "params": {},
    "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
    "constraints": [], "success_criteria": [],
    "answer_shape": {"required_ref_kinds": ["static"]},
})
_PLAN = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 1 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "{row0.cnt}", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}},
    "custom_extract": [],
})


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    from agent import learned_store
    monkeypatch.setenv("INTERPRETER_ENABLED", "1")
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


def test_interpreted_happy_path_answers_once():
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(_INTENT, _PLAN)):
        m = run_pipeline(vm, instruction="how many", task_id="t_int", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"


def test_interpreted_genuine_verify_fail_via_success_criteria():
    # Exercises the genuine verify() failure path: interpret() SUCCEEDS (no InterpretError)
    # because required_ref_kinds=[] so the refuse-invariant never fires, then verify() returns
    # (False, ...) because success_criteria[0] requires row0.cnt == "999" but plan yields "5".
    # Three cycles: interpret() resolves normally each time, verify() rejects each time -> LEARN
    # -> exhaust -> OUTCOME_NONE_CLARIFICATION. vm.answer called exactly once (terminal clarify).
    intent_no_runtime_req = json.dumps({
        "objective": "count", "desired_outcome": "int", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [],
        # success_criteria: row0.cnt must equal "999", but plan produces "5" -> always False
        "success_criteria": [{"op": "eq", "lhs": "$row0.cnt", "rhs": "999"}],
        # required_ref_kinds=[] -> interpreter refuse-invariant never fires for static-only refs
        "answer_shape": {"required_ref_kinds": []},
    })
    learn = json.dumps({"rule_content": "cnt must be 999", "reasoning": "verify failed",
                        "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    # 1 INTENT + 3x(PLAN + LEARN)
    seq = [intent_no_runtime_req, _PLAN, learn, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="how many items", task_id="t_gvf", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"


def test_interpreted_verify_fail_then_learn_then_exhaust():
    # Exercises the interpreter REFUSE-INVARIANT path (InterpretError), not verify():
    # answer_shape demands runtime ref but plan emits only a static ref -> InterpretError every cycle
    intent_runtime = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [],
        "answer_shape": {"required_ref_kinds": ["runtime"]},
    })
    learn = json.dumps({"rule_content": "Always bind a runtime $ref for OK answers",
                        "reasoning": "verify failed", "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    # 1 INTENT + 3x(PLAN + LEARN)
    seq = [intent_runtime, _PLAN, learn, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="x", task_id="t_vf", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"


def test_learn_from_grader_consumes_ir_artifacts(tmp_path, monkeypatch):
    from agent import learned_store
    from agent.pipeline import learn_from_grader
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    heur = tmp_path / "data" / "heuristics"; heur.mkdir(parents=True, exist_ok=True)
    (heur / "t_ir.intent.json").write_text(_INTENT)
    (heur / "t_ir.plan.json").write_text(_PLAN)
    learn = json.dumps({"rule_content": "Always cite the record path in refs",
                        "reasoning": "grader said missing ref", "deactivate_ids": [], "skip": False})
    with patch("agent.pipeline.call_llm_raw", return_value=learn):
        made = learn_from_grader("t_ir", ["answer missing required reference"])
    assert made is True
    data = __import__("yaml").safe_load((tmp_path / "t_ir.yaml").read_text())
    assert any(e.get("content") for e in data["entries"])
