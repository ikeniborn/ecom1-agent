import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.pipeline import run_pipeline
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt


def _make_pre():
    return PrephaseResult(
        agents_md_content="AGENTS",
        agents_md_path="/AGENTS.MD",
        db_schema="CREATE TABLE orders(id INT, status TEXT)",
        task_type="sql",
    )


def _mock_assemble(*_a, **_kw):
    return AssembledPrompt(unified_context="mocked-context")


_VALID_SCRIPT = """
_result = {"message": "3 orders", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
"""


def test_fast_path_skips_llm_when_heuristic_valid(tmp_path, monkeypatch):
    """Fast path: existing script + heuristic_valid=True → 0 LLM calls, vm.answer called."""
    vm = MagicMock()
    pre = _make_pre()
    task_id = "t_fp_01"

    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)
    (heur_dir / f"{task_id}.py").write_text(_VALID_SCRIPT)

    last_run_data = {
        "task_id": task_id,
        "last_run": {"status": "success", "outcome": "OUTCOME_OK", "cycles_used": 1,
                     "grounding_refs_count": 0, "heuristic_valid": True, "date": "2026-05-27"},
        "entries": [],
    }
    import yaml
    learned_dir = tmp_path / "data" / "learned"
    learned_dir.mkdir(parents=True)
    (learned_dir / f"{task_id}.yaml").write_text(
        yaml.dump(last_run_data, allow_unicode=True)
    )

    # Change cwd so Path("data") resolves into tmp_path
    monkeypatch.chdir(tmp_path)

    with patch("agent.pipeline.call_llm_raw") as mock_llm, \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir):

        stats, _ = run_pipeline(
            vm=vm,
            model="anthropic/claude-sonnet-4-6",
            task_text="How many orders?",
            pre=pre,
            cfg={},
            task_id=task_id,
        )

    mock_llm.assert_not_called()
    vm.answer.assert_called_once()
    assert stats["outcome"] == "OUTCOME_OK"


def test_fast_path_failure_falls_through_to_full_path(tmp_path, monkeypatch):
    """Fast path script raises → fall through to full path immediately (same run)."""
    vm = MagicMock()
    pre = _make_pre()
    task_id = "t_fp_02"

    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)
    (heur_dir / f"{task_id}.py").write_text("raise RuntimeError('broken')")

    last_run_data = {
        "task_id": task_id,
        "last_run": {"status": "success", "outcome": "OUTCOME_OK", "cycles_used": 1,
                     "grounding_refs_count": 0, "heuristic_valid": True, "date": "2026-05-27"},
        "entries": [],
    }
    import yaml
    learned_dir = tmp_path / "data" / "learned"
    learned_dir.mkdir(parents=True)
    (learned_dir / f"{task_id}.yaml").write_text(
        yaml.dump(last_run_data, allow_unicode=True)
    )

    def _idd_json():
        return json.dumps({
            "intent_objective": "count", "reformulated_task": "How many orders?",
            "intent_type": "read", "extracted_params": {}, "success_criteria": ["positive int"],
            "stop_rules": [], "health_metrics": [], "decision": "proceed",
            "stop_code": "", "stop_message": "", "stop_refs": [], "reasoning": "",
        })

    def _sdd_json():
        return json.dumps({
            "spec_goal": "count", "success_criteria": ["positive int"],
            "plan": ["query"], "actions": ["SELECT COUNT(*) FROM orders"], "error_code": "",
        })

    def _plan_json():
        return json.dumps({"approach": "count", "steps": ["run query"],
                           "action": "SELECT COUNT(*) FROM orders"})

    _GOOD_SCRIPT_FULL = '''
_result = {"message": "5 orders", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
'''
    _CODEGEN_JSON = json.dumps({"script": _GOOD_SCRIPT_FULL, "test": "assert True"})

    llm_responses = [_idd_json(), _sdd_json(), _plan_json(), _CODEGEN_JSON]
    llm_iter = iter(llm_responses)

    # Change cwd so Path("data") resolves into tmp_path
    monkeypatch.chdir(tmp_path)

    with patch("agent.pipeline.call_llm_raw", side_effect=lambda *a, **kw: next(llm_iter)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir):

        stats, _ = run_pipeline(
            vm=vm,
            model="anthropic/claude-sonnet-4-6",
            task_text="How many orders?",
            pre=pre,
            cfg={},
            task_id=task_id,
        )

    assert vm.answer.call_count >= 1


def test_fast_path_not_eligible_when_heuristic_invalid(tmp_path):
    """heuristic_valid=False → skip fast path, run full pipeline."""
    vm = MagicMock()
    pre = _make_pre()
    task_id = "t_fp_03"

    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)
    (heur_dir / f"{task_id}.py").write_text(_VALID_SCRIPT)

    last_run_data = {
        "task_id": task_id,
        "last_run": {"status": "failure", "outcome": "OUTCOME_NONE_CLARIFICATION",
                     "cycles_used": 3, "grounding_refs_count": 0,
                     "heuristic_valid": False, "date": "2026-05-27"},
        "entries": [],
    }
    import yaml
    learned_dir = tmp_path / "data" / "learned"
    learned_dir.mkdir(parents=True)
    (learned_dir / f"{task_id}.yaml").write_text(
        yaml.dump(last_run_data, allow_unicode=True)
    )

    llm_calls: list[str] = []

    def _tracking_llm(*a, **kw):
        llm_calls.append("called")
        return json.dumps({
            "intent_objective": "x", "reformulated_task": "y", "intent_type": "read",
            "extracted_params": {}, "success_criteria": ["z"], "stop_rules": [],
            "health_metrics": [], "decision": "hard_stop",
            "stop_code": "OUTCOME_NONE_CLARIFICATION",
            "stop_message": "not enough data", "stop_refs": [], "reasoning": "",
        })

    with patch("agent.pipeline.call_llm_raw", side_effect=_tracking_llm), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir):

        run_pipeline(
            vm=vm, model="anthropic/claude-sonnet-4-6",
            task_text="How many orders?", pre=pre, cfg={}, task_id=task_id,
        )

    assert len(llm_calls) > 0, "Full path should have run LLM calls"
