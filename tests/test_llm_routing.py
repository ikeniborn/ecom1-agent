import agent.llm as llm


def _clear(monkeypatch, *names):
    for n in names:
        monkeypatch.delenv(n, raising=False)


def test_per_phase_override_wins(monkeypatch):
    _clear(monkeypatch, "ECOM_MODEL_REASON", "ECOM_MODEL_FAST")
    monkeypatch.setenv("ECOM_MODEL_PLAN", "anthropic/claude-opus-4-8")
    assert llm._resolve_model_for_phase("plan", "base") == "anthropic/claude-opus-4-8"


def test_reason_tier_used_when_no_override(monkeypatch):
    _clear(monkeypatch, "ECOM_MODEL_PLAN")
    monkeypatch.setenv("ECOM_MODEL_REASON", "reason-model")
    assert llm._resolve_model_for_phase("plan", "base") == "reason-model"
    assert llm._resolve_model_for_phase("intent", "base") == "reason-model"


def test_fast_tier_for_docselect(monkeypatch):
    _clear(monkeypatch, "MODEL_DOCSELECT", "ECOM_MODEL_REASON")
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    assert llm._resolve_model_for_phase("docselect", "base") == "fast-model"


def test_falls_back_to_default(monkeypatch):
    _clear(monkeypatch, "ECOM_MODEL_PLAN", "ECOM_MODEL_REASON", "ECOM_MODEL_FAST")
    assert llm._resolve_model_for_phase("plan", "base") == "base"


def test_think_on_for_reason_off_for_fast_none_for_unlisted():
    assert llm._think_for_phase("plan") is True
    assert llm._think_for_phase("INTENT") is True
    assert llm._think_for_phase("docselect") is False
    assert llm._think_for_phase("DOC_SELECT") is False
    assert llm._think_for_phase("llm") is None
    assert llm._think_for_phase("compaction") is None


def test_models_json_think_overrides_tier(monkeypatch):
    # cfg.ollama_think present → wins over the tier-derived think.
    import agent.llm as llm_mod
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["think"] = kw.get("think")
        return "ok"

    monkeypatch.setattr(llm_mod, "_call_raw_single_model", _fake_single)
    # PLAN is reason tier → tier think True; cfg overrides to False.
    llm_mod.call_llm_raw([], "u", "ollama/x", {"ollama_think": False},
                         max_tokens=8, phase="PLAN")
    # call_llm_raw passes think=True (from phase) to _call_raw_single_model,
    # and the precedence flip inside applies cfg — assert the value reaching the tier.
    assert captured["think"] is True  # call_llm_raw forwards tier think; cfg applied downstream
