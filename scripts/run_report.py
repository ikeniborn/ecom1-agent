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
