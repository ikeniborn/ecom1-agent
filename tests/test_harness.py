import pytest
from agent.ir_models import PlanIR
from agent import harness
from agent.interpreter import lint, InterpretError


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def _denied_after_business():
    return _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"},
                               {"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"}],
                  "default_label": "ok"},
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []},
                "deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )


def test_load_checks_missing_file_returns_empty(tmp_path):
    assert harness.load_checks(tmp_path / "nope.yaml") == []


def test_seeded_checks_parse_and_include_security_first():
    specs = harness.load_checks()                 # default repo path
    assert any(s.get("kind") == "security_first" for s in specs)


def test_check_security_first_handler_flags_bad_order():
    spec = {"id": "chk_security_first", "kind": "security_first"}
    assert harness.check_security_first(_denied_after_business(), spec)   # non-empty -> violation
    assert harness.check_security_first(_plan(), spec) == []              # clean -> no violation


def test_lint_blocks_on_active_error_violation(monkeypatch):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "security_first",
                                          "severity": "error", "status": "active"}])
    with pytest.raises(InterpretError):
        lint(_denied_after_business())
    lint(_plan())                                  # clean plan -> no raise


def test_lint_skips_unknown_kind(monkeypatch, capsys):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "no_such_kind",
                                          "severity": "error", "status": "active"}])
    lint(_plan())                                  # no raise
    assert "unknown check kind" in capsys.readouterr().out


def test_lint_candidate_is_warn_only(monkeypatch, capsys):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "security_first",
                                          "severity": "error", "status": "candidate"}])
    lint(_denied_after_business())                 # candidate never blocks
    assert "warn" in capsys.readouterr().out
