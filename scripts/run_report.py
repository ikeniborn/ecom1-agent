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


@dataclass
class TaskCell:
    task_id: str
    status: str
    cycles: "int | None"
    errors: list


@dataclass
class Rule:
    task_id: str
    id: str
    created: str
    status: str
    surface: str


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
