"""Offline distill→candidate→promote gate.

Activates each candidate atom, runs the task set `source ∪ green-suite`, and
promotes only when every green-suite task held its reference score AND the
candidate's source task improved. Promote is a separate offline pass (not run
on production tasks) because score is visible only post-SubmitRun.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_DEFAULT_GREEN = Path(__file__).resolve().parent.parent / "data" / "oracle" / "green_suite.yaml"


def load_green_suite(path: str | Path | None = None) -> list[tuple[str, float]]:
    """Return [(task_id, reference_score), ...]. Missing file → FileNotFoundError
    (promote must never silently proceed without its gate)."""
    p = Path(path or _DEFAULT_GREEN)
    if not p.exists():
        raise FileNotFoundError(f"green_suite manifest not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [(str(d["task_id"]), float(d["reference"])) for d in raw]


def promote_decision(
    run_scores: dict[str, float],
    source_task: str,
    source_baseline: float,
    green_suite: list[tuple[str, float]],
    eps: float = 1e-9,
) -> str:
    """Verdict for one candidate, given post-pass scores.

    Returns:
      "halt"       — a green-suite task dropped below its reference (regression).
      "promote"    — green held AND source improved over baseline.
      "no_improve" — green held but source did not improve.
    """
    for tid, ref in green_suite:
        if run_scores.get(tid, 0.0) + eps < ref:
            return "halt"
    if run_scores.get(source_task, 0.0) > source_baseline + eps:
        return "promote"
    return "no_improve"
