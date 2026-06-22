from agent.decide import identity_of, has_protected_action, _holds
from agent.ir_models import IntentSpec
from agent.interpreter import InterpretResult, CapturedAnswer
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _intent(**over):
    base = dict(objective="o", desired_outcome="d",
                outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY",
                               "OUTCOME_NONE_UNSUPPORTED", "OUTCOME_NONE_CLARIFICATION"],
                constraints=[], success_criteria={}, answer_shape={}, required_refs={})
    base.update(over)
    return IntentSpec(**base)


def _result(outcome="OUTCOME_OK", refs=None, env=None, message="m", mutation=False):
    return InterpretResult(
        captured=CapturedAnswer(message=message, outcome=outcome, refs=refs or []),
        env=env or {}, observations=[], sql_results=[], mutation_landed=mutation, label="x")


class _Facts:
    def __init__(self, identity):
        self.identity = identity


def test_holds_guards_none_and_eval_errors():
    assert _holds(None, {}) is False
    # contains_any on a non-iterable lhs would raise inside evaluate -> guarded to False
    bad = {"op": "contains_any", "lhs": "$x", "rhs": ["a"]}
    from agent.ir_models import PredExpr
    assert _holds(PredExpr(**bad), {"x": 5}) in (True, False)  # never raises


def test_identity_prefers_facts_identity():
    vm = MockVMSpy(fixtures={})
    assert identity_of(vm, _Facts({"kind": "customer", "customer_id": "cust_016"})) == \
        {"kind": "customer", "customer_id": "cust_016"}


def test_identity_falls_back_to_bin_id_exec():
    vm = MockVMSpy(fixtures={fixture_key("Exec", "/bin/id"): {"stdout": "user=cust_016 kind=customer"}})
    out = identity_of(vm, None)
    assert out.get("user") == "cust_016" and out.get("kind") == "customer"


def test_identity_never_raises_returns_empty():
    class Boom:
        def __getattr__(self, _):
            raise RuntimeError("vm exploded")
    assert identity_of(Boom(), None) == {}


def test_has_protected_action_from_mutation():
    assert has_protected_action(_intent(), _result(mutation=True)) is True


def test_has_protected_action_from_marked_constraint():
    intent = _intent(constraints=[{"anchor": "#co", "rule": "checkout", "protected_action": True}])
    assert has_protected_action(intent, None) is True


def test_has_protected_action_false_for_readonly():
    assert has_protected_action(_intent(), _result(mutation=False)) is False
