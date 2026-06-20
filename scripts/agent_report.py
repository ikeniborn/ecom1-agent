#!/usr/bin/env python3
"""Self-contained HTML report over v2 JSONL traces (logs/<run>/*.jsonl).

One file, both themes (CSS custom properties + prefers-color-scheme), no external
resources. Run-overview grid + per-task drill-down (step timeline, cycle SVG, tool
usage, reasoning panels, prompt-redundancy metric). HALTS on an unreadable source —
never fabricates data.

Usage:
    uv run python scripts/agent_report.py --logs logs/<run_dir> --out docs/reports/agent-report.html
"""
from __future__ import annotations

import argparse
import difflib
import html as _html
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LlmCall:
    seq: int
    cycle: int
    phase: str
    step_type: str
    user_msg: str
    raw_response: str
    reasoning: str
    reasoning_available: bool
    tokens_in: int
    tokens_out: int
    cache_read: int
    cache_creation: int
    duration_ms: int


@dataclass
class VmCall:
    seq: int
    cycle: int
    step_type: str
    rpc: str
    args: dict
    validation: str
    bytes: int
    has_data: bool
    mutated: bool
    duration_ms: int
    result_head: str


@dataclass
class Gate:
    seq: int
    cycle: int
    step_type: str
    passed: bool
    reason: str


@dataclass
class TaskTrace:
    task_id: str
    model: str
    instruction: str
    outcome: str
    score: "float | None"
    cycles: "int | None"
    elapsed_ms: int
    score_detail: list
    llm_calls: list = field(default_factory=list)
    vm_calls: list = field(default_factory=list)
    gates: list = field(default_factory=list)
    answer: "dict | None" = None
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    rpc_counts: dict = field(default_factory=dict)
    empty_results: int = 0
    validation_failures: int = 0
    facts_overlap: "float | None" = None


_FACTS_MARKER = "PRE-PHASE FACTS:"
_FACTS_END = ("\n\nINSTRUCTION:", "\n\nINTENT_SPEC:", "\n\nLEARNED_RULES",
              "\n\nOBSERVED_RPC_OUTPUTS", "\n\nPREVIOUS_ERROR")


def _facts_block(user_msg: str) -> str:
    """Extract the shared PRE-PHASE FACTS block from an INTENT/PLAN user_msg."""
    i = user_msg.find(_FACTS_MARKER)
    if i < 0:
        return ""
    rest = user_msg[i:]
    end = len(rest)
    for marker in _FACTS_END:
        j = rest.find(marker)
        if 0 <= j < end:
            end = j
    return rest[:end]


def parse_task_trace(path: Path) -> TaskTrace:
    """Parse one v2 trace file. HALTS (raises) on an unreadable file."""
    text = Path(path).read_text(encoding="utf-8")
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))  # malformed line -> raises -> halt

    header = next((r for r in records if r.get("type") == "header"), {})
    tr = next((r for r in reversed(records) if r.get("type") == "task_result"), None)
    ans = next((r for r in reversed(records) if r.get("type") == "answer"), None)

    task = TaskTrace(
        task_id=header.get("task_id") or path.stem,
        model=header.get("model", ""),
        instruction=header.get("task_text", ""),
        outcome=(tr or ans or {}).get("outcome", ""),
        score=(tr or {}).get("score"),
        cycles=(tr or {}).get("cycles_used") or (ans or {}).get("cycle"),
        elapsed_ms=(tr or {}).get("elapsed_ms", 0),
        score_detail=list((tr or {}).get("score_detail") or []),
        answer=ans,
    )

    for r in records:
        t = r.get("type")
        if t == "llm_call":
            task.llm_calls.append(LlmCall(
                seq=r.get("seq", 0), cycle=r.get("cycle", 0), phase=r.get("phase", ""),
                step_type=r.get("step_type", ""), user_msg=r.get("user_msg", ""),
                raw_response=r.get("raw_response", ""), reasoning=r.get("reasoning", ""),
                reasoning_available=bool(r.get("reasoning_available")),
                tokens_in=r.get("tokens_in", 0), tokens_out=r.get("tokens_out", 0),
                cache_read=r.get("cache_read", 0), cache_creation=r.get("cache_creation", 0),
                duration_ms=r.get("duration_ms", 0)))
        elif t == "vm_call":
            task.vm_calls.append(VmCall(
                seq=r.get("seq", 0), cycle=r.get("cycle", 0),
                step_type=r.get("step_type", ""), rpc=r.get("rpc", ""),
                args=r.get("args", {}), validation=r.get("validation", "ok"),
                bytes=r.get("bytes", 0), has_data=bool(r.get("has_data")),
                mutated=bool(r.get("mutated")), duration_ms=r.get("duration_ms", 0),
                result_head=r.get("result_head", "")))
        elif t == "gate":
            task.gates.append(Gate(seq=r.get("seq", 0), cycle=r.get("cycle", 0),
                                   step_type=r.get("step_type", ""),
                                   passed=bool(r.get("passed")), reason=r.get("reason", "")))

    for c in task.llm_calls:
        task.tokens_in += c.tokens_in
        task.tokens_out += c.tokens_out
        task.cache_read += c.cache_read
        task.cache_creation += c.cache_creation
    for v in task.vm_calls:
        task.rpc_counts[v.rpc] = task.rpc_counts.get(v.rpc, 0) + 1
        if not v.has_data:
            task.empty_results += 1
        if not v.validation.startswith("ok"):
            task.validation_failures += 1

    intent = next((c for c in task.llm_calls if c.step_type == "INTENT"), None)
    plan = next((c for c in task.llm_calls if c.step_type == "PLAN"), None)
    if intent and plan:
        a, b = _facts_block(intent.user_msg), _facts_block(plan.user_msg)
        if a or b:
            task.facts_overlap = round(difflib.SequenceMatcher(None, a, b).ratio(), 3)

    return task


def discover_traces(logs_dir: Path) -> list[Path]:
    return sorted(Path(logs_dir).glob("t*.jsonl"))


_CSS = """:root{--bg:#fff;--fg:#222;--muted:#777;--line:#ccc;--ok:#2e7d32;
--warn:#f9a825;--bad:#c62828;--panel:#fafafa;--accent:#1565c0}
@media (prefers-color-scheme: dark){:root{--bg:#15171a;--fg:#e6e6e6;--muted:#9aa0a6;
--line:#39414a;--ok:#66bb6a;--warn:#ffca28;--bad:#ef5350;--panel:#1e2227;--accent:#64b5f6}}
body{font:13px/1.45 system-ui,sans-serif;margin:24px;background:var(--bg);color:var(--fg)}
h1,h2,h3{border-bottom:1px solid var(--line);padding-bottom:4px}
table{border-collapse:collapse;margin:8px 0}
th,td{border:1px solid var(--line);padding:3px 7px;text-align:center;white-space:nowrap}
th.l,td.l{text-align:left}
th{background:var(--panel)}
details{margin:6px 0;border:1px solid var(--line);border-radius:4px;padding:4px 8px;background:var(--panel)}
summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;word-break:break-word;margin:4px 0}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.muted{color:var(--muted)}
.timeline span{display:inline-block;margin:1px;padding:1px 5px;border-radius:3px;
background:var(--panel);border:1px solid var(--line);font-size:11px}"""

_HEAD = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
         "<title>Agent Report</title><style>" + _CSS + "</style></head><body>"
         "<h1>Agent Observability Report</h1>")
_FOOT = "</body></html>"


def _esc(s) -> str:
    return _html.escape(str(s))


def _overview_table(tasks: list[TaskTrace]) -> str:
    head = ("<tr><th class='l'>task</th><th>outcome</th><th>score</th><th>cycles</th>"
            "<th>tok in/out</th><th>cache r/c</th><th>time</th>"
            "<th>facts overlap</th></tr>")
    rows = []
    for t in tasks:
        cls = "ok" if t.outcome == "OUTCOME_OK" else "warn"
        score = "" if t.score is None else f"{t.score:.2f}"
        overlap = "" if t.facts_overlap is None else f"{t.facts_overlap:.2f}"
        rows.append(
            f"<tr><td class='l'>{_esc(t.task_id)}</td>"
            f"<td class='{cls}'>{_esc(t.outcome)}</td><td>{score}</td>"
            f"<td>{_esc(t.cycles or '')}</td>"
            f"<td>{t.tokens_in}/{t.tokens_out}</td>"
            f"<td>{t.cache_read}/{t.cache_creation}</td>"
            f"<td>{t.elapsed_ms}ms</td><td>{overlap}</td></tr>")
    return "<h2>Run Overview</h2><table>" + head + "".join(rows) + "</table>"


def _error_summary(tasks: list[TaskTrace]) -> str:
    agg: dict = {}
    for t in tasks:
        for d in t.score_detail:
            agg[d] = agg.get(d, 0) + 1
    if not agg:
        return "<h3>Error summary</h3><p class='muted'>no grader failures recorded</p>"
    rows = "".join(f"<tr><td class='l'>{_esc(k)}</td><td>{v}</td></tr>"
                   for k, v in sorted(agg.items(), key=lambda kv: -kv[1]))
    return f"<h3>Error summary</h3><table><tr><th class='l'>detail</th><th>n</th></tr>{rows}</table>"


def _tool_summary(tasks: list[TaskTrace]) -> str:
    counts: dict = {}
    empty: dict = {}
    fails: dict = {}
    for t in tasks:
        for v in t.vm_calls:
            counts[v.rpc] = counts.get(v.rpc, 0) + 1
            if not v.has_data:
                empty[v.rpc] = empty.get(v.rpc, 0) + 1
            if not v.validation.startswith("ok"):
                fails[v.rpc] = fails.get(v.rpc, 0) + 1
    rows = "".join(
        f"<tr><td class='l'>{_esc(rpc)}</td><td>{n}</td>"
        f"<td>{empty.get(rpc, 0)}</td><td>{fails.get(rpc, 0)}</td></tr>"
        for rpc, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    if not rows:
        rows = "<tr><td colspan='4' class='muted'>no tool calls</td></tr>"
    return ("<h3>Tool usage</h3><table>"
            "<tr><th class='l'>rpc</th><th>count</th><th>empty</th><th>val-fail</th></tr>"
            + rows + "</table>")


def render_report(tasks: list[TaskTrace]) -> str:
    tasks = sorted(tasks, key=lambda t: t.task_id)
    parts = [_HEAD, _overview_table(tasks), _error_summary(tasks), _tool_summary(tasks)]
    parts += [render_task_section(t) for t in tasks]
    parts.append(_FOOT)
    return "\n".join(parts)


def render_task_section(task: TaskTrace) -> str:  # replaced in Task 17
    return f"<h2 id='{_esc(task.task_id)}'>{_esc(task.task_id)}</h2>"


def main() -> int:
    ap = argparse.ArgumentParser(description="HTML report over v2 JSONL traces.")
    ap.add_argument("--logs", required=True, help="run dir holding t*.jsonl traces")
    ap.add_argument("--out", required=True, help="output HTML path")
    args = ap.parse_args()

    paths = discover_traces(Path(args.logs))
    if not paths:
        print(f"no t*.jsonl traces under {args.logs}", file=sys.stderr)
        return 1
    tasks = [parse_task_trace(p) for p in paths]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(tasks), encoding="utf-8")
    print(f"wrote {out}  ({len(tasks)} tasks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
