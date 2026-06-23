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


def test_t38_cure_identity_only_deny_gated_loop_runs_ok():
    # t38 cure: guest identity + identity-only deny_when (no protected_action)
    # -> security_deny GATES it -> preflight returns None -> loop runs ->
    # PLAN over-refuses (OUTCOME_DENIED_SECURITY) -> decide_outcome anti_give_up_ok
    # sees success_criteria satisfied -> flips to OUTCOME_OK.
    # Key distinction: cycles_used >= 1 (the loop RAN; not a preflight short-circuit).
    intent = json.dumps({
        "objective": "show stock", "desired_outcome": "int", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        "constraints": [{"anchor": "#g", "rule": "guests denied", "security": True,
                         "deny_when": {"op": "eq", "lhs": "$_facts.identity.kind", "rhs": "guest"}}],
        "success_criteria": {"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]},
        "answer_shape": {}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    facts = {"identity": {"kind": "guest"}}
    # PLAN over-refuses with DENIED even though identity-only deny is gated -> flipped to OK
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_DENY)):
        m = run_pipeline(vm, instruction="how many in stock", task_id="t_t38",
                         agents_md_text="A", facts=facts)
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"
    assert m["cycles_used"] >= 1   # loop ran; preflight did NOT short-circuit at cycles=0


def test_preflight_defers_record_citing_checkout_then_loop_denies():
    # T3 regression: when required_refs["OUTCOME_DENIED_SECURITY"] contains a record_path
    # RefSpec, security_preflight must DEFER (return None) so the loop runs and the basket
    # record is discovered before the denial is issued.
    # Verifies: cycles_used >= 1 (loop ran), outcome == OUTCOME_DENIED_SECURITY,
    # basket record path in answer_refs, no mutation on vm.
    _BASKET_PATH = "/proc/baskets/basket_139.json"
    intent = json.dumps({
        "objective": "checkout", "desired_outcome": "deny", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY", "OUTCOME_NONE_UNSUPPORTED"],
        "constraints": [{"anchor": "#co", "rule": "guests cannot checkout",
                         "security": True, "protected_action": True,
                         "deny_when": {"op": "ne", "lhs": "$_facts.identity.kind",
                                       "rhs": "customer"}}],
        "success_criteria": {},
        "answer_shape": {},
        "required_refs": {
            "OUTCOME_DENIED_SECURITY": [
                {"kind": "policy_doc", "path": "/docs/checkout.md"},
                {"kind": "record_path", "source": "$basket.record_path"},
            ],
        },
    })
    # PLAN: read-only discovery of the basket, then deny.
    # The basket query returns one row with record_path; compute first binds $basket.
    plan = json.dumps({
        "discovery": [{"rpc": "Exec",
                       "args": {"path": "/bin/sql",
                                "stdin": "SELECT record_path FROM shopping_baskets LIMIT 1"},
                       "bind": "raw"}],
        "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        "compute": [{"prim": "first", "args": ["$rows"], "into": "basket"}],
        "decision": {
            "branches": [{"when": {"op": "ne", "lhs": "$_facts.identity.kind", "rhs": "customer"},
                          "label": "deny"}],
            "default_label": "ok",
        },
        "ops": [],
        "answer": {
            "deny": {"message": "Denied: guests cannot checkout.",
                     "outcome": "OUTCOME_DENIED_SECURITY",
                     "refs": ["$basket.record_path", "/docs/checkout.md"]},
            "ok": {"message": "OK", "outcome": "OUTCOME_OK", "refs": []},
        },
        "custom_extract": [],
    })
    vm = MagicMock()
    # Discovery exec returns one basket row with record_path column.
    vm.exec.return_value = {"stdout": f"record_path\n{_BASKET_PATH}"}
    facts = {"identity": {"kind": "guest"}}
    # LLM sequence: INTENT + one PLAN. Preflight MUST defer (record_path in required_refs),
    # so PLAN is called; if PLAN is never called the deny short-circuited wrongly.
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, plan)):
        m = run_pipeline(vm, instruction="checkout my basket", task_id="t_t50_defer",
                         agents_md_text="A", facts=facts)
    vm.answer.assert_called_once()
    # Preflight deferred -> loop ran (cycles_used >= 1, NOT cycles=0).
    assert m["cycles_used"] >= 1, (
        f"Expected loop to run (cycles >= 1) but got cycles_used={m['cycles_used']}. "
        "security_preflight should have deferred due to record_path in required_refs."
    )
    assert m["outcome"] == "OUTCOME_DENIED_SECURITY"
    # The basket record path must appear in the answer refs.
    assert _BASKET_PATH in m.get("answer_refs", []), (
        f"Expected {_BASKET_PATH!r} in answer_refs={m.get('answer_refs')}. "
        "decide_outcome should resolve $basket.record_path from the bound env."
    )
    # /docs/checkout.md must also be cited (policy_doc required_ref).
    assert "/docs/checkout.md" in m.get("answer_refs", [])
    # No mutation: the checkout op is guarded behind the allow branch only.
    vm.write.assert_not_called()
    vm.delete.assert_not_called()


def test_t50_protected_action_preflight_deny_with_required_ref():
    # t50 path: guest identity + protected_action-marked constraint ->
    # has_protected_action(intent, None) = True -> NOT gated -> security_deny fires ->
    # terminal preflight DENIED at cycles=0, citing /docs/checkout.md (H2) + /docs/security.md.
    intent = json.dumps({
        "objective": "checkout", "desired_outcome": "deny", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        "constraints": [{"anchor": "#co", "rule": "guests cannot checkout",
                         "security": True, "protected_action": True,
                         "deny_when": {"op": "ne", "lhs": "$_facts.identity.kind",
                                       "rhs": "customer"}}],
        "success_criteria": {},
        "answer_shape": {}, "required_refs": {
            "OUTCOME_DENIED_SECURITY": [{"kind": "policy_doc", "path": "/docs/checkout.md"}],
        },
    })
    vm = MagicMock()
    facts = {"identity": {"kind": "guest"}}
    # Only INTENT is in the sequence; PLAN must never be called.
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent)):
        m = run_pipeline(vm, instruction="checkout my basket", task_id="t_t50",
                         agents_md_text="A", facts=facts)
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_DENIED_SECURITY"
    assert m["cycles_used"] == 0
    vm.exec.assert_not_called()   # loop never ran
    assert "/docs/checkout.md" in m["answer_refs"]
    assert "/docs/security.md" in m["answer_refs"]
