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

    # I1: ref-grounding on OK answers
    if ans.outcome == "OUTCOME_OK":
        unresolved = [r for r in ans.refs if isinstance(r, str) and r.startswith("$")]
        if unresolved:
            return False, f"I1: unresolved refs {unresolved!r} on OK answer"
        if "runtime" in intent.answer_shape.required_ref_kinds:
            non_static = [r for r in ans.refs if not str(r).startswith("/docs/")]
            if not non_static:
                return False, "I1: OK answer requires a runtime ref but carries only static refs"

    # I3: independent security re-check from the frozen IntentSpec (defense in depth)
    for c in intent.constraints:
        if c.security and c.deny_when is not None and evaluate(c.deny_when, env):
            if ans.outcome != "OUTCOME_DENIED_SECURITY":
                return False, (f"I3: security constraint {c.anchor!r} deny_when holds "
                               f"but outcome is {ans.outcome!r}, not DENIED_SECURITY")

    # success_criteria: every PredExpr over env+answer must hold
    for i, crit in enumerate(intent.success_criteria):
        if not evaluate(crit, env):
            return False, f"success_criteria[{i}] failed: {crit.model_dump()!r}"

    return True, ""
