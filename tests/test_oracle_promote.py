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


_GREEN = [("t01", 1.0), ("t51", 1.0)]


def test_promote_when_green_held_and_source_improved():
    scores = {"t01": 1.0, "t51": 1.0, "t38": 0.8}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "promote"


def test_halt_when_green_dropped():
    scores = {"t01": 1.0, "t51": 0.6, "t38": 0.9}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "halt"


def test_no_improve_when_source_flat():
    scores = {"t01": 1.0, "t51": 1.0, "t38": 0.5}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "no_improve"


def test_missing_source_score_is_no_improve():
    scores = {"t01": 1.0, "t51": 1.0}
    assert promote_decision(scores, "t38", 0.0, _GREEN) == "no_improve"
