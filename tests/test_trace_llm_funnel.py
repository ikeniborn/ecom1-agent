"""call_llm_raw funnel must mirror every LLM call (system/user/assistant) into the
active TraceLogger as an `llm_call` record. This is the single hook that makes
per-task traces show the prompts sent and the model's reply."""
import json
from pathlib import Path

import agent.llm as llm
from agent.trace import TraceLogger, current_cycle, set_cycle, set_trace


def _records(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_call_llm_raw_logs_user_and_assistant(tmp_path, monkeypatch):
    def fake_single(system, user_msg, model, cfg, **kw):
        tok = kw.get("token_out")
        if tok is not None:
            tok["input"] = 11
            tok["output"] = 7
        return "ASSISTANT REPLY"

    monkeypatch.setattr(llm, "_call_raw_single_model", fake_single)
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    set_trace(t)
    set_cycle(2)
    try:
        out = llm.call_llm_raw(
            [{"type": "text", "text": "SYS"}], "USER MSG", "m", {}, phase="DESIGN"
        )
    finally:
        set_trace(None)
        set_cycle(0)
        t.close()

    assert out == "ASSISTANT REPLY"
    recs = _records(p)
    call = next(r for r in recs if r["type"] == "llm_call")
    assert call["phase"] == "DESIGN"
    assert call["cycle"] == 2
    assert call["user_msg"] == "USER MSG"
    assert call["raw_response"] == "ASSISTANT REPLY"
    assert call["tokens_in"] == 11 and call["tokens_out"] == 7
    assert call["success"] is True
    # system prompt captured once via header_system dedup
    assert any(r["type"] == "header_system" for r in recs)


def test_call_llm_raw_no_trace_is_noop(monkeypatch):
    monkeypatch.setattr(llm, "_call_raw_single_model", lambda *a, **k: "x")
    set_trace(None)
    assert llm.call_llm_raw("s", "u", "m", {}) == "x"


def test_current_cycle_defaults_zero():
    set_cycle(0)
    assert current_cycle() == 0
