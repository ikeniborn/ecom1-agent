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
    assert _holds(PredExpr(**bad), {"x": 5}) is False  # never raises; non-iterable lhs -> guarded to False


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


from agent.decide import security_deny, _merge_constraint_refs


def test_security_deny_fires_when_deny_when_holds():
    intent = _intent(constraints=[{
        "anchor": "#s", "rule": "no override", "security": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    c = security_deny(intent, {"flags": ["override"]}, protected=False)
    assert c is not None and c.anchor == "#s"


def test_security_deny_none_when_predicate_false():
    intent = _intent(constraints=[{
        "anchor": "#s", "rule": "no override", "security": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    assert security_deny(intent, {"flags": []}, protected=False) is None


def test_gated_injection_skipped_on_readonly():
    intent = _intent(constraints=[{
        "anchor": "#inj", "rule": "system override text", "security": True,
        "requires_protected_action": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    # holds, but the gate requires a protected action and there is none -> no deny.
    assert security_deny(intent, {"flags": ["override"]}, protected=False) is None


def test_gated_injection_fires_when_protected():
    intent = _intent(constraints=[{
        "anchor": "#inj", "rule": "system override text", "security": True,
        "requires_protected_action": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    c = security_deny(intent, {"flags": ["override"]}, protected=True)
    assert c is not None and c.anchor == "#inj"


def test_security_deny_ignores_non_security_constraints():
    intent = _intent(constraints=[{
        "anchor": "#x", "rule": "not security", "security": False,
        "deny_when": {"op": "nonempty", "lhs": "$flags"}}])
    assert security_deny(intent, {"flags": [1]}, protected=False) is None


def test_merge_constraint_refs_policy_and_record():
    from agent.ir_models import Constraint
    c = Constraint(anchor="#s", rule="r", security=True, refs=[
        {"kind": "policy_doc", "path": "/docs/checkout.md"},
        {"kind": "record_path", "source": "$row.record_path"}])
    out = _merge_constraint_refs(["/docs/base.md"], c, {"row": {"record_path": "/proc/baskets/b.json"}})
    assert out == ["/docs/base.md", "/docs/checkout.md", "/proc/baskets/b.json"]


def test_merge_constraint_refs_drops_unresolved_record_source():
    from agent.ir_models import Constraint
    c = Constraint(anchor="#s", rule="r", security=True, refs=[
        {"kind": "record_path", "source": "$missing"}])
    assert _merge_constraint_refs([], c, {}) == []
