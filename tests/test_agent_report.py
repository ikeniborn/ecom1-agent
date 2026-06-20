import json
from pathlib import Path

import scripts.agent_report as R


def _write_trace(p: Path, records: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _v2_records() -> list[dict]:
    return [
        {"type": "meta", "seq": 0, "task_id": "t38", "model": "m"},
        {"type": "header", "seq": 1, "task_id": "t38", "model": "m", "task_text": "do x"},
        {"type": "facts", "seq": 2, "task_id": "t38",
         "docs_inventory": "/docs/p.md", "gather_status": {"policies": "ok"}},
        {"type": "llm_call", "seq": 3, "cycle": 0, "phase": "INTENT",
         "step_type": "INTENT", "user_msg": "PRE-PHASE FACTS:\nA B C\n\nINSTRUCTION:\nx",
         "raw_response": "{}", "reasoning": "thinking hard", "reasoning_available": True,
         "tokens_in": 10, "tokens_out": 5, "cache_read": 100, "cache_creation": 0,
         "duration_ms": 50, "success": True},
        {"type": "llm_call", "seq": 4, "cycle": 1, "phase": "PLAN",
         "step_type": "PLAN", "user_msg": "PRE-PHASE FACTS:\nA B C\n\nINTENT_SPEC:\n{}",
         "raw_response": "{}", "reasoning": "", "reasoning_available": False,
         "tokens_in": 20, "tokens_out": 8, "cache_read": 900, "cache_creation": 1200,
         "duration_ms": 80, "success": True},
        {"type": "vm_call", "seq": 5, "cycle": 1, "step_type": "INTERPRET",
         "rpc": "Exec", "args": {"path": "/bin/sql"}, "validation": "ok",
         "bytes": 4, "has_data": True, "mutated": False, "duration_ms": 12,
         "result_head": "n\n1"},
        {"type": "vm_call", "seq": 6, "cycle": 1, "step_type": "INTERPRET",
         "rpc": "Read", "args": {"path": "/docs/p.md"}, "validation": "fail(arg 'x')",
         "bytes": 0, "has_data": False, "mutated": False, "duration_ms": 1,
         "result_head": ""},
        {"type": "gate", "seq": 7, "cycle": 1, "step_type": "VERIFY",
         "passed": True, "reason": ""},
        {"type": "answer", "seq": 8, "cycle": 1, "message": "1",
         "outcome": "OUTCOME_OK", "refs": ["/docs/p.md"]},
        {"type": "task_result", "seq": 9, "outcome": "OUTCOME_OK", "score": 1.0,
         "cycles_used": 1, "total_tokens_in": 30, "total_tokens_out": 13,
         "elapsed_ms": 130, "score_detail": []},
    ]


def test_parse_task_trace_summary(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    task = R.parse_task_trace(p)
    assert task.task_id == "t38"
    assert task.outcome == "OUTCOME_OK" and task.score == 1.0 and task.cycles == 1
    assert task.tokens_in == 30
    assert task.cache_read == 1000 and task.cache_creation == 1200
    assert task.rpc_counts["Exec"] == 1 and task.rpc_counts["Read"] == 1
    assert task.empty_results == 1 and task.validation_failures == 1


def test_facts_overlap_ratio_between_intent_and_plan(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    task = R.parse_task_trace(p)
    assert task.facts_overlap == 1.0


def test_render_overview_no_external_resources(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    html_doc = R.render_report([R.parse_task_trace(p)])
    assert "src=" not in html_doc and "href=" not in html_doc
    assert "t38" in html_doc and "OUTCOME_OK" in html_doc
    assert "--bg" in html_doc and "prefers-color-scheme: dark" in html_doc


def test_per_task_section_has_timeline_svg_reasoning(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    html_doc = R.render_report([R.parse_task_trace(p)])
    # anchored section
    assert "id='t38'" in html_doc
    # step timeline mentions step types
    assert "INTENT" in html_doc and "PLAN" in html_doc and "INTERPRET" in html_doc
    # cycle diagram rendered as inline SVG (no external image)
    assert "<svg" in html_doc and "verify" in html_doc.lower()
    # reasoning panel for the INTENT call (reasoning_available True)
    assert "thinking hard" in html_doc
    # per-task tool-usage table shows validation failure
    assert "fail(" in html_doc or "val-fail" in html_doc
    # still self-contained
    assert "src=" not in html_doc and "href='http" not in html_doc


def test_cycle_svg_is_inline_and_static():
    svg = R._cycle_svg()
    assert svg.startswith("<svg") and "PLAN" in svg and "iLEARN" in svg
    assert "http" not in svg  # no external refs
