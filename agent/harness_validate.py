"""Validation gate for a candidate check-spec (mirror of oracle_validate).

A candidate is promotable only when it FLAGS the failing plan it was distilled from AND
does NOT flag a known-good plan (no false positive). Pure structural evaluation via the
kind handler — named *_via_grader for parallelism with oracle_validate; no live grader
round-trip is required for a structural check.
"""
from __future__ import annotations

from . import harness


def validate_check_via_grader(check: dict, failing_plan, good_plan) -> bool:
    """True iff the check flags `failing_plan` and does not flag `good_plan`."""
    handler = harness.handler_for(check.get("kind"))
    if handler is None:
        return False
    try:
        flags_bad = bool(handler(failing_plan, check))
        flags_good = bool(handler(good_plan, check)) if good_plan is not None else False
    except Exception:
        return False
    return flags_bad and not flags_good
