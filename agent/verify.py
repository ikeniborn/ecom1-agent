"""Deterministic VERIFY (0 LLM): built-in invariants + IntentSpec.success_criteria.

Same predicate engine as the interpreter. Returns (ok, error); error feeds LEARN.
"""
from __future__ import annotations

from .interpreter import InterpretResult, _project_required_refs
from .ir_models import IntentSpec
from .predicates import evaluate


def verify(result: InterpretResult, intent: IntentSpec) -> tuple[bool, str]:
    ans = result.captured
    env = dict(result.env)
    env["answer"] = {"message": ans.message, "outcome": ans.outcome, "refs": list(ans.refs)}

    # I2: outcome within the declared space
    if ans.outcome not in intent.outcome_space:
        return False, f"I2: outcome {ans.outcome!r} not in outcome_space {intent.outcome_space!r}"

    # I1: ref-grounding — enforced on EVERY outcome (not just OK), presence-based
    # (not count). grounding.ground_refs has already overwritten ans.refs with the
    # authoritative VM-derived set before verify runs.
    unresolved = [r for r in ans.refs if isinstance(r, str) and r.startswith("$")]
    if unresolved:
        return False, f"I1: unresolved refs {unresolved!r} on {ans.outcome} answer"
    required_vals, _missing_src = _project_required_refs(intent, ans.outcome, env)
    absent = [v for v in required_vals if v not in ans.refs]
    if absent:
        return False, (f"I1: required ref(s) {absent!r} absent from "
                       f"{ans.outcome} answer")

    # I3: independent security re-check from the frozen IntentSpec (defense in depth)
    for c in intent.constraints:
        if c.security and c.deny_when is not None and evaluate(c.deny_when, env):
            if ans.outcome != "OUTCOME_DENIED_SECURITY":
                return False, (f"I3: security constraint {c.anchor!r} deny_when holds "
                               f"but outcome is {ans.outcome!r}, not DENIED_SECURITY")

    # success_criteria: only the criteria for the chosen outcome must hold.
    # A valid negative outcome (e.g. OUTCOME_NONE_UNSUPPORTED) with no criteria
    # passes here; it is still gated by I2 (outcome_space) above.
    for i, crit in enumerate(intent.success_criteria.get(ans.outcome, [])):
        if not evaluate(crit, env):
            return False, f"success_criteria[{ans.outcome}][{i}] failed: {crit.model_dump()!r}"

    return True, ""
