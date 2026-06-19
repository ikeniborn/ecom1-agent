import yaml
from agent import learned_store
from agent.models import LearnConsolidateOutput


def _add(tid, c):
    learned_store.apply_learn_diff(
        tid, LearnConsolidateOutput(rule_content=c, reasoning="r", deactivate_ids=[], skip=False),
        surface="ir")


def test_cap_keeps_newest_unpinned(tmp_path, monkeypatch):
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.setenv("ECOM_LEARN_MAX_ACTIVE", "2")
    _add("tX", "Always do A correctly for this particular test case")
    _add("tX", "Always do B correctly for this particular test case")
    _add("tX", "Always do C correctly for this particular test case")  # cap 2 -> A dropped
    act = [e for e in learned_store.load_entries("tX") if e.get("content")]
    txt = " ".join(e["content"] for e in act)
    assert len(act) == 2 and "do C" in txt and "do B" in txt and "do A" not in txt


def test_cap_exempts_pinned(tmp_path, monkeypatch):
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.setenv("ECOM_LEARN_MAX_ACTIVE", "1")
    (tmp_path / "tY.yaml").write_text(yaml.dump({"task_id": "tY", "entries": [{
        "id": "rc1", "content": "Always keep me — pinned authoritative rule for the task",
        "status": "active", "pinned": True, "surface": "ir", "created": "2026-06-19",
        "reasoning": "x", "agents_md_anchor": None, "deactivated_reason": None}]}))
    _add("tY", "Always add a noisy newer rule that should not evict the pinned one")
    ids = {e["id"] for e in learned_store.load_entries("tY") if e.get("content")}
    assert "rc1" in ids   # pinned survives cap=1 even with a newer rule
