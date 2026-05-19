import yaml
import pytest
from unittest.mock import patch
from pathlib import Path


def _write_new_schema(path: Path, entries: list[dict]) -> None:
    path.write_text(
        yaml.dump({"task_id": path.stem, "entries": entries}, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def test_load_learned_ctx_returns_only_active(tmp_path):
    from agent.prompt_assembler import load_learned_ctx
    _write_new_schema(tmp_path / "t01.yaml", [
        {"id": "r001", "content": "Always SELECT sku", "status": "active", "source": "learn",
         "created": "2026-05-19", "reasoning": "needed", "deactivated_reason": None},
        {"id": "r002", "content": "Old rule", "status": "inactive", "source": "learn",
         "created": "2026-05-18", "reasoning": "old", "deactivated_reason": "superseded"},
    ])
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        ctx = load_learned_ctx("t01")
    assert ctx == ["Always SELECT sku"]
    assert "Old rule" not in ctx


def test_load_learned_ctx_empty_file(tmp_path):
    from agent.prompt_assembler import load_learned_ctx
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        assert load_learned_ctx("t01") == []


def test_load_learned_ctx_no_task_id(tmp_path):
    from agent.prompt_assembler import load_learned_ctx
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        assert load_learned_ctx("") == []


def test_load_learned_entries_returns_all(tmp_path):
    from agent.prompt_assembler import load_learned_entries
    _write_new_schema(tmp_path / "t01.yaml", [
        {"id": "r001", "content": "rule 1", "status": "active", "source": "learn",
         "created": "2026-05-19", "reasoning": "", "deactivated_reason": None},
        {"id": "r002", "content": "rule 2", "status": "inactive", "source": "learn",
         "created": "2026-05-18", "reasoning": "", "deactivated_reason": "old"},
    ])
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        entries = load_learned_entries("t01")
    assert len(entries) == 2
    assert entries[0]["id"] == "r001"
    assert entries[1]["status"] == "inactive"


def test_apply_learn_diff_adds_first_entry(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_ctx, load_learned_entries
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Always SELECT sku", "sku needed", [], None)
        entries = load_learned_entries("t01")
        assert len(entries) == 1
        assert entries[0]["id"] == "r001"
        assert entries[0]["status"] == "active"
        assert entries[0]["source"] == "learn"
        assert load_learned_ctx("t01") == ["Always SELECT sku"]


def test_apply_learn_diff_deactivates_entries(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_ctx
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Rule 1", "reason 1", [], None)
        _apply_learn_diff("t01", "Rule 2", "reason 2", ["r001"], "superseded by rule 2")
        ctx = load_learned_ctx("t01")
    assert ctx == ["Rule 2"]


def test_apply_learn_diff_id_monotonic(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_entries
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Rule 1", "r1", [], None)
        _apply_learn_diff("t01", "Rule 2", "r2", [], None)
        _apply_learn_diff("t01", "Rule 3", "r3", [], None)
        entries = load_learned_entries("t01")
    assert [e["id"] for e in entries] == ["r001", "r002", "r003"]


def test_apply_learn_diff_deactivated_ids_stay_in_file(tmp_path):
    from agent.prompt_assembler import _apply_learn_diff, load_learned_entries
    with patch("agent.prompt_assembler._LEARNED_DIR", tmp_path):
        _apply_learn_diff("t01", "Old rule", "old reason", [], None)
        _apply_learn_diff("t01", "New rule", "new reason", ["r001"], "superseded")
        entries = load_learned_entries("t01")
    assert len(entries) == 2
    assert entries[0]["status"] == "inactive"
    assert entries[0]["deactivated_reason"] == "superseded"
    assert entries[1]["status"] == "active"
