from agent.decide import identity_of, has_protected_action, _holds, _is_identity_only
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


from agent.decide import unsupported_or_clarify


def test_unsupported_when_maps_to_unsupported():
    intent = _intent(constraints=[{
        "anchor": "#paid", "rule": "already paid", "security": False,
        "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}}])
    assert unsupported_or_clarify(intent, {"state": "paid"}) == "OUTCOME_NONE_UNSUPPORTED"


def test_clarify_when_maps_to_clarification():
    intent = _intent(constraints=[{
        "anchor": "#amb", "rule": "amount only", "security": False,
        "clarify_when": {"op": "isnull", "lhs": "$basket"}}])
    assert unsupported_or_clarify(intent, {"basket": None}) == "OUTCOME_NONE_CLARIFICATION"


def test_unsupported_outranks_clarify():
    intent = _intent(constraints=[
        {"anchor": "#paid", "rule": "paid", "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}},
        {"anchor": "#amb", "rule": "amb", "clarify_when": {"op": "isnull", "lhs": "$basket"}}])
    assert unsupported_or_clarify(intent, {"state": "paid", "basket": None}) == "OUTCOME_NONE_UNSUPPORTED"


def test_outcome_gated_by_space():
    # unsupported_when holds but OUTCOME_NONE_UNSUPPORTED is not in the space -> None.
    intent = _intent(outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
                     constraints=[{"anchor": "#p", "rule": "p",
                                   "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}}])
    assert unsupported_or_clarify(intent, {"state": "paid"}) is None


def test_no_predicate_returns_none():
    assert unsupported_or_clarify(_intent(), {"state": "open"}) is None


from agent.decide import anti_give_up_ok


def test_anti_give_up_forces_ok_when_criteria_hold():
    intent = _intent(success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(message="5 in stock")
    env = {"answer": {"message": "5 in stock"}}
    assert anti_give_up_ok(intent, res, env) is True


def test_anti_give_up_false_when_criteria_fail():
    intent = _intent(success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(message="")
    env = {"answer": {"message": ""}}
    assert anti_give_up_ok(intent, res, env) is False


def test_anti_give_up_false_when_no_criteria():
    # empty criteria -> cannot assert solved -> never fabricate OK.
    assert anti_give_up_ok(_intent(success_criteria={}), _result(message="x"), {}) is False


def test_anti_give_up_false_when_ok_not_in_space():
    intent = _intent(outcome_space=["OUTCOME_DENIED_SECURITY"],
                     constraints=[{"anchor": "#s", "rule": "r", "security": True,
                                   "deny_when": {"op": "nonempty", "lhs": "$x"}}],
                     success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    assert anti_give_up_ok(intent, _result(message="x"), {"answer": {"message": "x"}}) is False


def test_anti_give_up_false_when_unresolved_ref_present():
    intent = _intent(success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(message="x", refs=["$still_a_ref"])
    assert anti_give_up_ok(intent, res, {"answer": {"message": "x"}}) is False


from agent.decide import decide_outcome, security_preflight


def test_decide_security_deny_outranks_all():
    intent = _intent(
        constraints=[{"anchor": "#s", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}],
        success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(outcome="OUTCOME_OK", env={"flags": ["override"]}, message="x")
    out, refs = decide_outcome(intent, res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_DENIED_SECURITY"
    assert "/docs/security.md" in refs


def test_decide_unsupported_outranks_anti_give_up():
    intent = _intent(
        constraints=[{"anchor": "#p", "rule": "paid",
                      "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}}],
        success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(outcome="OUTCOME_OK", env={"state": "paid"}, message="x")
    out, _ = decide_outcome(intent, res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_NONE_UNSUPPORTED"


def test_decide_anti_give_up_flips_over_refusal_to_ok():
    # The 5-over-refusal class: PLAN authored DENIED, but no deny_when holds and the OK
    # criteria are satisfied -> forced OK.
    intent = _intent(
        constraints=[{"anchor": "#s", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}],
        success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(outcome="OUTCOME_DENIED_SECURITY", env={"flags": []}, message="5 in stock")
    out, _ = decide_outcome(intent, res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_OK"


def test_decide_falls_back_to_plan_outcome():
    # Nothing fires (no criteria, no predicates) -> the plan's own outcome stands.
    res = _result(outcome="OUTCOME_NONE_CLARIFICATION", message="need more info")
    out, _ = decide_outcome(_intent(), res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_NONE_CLARIFICATION"


def test_preflight_terminal_deny_from_identity():
    intent = _intent(
        outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        constraints=[{"anchor": "#g", "rule": "guests not authorized", "security": True,
                      "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    out = security_preflight(intent, MockVMSpy(fixtures={}), _Facts({"kind": "guest"}))
    assert out is not None
    outcome, msg, refs = out
    assert outcome == "OUTCOME_DENIED_SECURITY"
    assert "guests not authorized" in msg
    assert "/docs/security.md" in refs


def test_preflight_none_when_no_deny():
    intent = _intent(
        constraints=[{"anchor": "#g", "rule": "guests not authorized", "security": True,
                      "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    assert security_preflight(intent, MockVMSpy(fixtures={}), _Facts({"kind": "customer"})) is None


def test_preflight_gated_deny_fires_from_marked_constraint():
    # A constraint that is BOTH requires_protected_action=True AND protected_action=True
    # self-satisfies the blast-radius gate: has_protected_action(intent, None) returns True
    # (the marked constraint itself counts), so security_deny fires with protected=True,
    # and security_preflight returns a terminal deny pre-loop without any mutation.
    intent = _intent(
        outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        constraints=[{"anchor": "#blast", "rule": "guest blast-radius check",
                      "security": True,
                      "requires_protected_action": True,
                      "protected_action": True,
                      "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    out = security_preflight(intent, MockVMSpy(fixtures={}), _Facts({"kind": "guest"}))
    assert out is not None
    outcome, msg, refs = out
    assert outcome == "OUTCOME_DENIED_SECURITY"
    assert "/docs/security.md" in refs


def test_preflight_gated_deny_skipped_without_protected_marker():
    # Same constraint but WITHOUT protected_action=True: has_protected_action(intent, None)
    # returns False, so security_deny skips the requires_protected_action constraint ->
    # preflight returns None (the deny cannot fire pre-loop; it needs a mutation landing first).
    intent = _intent(
        outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        constraints=[{"anchor": "#blast", "rule": "guest blast-radius check",
                      "security": True,
                      "requires_protected_action": True,
                      "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    # Confirm the gate is False (no protected_action marker, no result mutation)
    assert has_protected_action(intent, None) is False
    assert security_preflight(intent, MockVMSpy(fixtures={}), _Facts({"kind": "guest"})) is None


# ---------------------------------------------------------------------------
# _is_identity_only tests
# ---------------------------------------------------------------------------

from agent.ir_models import PredExpr


def test_is_identity_only_eq_identity_dot():
    # (a) $identity.kind -> True (identity-rooted)
    e = PredExpr(**{"op": "eq", "lhs": "$identity.kind", "rhs": "guest"})
    assert _is_identity_only(e) is True


def test_is_identity_only_facts_identity_dot():
    # (b) $_facts.identity.kind -> True
    e = PredExpr(**{"op": "eq", "lhs": "$_facts.identity.kind", "rhs": "guest"})
    assert _is_identity_only(e) is True


def test_is_identity_only_owner_mismatch_false():
    # (c) AND with $record.customer_id (non-identity) -> False
    e = PredExpr(**{
        "op": "and",
        "args": [
            {"op": "eq", "lhs": "$_facts.identity.kind", "rhs": "customer"},
            {"op": "ne", "lhs": "$record.customer_id", "rhs": "$_facts.identity.customer_id"},
        ]
    })
    assert _is_identity_only(e) is False


def test_is_identity_only_contains_any_flags_false():
    # (d) $flags -> not identity-rooted -> False
    e = PredExpr(**{"op": "contains_any", "lhs": "$flags", "rhs": ["override"]})
    assert _is_identity_only(e) is False


def test_is_identity_only_state_eq_false():
    # (e) $state is not identity-rooted -> False
    e = PredExpr(**{"op": "eq", "lhs": "$state", "rhs": "paid"})
    assert _is_identity_only(e) is False


def test_is_identity_only_all_identity_refs_true():
    # (f) AND where both leaves are identity-rooted -> True
    e = PredExpr(**{
        "op": "and",
        "args": [
            {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"},
            {"op": "ne", "lhs": "$_facts.identity.customer_id", "rhs": "x"},
        ]
    })
    assert _is_identity_only(e) is True


def test_is_identity_only_no_refs_false():
    # An op with no $-refs at all (rhs is literal, lhs is also literal treated via op) -> False
    # The simplest way: an eq with two literal strings (no $ prefix) has no refs
    e = PredExpr(**{"op": "eq", "lhs": "paid", "rhs": "open"})
    assert _is_identity_only(e) is False


# ---------------------------------------------------------------------------
# security_deny gating tests (identity-only deny fires only when protected)
# ---------------------------------------------------------------------------


def test_security_deny_identity_only_skipped_when_not_protected():
    # identity-only deny_when (guest check) holds, but protected=False -> skipped (returns None)
    intent = _intent(constraints=[{
        "anchor": "#g", "rule": "guests not allowed", "security": True,
        "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    env = {"identity": {"kind": "guest"}, "flags": []}
    assert security_deny(intent, env, protected=False) is None


def test_security_deny_identity_only_fires_when_protected():
    # same constraint + protected=True -> fires
    intent = _intent(constraints=[{
        "anchor": "#g", "rule": "guests not allowed", "security": True,
        "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    env = {"identity": {"kind": "guest"}, "flags": []}
    c = security_deny(intent, env, protected=True)
    assert c is not None and c.anchor == "#g"


def test_security_deny_non_identity_fires_regardless_of_protected():
    # A non-identity deny ($flags contains_any) holds + protected=False -> still fires (regression guard)
    intent = _intent(constraints=[{
        "anchor": "#s", "rule": "no override", "security": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    env = {"flags": ["override"], "identity": {"kind": "customer"}}
    c = security_deny(intent, env, protected=False)
    assert c is not None and c.anchor == "#s"
