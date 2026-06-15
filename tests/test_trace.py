import json
import threading
from pathlib import Path

from agent.trace import TraceLogger, get_trace, set_trace


def _read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_get_trace_none_by_default():
    assert get_trace() is None


def test_set_and_get_trace(tmp_path):
    t = TraceLogger(tmp_path / "t.jsonl", "t01")
    set_trace(t)
    assert get_trace() is t
    set_trace(None)
    assert get_trace() is None
    t.close()


def test_header_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_header("find speakers under 5000", "claude-sonnet-4-6")
    t.close()
    recs = _read_records(p)
    assert len(recs) == 1
    r = recs[0]
    assert r["type"] == "header"
    assert r["task_id"] == "t01"
    assert r["task_text"] == "find speakers under 5000"
    assert r["model"] == "claude-sonnet-4-6"
    assert "ts" in r


def test_llm_call_deduplication(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    system = [{"type": "text", "text": "be helpful"}]
    t.log_llm_call("sql_plan", 1, system, "TASK: find X", "raw", {"queries": []}, 100, 50, 1200)
    t.log_llm_call("learn", 1, system, "TASK: find X\nERROR: ...", "raw2", {}, 90, 40, 900)
    t.close()
    recs = _read_records(p)
    # header_system written once, two llm_call records
    types = [r["type"] for r in recs]
    assert types.count("header_system") == 1
    assert types.count("llm_call") == 2
    sha = next(r["sha256"] for r in recs if r["type"] == "header_system")
    for r in recs:
        if r["type"] == "llm_call":
            assert r["system_sha256"] == sha
            assert "system" not in r


def test_llm_call_new_system_writes_new_header_system(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_llm_call("sql_plan", 1, [{"type": "text", "text": "A"}], "msg1", "r1", {}, 10, 5, 100)
    t.log_llm_call("answer", 1, [{"type": "text", "text": "B"}], "msg2", "r2", {}, 10, 5, 100)
    t.close()
    recs = _read_records(p)
    assert [r["type"] for r in recs].count("header_system") == 2


def test_gate_check_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_gate_check(1, "security", ["SELECT *"], True, "DDL not allowed")
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "gate_check"
    assert r["cycle"] == 1
    assert r["gate_type"] == "security"
    assert r["blocked"] is True
    assert r["error"] == "DDL not allowed"


def test_gate_check_not_blocked(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_gate_check(1, "schema", ["SELECT brand FROM products"], False, None)
    t.close()
    r = _read_records(p)[0]
    assert r["blocked"] is False
    assert r["error"] is None


def test_sql_validate_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_sql_validate(1, "SELECT 1", "1", None)
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "sql_validate"
    assert r["explain_result"] == "1"
    assert r["error"] is None


def test_sql_execute_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_sql_execute(1, "SELECT brand FROM products", "brand\nHeco\n", True, 230)
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "sql_execute"
    assert r["has_data"] is True
    assert r["duration_ms"] == 230


def test_resolve_exec_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_resolve_exec("SELECT DISTINCT brand FROM products WHERE brand ILIKE '%Heco%'", "brand\nHeco\n", "Heco")
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "resolve_exec"
    assert r["value_extracted"] == "Heco"


def test_task_result_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_task_result("OUTCOME_OK", 1.0, 2, 7499, 1479, 65000, [])
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "task_result"
    assert r["outcome"] == "OUTCOME_OK"
    assert r["score"] == 1.0
    assert r["cycles_used"] == 2


def test_log_test_gen(tmp_path):
    import json
    from agent.trace import TraceLogger, set_trace
    log_file = tmp_path / "trace.jsonl"
    logger = TraceLogger(log_file, "task-tdd")
    set_trace(logger)
    logger.log_test_gen("def test_sql(results): pass", "def test_answer(sql_results, answer): pass")
    logger.close()
    set_trace(None)
    records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
    tg = next(r for r in records if r["type"] == "test_gen")
    assert tg["sql_tests"] == "def test_sql(results): pass"
    assert tg["answer_tests"] == "def test_answer(sql_results, answer): pass"


def test_log_test_run(tmp_path):
    import json
    from agent.trace import TraceLogger, set_trace
    log_file = tmp_path / "trace.jsonl"
    logger = TraceLogger(log_file, "task-tdd2")
    set_trace(logger)
    logger.log_test_run(1, "sql", True, "")
    logger.log_test_run(2, "answer", False, "AssertionError: wrong outcome")
    logger.close()
    set_trace(None)
    records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
    runs = [r for r in records if r["type"] == "test_run"]
    assert runs[0]["cycle"] == 1 and runs[0]["suite"] == "sql" and runs[0]["passed"] is True
    assert runs[1]["passed"] is False
    assert "AssertionError" in runs[1]["error"]


def test_thread_isolation(tmp_path):
    results = {}

    def worker(tid: str):
        p = tmp_path / f"{tid}.jsonl"
        t = TraceLogger(p, tid)
        set_trace(t)
        assert get_trace() is t
        t.log_header("task", "model")
        t.close()
        set_trace(None)
        results[tid] = _read_records(p)

    threads = [threading.Thread(target=worker, args=(f"t0{i}",)) for i in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    for tid, recs in results.items():
        assert recs[0]["task_id"] == tid


def test_log_facts_record_and_caps(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    big = "x" * 5000
    t.log_facts({
        "docs_inventory": "/docs/a.md\n/docs/b.md",
        "policies": {"/docs/a.md": big},
        "schema": big,
        "sample_rows": "h\n1",
        "identity": {"role": "employee"},
        "target_records": {"/proc/p.json": big},
        "gather_status": {"policies": "ok", "schema": "ok"},
    })
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "facts"
    assert r["docs_inventory"] == "/docs/a.md\n/docs/b.md"
    assert r["identity"] == {"role": "employee"}
    assert r["gather_status"]["policies"] == "ok"
    # 2000-char cap applied to policy/schema/target bodies
    assert len(r["policies"]["/docs/a.md"]) <= 2000 + 40
    assert "[+" in r["policies"]["/docs/a.md"]
    assert len(r["schema"]) <= 2000 + 40
    assert "[+" in r["target_records"]["/proc/p.json"]


def test_log_vm_call_record_filters_args_and_caps(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_vm_call(2, "EXEC", "Exec",
                  {"path": "/bin/sql", "args": ["SELECT 1"], "secret": "drop"},
                  "n\n" + "9" * 4000, mutated=False)
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "vm_call" and r["cycle"] == 2 and r["phase"] == "EXEC"
    assert r["rpc"] == "Exec"
    assert r["args"] == {"path": "/bin/sql", "args": ["SELECT 1"]}  # 'secret' dropped
    assert len(r["result_head"]) <= 1000 + 40 and "[+" in r["result_head"]
    assert r["mutated"] is False


def test_log_answer_keeps_refs_full(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    refs = ["/docs/x.md", "/proc/incoming/payments/inpay_eojzdRua.json"]
    t.log_answer(1, "1", "OUTCOME_OK", refs)
    t.close()
    r = _read_records(p)[0]
    assert r["type"] == "answer" and r["message"] == "1"
    assert r["outcome"] == "OUTCOME_OK" and r["refs"] == refs


def test_trace_logger_exposes_path(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    assert t.path == p
    t.close()


def test_render_trace_sections_and_no_color():
    from agent.trace import render_trace
    records = [
        {"type": "header", "task_id": "t55", "model": "sonnet", "task_text": "last txn"},
        {"type": "facts", "docs_inventory": "/docs/a.md\n/docs/b.md",
         "policies": {"/docs/a.md": "RULE BODY"}, "schema": "CREATE TABLE x",
         "sample_rows": "", "identity": {"role": "emp"},
         "target_records": {}, "gather_status": {"policies": "ok"}},
        {"type": "vm_call", "cycle": 1, "phase": "EXEC", "rpc": "Exec",
         "args": {"path": "/bin/sql", "args": ["SELECT COUNT(*) n"]},
         "result_head": "n\n1", "mutated": False},
        {"type": "answer", "cycle": 1, "message": "1", "outcome": "OUTCOME_OK",
         "refs": ["/proc/incoming/payments/inpay_X.json"]},
        {"type": "task_result", "outcome": "OUTCOME_OK", "score": 1.0,
         "cycles_used": 1, "total_tokens_in": 10, "total_tokens_out": 20,
         "elapsed_ms": 100, "score_detail": []},
    ]
    text = render_trace(records, color=False)
    assert "PRE-PHASE FACTS" in text
    assert "/docs/a.md" in text and "RULE BODY" in text
    assert "[Exec /bin/sql" in text and "n\n1" in text or "-> n" in text
    assert "ANSWER" in text and "inpay_X.json" in text
    assert "RESULT" in text
    assert "\x1b[" not in text  # color=False -> no ANSI escapes


def test_detail_log_written_live_before_close(tmp_path):
    p = tmp_path / "t01.jsonl"
    detail = tmp_path / "t01.detail.log"
    t = TraceLogger(p, "t01")
    t.log_header("last txn", "sonnet")
    assert detail.exists()  # materialises on the FIRST record, not at close
    t.log_facts({"docs_inventory": "/docs/a.md", "gather_status": {"schema": "ok"}})
    t.log_vm_call(1, "EXEC", "Exec", {"path": "/bin/sql", "args": ["SELECT 1"]}, "n\n1", False)
    t.log_answer(1, "1", "OUTCOME_OK", ["/docs/a.md"])
    mid = detail.read_text()  # readable mid-run, before close()
    assert "PRE-PHASE FACTS" in mid and "[Exec /bin/sql" in mid and "ANSWER" in mid
    assert "\x1b[" not in mid  # plain text
    t.close()


def test_log_schema_refresh(tmp_path):
    from agent.trace import TraceLogger
    import json
    p = tmp_path / "trace.jsonl"
    t = TraceLogger(p, "task_x")
    t.log_schema_refresh(cycle=2, added_tables=["product_kinds", "carts"])
    t._fh.flush()
    lines = [json.loads(ln) for ln in p.read_text().splitlines() if ln]
    refresh = [ln for ln in lines if ln.get("type") == "schema_refresh"]
    assert len(refresh) == 1
    assert refresh[0]["cycle"] == 2
    assert refresh[0]["added_tables"] == ["product_kinds", "carts"]
