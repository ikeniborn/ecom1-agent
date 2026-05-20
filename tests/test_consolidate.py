import json
from unittest.mock import MagicMock, patch, call

from agent.pipeline import _run_consolidate


def _consolidate_skip_json():
    return json.dumps({
        "skip": True,
        "skip_reason": "all rules distinct",
        "consolidations": [],
    })


def _consolidate_merge_json(deactivate=None, merged_rule="merged content"):
    return json.dumps({
        "skip": False,
        "skip_reason": None,
        "consolidations": [
            {
                "deactivate": deactivate or ["r002", "r003"],
                "merged_rule": merged_rule,
                "merged_reasoning": "r002 and r003 are duplicates",
            }
        ],
    })


def _make_entry(eid, content, status="active"):
    return {"id": eid, "content": content, "status": status}


def test_run_consolidate_fewer_than_2_active_skips_llm():
    """With 1 active entry, no LLM call made."""
    entries = [_make_entry("r001", "only rule")]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw") as mock_llm:
        _run_consolidate("mocked-ctx", "model", {}, "t01", ["only rule"], cycle=1)

    mock_llm.assert_not_called()


def test_run_consolidate_zero_active_skips_llm():
    """With 0 active entries, no LLM call made."""
    entries = [_make_entry("r001", "rule", status="inactive")]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw") as mock_llm:
        _run_consolidate("mocked-ctx", "model", {}, "t01", [], cycle=1)

    mock_llm.assert_not_called()


def test_run_consolidate_skip_true_no_apply():
    """LLM returns skip=true → _apply_learn_diff not called, learn_ctx unchanged."""
    entries = [
        _make_entry("r002", "rule A"),
        _make_entry("r003", "rule B"),
    ]
    learn_ctx = ["rule A", "rule B"]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw", return_value=_consolidate_skip_json()), \
         patch("agent.pipeline._apply_learn_diff") as mock_apply:
        _run_consolidate("ctx", "model", {}, "t01", learn_ctx, cycle=1)

    mock_apply.assert_not_called()
    assert learn_ctx == ["rule A", "rule B"]


def test_run_consolidate_merges_rules():
    """LLM returns consolidation → _apply_learn_diff called, learn_ctx reduced."""
    entries = [
        _make_entry("r002", "rule A"),
        _make_entry("r003", "rule B"),
        _make_entry("r007", "rule C"),
    ]
    learn_ctx = ["rule A", "rule B", "rule C"]

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw", return_value=_consolidate_merge_json(
             deactivate=["r002", "r003"], merged_rule="merged rule",
         )), \
         patch("agent.pipeline._apply_learn_diff") as mock_apply:
        _run_consolidate("ctx", "model", {}, "t01", learn_ctx, cycle=1)

    mock_apply.assert_called_once()
    call_args = mock_apply.call_args[0]
    assert call_args[0] == "t01"           # task_id
    assert call_args[1] == "merged rule"   # merged_rule
    assert call_args[3] == ["r002", "r003"]  # deactivate list
    # learn_ctx: rule A and rule B removed, merged rule added
    assert "rule A" not in learn_ctx
    assert "rule B" not in learn_ctx
    assert "merged rule" in learn_ctx
    assert "rule C" in learn_ctx           # untouched entry remains


def test_run_consolidate_empty_merged_rule_skips_item():
    """Consolidation item with empty merged_rule is silently skipped."""
    entries = [_make_entry("r001", "A"), _make_entry("r002", "B")]

    bad_json = json.dumps({
        "skip": False,
        "skip_reason": None,
        "consolidations": [{"deactivate": ["r001"], "merged_rule": "", "merged_reasoning": "bad"}],
    })

    with patch("agent.pipeline.load_learned_entries", return_value=entries), \
         patch("agent.pipeline.call_llm_raw", return_value=bad_json), \
         patch("agent.pipeline._apply_learn_diff") as mock_apply:
        _run_consolidate("ctx", "model", {}, "t01", ["A", "B"], cycle=1)

    mock_apply.assert_not_called()
