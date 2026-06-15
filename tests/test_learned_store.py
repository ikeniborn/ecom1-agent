from pathlib import Path

import pytest
import yaml

from agent import learned_store
from agent.models import LearnConsolidateOutput


@pytest.fixture
def tid_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    return tmp_path


def _seed(tid_dir, tid, entries=None, last_run=None):
    data = {"task_id": tid, "entries": entries or [], "last_run": last_run}
    (tid_dir / f"{tid}.yaml").write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def test_load_entries_active_only(tid_dir):
    _seed(tid_dir, "t01", entries=[
        {"id": "r001", "content": "Use LIKE for series names", "status": "active"},
        {"id": "r002", "content": "old rule", "status": "inactive"},
    ])
    entries = learned_store.load_entries("t01")
    assert [e["id"] for e in entries] == ["r001"]


def test_load_entries_missing_file_returns_empty(tid_dir):
    assert learned_store.load_entries("t_missing") == []


def test_apply_learn_diff_appends_new_entry(tid_dir):
    _seed(tid_dir, "t02", entries=[])
    out = LearnConsolidateOutput(
        rule_content="Never hardcode SKUs from task_text",
        reasoning="prev hardcoded value",
        agents_md_anchor="#products > naming",
        deactivate_ids=[],
        skip=False,
    )
    learned_store.apply_learn_diff("t02", out)
    data = yaml.safe_load((tid_dir / "t02.yaml").read_text())
    assert data["entries"][0]["id"] == "r001"
    assert data["entries"][0]["status"] == "active"
    assert data["entries"][0]["agents_md_anchor"] == "#products > naming"
    assert data["entries"][0]["content"].startswith("Never hardcode")


def test_apply_learn_diff_deactivates_prior(tid_dir):
    _seed(tid_dir, "t03", entries=[
        {"id": "r001", "content": "Use exact eq on products.name", "status": "active"},
    ])
    out = LearnConsolidateOutput(
        rule_content="Use LIKE with token splits instead of exact eq on products.name",
        reasoning="exact eq missed multi-word names",
        deactivate_ids=["r001"],
        deactivate_reason="superseded by LIKE rule",
        skip=False,
    )
    learned_store.apply_learn_diff("t03", out)
    data = yaml.safe_load((tid_dir / "t03.yaml").read_text())
    ids = {e["id"]: e for e in data["entries"]}
    assert ids["r001"]["status"] == "inactive"
    assert ids["r001"]["deactivated_reason"] == "superseded by LIKE rule"
    assert ids["r002"]["status"] == "active"


def test_apply_learn_diff_skip_writes_nothing(tid_dir):
    _seed(tid_dir, "t04", entries=[{"id": "r001", "content": "rule", "status": "active"}])
    out = LearnConsolidateOutput(
        rule_content="",
        reasoning="duplicate",
        deactivate_ids=[],
        skip=True,
        skip_reason="r001",
    )
    learned_store.apply_learn_diff("t04", out)
    data = yaml.safe_load((tid_dir / "t04.yaml").read_text())
    assert [e["id"] for e in data["entries"]] == ["r001"]


def test_save_last_run_no_heuristic_valid_no_schema_hash(tid_dir):
    learned_store.save_last_run("t05", status="success", outcome="OUTCOME_OK", cycles_used=2)
    data = yaml.safe_load((tid_dir / "t05.yaml").read_text())
    lr = data["last_run"]
    assert lr["status"] == "success"
    assert lr["outcome"] == "OUTCOME_OK"
    assert lr["cycles_used"] == 2
    assert "heuristic_valid" not in lr
    assert "schema_hash" not in lr
    assert "date" in lr


def test_next_verdict_id_first(tid_dir):
    assert learned_store._next_verdict_id([]) == "v001"


def test_next_verdict_id_skips_rule_ids(tid_dir):
    entries = [
        {"id": "r001", "status": "active"},
        {"id": "v001", "status": "active"},
        {"id": "v002", "status": "inactive"},
    ]
    assert learned_store._next_verdict_id(entries) == "v003"


def test_write_verdict_appends_entry(tid_dir):
    _seed(tid_dir, "t10", entries=[])
    learned_store.write_verdict(
        "t10",
        score=0.5,
        score_detail=["answer missing field customer_id", "wrong total: expected 3, got 1"],
        submitted_message="Found 1 basket.",
        submitted_outcome="OUTCOME_OK",
        submitted_refs=["ref://basket/42"],
    )
    data = yaml.safe_load((tid_dir / "t10.yaml").read_text())
    e = data["entries"][0]
    assert e["id"] == "v001"
    assert e["source"] == "verdict"
    assert e["score"] == 0.5
    assert e["score_detail"] == ["answer missing field customer_id", "wrong total: expected 3, got 1"]
    assert e["submitted_message"] == "Found 1 basket."
    assert e["submitted_outcome"] == "OUTCOME_OK"
    assert e["submitted_refs"] == ["ref://basket/42"]
    assert e["status"] == "active"
    assert e["content"] is None


def test_write_verdict_deactivates_prior_verdict(tid_dir):
    _seed(tid_dir, "t11", entries=[
        {"id": "v001", "source": "verdict", "status": "active", "content": None},
        {"id": "r001", "source": "rule", "status": "active", "content": "always cite the catalog path"},
    ])
    learned_store.write_verdict(
        "t11", score=0.0, score_detail=["nope"],
        submitted_message="m", submitted_outcome="OUTCOME_OK", submitted_refs=[],
    )
    data = yaml.safe_load((tid_dir / "t11.yaml").read_text())
    by_id = {e["id"]: e for e in data["entries"]}
    assert by_id["v001"]["status"] == "inactive"
    assert by_id["v002"]["status"] == "active"
    assert by_id["r001"]["status"] == "active"


def test_write_verdict_empty_tid_noop(tid_dir):
    learned_store.write_verdict("", score=0.0, score_detail=[], submitted_message="",
                                submitted_outcome="", submitted_refs=[])
    assert not (tid_dir / ".yaml").exists()


def test_format_entry_rule(tid_dir):
    e = {"id": "r001", "content": "always cite the catalog path"}
    assert learned_store._format_entry(e) == "  - [r001] always cite the catalog path"


def test_format_entry_verdict(tid_dir):
    e = {
        "id": "v001", "source": "verdict", "score": 0.5,
        "score_detail": ["answer missing field customer_id", "wrong total: expected 3, got 1"],
        "content": None,
    }
    assert learned_store._format_entry(e) == (
        "  - [v001] VERDICT score=0.5: "
        "answer missing field customer_id; wrong total: expected 3, got 1"
    )


def test_format_entry_verdict_no_detail(tid_dir):
    e = {"id": "v002", "source": "verdict", "score": 0.0, "score_detail": [], "content": None}
    assert learned_store._format_entry(e) == "  - [v002] VERDICT score=0.0: "


def test_load_entries_surface_filter(tid_dir):
    _seed(tid_dir, "t10", entries=[
        {"id": "r001", "content": "ir rule", "status": "active", "surface": "ir"},
        {"id": "r002", "content": "codegen rule", "status": "active", "surface": "codegen"},
        {"id": "r003", "content": "legacy untagged", "status": "active"},  # no surface
    ])
    assert [e["id"] for e in learned_store.load_entries("t10", surface="ir")] == ["r001"]
    # untagged defaults to codegen
    assert {e["id"] for e in learned_store.load_entries("t10", surface="codegen")} == {"r002", "r003"}
    assert len(learned_store.load_entries("t10")) == 3  # no filter -> all active


def test_apply_learn_diff_stamps_surface(tid_dir):
    _seed(tid_dir, "t11", entries=[])
    out = LearnConsolidateOutput(rule_content="Always bind a runtime ref for OK answers",
                                 reasoning="r", deactivate_ids=[], skip=False)
    learned_store.apply_learn_diff("t11", out, surface="ir")
    data = yaml.safe_load((tid_dir / "t11.yaml").read_text())
    assert data["entries"][0]["surface"] == "ir"


def test_prephase_deep_read_round_trip(tid_dir):
    learned_store.append_prephase_deep_read("t12", ["payment_transaction_items", "/proc/incoming/payments"])
    learned_store.append_prephase_deep_read("t12", ["payment_transaction_items"])  # dedup
    assert learned_store.load_prephase_deep_read("t12") == [
        "payment_transaction_items", "/proc/incoming/payments"]
    assert learned_store.load_prephase_deep_read("t_none") == []
