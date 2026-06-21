"""scripts/lint_report.py aggregates lint_fire telemetry across trace JSONL files."""
import json


def test_aggregate_counts(tmp_path):
    from scripts.lint_report import aggregate, render
    f1 = tmp_path / "t01.jsonl"
    f1.write_text("\n".join([
        json.dumps({"type": "lint_fire", "check_id": "chk_a", "kind": "primitive_contract",
                    "blocking": True, "task_id": "t01", "message": "m1"}),
        json.dumps({"type": "vm_call", "rpc": "Read"}),  # noise, ignored
        json.dumps({"type": "lint_fire", "check_id": "chk_a", "kind": "primitive_contract",
                    "blocking": False, "task_id": "t01", "message": "m1b"}),
    ]), encoding="utf-8")
    f2 = tmp_path / "t02.jsonl"
    f2.write_text(
        json.dumps({"type": "lint_fire", "check_id": "chk_a", "kind": "primitive_contract",
                    "blocking": True, "task_id": "t02", "message": "m2"}) + "\nGARBAGE LINE\n",
        encoding="utf-8")

    stats = aggregate(tmp_path)
    a = stats["chk_a"]
    assert a["fires"] == 3
    assert a["blocked"] == 2
    assert a["warned"] == 1
    assert len(a["tasks"]) == 2
    assert a["kind"] == "primitive_contract"

    text = render(stats)
    assert "chk_a" in text


def test_aggregate_empty_dir(tmp_path):
    from scripts.lint_report import aggregate, render
    assert render(aggregate(tmp_path)) == "no lint_fire records"
