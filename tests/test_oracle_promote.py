import pytest
from agent.promote import load_green_suite, promote_decision


def test_load_green_suite(tmp_path):
    p = tmp_path / "green_suite.yaml"
    p.write_text(
        "- task_id: t01\n  reference: 1.0\n"
        "- task_id: t51\n  reference: 1.0\n"
    )
    suite = load_green_suite(p)
    assert suite == [("t01", 1.0), ("t51", 1.0)]


def test_load_green_suite_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_green_suite(tmp_path / "nope.yaml")
