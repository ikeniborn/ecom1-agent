import json
from pathlib import Path

from agent import trace
from agent.trace import TraceLogger, current_step_type, set_step_type


def _records(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_seq_is_monotonic_and_global(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_header("task", "m")
    t.log_facts({"docs_inventory": "/d.md", "gather_status": {}})
    t.log_answer(1, "msg", "OUTCOME_OK", ["/d.md"])
    t.close()
    seqs = [r["seq"] for r in _records(p)]
    assert seqs == sorted(seqs)
    assert seqs == list(range(len(seqs)))


def test_step_type_thread_local_default_and_set():
    set_step_type("")
    assert current_step_type() == ""
    set_step_type("INTERPRET")
    assert current_step_type() == "INTERPRET"
    set_step_type("")


def test_llm_call_v2_fields(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    sysblk = [{"type": "text", "text": "SYS"}]
    t.log_llm_call("INTENT", 0, sysblk, "u1", "r1", None, 10, 5, 100)
    t.log_llm_call(
        "PLAN", 1, sysblk, "u2", "r2", {"ok": 1}, 20, 8, 200,
        reasoning="because X", raw_response_full="<think>because X</think>r2",
        cache_read=900, cache_creation=1200,
    )
    t.close()
    calls = [r for r in _records(p) if r["type"] == "llm_call"]
    a, b = calls
    assert a["step_type"] == "INTENT" and a["prev_llm_seq"] is None
    assert a["reasoning_available"] is False and a["reasoning"] == ""
    assert b["step_type"] == "PLAN" and b["prev_llm_seq"] == a["seq"]
    assert b["reasoning_available"] is True and b["reasoning"] == "because X"
    assert b["raw_response_full"].endswith("r2")
    assert b["cache_read"] == 900 and b["cache_creation"] == 1200


def test_no_llm_call_phase_is_literal_llm(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_llm_call("RERANK", 0, [{"type": "text", "text": "S"}], "u", "r", None, 1, 1, 1)
    t.close()
    rec = next(r for r in _records(p) if r["type"] == "llm_call")
    assert rec["phase"] != "llm"
    assert rec["step_type"] == "ORACLE_RETRIEVE"  # RERANK maps to ORACLE_RETRIEVE
