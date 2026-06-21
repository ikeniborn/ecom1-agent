#!/usr/bin/env python3
"""Offline harness->oracle "teach" bridge: turn frequently-firing data/harness/checks.yaml
checks into validated positive oracle method-atoms.

Per hot check: distil a candidate `method` atom seeded by the check's contract, validate it by
re-running the check's source task end-to-end with the candidate force-active in PLAN, and
promote (candidate->active) on a grader score of 1.0. Reuses the oracle distil/validate/promote
machinery. Offline — grader round-trips happen out of band.

Usage:  uv run python scripts/harness_to_oracle.py [trace_dir]   (default: logs)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

# Allow `python scripts/harness_to_oracle.py` from the repo root (sys.path[0] is scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import harness
from agent.oracle import KnowledgeOracle
from agent.oracle_validate import validate_atom_via_full_run
from scripts.lint_report import aggregate


def select_hot_checks(stats, checks, min_fires, max_atoms):
    """Checks that fired >= min_fires, ranked by fires desc, capped at max_atoms.
    `stats` is the lint_report aggregate (check_id -> {fires, ...}); `checks` is
    harness.load_checks() (list of spec dicts). A check_id present in `stats` but absent
    from `checks` is ignored."""
    by_id = {c.get("id", ""): c for c in checks}
    hot = [(s.get("fires", 0), by_id[cid]) for cid, s in stats.items()
           if s.get("fires", 0) >= min_fires and cid in by_id]
    hot.sort(key=lambda t: t[0], reverse=True)
    return [c for _f, c in hot[:max_atoms]]


def _source_artifacts(source_task):
    """(objective, good_plan_json) for the check's source task, or (None, None) when the
    persisted intent/plan are missing."""
    heur = Path("data/heuristics")
    ip, pp = heur / f"{source_task}.intent.json", heur / f"{source_task}.plan.json"
    if not (source_task and ip.exists() and pp.exists()):
        return None, None
    try:
        from agent.ir_models import IntentSpec
        intent = IntentSpec.model_validate_json(ip.read_text(encoding="utf-8"))
        return intent.objective, pp.read_text(encoding="utf-8")
    except Exception:
        return None, None


def bridge_one(check, oracle, validate_fn=validate_atom_via_full_run):
    """distil -> validate -> promote for ONE hot check. Returns a one-line outcome string.
    Never raises."""
    cid = check.get("id", "")
    src = check.get("source_task", "")
    objective, good_plan = _source_artifacts(src)
    if objective is None:
        return f"{cid}: skip (no source_task / no known-good artifacts)"
    seed = (f"Avoid the anti-pattern caught by lint check '{cid}' "
            f"({check.get('kind', '')}): {check.get('message', '')}. "
            f"State the correct method generally.")
    try:
        atom = oracle.distill(design_intent=objective, error=seed, script_code=good_plan,
                              source_task=src, polarity="method", status="candidate")
    except Exception as e:
        return f"{cid}: skip (distill error: {e})"
    if atom is None:
        return f"{cid}: skip (distill produced nothing)"
    if atom.status == "active":
        return f"{cid}: skip (already bridged -> {atom.id})"
    if not validate_fn(atom, src):
        return f"{cid}: distilled {atom.id} (candidate; validation < 1.0)"
    oracle.promote(atom.id, validated_by="harness-bridge", validated_at=str(date.today()))
    return f"{cid}: PROMOTED {atom.id} (grader 1.0)"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Distil + auto-promote oracle method-atoms from hot lint checks.")
    ap.add_argument("trace_dir", nargs="?", default="logs",
                    help="directory scanned recursively for *.jsonl lint_fire telemetry (default: logs)")
    args = ap.parse_args(argv)
    min_fires = int(os.environ.get("ECOM_BRIDGE_MIN_FIRES", "3"))
    max_atoms = int(os.environ.get("ECOM_BRIDGE_MAX_ATOMS", "3"))
    stats = aggregate(args.trace_dir)
    checks = harness.load_checks()
    hot = select_hot_checks(stats, checks, min_fires, max_atoms)
    if not hot:
        print(f"no hot checks (>= {min_fires} fires) in {args.trace_dir}")
        return
    oracle = KnowledgeOracle()
    for check in hot:
        print(bridge_one(check, oracle))


if __name__ == "__main__":
    main()
