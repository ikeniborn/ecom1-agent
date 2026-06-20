# tests/test_investigate.py
import os
from agent.llm import _resolve_model_for_phase, _think_for_phase


def test_investigate_phase_is_fast_tier(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.delenv("ECOM_MODEL_INVESTIGATE", raising=False)
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "fast-model"
    assert _think_for_phase("INVESTIGATE") is False


def test_investigate_phase_override_wins(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.setenv("ECOM_MODEL_INVESTIGATE", "explicit-model")
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "explicit-model"
