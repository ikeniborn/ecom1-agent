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


def run_promote(oracle, green_suite, run_fn, validated_at, validated_by="grader"):
    """Iterate candidate atoms; promote those that hold green + improve source.

    `run_fn(task_ids: list[str], active_atom_id: str | None) -> dict[str, float]`
    runs the harness over `task_ids` with the given candidate active (or none for
    the baseline pass) and returns {task_id: score}. Injected so unit tests need
    no real harness.

    Returns [(atom_id, verdict), ...]. On any error the candidate is left
    untouched (fail-safe: zero bank change).
    """
    candidates = [a for a in oracle.atoms if a.status == "candidate"]
    green_ids = [tid for tid, _ in green_suite]

    # A3 DoD gate-warning: promote logs the active count; crossing >10 without a
    # top-N bump is a warning (top-N must drop below bank for cosine to filter).
    active_n = len([a for a in oracle.atoms if a.status == "active"])
    print(f"[promote] active={active_n} candidates={len(candidates)}")
    if active_n > 10:
        import os
        topn = int(os.environ.get("ORACLE_TOPN", "10"))
        if topn >= active_n:
            print(f"[promote] WARNING: active={active_n} but ORACLE_TOPN={topn} — "
                  "lower ORACLE_TOPN (ceil(active*0.5)) so cosine filters.")

    results: list[tuple[str, str]] = []
    for atom in candidates:
        source_task = atom.source_task
        task_ids = sorted(set(green_ids) | ({source_task} if source_task else set()))
        try:
            baseline = run_fn(task_ids, None)
            scores = run_fn(task_ids, atom.id)
        except Exception as e:
            print(f"[promote] {atom.id}: run failed ({e}) — staying candidate")
            results.append((atom.id, "halt"))
            continue
        verdict = promote_decision(
            scores, source_task, baseline.get(source_task, 0.0), green_suite
        )
        if verdict == "promote":
            oracle.promote(atom.id, validated_by=validated_by, validated_at=validated_at)
            print(f"[promote] {atom.id}: PROMOTED (source {source_task} improved, green held)")
        else:
            print(f"[promote] {atom.id}: {verdict} — staying candidate")
        results.append((atom.id, verdict))
    return results
