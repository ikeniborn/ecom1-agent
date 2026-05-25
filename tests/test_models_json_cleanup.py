import json
from pathlib import Path


_MODELS = json.loads((Path(__file__).parent.parent / "models.json").read_text())


def test_no_profiles_section():
    assert "_profiles" not in _MODELS


def test_no_ollama_tuning_rationale():
    assert "_ollama_tuning_rationale" not in _MODELS


def test_no_dead_anthropic_opus46():
    assert "anthropic/claude-opus-4.6" not in _MODELS


def test_no_thinking_budget():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        assert "thinking_budget" not in cfg, f"{key} still has thinking_budget"


def test_no_ollama_variant_keys():
    dead = (
        "ollama_options_think",
        "ollama_options_longContext",
        "ollama_options_coder",
        "ollama_options_classifier",
        "ollama_options_evaluator",
    )
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        for dead_key in dead:
            assert dead_key not in cfg, f"{key} still has {dead_key}"


def test_no_cc_options_classifier():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        assert "cc_options_classifier" not in cfg, f"{key} still has cc_options_classifier"


def test_ollama_options_are_dicts():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        if "ollama_options" in cfg:
            assert isinstance(cfg["ollama_options"], dict), (
                f"{key}.ollama_options is a string, should be inlined dict"
            )


def test_cc_options_are_dicts():
    for key, cfg in _MODELS.items():
        if key.startswith("_"):
            continue
        if "cc_options" in cfg:
            assert isinstance(cfg["cc_options"], dict), (
                f"{key}.cc_options is a string, should be inlined dict"
            )


def test_cc_keys_versionless():
    assert "claude-code/haiku" in _MODELS
    assert "claude-code/sonnet" in _MODELS
    assert "claude-code/opus" in _MODELS
    assert "claude-code/haiku-4.5" not in _MODELS
    assert "claude-code/sonnet-4.6" not in _MODELS
    assert "claude-code/opus-4.7" not in _MODELS


def test_anthropic_opus47_mapping():
    from agent.llm import get_anthropic_model_id
    assert get_anthropic_model_id("anthropic/claude-opus-4.7") == "claude-opus-4-7"


def test_anthropic_opus46_mapping_removed():
    from agent.llm import _ANTHROPIC_MODEL_MAP
    assert "claude-opus-4.6" not in _ANTHROPIC_MODEL_MAP
