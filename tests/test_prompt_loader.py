from agent.prompt import load_prompt


def test_design_prompt_loaded():
    txt = load_prompt("design")
    assert "DESIGN" in txt
    assert "tool_plan" in txt or "tool plan" in txt.lower()


def test_codegen_prompt_loaded():
    txt = load_prompt("codegen")
    assert "CODEGEN" in txt
    assert "script_code" in txt


def test_learn_prompt_loaded():
    txt = load_prompt("learn")
    assert "LEARN" in txt
    assert "rule_content" in txt


def test_deleted_prompts_absent():
    for name in ("idd", "sdd", "plan", "assembler", "tdd", "answer", "consolidate"):
        assert load_prompt(name) == "", f"{name} prompt must be deleted"
