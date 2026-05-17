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
    fake_unified = "# LEARNED\n\n# RULES\nrule1\n\n# SECURITY\nsec1\n\n# BASE\nbase"

    with patch("agent.prompt_assembler.call_llm_raw", return_value=fake_unified), \
         patch("agent.prompt_assembler._RULES_DIR", tmp_path / "rules"), \
         patch("agent.prompt_assembler._SECURITY_DIR", tmp_path / "security"), \
         patch("agent.prompt_assembler._LEARNED_DIR", tmp_path / "learned"):
        (tmp_path / "rules").mkdir()
        (tmp_path / "security").mkdir()
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


def test_assemble_loads_learned_ctx_from_file(tmp_path):
    pre = _make_pre()
    learned_dir = tmp_path / "learned"
    learned_dir.mkdir()
    import yaml
    (learned_dir / "t99.yaml").write_text(
        yaml.dump({"task_id": "t99", "learn_ctx": ["persisted rule"]}),
        encoding="utf-8",
    )

    calls = []
    def fake_llm(system, user_msg, model, cfg, **kw):
        calls.append(user_msg)
        return "# LEARNED\npersisted rule\n\n# RULES\n\n# SECURITY\n\n# BASE\n"

    with patch("agent.prompt_assembler.call_llm_raw", side_effect=fake_llm), \
         patch("agent.prompt_assembler._RULES_DIR", tmp_path / "rules"), \
         patch("agent.prompt_assembler._SECURITY_DIR", tmp_path / "security"), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir):
        (tmp_path / "rules").mkdir()
        (tmp_path / "security").mkdir()
        result = assemble_prompt(
            task_text="test task",
            task_type="sql",
            prephase_result=pre,
            learn_ctx=[],
            model="test-model",
            cfg={},
            task_id="t99",
        )

    assert "persisted rule" in calls[0]
