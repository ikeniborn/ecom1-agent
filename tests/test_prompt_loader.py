# tests/test_prompt_loader.py
from agent.prompt import load_prompt, load_task_blocks


def test_load_prompt_unknown_returns_empty():
    assert load_prompt("nonexistent_block_xyz") == ""


def test_load_task_blocks_returns_list():
    blocks = load_task_blocks("default")
    assert isinstance(blocks, list)


def test_load_task_blocks_unknown_falls_back_to_default():
    blocks = load_task_blocks("unknown_type_xyz")
    default_blocks = load_task_blocks("default")
    assert blocks == default_blocks


def test_load_prompt_sdd_exists():
    text = load_prompt("sdd")
    assert len(text) > 50


def test_load_prompt_assembler_exists():
    text = load_prompt("assembler")
    assert len(text) > 50


def test_load_task_blocks_sql_returns_list():
    blocks = load_task_blocks("sql")
    assert isinstance(blocks, list)


def test_load_prompt_learn_exists():
    text = load_prompt("learn")
    assert len(text) > 50


def test_load_prompt_answer_exists():
    text = load_prompt("answer")
    assert len(text) > 50


def test_load_prompt_pipeline_evaluator_exists():
    text = load_prompt("pipeline_evaluator")
    assert len(text) > 50


def test_email_prompt_not_loaded():
    assert load_prompt("email") == ""


def test_inbox_prompt_not_loaded():
    assert load_prompt("inbox") == ""


def test_task_blocks_yaml_has_no_email_inbox():
    import yaml
    from pathlib import Path
    cfg_file = Path(__file__).parent.parent / "data" / "config" / "task_blocks.yaml"
    if cfg_file.exists():
        cfg = yaml.safe_load(cfg_file.read_text()) or {}
        assert "email" not in cfg
        assert "inbox" not in cfg
        assert "queue" not in cfg
