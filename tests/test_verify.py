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
                answer_shape={"required_ref_kinds": []},   # dropped in Task 12
                required_refs={})
    base.update(over)
    return IntentSpec(**base)


def test_i1_ok_with_unresolved_dollar_ref_fails():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["$still_a_ref"]))
    ok, err = verify(res, _intent())
    assert not ok and "ref" in err.lower()


def test_i1_ok_missing_a_required_ref_fails():
    # one record_path required, but the answer carries no refs -> fail
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$row.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]))
    ok, err = verify(res, intent)
    assert not ok


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
    ok, err = verify(res, _intent(answer_shape={"required_ref_kinds": []}))
    assert not ok


def test_i3_security_deny_when_true_but_outcome_ok_fails():
    intent = _intent(
        answer_shape={"required_ref_kinds": []},
        constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}],
    )
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["x"]),
                  env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert not ok and "security" in err.lower()


def test_i3_security_deny_when_true_and_denied_passes():
    intent = _intent(
        answer_shape={"required_ref_kinds": []},
        constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}],
    )
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert ok, err


def test_success_criteria_must_hold():
    intent = _intent(answer_shape={"required_ref_kinds": []},
                     success_criteria=[{"op": "nonempty", "lhs": "$answer.message"}])
    res_bad = _result(CapturedAnswer(message="", outcome="OUTCOME_OK", refs=["x"]))
    ok, _ = verify(res_bad, intent)
    assert not ok
    res_ok = _result(CapturedAnswer(message="hi", outcome="OUTCOME_OK", refs=["x"]))
    ok, err = verify(res_ok, intent)
    assert ok, err
