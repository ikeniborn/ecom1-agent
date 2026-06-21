"""Lint-firing telemetry: lint() emits one `lint_fire` trace record per fired check
(blocking AND warn), the emit helper is no-op without an active logger, and the record
renders as a readable line."""
import json
from pathlib import Path

import pytest

from agent.ir_models import PlanIR
from agent import harness
from agent.interpreter import lint, InterpretError
from agent.trace import (
    TraceLogger, set_trace, set_cycle, log_lint_fire_auto, render_trace,
)


def _records(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def test_log_lint_fire_auto_writes_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    set_trace(t)
    set_cycle(3)
    try:
        log_lint_fire_auto("chk_x", "primitive_contract", "error", True, "boom")
    finally:
        t.close()
        set_trace(None)
    fires = [r for r in _records(p) if r.get("type") == "lint_fire"]
    assert len(fires) == 1
    r = fires[0]
    assert r["check_id"] == "chk_x"
    assert r["kind"] == "primitive_contract"
    assert r["severity"] == "error"
    assert r["blocking"] is True
    assert r["message"] == "boom"
    assert r["cycle"] == 3
    assert r["task_id"] == "t01"


def test_log_lint_fire_auto_no_logger_is_noop():
    set_trace(None)
    # Must not raise when there is no active logger.
    log_lint_fire_auto("chk_x", "k", "error", True, "msg")


def _denied_after_business():
    # Trips the security_first handler: a DENIED_SECURITY branch follows a business branch.
    return _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"},
                               {"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"}],
                  "default_label": "ok"},
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []},
                "deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )


def test_lint_emits_fire_for_warn_and_blocking(tmp_path, monkeypatch):
    # warn spec first (records, does not block), then an active error spec (records, blocks).
    monkeypatch.setattr(harness, "load_checks", lambda *a, **k: [
        {"id": "warn1", "kind": "security_first", "severity": "warn", "status": "active"},
        {"id": "err1", "kind": "security_first", "severity": "error", "status": "active"},
    ])
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    set_trace(t)
    set_cycle(1)
    try:
        with pytest.raises(InterpretError):
            lint(_denied_after_business())
    finally:
        t.close()
        set_trace(None)
    fires = [r for r in _records(p) if r.get("type") == "lint_fire"]
    assert [f["check_id"] for f in fires] == ["warn1", "err1"]
    assert fires[0]["blocking"] is False
    assert fires[1]["blocking"] is True


def test_render_trace_shows_lint_fire():
    rec = {"type": "lint_fire", "cycle": 2, "check_id": "chk_x", "kind": "primitive_contract",
           "severity": "error", "blocking": True, "message": "boom contract"}
    text = render_trace([rec], color=False)
    assert "lint_fire" in text
    assert "chk_x" in text
    assert "BLOCK" in text
    assert "boom contract" in text
