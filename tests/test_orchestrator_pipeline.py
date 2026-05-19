# tests/test_orchestrator_pipeline.py
import importlib
import pytest
from unittest.mock import MagicMock, patch
from agent.orchestrator import run_agent


def _make_vm_mock():
    vm = MagicMock()
    agents_r = MagicMock(); agents_r.content = "AGENTS"
    exec_r = MagicMock(); exec_r.stdout = "CREATE TABLE products(...)"
    vm.read.return_value = agents_r
    vm.exec.return_value = exec_r
    return vm


def test_lookup_routes_to_pipeline():
    """run_agent calls run_pipeline for all tasks."""
    with patch("agent.orchestrator.EcomRuntimeClientSync", return_value=_make_vm_mock()), \
         patch("agent.orchestrator.run_pipeline") as mock_pipeline:
        mock_pipeline.return_value = (
            {
                "outcome": "OUTCOME_OK",
                "step_facts": [],
                "done_ops": [],
                "input_tokens": 10,
                "output_tokens": 5,
                "total_elapsed_ms": 100,
            },
            None,
        )
        result = run_agent({}, "http://localhost:9001", "How many Lawn Mowers?", "t01")

    mock_pipeline.assert_called_once()
    assert result["outcome"] == "OUTCOME_OK"
    assert result["task_type"] == "lookup"


def test_loop_module_deleted():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent.loop")


def test_run_agent_no_dead_stats():
    """run_agent() result must not contain builder_*/contract_*/eval_rejection_count fields."""
    with patch("agent.orchestrator.EcomRuntimeClientSync", return_value=_make_vm_mock()), \
         patch("agent.orchestrator.run_pipeline") as mock_pipeline:
        mock_pipeline.return_value = (
            {
                "outcome": "OUTCOME_OK",
                "step_facts": [],
                "done_ops": [],
                "input_tokens": 10,
                "output_tokens": 5,
                "total_elapsed_ms": 0,
            },
            None,
        )
        result = run_agent({}, "http://localhost:9001", "test", "t01")

    dead_keys = {"builder_used", "builder_in_tok", "builder_out_tok", "builder_addendum",
                 "contract_rounds_taken", "contract_is_default", "eval_rejection_count"}
    found = dead_keys & result.keys()
    assert not found, f"Dead stats keys found: {found}"


def test_write_wiki_fragment_removed():
    import agent.orchestrator as orch
    assert not hasattr(orch, "write_wiki_fragment"), "write_wiki_fragment should be removed"


def test_build_system_prompt_not_imported():
    import agent.orchestrator as orch
    assert not hasattr(orch, "build_system_prompt"), "build_system_prompt should not be in orchestrator"


def test_run_agent_returns_dict():
    """run_agent() always returns a plain dict (public API unchanged)."""
    import threading
    with patch("agent.orchestrator.EcomRuntimeClientSync", return_value=_make_vm_mock()), \
         patch("agent.orchestrator.run_pipeline") as mock_pipeline:
        mock_pipeline.return_value = (
            {
                "outcome": "OUTCOME_OK",
                "step_facts": [],
                "done_ops": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "total_elapsed_ms": 0,
            },
            None,
        )
        result = run_agent({}, "http://localhost:9001", "task", "t01")

    assert isinstance(result, dict)
    assert result["outcome"] == "OUTCOME_OK"


def test_run_agent_passes_injection_params():
    """run_agent forwards injection params + task_id to run_pipeline."""
    mock_pre = MagicMock()
    mock_pre.agents_md_content = ""
    mock_pre.agents_md_index = {}
    mock_pre.db_schema = ""
    mock_pre.schema_digest = {"tables": {}}

    with patch("agent.orchestrator.EcomRuntimeClientSync"), \
         patch("agent.orchestrator.run_prephase", return_value=mock_pre), \
         patch("agent.orchestrator.run_pipeline", return_value=(
             {"outcome": "OUTCOME_OK", "cycles_used": 1, "step_facts": [],
              "done_ops": [], "input_tokens": 0, "output_tokens": 0, "total_elapsed_ms": 0},
             None,
         )) as mock_pipeline:
        run_agent(
            model_configs={},
            harness_url="http://localhost",
            task_text="test",
            task_id="t01",
            injected_session_rules=["rule1"],
            injected_prompt_addendum="addon",
        )
    _args, kwargs = mock_pipeline.call_args
    assert kwargs["task_id"] == "t01"
    assert kwargs["injected_session_rules"] == ["rule1"]
    assert kwargs["injected_prompt_addendum"] == "addon"
