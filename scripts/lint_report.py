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
