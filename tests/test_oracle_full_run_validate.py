"""Efficacy validator: grade_full_run runs the full agent for a task with the candidate atom
force-active, and validate_atom_via_full_run gates promotion on score >= 1.0."""
import os
import types

import pytest

import agent.oracle_validate as ov
from agent.oracle_atoms import Atom


def _atom(id_="cand1"):
    return Atom(id=id_, description="d", domain=[], content="c", source="distilled",
                validated_by="", validated_at="", status="candidate")


def test_validate_true_when_score_meets_min(monkeypatch):
    monkeypatch.setattr(ov, "grade_full_run", lambda tid, fid: (1.0, []))
    assert ov.validate_atom_via_full_run(_atom(), "t01") is True


def test_validate_false_when_score_below_min(monkeypatch):
    monkeypatch.setattr(ov, "grade_full_run", lambda tid, fid: (0.5, ["x"]))
    assert ov.validate_atom_via_full_run(_atom(), "t01") is False


def test_validate_false_when_grade_raises(monkeypatch):
    def boom(tid, fid):
        raise RuntimeError("no grader")
    monkeypatch.setattr(ov, "grade_full_run", boom)
    assert ov.validate_atom_via_full_run(_atom(), "t01") is False


def _fake_harness(monkeypatch, target_task):
    """Wire a fake harness client + EcomRuntime so grade_full_run drives one matching trial."""
    trial = types.SimpleNamespace(trial_id="trial-1", task_id=target_task,
                                  harness_url="http://vm", instruction="do the thing")
    submit = types.SimpleNamespace(trials=[types.SimpleNamespace(
        task_id=target_task, score=1.0, score_available=True, score_detail=[])])

    class FakeClient:
        def __init__(self, url): pass
        def start_run(self, req): return types.SimpleNamespace(run_id="run-1", trial_ids=["trial-1"])
        def start_trial(self, req): return trial
        def end_trial(self, req): return None
        def submit_run(self, req): return submit

    monkeypatch.setattr(ov, "HarnessServiceClientSync", FakeClient)
    monkeypatch.setattr(ov, "EcomRuntimeClientSync", lambda url: object())
    return trial


def test_grade_full_run_sets_and_clears_force_active(monkeypatch):
    _fake_harness(monkeypatch, "t01")
    seen = {}

    def fake_run_agent(cfg, url, text, task_id=""):
        seen["force"] = os.environ.get("ECOM_ORACLE_FORCE_ACTIVE")
        seen["url"] = url
        return {}

    import agent.orchestrator as orch
    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    monkeypatch.delenv("ECOM_ORACLE_FORCE_ACTIVE", raising=False)

    score, _detail = ov.grade_full_run("t01", "cand1")
    assert score == 1.0
    assert seen["force"] == "cand1"          # set during the run
    assert seen["url"] == "http://vm"
    assert "ECOM_ORACLE_FORCE_ACTIVE" not in os.environ   # cleared after


def test_grade_full_run_clears_force_active_on_raise(monkeypatch):
    _fake_harness(monkeypatch, "t01")

    def boom_run_agent(cfg, url, text, task_id=""):
        raise RuntimeError("pipeline blew up")

    import agent.orchestrator as orch
    monkeypatch.setattr(orch, "run_agent", boom_run_agent)
    monkeypatch.delenv("ECOM_ORACLE_FORCE_ACTIVE", raising=False)

    with pytest.raises(RuntimeError):
        ov.grade_full_run("t01", "cand1")
    assert "ECOM_ORACLE_FORCE_ACTIVE" not in os.environ   # finally cleared even on error
