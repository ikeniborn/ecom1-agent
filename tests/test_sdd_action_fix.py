import json
from unittest.mock import MagicMock, patch

from agent.pipeline import run_pipeline
from tests.test_pipeline import (
    _make_pre, _mock_assemble, _seq_llm,
    _plan_json, _learn_json, _answer_json, _sdd_json, _idd_json,
    _make_exec_result,
)


def _failing_exec_sdd_json():
    return json.dumps({
        "spec_goal": "list payment files",
        "success_criteria": ["files listed"],
        "plan": ["list files in payments dir"],
        "actions": ["/bin/xyznotacommand"],
        "error_code": "",
    })


def test_pipeline_retries_on_exec_runtime_error():
    """Exec action fails at runtime → pipeline routes to LEARN → retry with SQL action → success."""
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
             _idd_json(),               # IDD cycle 1
             _failing_exec_sdd_json(),  # SDD cycle 1: exec action that fails at runtime
             _plan_json(),              # PLAN cycle 1
             _learn_json(),             # LEARN cycle 1 (empty result)
             _idd_json(),               # IDD cycle 2
             _sdd_json(),               # SDD cycle 2: valid SQL action
             _plan_json(),              # PLAN cycle 2
             _answer_json(),            # ANSWER cycle 2
         ])), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None), \
         patch("agent.pipeline.load_learned_entries", return_value=[]), \
         patch("agent.pipeline.load_learned_ctx", return_value=[]):
        stats, _ = run_pipeline(vm, "model", "task", pre, {}, task_id="t99")

    assert stats["outcome"] == "OUTCOME_OK"
