import agent.llm as llm


def test_resolve_model_cfg_returns_block_for_known_model():
    cfg = llm.resolve_model_cfg("claude-code/sonnet")
    assert cfg.get("cc_model") == "sonnet"
    assert cfg.get("cc_options", {}).get("cc_timeout_s") == 180


def test_resolve_model_cfg_empty_for_unknown_model():
    assert llm.resolve_model_cfg("no/such-model") == {}


def test_resolve_model_cfg_skips_underscore_docs():
    assert llm.resolve_model_cfg("_fields") == {}


def test_call_llm_raw_defaults_empty_cfg_from_models_json(monkeypatch):
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["cfg"] = cfg
        return "ok"

    monkeypatch.setattr(llm, "_call_raw_single_model", _fake_single)
    llm.call_llm_raw([], "u", "claude-code/sonnet", {}, max_tokens=8, phase="PLAN")
    assert captured["cfg"].get("cc_model") == "sonnet"
    assert captured["cfg"].get("cc_options", {}).get("cc_timeout_s") == 180


def test_call_llm_raw_keeps_explicit_cfg(monkeypatch):
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["cfg"] = cfg
        return "ok"

    monkeypatch.setattr(llm, "_call_raw_single_model", _fake_single)
    llm.call_llm_raw([], "u", "claude-code/sonnet", {"cc_model": "opus"},
                     max_tokens=8, phase="PLAN")
    assert captured["cfg"] == {"cc_model": "opus"}  # caller cfg wins, not overridden


def test_call_llm_raw_unknown_model_keeps_empty_cfg(monkeypatch):
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["cfg"] = cfg
        return "ok"

    monkeypatch.setattr(llm, "_call_raw_single_model", _fake_single)
    llm.call_llm_raw([], "u", "no/such-model", {}, max_tokens=8, phase="PLAN")
    assert captured["cfg"] == {}
