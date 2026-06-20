# tests/test_investigate.py
import os
from agent.llm import _resolve_model_for_phase, _think_for_phase


def test_investigate_phase_is_fast_tier(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.delenv("ECOM_MODEL_INVESTIGATE", raising=False)
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "fast-model"
    assert _think_for_phase("INVESTIGATE") is False


def test_investigate_phase_override_wins(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.setenv("ECOM_MODEL_INVESTIGATE", "explicit-model")
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "explicit-model"


# append to tests/test_investigate.py
from agent.investigate import Note, Brief, render_brief


def test_brief_accumulates_notes_and_env():
    brief = Brief()
    brief.notes.append(Note(goal="find incident", tool="exec",
                            args={"path": "/bin/sql"}, observation_digest="3 rows",
                            lesson="incident id lives in fraud_reports",
                            refs_found=["/payments/p_1.json"]))
    brief.env["incident_id"] = "INC-7"
    assert len(brief.notes) == 1
    assert brief.env["incident_id"] == "INC-7"


def test_render_brief_is_compact_and_contains_env_and_lessons():
    brief = Brief()
    brief.notes.append(Note(goal="g", tool="read", args={"path": "/docs/x.md"},
                            observation_digest="policy says N=2", lesson="use N=2",
                            refs_found=[]))
    brief.env["governing_doc"] = "/docs/x.md"
    out = render_brief(brief)
    assert "INVESTIGATION_BRIEF" in out
    assert "use N=2" in out               # lesson surfaced
    assert "governing_doc" in out         # env surfaced
    assert "/docs/x.md" in out


def test_render_brief_empty_is_falsy_marker():
    assert render_brief(Brief()) == ""
