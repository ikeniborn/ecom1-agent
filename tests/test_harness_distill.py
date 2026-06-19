from unittest.mock import patch
from agent import harness, harness_validate
from agent.ir_models import PlanIR


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def test_distill_appends_candidate_of_known_kind(tmp_path, monkeypatch):
    checks = tmp_path / "checks.yaml"; checks.write_text("[]")
    monkeypatch.setattr(harness, "_DEFAULT_CHECKS", checks)
    fake = {"id": "chk_new", "kind": "primitive_contract", "prim": "column",
            "arg_index": 0, "forbid_source": ["first"], "severity": "error",
            "message": "x"}
    plan = _plan(compute=[{"prim": "first", "args": ["$rows"], "into": "r0"}])
    with patch("agent.harness.call_llm_json", return_value=fake):
        spec = harness.distill(plan, "compute step 'column' failed", source_task="t01")
    assert spec["status"] == "candidate" and spec["source_task"] == "t01"
    assert any(c["id"] == "chk_new" and c["status"] == "candidate"
               for c in harness.load_checks(checks))


def test_distill_rejects_unknown_kind(tmp_path, monkeypatch):
    checks = tmp_path / "checks.yaml"; checks.write_text("[]")
    monkeypatch.setattr(harness, "_DEFAULT_CHECKS", checks)
    with patch("agent.harness.call_llm_json", return_value={"id": "x", "kind": "made_up"}):
        assert harness.distill(_plan(), "err") is None


def test_promote_flips_candidate_to_active(tmp_path):
    checks = tmp_path / "checks.yaml"
    harness.save_checks([{"id": "c", "kind": "sql_stdin", "status": "candidate",
                          "severity": "warn"}], checks)
    assert harness.promote("c", path=checks) is True
    assert harness.load_checks(checks)[0]["status"] == "active"


def test_validate_requires_catches_bad_and_not_good():
    check = {"id": "chk_column_on_scalar", "kind": "primitive_contract", "prim": "column",
             "arg_index": 0, "forbid_source": ["first", "get"], "message": "m"}
    bad = _plan(compute=[{"prim": "first", "args": ["$rows"], "into": "r0"},
                         {"prim": "column", "args": ["$r0", "name"], "into": "out"}])
    good = _plan(compute=[{"prim": "column", "args": ["$rows", "name"], "into": "out"}])
    assert harness_validate.validate_check_via_grader(check, bad, good) is True
    assert harness_validate.validate_check_via_grader(check, bad, bad) is False   # flags good too
    assert harness_validate.validate_check_via_grader(check, good, good) is False  # never flags bad


def test_inline_validate_promotes_candidate_when_catches_bad_not_good(tmp_path, monkeypatch):
    import json
    from agent import pipeline
    from agent.ir_models import PlanIR
    checks = tmp_path / "checks.yaml"; checks.write_text("[]")
    monkeypatch.setattr(harness, "_DEFAULT_CHECKS", checks)
    monkeypatch.setenv("ECOM_HARNESS_DISTILL", "1")
    monkeypatch.setenv("ECOM_HARNESS_VALIDATE_INLINE", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)
    good = {"discovery": [], "rowsets": [],
            "compute": [{"prim": "column", "args": ["$rows", "name"], "into": "out"}],
            "decision": {"branches": [], "default_label": "ok"}, "ops": [],
            "answer": {"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
            "custom_extract": []}
    (tmp_path / "data" / "heuristics" / "tX.plan.json").write_text(json.dumps(good))
    failing = PlanIR(**{**good, "compute": [
        {"prim": "first", "args": ["$rows"], "into": "r0"},
        {"prim": "column", "args": ["$r0", "name"], "into": "out"}]})
    cand = {"id": "chk_auto", "kind": "primitive_contract", "prim": "column",
            "arg_index": 0, "forbid_source": ["first", "get"], "severity": "error",
            "message": "auto"}
    with patch("agent.harness.call_llm_json", return_value=cand):
        pipeline._maybe_harness_distill(failing, "compute step 'column' failed", "tX")
    promoted = {c["id"]: c for c in harness.load_checks(checks)}
    assert promoted["chk_auto"]["status"] == "active"   # validated -> promoted
