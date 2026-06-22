import yaml
from scripts.prune_inactive_rules import prune_entries


def test_prune_keeps_active_drops_inactive_unpinned():
    data = {
        "task_id": "tX",
        "entries": [
            {"id": "r1", "status": "active", "content": "keep me"},
            {"id": "r2", "status": "inactive", "content": "drop me"},
            {"id": "r3", "status": "inactive", "pinned": True, "content": "pinned survives"},
            {"id": "v1", "status": "active", "source": "verdict", "content": None},
        ],
        "last_run": {"status": "failure", "outcome": "X", "cycles_used": 2, "date": "2026-06-22"},
    }
    pruned, dropped = prune_entries(data)
    ids = [e["id"] for e in pruned["entries"]]
    assert ids == ["r1", "r3", "v1"]
    assert dropped == 1
    assert pruned["last_run"] == data["last_run"]
    assert pruned["task_id"] == "tX"


def test_prune_empty_entries_is_noop():
    data = {"task_id": "tY", "entries": []}
    pruned, dropped = prune_entries(data)
    assert dropped == 0
    assert pruned["entries"] == []
