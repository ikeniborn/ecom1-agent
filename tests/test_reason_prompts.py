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
    assert "ALWAYS cite both" not in g          # PLAN no longer authors refs
    assert "facts.policies" in g                # PLAN reads the eligibility rule


def test_ilearn_prompt_loads_and_is_planir_framed():
    from agent.prompt import load_prompt
    txt = load_prompt("ilearn")
    assert txt and "PLAN" in txt.upper()
    assert "prephase_deep_read" in txt
    assert "fidelity" not in txt.lower()           # no codegen framing


def test_plan_system_includes_tool_catalog(monkeypatch):
    import agent.reason as reason
    from agent.ir_models import AnswerShape, IntentSpec

    captured = {}

    def fake_raw(system, user, model, cfg, **kw):
        captured["system"] = system
        return '{"discovery": [], "decision": {"branches": [], "default_label": "d"}, ' \
               '"answer": {"d": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}}}'

    monkeypatch.setattr(reason, "_call_llm_raw", fake_raw)
    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape=AnswerShape())
    reason.run_plan(intent, None, [], None)
    sys_text = "\n".join(b["text"] for b in captured["system"])
    assert "TOOL CATALOG" in sys_text
    assert "Frobnicate" not in sys_text  # only catalog rpcs
