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
