import json
from unittest.mock import MagicMock, patch

from agent.pipeline import run_pipeline
from tests.test_pipeline import (
    _make_pre, _mock_assemble, _seq_llm,
    _plan_json, _learn_json, _sdd_json, _idd_json, _codegen_json,
)


def _failing_codegen_json():
    """CODEGEN response that passes lint but script raises at runtime."""
    script = "raise RuntimeError('bad action at runtime')"
    return json.dumps({"script": script, "test": "assert True"})


def test_pipeline_retries_on_exec_runtime_error():
    """Script raises at runtime → pipeline routes to LEARN → retry with working script → success."""
    vm = MagicMock()
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([
             _idd_json(),              # IDD cycle 1
             _sdd_json(),              # SDD cycle 1
             _plan_json(),             # PLAN cycle 1
             _failing_codegen_json(),  # CODEGEN cycle 1: script raises at runtime → LEARN
             _learn_json(),            # LEARN cycle 1
             _idd_json(),              # IDD cycle 2
             _sdd_json(),              # SDD cycle 2
             _plan_json(),             # PLAN cycle 2
             _codegen_json(),          # CODEGEN cycle 2: success
         ])), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None), \
         patch("agent.pipeline.load_learned_entries", return_value=[]), \
         patch("agent.pipeline.load_learned_ctx", return_value=[]):
        stats, _ = run_pipeline(vm, "model", "task", pre, {}, task_id="t99")

    assert stats["outcome"] == "OUTCOME_OK"
