import os


def test_dispatch_module_deleted():
    import importlib
    import pytest
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agent.dispatch")


def test_llm_module_exports():
    from agent.llm import call_llm_raw, OUTCOME_BY_NAME
    assert callable(call_llm_raw)
    assert "OUTCOME_OK" in OUTCOME_BY_NAME


def test_llm_exports_cli_colors():
    from agent.llm import CLI_RED, CLI_GREEN, CLI_CLR, CLI_BLUE, CLI_YELLOW
    assert CLI_CLR == "\x1B[0m"


def test_dispatch_function_removed():
    import agent.llm as llm
    assert not hasattr(llm, "dispatch"), "dispatch() should be removed from llm.py"


def test_system_as_str_from_blocks():
    """_system_as_str flattens list[dict] blocks to newline-joined text."""
    from agent.llm import _system_as_str
    blocks = [
        {"type": "text", "text": "block one"},
        {"type": "text", "text": "block two", "cache_control": {"type": "ephemeral"}},
    ]
    result = _system_as_str(blocks)
    assert "block one" in result
    assert "block two" in result


def test_system_as_str_passthrough_str():
    """_system_as_str returns str unchanged."""
    from agent.llm import _system_as_str
    assert _system_as_str("plain text") == "plain text"


def test_ollama_key_constant_exists_and_fallback():
    """_OLLAMA_KEY attribute must exist on module and use or-fallback logic."""
    import agent.llm as llm_mod

    # Attribute must exist — fails before Task 2 implementation
    assert hasattr(llm_mod, "_OLLAMA_KEY"), "_OLLAMA_KEY not defined in agent.llm"

    # Value must match or-fallback of current env
    expected = os.environ.get("OLLAMA_API_KEY") or "ollama"
    assert llm_mod._OLLAMA_KEY == expected


def test_resolve_model_for_phase_uses_env(monkeypatch):
    import agent.llm as llm
    monkeypatch.setitem(llm._PHASE_MODEL_MAP, "design", "anthropic/claude-haiku-4-5-20251001")
    result = llm._resolve_model_for_phase("design", "anthropic/claude-sonnet-4-6")
    assert result == "anthropic/claude-haiku-4-5-20251001"


def test_resolve_model_for_phase_falls_back_to_default(monkeypatch):
    import agent.llm as llm
    monkeypatch.setitem(llm._PHASE_MODEL_MAP, "design", None)
    result = llm._resolve_model_for_phase("design", "anthropic/claude-sonnet-4-6")
    assert result == "anthropic/claude-sonnet-4-6"


def test_resolve_model_for_phase_unknown_phase(monkeypatch):
    import agent.llm as llm
    result = llm._resolve_model_for_phase("unknown_phase", "anthropic/claude-sonnet-4-6")
    assert result == "anthropic/claude-sonnet-4-6"


def test_resolve_codegen_phase_uses_model_codegen(monkeypatch):
    import os
    monkeypatch.setenv("MODEL_CODEGEN", "anthropic/claude-haiku-4-5-20251001")
    import importlib
    import agent.llm as llm_mod
    importlib.reload(llm_mod)
    result = llm_mod._resolve_model_for_phase("codegen", "anthropic/claude-sonnet-4-6")
    assert result == "anthropic/claude-haiku-4-5-20251001"
