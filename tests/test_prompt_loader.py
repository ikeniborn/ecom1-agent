from agent.prompt import load_prompt


def test_intent_prompt_loaded():
    txt = load_prompt("intent")
    assert "INTENT" in txt
    assert "IntentSpec" in txt


def test_plan_prompt_loaded():
    txt = load_prompt("plan")
    assert "PLAN" in txt
    assert "PlanIR" in txt


def test_ilearn_prompt_loaded():
    txt = load_prompt("ilearn")
    assert "LEARN" in txt
    assert "rule_content" in txt


def test_learn_prompt_loaded():
    txt = load_prompt("learn")
    assert "LEARN" in txt
    assert "rule_content" in txt


def test_compact_prompt_loaded():
    txt = load_prompt("compact")
    assert "COMPACT" in txt


def test_deleted_prompts_absent():
    for name in ("design", "codegen", "test", "idd", "sdd",
                 "assembler", "tdd", "answer", "consolidate"):
        assert load_prompt(name) == "", f"{name} prompt must be deleted"
