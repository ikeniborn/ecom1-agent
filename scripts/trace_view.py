#!/usr/bin/env python3
"""Pretty-print a per-task trace JSONL (logs/<run>/<task_id>.jsonl).

Renders the LLM conversation in timeline order: the system prompt, the user
message sent each phase/cycle, and the model's reply (assistant). System prompts
are deduplicated in the trace (one `header_system` per sha256, referenced by many
`llm_call` records); this viewer resolves the reference and prints the full
system text once per sha, then a back-reference afterwards.

Usage:
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl
    uv run python scripts/trace_view.py logs/<run>/          # list task traces
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl --phase PLAN
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl --no-system
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl --max-chars 2000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ANSI palette — applied only when stdout is a terminal.
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_BLUE = "\x1b[34m"
_MAGENTA = "\x1b[35m"
_CYAN = "\x1b[36m"

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if _USE_COLOR else text


def _sha8(sha: str) -> str:
    return (sha or "")[:8]


def _system_text(blocks) -> str:
    """Flatten a header_system `blocks` list into plain text."""
    if isinstance(blocks, str):
        return blocks
    parts = []
    for b in blocks or []:
        if isinstance(b, dict):
            parts.append(b.get("text", ""))
        else:
            parts.append(str(b))
    return "\n".join(parts)


def _indent(text: str, max_chars: int) -> str:
    body = text if not max_chars or len(text) <= max_chars else (
        text[:max_chars] + _c(f"\n… [truncated {len(text) - max_chars} chars]", _DIM)
    )
    return "\n".join("    " + line for line in body.splitlines()) or "    (empty)"


def _render_llm_call(rec: dict, systems: dict, shown: set, args) -> None:
    cycle = rec.get("cycle", 0)
    phase = rec.get("phase", "?")
    dur = rec.get("duration_ms", 0)
    ti, to = rec.get("tokens_in", 0), rec.get("tokens_out", 0)
    ok = rec.get("success")
    mark = _c("OK", _GREEN) if ok else _c("FAIL", _RED)
    bar = "━" * 72
    head = (
        f"{_c(bar, _BLUE)}\n"
        f"{_c('cycle ' + str(cycle), _BOLD)} · {_c(phase, _MAGENTA + _BOLD)} · "
        f"{dur}ms · tokens {ti}/{to} · {mark}"
    )
    print(head)

    sha = rec.get("system_sha256", "")
    if not args.no_system:
        sys_text = _system_text(systems.get(sha))
        if args.full_system or sha not in shown:
            shown.add(sha)
            print(_c(f"┌ SYSTEM  ({_sha8(sha)})", _CYAN))
            print(_indent(sys_text, args.max_chars))
        else:
            print(_c(f"┌ SYSTEM  ({_sha8(sha)})  — same as shown above", _DIM))

    print(_c("├ USER", _YELLOW))
    print(_indent(rec.get("user_msg", ""), args.max_chars))
    print(_c("└ ASSISTANT", _GREEN))
    print(_indent(rec.get("raw_response", ""), args.max_chars))
    print()


def _render_event(rec: dict) -> None:
    """Compact one-liners for non-LLM timeline records."""
    t = rec["type"]
    cyc = rec.get("cycle", "")
    pre = _c(f"  · [{t}]", _DIM)
    if t == "gate_check":
        s = "BLOCKED" if rec.get("blocked") else "pass"
        print(f"{pre} c{cyc} {rec.get('gate_type')} {s} {rec.get('error') or ''}")
    elif t == "sql_validate":
        print(f"{pre} c{cyc} {rec.get('query','')[:80]} -> {rec.get('error') or 'ok'}")
    elif t == "sql_execute":
        print(f"{pre} c{cyc} {rec.get('duration_ms')}ms data={rec.get('has_data')} {rec.get('query','')[:70]}")
    elif t == "resolve_exec":
        print(f"{pre} {rec.get('value_extracted')!r} <- {rec.get('query','')[:70]}")
    elif t == "test_run":
        s = _c("pass", _GREEN) if rec.get("passed") else _c("FAIL", _RED)
        print(f"{pre} c{cyc} {rec.get('suite')} {s} {rec.get('error','')[:80]}")
    elif t == "test_gen":
        print(f"{pre} sql+answer tests generated")
    elif t == "tdd_warning":
        print(f"{pre} {rec.get('suite')}: {', '.join(rec.get('warnings', []))}")
    elif t == "schema_refresh":
        print(f"{pre} c{cyc} +tables {rec.get('added_tables')}")
    else:
        print(f"{pre} {json.dumps({k: v for k, v in rec.items() if k not in ('ts', 'task_id', 'type')}, ensure_ascii=False)[:120]}")


def _render(path: Path, args) -> None:
    systems: dict[str, list] = {}
    shown: set[str] = set()
    records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # Pre-pass: collect every system prompt so a referenced sha resolves even if
    # its header_system record sits later than expected.
    for r in records:
        if r.get("type") == "header_system":
            systems[r["sha256"]] = r.get("blocks")

    for r in records:
        t = r.get("type")
        if t == "header":
            print(_c("═" * 72, _BOLD))
            print(_c(f"TASK {r.get('task_id')}  ·  model={r.get('model')}", _BOLD))
            print(f"  {r.get('task_text', '')}")
            print(_c("═" * 72, _BOLD))
            print()
        elif t == "header_system":
            continue  # resolved lazily inside llm_call
        elif t == "llm_call":
            if args.phase and r.get("phase") != args.phase:
                continue
            _render_llm_call(r, systems, shown, args)
        elif t == "task_result":
            print(_c("═" * 72, _BOLD))
            sd = r.get("score_detail") or []
            print(
                _c("RESULT", _BOLD)
                + f"  {r.get('outcome')}  score={r.get('score')}  "
                + f"cycles={r.get('cycles_used')}  tokens {r.get('total_tokens_in')}/{r.get('total_tokens_out')}  "
                + f"{r.get('elapsed_ms')}ms"
            )
            for line in sd:
                print(f"  - {line}")
            print(_c("═" * 72, _BOLD))
        elif not args.llm_only:
            _render_event(r)


def main() -> int:
    ap = argparse.ArgumentParser(description="Pretty-print a per-task trace JSONL.")
    ap.add_argument("path", help="Path to <task_id>.jsonl, or a run dir to list traces")
    ap.add_argument("--phase", help="Show only this phase (DESIGN, CODEGEN, INTENT, PLAN, LEARN, …)")
    ap.add_argument("--no-system", action="store_true", help="Hide system prompts")
    ap.add_argument("--full-system", action="store_true", help="Print full system on every call (no dedup)")
    ap.add_argument("--llm-only", action="store_true", help="Hide non-LLM timeline events")
    ap.add_argument("--max-chars", type=int, default=0, help="Truncate each body to N chars (0 = unlimited)")
    args = ap.parse_args()

    p = Path(args.path)
    if not p.exists():
        print(f"not found: {p}", file=sys.stderr)
        return 1
    if p.is_dir():
        traces = sorted(p.glob("*.jsonl"))
        if not traces:
            print(f"no .jsonl traces in {p}", file=sys.stderr)
            return 1
        print(f"Task traces in {p}:")
        for t in traces:
            print(f"  {t.name}")
        print("\nRe-run with a file path to view one.")
        return 0

    _render(p, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
