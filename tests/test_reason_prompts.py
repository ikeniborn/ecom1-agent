# tests/test_reason_prompts.py
from agent.prompt import load_prompt


def test_intent_prompt_loads_and_is_general():
    g = load_prompt("intent")
    assert g and "IntentSpec" in g
    assert "required_refs" in g            # new per-outcome ref contract
    assert "required_ref_kinds" not in g   # old flat field removed
    for banned in ("basket_069", "Non-Bladed", "service_recovery"):
        assert banned not in g


def test_plan_prompt_loads_and_documents_ir():
    g = load_prompt("plan")
    assert g and "PlanIR" in g and "decision" in g and "discovery" in g
