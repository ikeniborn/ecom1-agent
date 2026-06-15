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
import html as _html
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
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
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


# ── HTML rendering ─────────────────────────────────────────────────────────────

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
            if (c := matrix[tid].get(r.label)) is not None
            and (v := value_fn(c)) is not None]
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
            # Intentional: a cell lights only when a rule's created date == the run's
            # calendar date — this is a per-day *creation* heatmap, not a cumulative
            # active-state heatmap. Do not change to cumulative without updating the spec.
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
