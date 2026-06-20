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


def test_vm_call_v2_fields(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_vm_call(1, "INTERPRET", "Exec",
                  {"path": "/bin/sql", "args": ["SELECT 1"]},
                  "n\n1\n", mutated=False, validation="ok", duration_ms=12)
    t.log_vm_call(2, "INTERPRET", "Exec",
                  {"path": "/bin/sql", "stdin": "SELECT 1"},
                  "", mutated=False, validation="fail(rpc 'Foo' not in catalog)")
    t.close()
    recs = [r for r in _records(p) if r["type"] == "vm_call"]
    ok, bad = recs
    assert ok["step_type"] == "INTERPRET" and ok["phase"] == "INTERPRET"
    assert ok["validation"] == "ok" and ok["has_data"] is True
    assert ok["bytes"] == len("n\n1\n") and ok["duration_ms"] == 12
    assert bad["has_data"] is False and bad["validation"].startswith("fail(")


def test_gate_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_gate(1, "LINT", True, "")
    t.log_gate(2, "VERIFY", False, "I1: unresolved refs")
    t.close()
    g = [r for r in _records(p) if r["type"] == "gate"]
    assert g[0]["step_type"] == "LINT" and g[0]["passed"] is True
    assert g[1]["step_type"] == "VERIFY" and g[1]["passed"] is False
    assert "unresolved" in g[1]["reason"]


def test_log_vm_auto_reads_thread_local(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    trace.set_cycle(3)
    trace.set_step_type("PREPHASE_GATHER")
    try:
        trace.log_vm_auto("Read", {"path": "/d.md"}, {"content": "hello"})
    finally:
        trace.set_trace(None)
        trace.set_step_type("")
    rec = next(r for r in _records(p) if r["type"] == "vm_call")
    assert rec["step_type"] == "PREPHASE_GATHER" and rec["cycle"] == 3
    assert rec["rpc"] == "Read" and rec["has_data"] is True


def test_log_vm_auto_noop_without_logger():
    trace.set_trace(None)
    trace.log_vm_auto("Read", {"path": "/x"}, {"content": "y"})  # must not raise
