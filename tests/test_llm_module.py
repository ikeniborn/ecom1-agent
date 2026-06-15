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
