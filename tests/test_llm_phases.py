import importlib


def test_plan_phase_resolves_to_default(monkeypatch):
    monkeypatch.delenv("MODEL_PLAN", raising=False)
    import agent.llm as llm_mod
    importlib.reload(llm_mod)
    result = llm_mod._resolve_model_for_phase("plan", "anthropic/claude-sonnet-4-6")
    assert result == "anthropic/claude-sonnet-4-6"


def test_plan_phase_resolves_to_override(monkeypatch):
    monkeypatch.setenv("MODEL_PLAN", "anthropic/claude-opus-4-7")
    import agent.llm as llm_mod
    importlib.reload(llm_mod)
    result = llm_mod._resolve_model_for_phase("plan", "anthropic/claude-sonnet-4-6")
    assert result == "anthropic/claude-opus-4-7"
