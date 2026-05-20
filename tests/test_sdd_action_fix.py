import json
from unittest.mock import MagicMock, patch

from agent.pipeline import run_pipeline
from tests.test_pipeline import (
    _make_pre, _mock_assemble, _seq_llm,
    _plan_json, _learn_json, _answer_json, _sdd_json,
    _make_exec_result,
)


def _nl_sdd_json():
    return json.dumps({
        "spec_goal": "list payment files",
        "success_criteria": ["files listed"],
        "plan": ["list files in payments dir"],
        "actions": ["List the payment record files in proc/payments/ directory,"],
        "error_code": "",
    })


def test_pipeline_retries_when_sdd_emits_prose_action():
    """Natural-language action → plan picks SQL → empty result → LEARN → retry → success.

    The NL prose action in SDD output causes no useful result. PLAN still picks a SQL
    action (since PLAN is mocked), which returns empty → triggers LEARN → retry → success.
    This tests that a cycle with a bad SDD output (prose action) feeds into LEARN and retries.
    """
    vm = MagicMock()
    # Cycle 1: PLAN picks SQL → EXPLAIN(empty) + SQL exec(empty) → empty result → LEARN
    # Cycle 2: valid SQL → EXPLAIN(ok) + SQL exec(data) → success
    vm.exec.side_effect = [
        _make_exec_result(""),               # cycle 1: EXPLAIN (passes, empty ok)
        _make_exec_result(""),               # cycle 1: SQL exec, empty result → LEARN
        _make_exec_result("ok"),             # cycle 2: EXPLAIN
        _make_exec_result('[{"count":3}]'),  # cycle 2: SQL exec → success
    ]
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([
             _nl_sdd_json(),   # SDD cycle 1: prose action
             _plan_json(),     # PLAN cycle 1
             _learn_json(),    # LEARN cycle 1 (empty result)
             _sdd_json(),      # SDD cycle 2: valid SQL action
             _plan_json(),     # PLAN cycle 2
             _answer_json(),   # ANSWER cycle 2
         ])), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None), \
         patch("agent.pipeline.load_learned_entries", return_value=[]), \
         patch("agent.pipeline.load_learned_ctx", return_value=[]):
        stats, _ = run_pipeline(vm, "model", "task", pre, {}, task_id="t99")

    assert stats["outcome"] != "OUTCOME_NONE_CLARIFICATION"
