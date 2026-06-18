"""Deterministic VERIFY (0 LLM): built-in invariants + IntentSpec.success_criteria.

Same predicate engine as the interpreter. Returns (ok, error); error feeds LEARN.
"""
from __future__ import annotations

from .interpreter import InterpretResult
from .ir_models import IntentSpec
from .predicates import evaluate


def verify(result: InterpretResult, intent: IntentSpec) -> tuple[bool, str]:
    ans = result.captured
    env = dict(result.env)
    env["answer"] = {"message": ans.message, "outcome": ans.outcome, "refs": list(ans.refs)}

    # I2: outcome within the declared space
    if ans.outcome not in intent.outcome_space:
        return False, f"I2: outcome {ans.outcome!r} not in outcome_space {intent.outcome_space!r}"

    # I1: ref-grounding on OK answers — every required ref for the selected
    # outcome must be present and non-empty. refs are projected by the
    # interpreter from intent.required_refs, so this is defense-in-depth.
    if ans.outcome == "OUTCOME_OK":
        unresolved = [r for r in ans.refs if isinstance(r, str) and r.startswith("$")]
        if unresolved:
            return False, f"I1: unresolved refs {unresolved!r} on OK answer"
        n_required = len(intent.required_refs.get(ans.outcome, []))
        if n_required and len(ans.refs) < n_required:
            return False, (f"I1: OK answer carries {len(ans.refs)} ref(s) "
                           f"but {n_required} required")

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
