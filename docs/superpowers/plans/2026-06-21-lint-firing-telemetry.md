---
review:
  plan_hash: 838be34b8fa01135
  spec_hash: 60862f0470b3e178
  last_run: 2026-06-21
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings: []
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-21-lint-firing-telemetry-design.md
---

# Lint-Firing Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record which `data/harness/checks.yaml` checks fire (id/kind/severity, blocking and warn-level) into the per-task trace, and add an offline aggregator that ranks fires across runs — data to choose a future harness→oracle bridge direction.

**Architecture:** Three independent units. (1) A best-effort emit helper in `agent/trace.py` mirroring `log_gate_auto`. (2) A one-line wire-in inside `agent/interpreter.py:lint()` that emits per fired check before the existing raise/print. (3) An offline `scripts/lint_report.py` that scans trace JSONL files and prints a ranked tally. Telemetry only — no oracle change, no distillation, no env gate.

**Tech Stack:** Python 3.12, pytest, `uv run` task runner. Existing modules: `agent/trace.py` (`TraceLogger`, thread-local `get_trace`/`current_cycle`, `render_trace`), `agent/interpreter.py` (`lint`), `agent/harness.py` (check catalogue).

**Spec:** `docs/superpowers/specs/2026-06-21-lint-firing-telemetry-design.md`

---

## File Structure

- **Modify** `agent/trace.py` — add `TraceLogger.log_lint_fire(...)` method + module-level `log_lint_fire_auto(...)` wrapper + a `lint_fire` branch in `render_trace()`'s `event()` dispatcher.
- **Modify** `agent/interpreter.py` — import `log_lint_fire_auto`; emit one record per fired check inside `lint()`.
- **Create** `scripts/lint_report.py` — offline aggregator (`aggregate(trace_dir) -> dict`, `render(stats) -> str`, `main()`).
- **Create** `tests/test_lint_telemetry.py` — covers emit, no-trace safety, wire-in, render.
- **Create** `tests/test_lint_report.py` — covers the aggregator.

Each task produces a self-contained, committable change.

> Note: the brainstorming skill did not create a dedicated worktree for this work; implement on the current branch (`heuristics`) unless you choose to branch first.

---

### Task 1: Emit helper in `agent/trace.py`

**Files:**
- Modify: `agent/trace.py` (add a method to `TraceLogger`, add a module-level wrapper near `log_gate_auto` at the end of the file)
- Test: `tests/test_lint_telemetry.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lint_telemetry.py` with:

```python
"""Lint-firing telemetry: lint() emits one `lint_fire` trace record per fired check
(blocking AND warn), the emit helper is no-op without an active logger, and the record
renders as a readable line."""
import json
from pathlib import Path

import pytest

from agent.ir_models import PlanIR
from agent import harness
from agent.interpreter import lint, InterpretError
from agent.trace import (
    TraceLogger, set_trace, set_cycle, log_lint_fire_auto, render_trace,
)


def _records(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def test_log_lint_fire_auto_writes_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    set_trace(t)
    set_cycle(3)
    try:
        log_lint_fire_auto("chk_x", "primitive_contract", "error", True, "boom")
    finally:
        t.close()
        set_trace(None)
    fires = [r for r in _records(p) if r.get("type") == "lint_fire"]
    assert len(fires) == 1
    r = fires[0]
    assert r["check_id"] == "chk_x"
    assert r["kind"] == "primitive_contract"
    assert r["severity"] == "error"
    assert r["blocking"] is True
    assert r["message"] == "boom"
    assert r["cycle"] == 3
    assert r["task_id"] == "t01"


def test_log_lint_fire_auto_no_logger_is_noop():
    set_trace(None)
    # Must not raise when there is no active logger.
    log_lint_fire_auto("chk_x", "k", "error", True, "msg")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_lint_telemetry.py::test_log_lint_fire_auto_writes_record tests/test_lint_telemetry.py::test_log_lint_fire_auto_no_logger_is_noop -v`
Expected: FAIL with `ImportError: cannot import name 'log_lint_fire_auto' from 'agent.trace'`.

- [ ] **Step 3: Add the `TraceLogger.log_lint_fire` method**

In `agent/trace.py`, inside `class TraceLogger`, add this method immediately after `log_gate` (around line 312, after the `log_gate` method body):

```python
    def log_lint_fire(self, cycle: int, check_id: str, kind: str,
                      severity: str, blocking: bool, message: str) -> None:
        """One fired lint check-spec (data/harness/checks.yaml): which check, its kind/
        severity, whether it blocked the plan, and the violation message. Captures warn-
        level fires that the aggregate LINT `gate` record does not surface."""
        self._write({
            "type": "lint_fire",
            "cycle": cycle,
            "check_id": check_id,
            "kind": kind,
            "severity": severity,
            "blocking": bool(blocking),
            "message": message,
        })
```

- [ ] **Step 4: Add the module-level `log_lint_fire_auto` wrapper**

In `agent/trace.py`, at the end of the file (immediately after the `log_gate_auto` function, around line 535), add:

```python
def log_lint_fire_auto(check_id: str, kind: str, severity: str,
                       blocking: bool, message: str) -> None:
    t = get_trace()
    if t is None:
        return
    try:
        t.log_lint_fire(current_cycle(), check_id, kind, severity, blocking, message)
    except Exception:
        pass
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_lint_telemetry.py::test_log_lint_fire_auto_writes_record tests/test_lint_telemetry.py::test_log_lint_fire_auto_no_logger_is_noop -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/trace.py tests/test_lint_telemetry.py
git commit -m "feat(trace): lint_fire telemetry record + log_lint_fire_auto helper"
```

---

### Task 2: Wire emit into `interpreter.lint()`

**Files:**
- Modify: `agent/interpreter.py` (import + emit inside `lint()`, the loop at lines 255-279)
- Test: `tests/test_lint_telemetry.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lint_telemetry.py`:

```python
def _denied_after_business():
    # Trips the security_first handler: a DENIED_SECURITY branch follows a business branch.
    return _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"},
                               {"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"}],
                  "default_label": "ok"},
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []},
                "deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )


def test_lint_emits_fire_for_warn_and_blocking(tmp_path, monkeypatch):
    # warn spec first (records, does not block), then an active error spec (records, blocks).
    monkeypatch.setattr(harness, "load_checks", lambda *a, **k: [
        {"id": "warn1", "kind": "security_first", "severity": "warn", "status": "active"},
        {"id": "err1", "kind": "security_first", "severity": "error", "status": "active"},
    ])
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    set_trace(t)
    set_cycle(1)
    try:
        with pytest.raises(InterpretError):
            lint(_denied_after_business())
    finally:
        t.close()
        set_trace(None)
    fires = [r for r in _records(p) if r.get("type") == "lint_fire"]
    assert [f["check_id"] for f in fires] == ["warn1", "err1"]
    assert fires[0]["blocking"] is False
    assert fires[1]["blocking"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_lint_telemetry.py::test_lint_emits_fire_for_warn_and_blocking -v`
Expected: FAIL — no `lint_fire` records found (assertion on `[f["check_id"] ...]` fails: list is empty).

- [ ] **Step 3: Add the import**

In `agent/interpreter.py`, add to the existing imports near the top of the file (after the other `from .` imports):

```python
from .trace import log_lint_fire_auto
```

- [ ] **Step 4: Emit inside the `lint()` loop**

In `agent/interpreter.py:lint()`, replace the tail of the loop body. Find:

```python
        if not violations:
            continue
        blocking = (spec.get("status", "active") == "active"
                    and spec.get("severity", "error") == "error")
        if blocking:
            raise InterpretError("; ".join(violations))
        print(f"[lint] warn ({spec.get('id')}): {violations[0]}")
```

Replace with:

```python
        if not violations:
            continue
        blocking = (spec.get("status", "active") == "active"
                    and spec.get("severity", "error") == "error")
        log_lint_fire_auto(spec.get("id", ""), spec.get("kind", ""),
                           spec.get("severity", "error"), blocking, violations[0])
        if blocking:
            raise InterpretError("; ".join(violations))
        print(f"[lint] warn ({spec.get('id')}): {violations[0]}")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_lint_telemetry.py::test_lint_emits_fire_for_warn_and_blocking -v`
Expected: PASS.

- [ ] **Step 6: Run the existing interpreter/harness suites for no regression**

Run: `uv run pytest tests/test_harness.py tests/test_interpreter.py -q`
Expected: PASS (no failures). Confirms block/warn semantics are unchanged by the additive emit.

- [ ] **Step 7: Commit**

```bash
git add agent/interpreter.py tests/test_lint_telemetry.py
git commit -m "feat(interpreter): emit lint_fire per fired check in lint()"
```

---

### Task 3: Render `lint_fire` in `render_trace()`

**Files:**
- Modify: `agent/trace.py` (`render_trace()` inner `event()` dispatcher, around lines 454-473)
- Test: `tests/test_lint_telemetry.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lint_telemetry.py`:

```python
def test_render_trace_shows_lint_fire():
    rec = {"type": "lint_fire", "cycle": 2, "check_id": "chk_x", "kind": "primitive_contract",
           "severity": "error", "blocking": True, "message": "boom contract"}
    text = render_trace([rec], color=False)
    assert "lint_fire" in text
    assert "chk_x" in text
    assert "BLOCK" in text
    assert "boom contract" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_lint_telemetry.py::test_render_trace_shows_lint_fire -v`
Expected: FAIL — the generic `event()` fallback dumps the record as JSON capped at 120 chars; `"BLOCK"` is absent, so `assert "BLOCK" in text` fails.

- [ ] **Step 3: Add the `lint_fire` branch**

In `agent/trace.py`, inside `render_trace()`'s nested `event(rec)` function, add a branch before the final `else:` (the `else` that JSON-dumps unknown records). The chain currently ends:

```python
        elif t == "schema_refresh":
            out.append(f"{pre} c{cyc} +tables {rec.get('added_tables')}")
        else:
            payload = {k: v for k, v in rec.items() if k not in ("ts", "task_id", "type")}
            out.append(f"{pre} {json.dumps(payload, ensure_ascii=False)[:120]}")
```

Change it to:

```python
        elif t == "schema_refresh":
            out.append(f"{pre} c{cyc} +tables {rec.get('added_tables')}")
        elif t == "lint_fire":
            mark = "BLOCK" if rec.get("blocking") else "warn"
            out.append(f"{pre} c{cyc} {rec.get('check_id')} [{mark}] "
                       f"{(rec.get('message') or '')[:80]}")
        else:
            payload = {k: v for k, v in rec.items() if k not in ("ts", "task_id", "type")}
            out.append(f"{pre} {json.dumps(payload, ensure_ascii=False)[:120]}")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_lint_telemetry.py::test_render_trace_shows_lint_fire -v`
Expected: PASS.

- [ ] **Step 5: Run the full telemetry file**

Run: `uv run pytest tests/test_lint_telemetry.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add agent/trace.py tests/test_lint_telemetry.py
git commit -m "feat(trace): render lint_fire records in render_trace"
```

---

### Task 4: Offline aggregator `scripts/lint_report.py`

**Files:**
- Create: `scripts/lint_report.py`
- Test: `tests/test_lint_report.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_lint_report.py`:

```python
"""scripts/lint_report.py aggregates lint_fire telemetry across trace JSONL files."""
import json


def test_aggregate_counts(tmp_path):
    from scripts.lint_report import aggregate, render
    f1 = tmp_path / "t01.jsonl"
    f1.write_text("\n".join([
        json.dumps({"type": "lint_fire", "check_id": "chk_a", "kind": "primitive_contract",
                    "blocking": True, "task_id": "t01", "message": "m1"}),
        json.dumps({"type": "vm_call", "rpc": "Read"}),  # noise, ignored
        json.dumps({"type": "lint_fire", "check_id": "chk_a", "kind": "primitive_contract",
                    "blocking": False, "task_id": "t01", "message": "m1b"}),
    ]), encoding="utf-8")
    f2 = tmp_path / "t02.jsonl"
    f2.write_text(
        json.dumps({"type": "lint_fire", "check_id": "chk_a", "kind": "primitive_contract",
                    "blocking": True, "task_id": "t02", "message": "m2"}) + "\nGARBAGE LINE\n",
        encoding="utf-8")

    stats = aggregate(tmp_path)
    a = stats["chk_a"]
    assert a["fires"] == 3
    assert a["blocked"] == 2
    assert a["warned"] == 1
    assert len(a["tasks"]) == 2
    assert a["kind"] == "primitive_contract"

    text = render(stats)
    assert "chk_a" in text


def test_aggregate_empty_dir(tmp_path):
    from scripts.lint_report import aggregate, render
    assert render(aggregate(tmp_path)) == "no lint_fire records"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_lint_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.lint_report'`.

- [ ] **Step 3: Write `scripts/lint_report.py`**

Create `scripts/lint_report.py`:

```python
#!/usr/bin/env python3
"""Offline aggregator for `lint_fire` telemetry. Scans trace JSONL files and prints a
table ranked by total fires, so the most-blocking data/harness checks are visible across
a benchmark run — the signal for choosing a harness->oracle bridge direction.

Usage:  uv run python scripts/lint_report.py [trace_dir]   (default: logs)
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _new_stat() -> dict:
    return {"kind": "", "fires": 0, "blocked": 0, "warned": 0, "tasks": set(), "sample": ""}


def aggregate(trace_dir) -> dict:
    """Tally lint_fire records by check_id across every *.jsonl under `trace_dir`.
    Malformed lines and unreadable files are skipped (telemetry must never crash)."""
    stats: dict = defaultdict(_new_stat)
    for p in sorted(Path(trace_dir).glob("**/*.jsonl")):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict) or rec.get("type") != "lint_fire":
                continue
            s = stats[rec.get("check_id", "")]
            s["kind"] = rec.get("kind", "") or s["kind"]
            s["fires"] += 1
            if rec.get("blocking"):
                s["blocked"] += 1
            else:
                s["warned"] += 1
            if rec.get("task_id"):
                s["tasks"].add(rec["task_id"])
            if not s["sample"]:
                s["sample"] = rec.get("message", "") or ""
    return stats


def render(stats: dict) -> str:
    if not stats:
        return "no lint_fire records"
    rows = sorted(stats.items(), key=lambda kv: kv[1]["fires"], reverse=True)
    header = (f"{'check_id':<28} {'kind':<26} {'fires':>5} {'blocked':>7} "
              f"{'warned':>6} {'tasks':>5}  sample")
    out = [header]
    for cid, s in rows:
        out.append(f"{cid:<28} {s['kind']:<26} {s['fires']:>5} {s['blocked']:>7} "
                   f"{s['warned']:>6} {len(s['tasks']):>5}  {s['sample'][:50]}")
    return "\n".join(out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Aggregate lint_fire telemetry from trace JSONL files.")
    ap.add_argument("trace_dir", nargs="?", default="logs",
                    help="directory scanned recursively for *.jsonl (default: logs)")
    args = ap.parse_args(argv)
    print(render(aggregate(args.trace_dir)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_lint_report.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Smoke-run the script**

Run: `uv run python scripts/lint_report.py /tmp/nonexistent-dir`
Expected: prints `no lint_fire records` (no crash on a missing/empty dir).

- [ ] **Step 6: Commit**

```bash
git add scripts/lint_report.py tests/test_lint_report.py
git commit -m "feat(scripts): lint_report aggregator for lint_fire telemetry"
```

---

### Task 5: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS — no failures introduced. (Pre-existing red `test_t09_replay_matches_known_good` is a known stale-fixture failure unrelated to this change; if it is the only failure, it is acceptable.)

- [ ] **Step 2: Commit (only if any incidental fixup was needed)**

```bash
git add -A
git commit -m "test: full-suite green for lint-firing telemetry"
```

If Step 1 was already green with no changes, skip this commit.

---

## Self-Review

**1. Spec coverage:**
- Emit helper (`log_lint_fire_auto` + `TraceLogger.log_lint_fire`, never-raise, record shape) → Task 1. ✓
- Wire-in (emit per fired check, blocking + warn, before raise/print; known first-blocker limitation preserved) → Task 2. ✓
- Render (`lint_fire` branch in `render_trace`) → Task 3. ✓
- Report (`scripts/lint_report.py`, columns check_id/kind/fires/blocked/warned/tasks/sample, malformed-line tolerance, empty-dir message) → Task 4. ✓
- Non-goals (no oracle write, no distillation, no env gate) → respected; none of the tasks touch `agent/oracle*.py` or add env vars. ✓
- Testing section items (emit error+warn, no-trace safety, render, report aggregate) → Tasks 1-4 tests. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has an expected result. ✓

**3. Type consistency:** `log_lint_fire(cycle, check_id, kind, severity, blocking, message)` defined in Task 1 is called by `log_lint_fire_auto` with `current_cycle()` first (Task 1) and by nothing else; `log_lint_fire_auto(check_id, kind, severity, blocking, message)` signature is identical at its call site in Task 2. The record `type` string `"lint_fire"` matches across emit (Task 1), render (Task 3), and aggregator filter (Task 4). `aggregate`/`render` names match between `scripts/lint_report.py` and `tests/test_lint_report.py`. ✓
