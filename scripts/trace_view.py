#!/usr/bin/env python3
"""Pretty-print a per-task trace JSONL (logs/<run>/<task_id>.jsonl).

Thin CLI over `agent.trace.render_trace` (the same renderer that writes the
auto `{task_id}.detail.log`). Renders the timeline: pre-phase facts, each VM
RPC + result head, the LLM conversation per phase/cycle, the projected/captured
answer (message + outcome + refs), and the final result.

Usage:
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl
    uv run python scripts/trace_view.py logs/<run>/          # list task traces
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl --phase PLAN
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl --no-system
    uv run python scripts/trace_view.py logs/<run>/t09.jsonl --max-chars 2000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/trace_view.py` from the repo root (sys.path[0] is scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.trace import render_trace  # noqa: E402


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

    print(render_trace(
        p, color=sys.stdout.isatty(), max_chars=args.max_chars, phase=args.phase,
        no_system=args.no_system, full_system=args.full_system, llm_only=args.llm_only,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
