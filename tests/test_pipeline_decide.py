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
    monkeypatch.setenv("ECOM_ORACLE_ENABLED", "0")        # no embedding call (Ollama unavailable)
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


# A plan that runs a trivial discovery and authors an OK answer.
_PLAN_OK = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 5 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "{row0.cnt} in stock", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})
# Same, but the model over-refuses (authors DENIED) despite nothing denying.
_PLAN_DENY = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 5 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "deny"}, "ops": [],
    "answer": {"deny": {"message": "{row0.cnt} in stock", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    "custom_extract": [],
})


def test_preflight_denies_before_loop():
    # Guest identity + a security deny_when on identity.kind -> terminal deny, 0 cycles,
    # PLAN never called (only INTENT is in the LLM sequence).
    intent = json.dumps({
        "objective": "checkout", "desired_outcome": "deny", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        "constraints": [{"anchor": "#g", "rule": "guests cannot checkout", "security": True,
                         "protected_action": True,
                         "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}],
        "success_criteria": {}, "answer_shape": {}, "required_refs": {},
    })
    vm = MagicMock()
    facts = {"identity": {"kind": "guest"}}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent)):
        m = run_pipeline(vm, instruction="check out my basket", task_id="t_pre",
                         agents_md_text="A", facts=facts)
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_DENIED_SECURITY"
    assert m["cycles_used"] == 0
    # the SQL discovery was never run because the loop never started
    vm.exec.assert_not_called()


def test_decide_flips_over_refusal_to_ok():
    # Security deny_when references identity.kind == guest, but the caller is a customer,
    # so the deny does NOT hold; PLAN over-refuses (DENIED); OK criteria are satisfied
    # -> decide_outcome forces OUTCOME_OK and verify passes.
    intent = json.dumps({
        "objective": "count stock", "desired_outcome": "int", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        "constraints": [{"anchor": "#g", "rule": "guests cannot do this", "security": True,
                         "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}],
        "success_criteria": {"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]},
        "answer_shape": {}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    facts = {"identity": {"kind": "customer", "customer_id": "cust_016"}}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_DENY)):
        m = run_pipeline(vm, instruction="how many in stock", task_id="t_flip",
                         agents_md_text="A", facts=facts)
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"


def test_happy_path_unaffected_by_decide():
    # No constraints, OK plan, OK criteria hold -> still OK (decide falls through cleanly).
    intent = json.dumps({
        "objective": "count", "desired_outcome": "int", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [],
        "success_criteria": {"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]},
        "answer_shape": {}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_OK)):
        m = run_pipeline(vm, instruction="how many", task_id="t_ok",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"
