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


def test_parse_oracle(tmp_path):
    atoms = tmp_path / "atoms.yaml"
    atoms.write_text(
        "- id: a1\n"
        "  domain: [sql, pricing]\n"
        "  status: validated\n"
        "  source_task: t51\n"
        "- id: a2\n"
        "  domain: [sql]\n"
        "  status: candidate\n"
        "  source_task: t38\n",
        encoding="utf-8",
    )
    stats = rr.parse_oracle(atoms)

    assert stats.total == 2
    assert stats.by_status == {"validated": 1, "candidate": 1}
    assert stats.by_source_task == {"t51": 1, "t38": 1}
    assert stats.top_domains[0] == ("sql", 2)   # sorted desc by count


def test_parse_oracle_missing(tmp_path):
    stats = rr.parse_oracle(tmp_path / "nope.yaml")
    assert stats.total == 0
    assert stats.by_status == {} and stats.top_domains == []


def test_snapshot_oracle_appends(tmp_path):
    hist = tmp_path / "history.jsonl"
    stats = rr.OracleStats(total=2, by_status={"validated": 1, "candidate": 1},
                           by_source_task={"t51": 1}, top_domains=[("sql", 2), ("pricing", 1)])

    rr.snapshot_oracle(stats, hist, date="2026-06-15")
    rr.snapshot_oracle(stats, hist, date="2026-06-16")

    lines = [json.loads(l) for l in hist.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2                       # appended, not overwritten
    assert lines[0]["date"] == "2026-06-15"
    assert lines[0]["total"] == 2
    assert lines[0]["by_status"] == {"validated": 1, "candidate": 1}
    assert lines[0]["top_domains"][0] == ["sql", 2]


def test_build_error_report(tmp_path):
    matrix = {
        "t01": {
            "run-A": rr.TaskCell("t01", "CLARIFY", 3, [
                "answer missing required reference '/proc/a.json'",
            ]),
            "run-B": rr.TaskCell("t01", "CLARIFY", 3, [
                "answer missing required reference '/proc/b.json'",   # same key, run-B
            ]),
        },
        "t02": {
            "run-A": rr.TaskCell("t02", "CLARIFY", 2, [
                "answer missing required reference '/proc/c.json'",   # same key, task t02
                "loop broken at cycle 3",
            ]),
        },
        "t03": {"run-A": rr.TaskCell("t03", "OK", 1, [])},            # no errors
    }

    report = rr.build_error_report(matrix)
    by_key = {c.key: c for c in report}

    miss = by_key["answer missing required reference"]
    assert miss.total == 3                      # 3 occurrences across cells
    assert miss.tasks == 2                       # t01 + t02
    assert miss.runs == ["run-A", "run-B"]
    assert miss.example.startswith("answer missing required reference")
    assert by_key["loop broken at cycle"].total == 1
    # sorted by total desc
    assert report[0].key == "answer missing required reference"


def test_render_html_smoke():
    runs = [rr.Run(dir=Path("logs/20260615_120000_m"), date="2026-06-15",
                   time="120000", model="m", label="2026-06-15 12:00 m")]
    matrix = {
        "t01": {"2026-06-15 12:00 m": rr.TaskCell("t01", "OK", 2, [])},
        "t02": {"2026-06-15 12:00 m": rr.TaskCell(
            "t02", "CLARIFY", 3, ["loop broken at cycle 3"])},
    }
    learned = [rr.Rule("t01", "r001", "2026-06-15", "active", "codegen")]
    oracle = rr.OracleStats(total=1, by_status={"validated": 1},
                            by_source_task={"t51": 1}, top_domains=[("sql", 1)])
    errors = rr.build_error_report(matrix)

    html = rr.render_html(runs, matrix, learned, oracle, errors)

    assert html.lstrip().startswith("<!DOCTYPE html>")
    for heading in ("RESULTS", "CYCLES", "ERRORS", "LEARNED", "Oracle", "Error Report"):
        assert heading in html
    assert "t01" in html and "t02" in html       # every task row present
    assert "loop broken at cycle" in html        # error category rendered
    assert html.rstrip().endswith("</html>")


def test_parse_run_tolerates_malformed_line(tmp_path):
    """Blocker regression: a truncated JSONL line (e.g. from interrupted run) must not
    crash _parse_task_file; valid task_result must still be read."""
    run_dir = tmp_path / "20260615_120000_m"
    run_dir.mkdir()
    # Write a t01.jsonl whose last line is deliberately invalid JSON
    (run_dir / "t01.jsonl").write_text(
        json.dumps({"type": "header", "task_id": "t01"}) + "\n"
        + json.dumps({"type": "task_result", "outcome": "OUTCOME_OK",
                      "cycles_used": 2, "score_detail": [], "task_id": "t01"}) + "\n"
        + '{"type": "llm_call", "cyc'  # truncated / malformed — no trailing newline
        ,
        encoding="utf-8",
    )

    run = rr.discover_runs(tmp_path)[0]
    cells = rr.parse_run(run)  # must NOT raise

    assert cells["t01"].status == "OK"
    assert cells["t01"].cycles == 2


def test_render_html_escapes_injection():
    """Security regression: data-derived strings with HTML/JS must be escaped in output."""
    runs = [rr.Run(dir=Path("logs/20260615_120000_m"), date="2026-06-15",
                   time="120000", model="<b>badmodel</b>", label="2026-06-15 12:00 <b>badmodel</b>")]
    injection_error = "<script>alert(1)</script> at /x/y.json"
    matrix = {
        "t01": {"2026-06-15 12:00 <b>badmodel</b>": rr.TaskCell(
            "t01", "CLARIFY", 2, [injection_error])},
    }
    learned = []
    oracle = rr.OracleStats(total=0, by_status={}, by_source_task={}, top_domains=[])
    errors = rr.build_error_report(matrix)

    html = rr.render_html(runs, matrix, learned, oracle, errors)

    # Raw tags must NOT appear verbatim
    assert "<script>" not in html
    assert "<b>badmodel</b>" not in html
    # Escaped forms MUST be present
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;badmodel&lt;/b&gt;" in html


def test_main_writes_report(tmp_path, monkeypatch, capsys):
    logs = tmp_path / "logs"
    run_dir = logs / "20260615_120000_m"
    run_dir.mkdir(parents=True)
    _write(run_dir / "t01.jsonl", [
        {"type": "task_result", "outcome": "OUTCOME_OK", "cycles_used": 1,
         "score_detail": [], "task_id": "t01"}])

    learned = tmp_path / "learned"
    learned.mkdir()
    (learned / "t01.yaml").write_text(
        "task_id: t01\nentries:\n- id: r001\n  created: '2026-06-15'\n"
        "  status: active\n  surface: codegen\n", encoding="utf-8")

    out = tmp_path / "report.html"
    hist = tmp_path / "history.jsonl"

    monkeypatch.setattr(sys, "argv", [
        "run_report.py",
        "--logs", str(logs), "--out", str(out),
        "--learned", str(learned), "--atoms", str(tmp_path / "atoms.yaml"),
        "--history", str(hist),
    ])
    rc = rr.main()

    assert rc == 0
    assert out.exists() and "<!DOCTYPE html>" in out.read_text(encoding="utf-8")
    assert "RESULTS" in out.read_text(encoding="utf-8")
    assert hist.exists()                          # snapshot appended
