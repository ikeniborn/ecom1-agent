---
review:
  plan_hash: 06e08e1717dd6cbd
  spec_hash: e5bca072453d969d
  last_run: 2026-06-15
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: WARNING
      section: "## ⚠️ Spec Deltas (read before implementing)"
      section_hash: 4f2aa7529de03574
      text: "Plan deliberately does not implement the spec Data-Sources/Cell-Semantics requirement to read tNN.trace.log and answer.outcome/answer.cycle. It substitutes task_result.score_detail/outcome/cycles_used per documented, code-verified Spec Deltas D1-D4 (the trace.log source was deleted in d9e1991; those jsonl events are never emitted live). Justified deviation, not a defect — flagged so the spec override is consciously accepted."
      verdict: wontfix
      verdict_at: 2026-06-15
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-15-run-report-heatmaps-design.md
---

# Run-Report Heatmaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/run_report.py` — a single self-contained HTML report over `logs/` showing four per-task/per-run heatmaps (RESULTS, CYCLES, ERRORS, LEARNED) plus an Oracle snapshot and an aggregated Error Report.

**Architecture:** A thin stdlib+pyyaml script (style of `scripts/trace_view.py`). Pure parsing functions take plain inputs and return plain data; only `main()` touches argv and the filesystem. Rendering is a pure function of parsed data, so it is unit-testable without real logs.

**Tech Stack:** Python 3, stdlib (`argparse`, `json`, `re`, `dataclasses`, `pathlib`), `pyyaml`. No matplotlib/pandas/plotly. HTML built as an inline-styled string.

---

## ⚠️ Spec Deltas (read before implementing)

The approved design `docs/superpowers/specs/2026-06-15-run-report-heatmaps-design.md` was written
**one hour after** commit `d9e1991` changed the logging format, and its data-source section is stale on
four points. The user's decision (2026-06-15) was: **derive all error signal from `{tid}.jsonl` events,
read-only, no pipeline changes.** This plan implements that decision against the *real* current jsonl.

| # | Spec says | Reality (verified in code) | This plan |
|---|-----------|----------------------------|-----------|
| D1 | `tNN.trace.log` is the error source | `tNN.trace.log` was **deleted** in `d9e1991`. `[pipeline] … failed` lines are stdout `print()` only — not in any file. | Do **not** read `trace.log`. |
| D2 | `gate_check` / `test_run` jsonl events carry per-cycle errors | Those `TraceLogger` methods are **defined but never called** by the live pipeline. Real per-task events: `header`, `facts`, `llm_call`, `vm_call`, `answer`, `task_result`. | Do **not** read `gate_check`/`test_run`. |
| D3 | RESULTS uses `answer.outcome`; no `answer` ⇒ INCOMPLETE | Terminal clarification calls **raw `vm.answer`** (bypasses `_AnswerGuard._emit`), so failing tasks emit **no `answer` event**. `answer` events appear on the OK path only. | RESULTS/CYCLES read **`task_result`** (`outcome`, `cycles_used`), emitted per completed task by `_finalize_task_trace`. `answer` is a fallback only. |
| D4 | "No grader scores exist in logs" | `task_result` carries `score` and **`score_detail[]`** (grader feedback strings) from `SubmitRun`. | ERRORS + Error Report normalize `task_result.score_detail[]`. (RESULTS still encodes outcome, not a 0–1 score — that part of the spec stands.) |

Everything else in the spec (normalization strip rules with **no truncation** per F-001, LEARNED from
`data/learned/*.yaml` by `created`-date match, Oracle snapshot + `history.jsonl`, CLI flags, color scales,
module layout) is implemented as written.

**Verified jsonl record shapes** (`agent/trace.py`):
- `task_result`: `{type, outcome, score, cycles_used, total_tokens_in, total_tokens_out, elapsed_ms, score_detail: list[str], ts, task_id}`
- `answer`: `{type, cycle, message, outcome, refs, ts, task_id}`
- `header`: `{type, task_text, model, ts, task_id}`
- `llm_call` / `vm_call`: carry an int `cycle` field (used as CYCLES fallback)

`outcome` values: `OUTCOME_OK` (success), `OUTCOME_NONE_CLARIFICATION` (failure) — confirmed `agent/pipeline.py`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| Create `scripts/run_report.py` | All parsing + rendering + `main()`. One module, function-per-responsibility. |
| Create `tests/test_run_report.py` | Unit tests on synthetic fixtures + render smoke test. |
| Runtime-only write `data/oracle/history.jsonl` | One appended snapshot line per report run (created if absent). Not a source file. |

`scripts/` is already a package (`scripts/__init__.py` exists), so tests import via `from scripts import run_report`.

### Data model (dataclasses, defined in Task 1, referenced everywhere)

```python
@dataclass
class Run:
    dir: Path
    date: str        # "YYYY-MM-DD"
    time: str        # "HHMMSS"
    model: str       # label tail of the dir name
    label: str       # "YYYY-MM-DD HH:MM <model>" — column header + matrix key

@dataclass
class TaskCell:
    task_id: str
    status: str          # "OK" | "CLARIFY" | "INCOMPLETE"
    cycles: int | None
    errors: list[str]    # raw score_detail lines (normalized lazily)

@dataclass
class Rule:
    task_id: str
    id: str
    created: str         # "YYYY-MM-DD"
    status: str          # "active" | "inactive"
    surface: str

@dataclass
class OracleStats:
    total: int
    by_status: dict[str, int]
    by_source_task: dict[str, int]
    top_domains: list[tuple[str, int]]   # sorted desc by count

@dataclass
class ErrorCategory:
    key: str             # normalized category
    total: int           # total occurrences across all task/run cells
    tasks: int           # count of distinct tasks affected
    runs: list[str]      # sorted run labels it appeared in
    example: str         # one raw (un-normalized) example message
```

The matrix passed between `main()` and the renderers is `dict[str, dict[str, TaskCell]]`
(`matrix[task_id][run.label] = TaskCell`).

---

## Task 1: Scaffold + dataclasses + `discover_runs`

**Files:**
- Create: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_report.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py::test_discover_runs_parses_dirname -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'scripts.run_report' has no attribute 'discover_runs'`.

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Self-contained HTML run-report over logs/ — four heatmaps + Oracle + Error Report.

Rows = tasks (t01…tNN), columns = runs (one per logs/<YYYYMMDD_HHMMSS_model>/ dir).
stdlib + pyyaml only. Pure parsing/rendering; only main() touches argv + fs output.

Usage:
    uv run python scripts/run_report.py                       # logs/ -> logs/report.html
    uv run python scripts/run_report.py --out r.html --logs logs/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Run:
    dir: Path
    date: str
    time: str
    model: str
    label: str


_RUN_RE = re.compile(r"^(\d{8})_(\d{6})_(.+)$")


def discover_runs(logs_dir) -> list[Run]:
    runs: list[Run] = []
    for d in sorted(Path(logs_dir).iterdir()):
        if not d.is_dir():
            continue
        m = _RUN_RE.match(d.name)
        if not m:
            continue
        ymd, hms, model = m.groups()
        date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        label = f"{date} {hms[:2]}:{hms[2:4]} {model}"
        runs.append(Run(dir=d, date=date, time=hms, model=model, label=label))
    runs.sort(key=lambda r: (r.date, r.time))
    return runs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py::test_discover_runs_parses_dirname -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): scaffold + discover_runs"
```

---

## Task 2: `normalize_error_key` (shared by ERRORS map + Error Report)

**Files:**
- Modify: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py::test_normalize_error_key -v`
Expected: FAIL — `AttributeError: ... has no attribute 'normalize_error_key'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_DIGITS = re.compile(r"\d+")


def normalize_error_key(raw: str) -> str:
    """Deterministic category key. Strip rules, in order (no truncation — F-001):
    (1) drop leading '[pipeline] '; (2) remove quoted strings; (3) drop path-like
    tokens (any non-space run containing '/'); (4) remove digit runs; (5) collapse
    whitespace and strip. The result is the category verbatim.
    """
    s = raw or ""
    if s.startswith("[pipeline] "):
        s = s[len("[pipeline] "):]
    s = _QUOTED.sub("", s)                                   # (2)
    s = " ".join(tok for tok in s.split() if "/" not in tok)  # (3) + partial collapse
    s = _DIGITS.sub("", s)                                   # (4)
    s = " ".join(s.split())                                  # (5)
    return s
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py::test_normalize_error_key -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): deterministic error-key normalization"
```

---

## Task 3: `parse_run` — RESULTS status, CYCLES, error dedup

**Files:**
- Modify: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

Reads each `t*.jsonl` in a run dir. Picks the latest training cycle per task
(`tNN.cK.jsonl` beats `tNN.jsonl`). Status/cycles/errors come from `task_result`
(fallback `answer`, then INCOMPLETE) per Spec Deltas D3/D4.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py -k parse_run -v`
Expected: FAIL — `has no attribute 'parse_run'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
@dataclass
class TaskCell:
    task_id: str
    status: str
    cycles: "int | None"
    errors: list


_TASK_FILE_RE = re.compile(r"^(t\d+)(?:\.c(\d+))?$")


def _task_id_and_cycle(name: str) -> "tuple[str, int]":
    base = name[:-len(".jsonl")]
    m = _TASK_FILE_RE.match(base)
    if not m:
        return base, 1
    return m.group(1), int(m.group(2) or 1)


def _parse_task_file(task_id: str, path: Path) -> TaskCell:
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    tr = next((r for r in reversed(records) if r.get("type") == "task_result"), None)
    ans = next((r for r in reversed(records) if r.get("type") == "answer"), None)

    if tr is not None:
        outcome = tr.get("outcome") or ""
        cycles = tr.get("cycles_used")
        errors = list(tr.get("score_detail") or [])
    elif ans is not None:
        outcome = ans.get("outcome") or ""
        cycles = ans.get("cycle")
        errors = []
    else:
        outcome, cycles, errors = "", None, []

    if tr is not None or ans is not None:
        status = "OK" if outcome == "OUTCOME_OK" else "CLARIFY"
    else:
        status = "INCOMPLETE"

    if not cycles:
        seen = [r["cycle"] for r in records if isinstance(r.get("cycle"), int)]
        cycles = max(seen) if seen else None

    return TaskCell(task_id=task_id, status=status, cycles=cycles, errors=errors)


def parse_run(run: Run) -> "dict[str, TaskCell]":
    latest: "dict[str, tuple[Path, int]]" = {}
    for p in sorted(run.dir.glob("t*.jsonl")):
        tid, cyc = _task_id_and_cycle(p.name)
        cur = latest.get(tid)
        if cur is None or cyc >= cur[1]:
            latest[tid] = (p, cyc)
    return {tid: _parse_task_file(tid, p) for tid, (p, _) in latest.items()}


def cell_error_keys(cell: TaskCell) -> set:
    return {k for k in (normalize_error_key(e) for e in cell.errors) if k}
```

> Move the `TaskCell` dataclass next to the other dataclasses if you prefer; keep one definition only.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py -k parse_run -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): parse_run results/cycles/errors from task_result"
```

---

## Task 4: `parse_learned`

**Files:**
- Modify: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py::test_parse_learned -v`
Expected: FAIL — `has no attribute 'parse_learned'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
@dataclass
class Rule:
    task_id: str
    id: str
    created: str
    status: str
    surface: str


def parse_learned(learned_dir) -> list:
    rules: list = []
    for p in sorted(Path(learned_dir).glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        tid = data.get("task_id") or p.stem
        for e in (data.get("entries") or []):
            rules.append(Rule(
                task_id=tid,
                id=str(e.get("id") or ""),
                created=str(e.get("created") or ""),
                status=str(e.get("status") or ""),
                surface=str(e.get("surface") or ""),
            ))
    return rules
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py::test_parse_learned -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): parse_learned from data/learned/*.yaml"
```

---

## Task 5: `parse_oracle` (+ missing-file handling)

**Files:**
- Modify: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

`data/oracle/atoms.yaml` is a **flat list** of atom dicts (`agent/oracle_atoms.save_atoms`)
and is **frequently absent** (only `.gitkeep` today) — handle both.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py -k parse_oracle -v`
Expected: FAIL — `has no attribute 'parse_oracle'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
@dataclass
class OracleStats:
    total: int
    by_status: dict
    by_source_task: dict
    top_domains: list


def parse_oracle(atoms_path) -> OracleStats:
    p = Path(atoms_path)
    if not p.exists():
        return OracleStats(total=0, by_status={}, by_source_task={}, top_domains=[])
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    atoms = data if isinstance(data, list) else (data.get("atoms") or [])

    by_status: dict = {}
    by_task: dict = {}
    dom: dict = {}
    for a in atoms:
        st = a.get("status") or "?"
        by_status[st] = by_status.get(st, 0) + 1
        src = a.get("source_task") or "—"
        by_task[src] = by_task.get(src, 0) + 1
        for d in (a.get("domain") or []):
            dom[d] = dom.get(d, 0) + 1

    top = sorted(dom.items(), key=lambda kv: (-kv[1], kv[0]))
    return OracleStats(total=len(atoms), by_status=by_status,
                       by_source_task=by_task, top_domains=top)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py -k parse_oracle -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): parse_oracle with missing-file handling"
```

---

## Task 6: `snapshot_oracle` — append to `history.jsonl`

**Files:**
- Modify: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

The snapshot `date` is passed in (latest run's date), not read from a clock — keeps it deterministic and testable.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py::test_snapshot_oracle_appends -v`
Expected: FAIL — `has no attribute 'snapshot_oracle'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
def snapshot_oracle(stats: OracleStats, hist_path, date: str) -> None:
    """Append one growth-series line to data/oracle/history.jsonl (created if absent)."""
    line = {
        "date": date,
        "total": stats.total,
        "by_status": stats.by_status,
        "top_domains": stats.top_domains[:10],
    }
    p = Path(hist_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py::test_snapshot_oracle_appends -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): snapshot_oracle appends history.jsonl"
```

---

## Task 7: `build_error_report` — global rollup

**Files:**
- Modify: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py::test_build_error_report -v`
Expected: FAIL — `has no attribute 'build_error_report'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
@dataclass
class ErrorCategory:
    key: str
    total: int
    tasks: int
    runs: list
    example: str


def build_error_report(matrix: dict) -> list:
    agg: dict = {}
    for task_id, run_cells in matrix.items():
        for run_label, cell in run_cells.items():
            for raw in cell.errors:
                key = normalize_error_key(raw)
                if not key:
                    continue
                a = agg.setdefault(
                    key, {"total": 0, "tasks": set(), "runs": set(), "example": raw})
                a["total"] += 1
                a["tasks"].add(task_id)
                a["runs"].add(run_label)
    out = [
        ErrorCategory(key=k, total=v["total"], tasks=len(v["tasks"]),
                      runs=sorted(v["runs"]), example=v["example"])
        for k, v in agg.items()
    ]
    out.sort(key=lambda c: (-c.total, c.key))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py::test_build_error_report -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): build_error_report rollup"
```

---

## Task 8: `render_html` — heatmaps + Oracle + Error Report

**Files:**
- Modify: `scripts/run_report.py`
- Test: `tests/test_run_report.py`

Pure function: HTML string from parsed data. Color scales computed in Python
(white→target interpolation for numeric maps; fixed status→color for RESULTS).
Oracle domain bars are `<div>` widths. No JS, no external assets.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py::test_render_html_smoke -v`
Expected: FAIL — `has no attribute 'render_html'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
import html as _html

_RED = (198, 40, 40)
_BLUE = (21, 101, 192)
_STATUS_COLOR = {"OK": "#2e7d32", "CLARIFY": "#f9a825", "INCOMPLETE": "#9e9e9e"}

_HEAD = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Run Report</title><style>
body{font:13px/1.4 system-ui,sans-serif;margin:24px;color:#222}
h2{margin-top:32px;border-bottom:2px solid #ddd;padding-bottom:4px}
table{border-collapse:collapse;margin:8px 0}
th,td{border:1px solid #ccc;padding:3px 6px;text-align:center;white-space:nowrap}
th.task,td.task{text-align:left;font-weight:600;position:sticky;left:0;background:#fafafa}
th{background:#f0f0f0;font-weight:600}
.bar{height:14px;background:#1565c0;display:inline-block;vertical-align:middle}
</style></head><body>
<h1>Run Report</h1>"""

_FOOT = "</body></html>"


def _esc(s) -> str:
    return _html.escape(str(s))


def _lerp_hex(t: float, target: tuple) -> str:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    r = int(255 + (target[0] - 255) * t)
    g = int(255 + (target[1] - 255) * t)
    b = int(255 + (target[2] - 255) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _task_sort_key(tid: str):
    m = re.search(r"\d+", tid)
    return (int(m.group()) if m else 9999, tid)


def _col_headers(runs: list) -> str:
    th = "".join(f"<th>{_esc(r.label)}</th>" for r in runs)
    return f"<tr><th class='task'>task</th>{th}</tr>"


def _results_table(runs, matrix, tasks) -> str:
    rows = []
    for tid in tasks:
        cells = []
        for r in runs:
            cell = matrix[tid].get(r.label)
            if cell is None:
                cells.append("<td></td>")
            else:
                color = _STATUS_COLOR.get(cell.status, "#fff")
                cells.append(f"<td style='background:{color};color:#fff'>{_esc(cell.status)}</td>")
        rows.append(f"<tr><td class='task'>{_esc(tid)}</td>{''.join(cells)}</tr>")
    return ("<h2>RESULTS</h2><table>"
            + _col_headers(runs) + "".join(rows) + "</table>")


def _numeric_table(title, runs, matrix, tasks, value_fn, target) -> str:
    vals = [v for tid in tasks for r in runs
            if (v := value_fn(matrix[tid].get(r.label))) is not None]
    vmax = max(vals) if vals else 1
    vmax = vmax or 1
    rows = []
    for tid in tasks:
        cells = []
        for r in runs:
            cell = matrix[tid].get(r.label)
            v = value_fn(cell) if cell is not None else None
            if v is None:
                cells.append("<td></td>")
            else:
                bg = _lerp_hex(v / vmax, target)
                cells.append(f"<td style='background:{bg}'>{_esc(v)}</td>")
        rows.append(f"<tr><td class='task'>{_esc(tid)}</td>{''.join(cells)}</tr>")
    return (f"<h2>{title}</h2><table>"
            + _col_headers(runs) + "".join(rows) + "</table>")


def _learned_table(runs, tasks, lcount, target) -> str:
    vmax = max(lcount.values()) if lcount else 1
    vmax = vmax or 1
    rows = []
    for tid in tasks:
        cells = []
        for r in runs:
            n = lcount.get((tid, r.date), 0)
            bg = _lerp_hex(n / vmax, target) if n else "#fff"
            txt = str(n) if n else ""
            cells.append(f"<td style='background:{bg}'>{txt}</td>")
        rows.append(f"<tr><td class='task'>{_esc(tid)}</td>{''.join(cells)}</tr>")
    return ("<h2>LEARNED</h2><table>"
            + _col_headers(runs) + "".join(rows) + "</table>")


def _oracle_section(oracle) -> str:
    if oracle.total == 0:
        return "<h2>Oracle</h2><p>No atoms (data/oracle/atoms.yaml absent or empty).</p>"
    dmax = oracle.top_domains[0][1] if oracle.top_domains else 1
    bars = "".join(
        f"<div>{_esc(tag)} ({n}) "
        f"<span class='bar' style='width:{int(200 * n / dmax)}px'></span></div>"
        for tag, n in oracle.top_domains[:15]
    )

    def _kv_table(title, d):
        rows = "".join(f"<tr><td class='task'>{_esc(k)}</td><td>{v}</td></tr>"
                       for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))
        return f"<h3>{title}</h3><table>{rows}</table>"

    return ("<h2>Oracle</h2>"
            f"<p>total atoms: {oracle.total}</p>{bars}"
            + _kv_table("by status", oracle.by_status)
            + _kv_table("by source_task", oracle.by_source_task))


def _error_report(errors) -> str:
    head = ("<tr><th class='task'>category</th><th>total</th><th>tasks</th>"
            "<th>runs</th><th>example</th></tr>")
    rows = "".join(
        f"<tr><td class='task'>{_esc(c.key)}</td><td>{c.total}</td><td>{c.tasks}</td>"
        f"<td>{len(c.runs)}</td><td>{_esc(c.example)}</td></tr>"
        for c in errors
    )
    if not rows:
        rows = "<tr><td colspan='5'>no errors recorded</td></tr>"
    return f"<h2>Error Report</h2><table>{head}{rows}</table>"


def render_html(runs, matrix, learned, oracle, errors) -> str:
    tasks = sorted(matrix.keys(), key=_task_sort_key)
    lcount: dict = {}
    for rule in learned:
        lcount[(rule.task_id, rule.created)] = lcount.get((rule.task_id, rule.created), 0) + 1
    parts = [
        _HEAD,
        _results_table(runs, matrix, tasks),
        _numeric_table("CYCLES", runs, matrix, tasks, lambda c: c.cycles, _RED),
        _numeric_table("ERRORS", runs, matrix, tasks,
                       lambda c: len(cell_error_keys(c)), _RED),
        _learned_table(runs, tasks, lcount, _BLUE),
        _oracle_section(oracle),
        _error_report(errors),
        _FOOT,
    ]
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py::test_render_html_smoke -v`
Expected: PASS

- [ ] **Step 5: Run the full test file**

Run: `uv run pytest tests/test_run_report.py -v`
Expected: PASS (all tests from Tasks 1–8)

- [ ] **Step 6: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): render_html heatmaps + oracle + error report"
```

---

## Task 9: `main()` — CLI wiring + end-to-end run

**Files:**
- Modify: `scripts/run_report.py`

Wires everything: discover runs, build the matrix, parse learned/oracle, snapshot,
build error report, render, write output. Default `--logs logs/`, `--out logs/report.html`.

- [ ] **Step 1: Write the failing test**

```python
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
```

> The `--learned`, `--atoms`, `--history` flags exist so the test can point at fixtures.
> They default to the real project paths for normal use.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_report.py::test_main_writes_report -v`
Expected: FAIL — `has no attribute 'main'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/run_report.py`:

```python
_REPO = Path(__file__).resolve().parent.parent
_DEF_LEARNED = _REPO / "data" / "learned"
_DEF_ATOMS = _REPO / "data" / "oracle" / "atoms.yaml"
_DEF_HISTORY = _REPO / "data" / "oracle" / "history.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description="HTML run-report over logs/.")
    ap.add_argument("--logs", default=str(_REPO / "logs"), help="root holding run dirs")
    ap.add_argument("--out", default=str(_REPO / "logs" / "report.html"), help="output HTML")
    ap.add_argument("--learned", default=str(_DEF_LEARNED), help="data/learned dir")
    ap.add_argument("--atoms", default=str(_DEF_ATOMS), help="oracle atoms.yaml")
    ap.add_argument("--history", default=str(_DEF_HISTORY), help="oracle history.jsonl")
    args = ap.parse_args()

    runs = discover_runs(args.logs)
    if not runs:
        print(f"no run dirs under {args.logs}", file=sys.stderr)
        return 1

    matrix: dict = {}
    for run in runs:
        for tid, cell in parse_run(run).items():
            matrix.setdefault(tid, {})[run.label] = cell

    learned = parse_learned(args.learned)
    oracle = parse_oracle(args.atoms)
    snapshot_oracle(oracle, args.history, date=runs[-1].date)
    errors = build_error_report(matrix)

    html_doc = render_html(runs, matrix, learned, oracle, errors)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html_doc, encoding="utf-8")
    print(f"wrote {args.out}  ({len(runs)} runs, {len(matrix)} tasks, {len(errors)} error categories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_run_report.py::test_main_writes_report -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite + a manual smoke against real paths**

Run: `uv run pytest tests/test_run_report.py -v`
Expected: PASS (all)

Run: `uv run python scripts/run_report.py --out /tmp/report.html`
Expected: either `wrote /tmp/report.html …` (if `logs/` has run dirs) or
`no run dirs under …/logs` exit 1 (empty `logs/` today — that is fine, not a failure of the script).

- [ ] **Step 6: Commit**

```bash
git add scripts/run_report.py tests/test_run_report.py
git commit -m "feat(run-report): main() CLI wiring + end-to-end report"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task(s) |
|--------------|---------|
| RESULTS heatmap | 3 (parse), 8 (render) |
| CYCLES heatmap | 3, 8 |
| ERRORS heatmap | 2 (normalize), 3 (dedup count), 8 |
| LEARNED heatmap | 4 (parse), 8 (render) |
| Oracle section (bars + status/source_task tables) | 5, 8 |
| Error Report rollup | 2, 7, 8 |
| Error categorization strip rules (no truncation, F-001) | 2 |
| `discover_runs` dir-name parse | 1 |
| `snapshot_oracle` → history.jsonl | 6 |
| Module layout (one responsibility per fn, pure render) | all |
| CLI `--logs` / `--out` | 9 |
| Rendering: stdlib HTML, inline styles, no JS | 8 |
| Testing: fixture run (OK + no-answer + repeated errors), parse_learned/parse_oracle, render smoke | 3, 4, 5, 8 |
| Out of scope (no scores-as-cells, no JS, no growth chart) | respected — RESULTS is status-only; history seeded only |

Deviations from spec are the four documented Spec Deltas (D1–D4), all consequences of the
same-day logging refactor `d9e1991`, implementing the user's "derive from jsonl" decision.

**2. Placeholder scan:** No TBD/TODO/"add error handling"/"similar to". Every code step shows complete code.

**3. Type consistency:** `Run`, `TaskCell`, `Rule`, `OracleStats`, `ErrorCategory` defined once (Tasks 1/3/4/5/7), field names stable across `parse_*`, `build_error_report`, and `render_html`. `cell_error_keys` (Task 3) is the single source of the ERRORS count, reused in render (Task 8) and consistent with `build_error_report` (Task 7). `normalize_error_key` (Task 2) is the single normalizer used by both. Matrix shape `dict[task_id][run.label] -> TaskCell` is consistent between `main()` (Task 9) and every renderer (Task 8). `_numeric_table` signature `(title, runs, matrix, tasks, value_fn, target)` matches its two call sites.
