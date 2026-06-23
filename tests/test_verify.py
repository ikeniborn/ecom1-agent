from agent.ir_models import IntentSpec
from agent.interpreter import InterpretResult, CapturedAnswer
from agent.verify import verify


def _result(captured, env=None):
    return InterpretResult(captured=captured, env=env or {}, observations=[],
                           sql_results=[], mutation_landed=False, label="ok")


def _intent(**over):
    base = dict(objective="o", desired_outcome="d",
                outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY",
                               "OUTCOME_NONE_UNSUPPORTED"],
                constraints=[], success_criteria=[],
                answer_shape={},
                required_refs={})
    base.update(over)
    return IntentSpec(**base)


def test_i1_ok_with_unresolved_dollar_ref_fails():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["$still_a_ref"]))
    ok, err = verify(res, _intent())
    assert not ok and "ref" in err.lower()


def test_i1_ok_missing_a_required_policy_doc_fails():
    # required policy_doc resolves to a literal path; absent from refs -> fail.
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "policy_doc", "path": "/docs/counting.md"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]))
    ok, err = verify(res, intent)
    assert not ok and "/docs/counting.md" in err


def test_i1_ok_with_all_required_refs_passes():
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "policy_doc", "path": "/docs/counting.md"},
        {"kind": "record_path", "source": "$row.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK",
                                 refs=["/docs/counting.md", "/proc/catalog/A.json"]))
    ok, err = verify(res, intent)
    assert ok, err


def test_i1_static_only_docs_ref_no_longer_auto_fails():
    # regression guard: the deleted /docs-static heuristic must NOT fire.
    # With required_refs empty, a /docs-only OK answer is acceptable to verify.
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["/docs/security.md"]))
    ok, err = verify(res, _intent())
    assert ok, err


def test_i2_outcome_outside_space_fails():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_ERR_INTERNAL", refs=["x"]))
    ok, err = verify(res, _intent(answer_shape={}))
    assert not ok


def test_i3_security_deny_when_true_but_outcome_ok_fails():
    intent = _intent(
        answer_shape={},
        constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}],
    )
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["x"]),
                  env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert not ok and "security" in err.lower()


def test_i3_security_deny_when_true_and_denied_passes():
    intent = _intent(
        answer_shape={},
        constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}],
    )
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert ok, err


def test_success_criteria_must_hold():
    intent = _intent(answer_shape={},
                     success_criteria=[{"op": "nonempty", "lhs": "$answer.message"}])
    res_bad = _result(CapturedAnswer(message="", outcome="OUTCOME_OK", refs=["x"]))
    ok, _ = verify(res_bad, intent)
    assert not ok
    res_ok = _result(CapturedAnswer(message="hi", outcome="OUTCOME_OK", refs=["x"]))
    ok, err = verify(res_ok, intent)
    assert ok, err


def test_i1_required_ref_enforced_on_non_ok_outcome():
    # the t26 class: a denial must still cite its required policy doc.
    intent = _intent(required_refs={"OUTCOME_NONE_UNSUPPORTED": [
        {"kind": "policy_doc", "path": "/docs/checkout.md"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_NONE_UNSUPPORTED",
                                 refs=["/docs/security.md"]))
    ok, err = verify(res, intent)
    assert not ok and "/docs/checkout.md" in err


def test_i1_required_ref_present_on_non_ok_passes():
    intent = _intent(required_refs={"OUTCOME_NONE_UNSUPPORTED": [
        {"kind": "policy_doc", "path": "/docs/checkout.md"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_NONE_UNSUPPORTED",
                                 refs=["/docs/checkout.md"]))
    ok, err = verify(res, intent)
    assert ok, err


def test_i1_dollar_ref_guard_fires_on_non_ok():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_NONE_UNSUPPORTED",
                                 refs=["$unresolved"]))
    ok, err = verify(res, _intent())
    assert not ok and "ref" in err.lower()


def test_i1_unresolved_record_path_source_skipped_when_path_present():
    # required record_path whose $source isn't in env, but grounding put the literal
    # path in refs -> presence-based check skips the unresolved source and passes.
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$row.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK",
                                 refs=["/proc/catalog/A.json"]))
    ok, err = verify(res, intent)
    assert ok, err

    # Inverse: when env resolves the source, absence from refs MUST fail (proves the
    # positive case passes because the path is present, not because nothing is required).
    res_env_resolves = _result(
        CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]),
        env={"row": {"record_path": "/proc/catalog/A.json"}})
    ok2, err2 = verify(res_env_resolves, intent)
    assert not ok2 and "/proc/catalog/A.json" in err2


def test_i3_reverse_denied_without_holding_predicate_fails():
    # A declared security deny_when exists but does NOT hold, yet the outcome is DENIED
    # -> spurious over-refusal -> verify rejects (the 5-over-refusal class).
    intent = _intent(constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                                    "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env={"tags": []})
    ok, err = verify(res, intent)
    assert not ok and "DENIED_SECURITY" in err


def test_i3_reverse_denied_with_no_declared_predicate_passes():
    # No declared security deny_when at all -> the model's denial is not second-guessed.
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]))
    ok, err = verify(res, _intent())
    assert ok, err


def test_i3_reverse_denied_with_holding_predicate_passes():
    intent = _intent(constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                                   "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert ok, err


# ── T2: identity-only gate (decide/verify parity) ────────────────────────────

_IDENTITY_DENY = {
    "anchor": "#id-sec", "rule": "guests denied", "security": True,
    "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"},
}
_IDENTITY_DENY_PROTECTED = dict(_IDENTITY_DENY, protected_action=True)

# verify builds env["identity"] from result.env["_facts"]["identity"]; pass via _facts.
_GUEST_ENV = {"_facts": {"identity": {"kind": "guest"}}}


def test_i3_forward_identity_only_deny_gated_passes():
    """Gated identity-only deny holds, outcome=OUTCOME_OK, no protected marker → PASS.

    Pre-T2: verify's forward I3 demands DENIED_SECURITY and REJECTS the OK.
    Post-T2: the gate skips this constraint → OK accepted.
    """
    intent = _intent(constraints=[_IDENTITY_DENY])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]),
                  env=_GUEST_ENV)
    ok, err = verify(res, intent)
    assert ok, f"Expected PASS (gated identity-only deny); got err={err!r}"


def test_i3_forward_identity_only_deny_enforced_when_protected():
    """Same deny but protected_action=True → gate OFF → verify still demands DENIED."""
    intent = _intent(constraints=[_IDENTITY_DENY_PROTECTED])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]),
                  env=_GUEST_ENV)
    ok, err = verify(res, intent)
    assert not ok and "security" in err.lower(), \
        f"Expected FAIL (protected, gate OFF); got ok={ok} err={err!r}"


def test_i3_reverse_identity_only_deny_gated_spurious_over_refusal():
    """Outcome=DENIED_SECURITY justified ONLY by a gated identity-only deny (not protected).

    The gated constraint must NOT count as valid justification → verify FAILS (spurious
    over-refusal).
    """
    intent = _intent(constraints=[_IDENTITY_DENY])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env=_GUEST_ENV)
    ok, err = verify(res, intent)
    assert not ok and "DENIED_SECURITY" in err, \
        f"Expected FAIL (spurious over-refusal); got ok={ok} err={err!r}"


def test_i3_reverse_identity_only_deny_protected_passes():
    """DENIED_SECURITY justified by an identity-only deny on a protected_action=True
    constraint (protected=True) → gate OFF → PASS."""
    intent = _intent(constraints=[_IDENTITY_DENY_PROTECTED])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env=_GUEST_ENV)
    ok, err = verify(res, intent)
    assert ok, f"Expected PASS (protected, gate OFF); got err={err!r}"
