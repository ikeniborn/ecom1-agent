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
