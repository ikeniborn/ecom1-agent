from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import main
import agent.learned_store as learned_store
from bitgn.harness_pb2 import TRIAL_STATE_DONE


@pytest.fixture
def patch_store(tmp_path, monkeypatch):
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.setattr(main, "save_last_run", learned_store.save_last_run)
    monkeypatch.setattr(main, "write_verdict", learned_store.write_verdict)
    return tmp_path


def _trial(task_id, score, detail, available=True):
    return SimpleNamespace(
        task_id=task_id,
        score=score,
        score_available=available,
        score_detail=detail,
        state=TRIAL_STATE_DONE,
    )


def test_settle_writes_verdict_on_failure(patch_store, monkeypatch):
    import yaml
    monkeypatch.setattr(main, "_finalize_task_trace", lambda *a, **k: None)
    token_stats = {
        "outcome": "OUTCOME_OK",
        "cycles_used": 2,
        "answer_message": "Found 1 basket.",
        "answer_refs": ["ref://basket/42"],
    }
    # pending shape: {task_id: (trial_id, task_elapsed, token_stats, trace)}
    pending = {"t10": ("trial-1", 1.5, token_stats, None)}
    submit = SimpleNamespace(trials=[_trial("t10", 0.5, ["wrong total: expected 3, got 1"])])

    main._settle_scores(submit, pending)

    data = yaml.safe_load((patch_store / "t10.yaml").read_text())
    verdicts = [e for e in data["entries"] if e.get("source") == "verdict"]
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["score"] == 0.5
    assert v["score_detail"] == ["wrong total: expected 3, got 1"]
    assert v["submitted_message"] == "Found 1 basket."
    assert v["submitted_outcome"] == "OUTCOME_OK"
    assert v["submitted_refs"] == ["ref://basket/42"]


def test_settle_no_verdict_on_perfect_score(patch_store, monkeypatch):
    monkeypatch.setattr(main, "_finalize_task_trace", lambda *a, **k: None)
    pending = {"t10": ("trial-1", 1.5, {"outcome": "OUTCOME_OK", "cycles_used": 1}, None)}
    submit = SimpleNamespace(trials=[_trial("t10", 1.0, [])])

    main._settle_scores(submit, pending)

    assert not (patch_store / "t10.yaml").exists()
