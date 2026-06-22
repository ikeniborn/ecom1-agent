import yaml
from scripts.prune_inactive_rules import prune_entries, prune_file


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


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_prune_file_dry_run_leaves_file_byte_identical(tmp_path):
    f = tmp_path / "t99.yaml"
    data = {
        "task_id": "t99",
        "entries": [
            {"id": "r1", "status": "active", "content": "keep"},
            {"id": "r2", "status": "inactive", "content": "drop"},
        ],
        "last_run": {"status": "failure", "outcome": "X", "cycles_used": 1, "date": "2026-06-22"},
    }
    _write_yaml(f, data)
    before = f.read_bytes()
    dropped = prune_file(f, dry_run=True)
    assert dropped == 1                      # reports what it WOULD drop
    assert f.read_bytes() == before          # but writes nothing in dry-run


def test_prune_file_writes_then_idempotent(tmp_path):
    f = tmp_path / "t98.yaml"
    data = {
        "task_id": "t98",
        "entries": [
            {"id": "r1", "status": "active", "content": "keep"},
            {"id": "r2", "status": "inactive", "content": "drop"},
            {"id": "r3", "status": "inactive", "pinned": True, "content": "pinned survives"},
        ],
    }
    _write_yaml(f, data)
    dropped = prune_file(f, dry_run=False)
    assert dropped == 1                       # only the unpinned inactive entry
    reloaded = yaml.safe_load(f.read_text(encoding="utf-8"))
    ids = [e["id"] for e in reloaded["entries"]]
    assert ids == ["r1", "r3"]                # active + pinned-inactive survive
    assert reloaded["task_id"] == "t98"       # metadata preserved
    # second run is a no-op (idempotent on disk)
    before = f.read_bytes()
    assert prune_file(f, dry_run=False) == 0
    assert f.read_bytes() == before
