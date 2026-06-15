import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_report as rr  # noqa: E402


def _write(p: Path, records: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_discover_runs_parses_dirname(tmp_path):
    (tmp_path / "20260615_103000_anthropic-claude-sonnet-4-6").mkdir()
    (tmp_path / "20260614_090000_ollama-qwen").mkdir()
    (tmp_path / "not-a-run").mkdir()           # ignored: no timestamp prefix
    (tmp_path / "20260615_103000_x.txt").write_text("x")  # ignored: not a dir

    runs = rr.discover_runs(tmp_path)

    assert [r.date for r in runs] == ["2026-06-14", "2026-06-15"]  # sorted by date,time
    assert runs[0].model == "ollama-qwen"
    assert runs[1].time == "103000"
    assert runs[1].label == "2026-06-15 10:30 anthropic-claude-sonnet-4-6"


def test_normalize_error_key():
    # quoted path stripped; no truncation (F-001)
    assert rr.normalize_error_key(
        "answer missing required reference '/proc/catalog/FST-APSRIZJW.json'"
    ) == "answer missing required reference"
    # two messages differing only by quoted path collapse to one key
    assert rr.normalize_error_key("answer missing required reference '/a/b.json'") == \
           rr.normalize_error_key("answer missing required reference '/c/d.json'")
    # [pipeline] prefix dropped, digits removed, whitespace collapsed
    assert rr.normalize_error_key("[pipeline]  loop broken at cycle 3") == \
           "loop broken at cycle"
    # bare unquoted path token dropped
    assert rr.normalize_error_key("real_vm_exec: read failed /docs/policy.md") == \
           "real_vm_exec: read failed"
    # no-op on a clean grader line (comma preserved, deterministic)
    assert rr.normalize_error_key("expected outcome OUTCOME_OK, got OUTCOME_NONE_CLARIFICATION") == \
           "expected outcome OUTCOME_OK, got OUTCOME_NONE_CLARIFICATION"


def test_parse_run_results_cycles_and_error_dedup(tmp_path):
    run_dir = tmp_path / "20260615_120000_m"
    run_dir.mkdir()
    # t01: clean OK, 2 cycles, no score_detail
    _write(run_dir / "t01.jsonl", [
        {"type": "header", "task_text": "do x", "task_id": "t01"},
        {"type": "task_result", "outcome": "OUTCOME_OK", "cycles_used": 2,
         "score_detail": [], "task_id": "t01"},
    ])
    # t02: CLARIFY, 3 cycles, two score_detail lines that normalize to ONE key
    _write(run_dir / "t02.jsonl", [
        {"type": "header", "task_text": "do y", "task_id": "t02"},
        {"type": "task_result", "outcome": "OUTCOME_NONE_CLARIFICATION", "cycles_used": 3,
         "score_detail": [
             "answer missing required reference '/proc/a.json'",
             "answer missing required reference '/proc/b.json'",   # dup category
             "expected outcome OUTCOME_OK, got OUTCOME_NONE_CLARIFICATION",
         ], "task_id": "t02"},
    ])
    # t03: interrupted — header + llm_call only, no task_result/answer
    _write(run_dir / "t03.jsonl", [
        {"type": "header", "task_text": "do z", "task_id": "t03"},
        {"type": "llm_call", "phase": "CODEGEN", "cycle": 1, "task_id": "t03"},
    ])

    run = rr.discover_runs(tmp_path)[0]
    cells = rr.parse_run(run)

    assert cells["t01"].status == "OK" and cells["t01"].cycles == 2
    assert cells["t02"].status == "CLARIFY" and cells["t02"].cycles == 3
    assert cells["t03"].status == "INCOMPLETE"
    assert len(rr.cell_error_keys(cells["t02"])) == 2   # dedup'd to 2 distinct keys
    assert rr.cell_error_keys(cells["t01"]) == set()


def test_parse_run_picks_latest_training_cycle(tmp_path):
    run_dir = tmp_path / "20260615_120000_m"
    run_dir.mkdir()
    _write(run_dir / "t01.jsonl", [
        {"type": "task_result", "outcome": "OUTCOME_NONE_CLARIFICATION",
         "cycles_used": 1, "score_detail": [], "task_id": "t01"}])
    _write(run_dir / "t01.c2.jsonl", [
        {"type": "task_result", "outcome": "OUTCOME_OK",
         "cycles_used": 1, "score_detail": [], "task_id": "t01"}])

    cells = rr.parse_run(rr.discover_runs(tmp_path)[0])
    assert cells["t01"].status == "OK"   # c2 (latest cycle) wins


def test_parse_learned(tmp_path):
    (tmp_path / "t01.yaml").write_text(
        "task_id: t01\n"
        "entries:\n"
        "- id: r001\n"
        "  created: '2026-06-15'\n"
        "  status: active\n"
        "  surface: codegen\n"
        "- id: v001\n"
        "  created: '2026-06-14'\n"
        "  status: inactive\n",
        encoding="utf-8",
    )
    (tmp_path / "t02.yaml").write_text(
        "task_id: t02\nentries: []\n", encoding="utf-8")

    rules = rr.parse_learned(tmp_path)

    assert len(rules) == 2
    by_id = {r.id: r for r in rules}
    assert by_id["r001"].task_id == "t01"
    assert by_id["r001"].created == "2026-06-15"
    assert by_id["r001"].surface == "codegen"
    assert by_id["v001"].status == "inactive"
