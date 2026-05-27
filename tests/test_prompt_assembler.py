import pytest
from unittest.mock import patch
from agent.prompt_assembler import assemble_prompt, AssembledPrompt
from agent.prephase import PrephaseResult


def _make_pre():
    return PrephaseResult(
        agents_md_content="## vault\nsome rules",
        agents_md_index={"vault": ["some rules"]},
        schema_digest={"tables": {"products": {"columns": [{"name": "sku", "type": "TEXT"}], "fk": [], "role": "products"}}},
        db_schema="CREATE TABLE products (sku TEXT)",
        task_type="sql",
    )


def test_assemble_returns_assembled_prompt(tmp_path):
    pre = _make_pre()
    fake_unified = "# LEARNED\n\n# BASE\nbase"

    with patch("agent.prompt_assembler.call_llm_raw", return_value=fake_unified), \
         patch("agent.prompt_assembler._LEARNED_DIR", tmp_path / "learned"):
        (tmp_path / "learned").mkdir()
        result = assemble_prompt(
            task_text="find products with sku ABC",
            task_type="sql",
            prephase_result=pre,
            learn_ctx=["Never use ILIKE"],
            model="test-model",
            cfg={},
        )

    assert isinstance(result, AssembledPrompt)
    assert result.unified_context == fake_unified


def test_assemble_includes_learn_ctx_in_sources(tmp_path):
    pre = _make_pre()
    captured_sources = []

    def _capture_llm(system, user_msg, *args, **kwargs):
        captured_sources.append(user_msg)
        return "unified"

    with patch("agent.prompt_assembler.call_llm_raw", side_effect=_capture_llm), \
         patch("agent.prompt_assembler._LEARNED_DIR", tmp_path / "learned"):
        (tmp_path / "learned").mkdir()
        assemble_prompt(
            task_text="find skus",
            task_type="sql",
            prephase_result=pre,
            learn_ctx=["Always SELECT sku"],
            model="m",
            cfg={},
        )

    assert "Always SELECT sku" in captured_sources[0]
    assert "## LEARNED" in captured_sources[0]


def test_save_last_run_heuristic_valid(tmp_path, monkeypatch):
    from agent import prompt_assembler
    monkeypatch.setattr(prompt_assembler, "_LEARNED_DIR", tmp_path)
    prompt_assembler.save_last_run(
        task_id="t99",
        status="success",
        outcome="OUTCOME_OK",
        cycles_used=1,
        grounding_refs_count=2,
        heuristic_valid=True,
    )
    import yaml
    data = yaml.safe_load((tmp_path / "t99.yaml").read_text())
    assert data["last_run"]["heuristic_valid"] is True


def test_save_last_run_heuristic_valid_default_false(tmp_path, monkeypatch):
    from agent import prompt_assembler
    monkeypatch.setattr(prompt_assembler, "_LEARNED_DIR", tmp_path)
    prompt_assembler.save_last_run("t99", "failure", "OUTCOME_NONE_CLARIFICATION", 3)
    import yaml
    data = yaml.safe_load((tmp_path / "t99.yaml").read_text())
    assert data["last_run"]["heuristic_valid"] is False
