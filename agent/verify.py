"""Deterministic VERIFY (0 LLM): built-in invariants + IntentSpec.success_criteria.

Same predicate engine as the interpreter. Returns (ok, error); error feeds LEARN.
"""
from __future__ import annotations

from .decide import has_protected_action, _is_identity_only
from .interpreter import InterpretResult, _project_required_refs
from .ir_models import IntentSpec
from .predicates import evaluate


def verify(result: InterpretResult, intent: IntentSpec) -> tuple[bool, str]:
    ans = result.captured
    env = dict(result.env)
    env["answer"] = {"message": ans.message, "outcome": ans.outcome, "refs": list(ans.refs)}

    # Phase 2: bind /bin/id identity for parity with decide.py's deny_when env so the
    # consistency re-check evaluates the same predicates the decision layer did.
    _facts = env.get("_facts")
    _ident = getattr(_facts, "identity", None)
    if _ident is None and isinstance(_facts, dict):
        _ident = _facts.get("identity")
    env["identity"] = _ident or {}

    # Single source of truth for the protected gate — mirrors decide.py's ladder.
    protected = has_protected_action(intent, result)

    # I2: outcome within the declared space
    if ans.outcome not in intent.outcome_space:
        return False, f"I2: outcome {ans.outcome!r} not in outcome_space {intent.outcome_space!r}"

    # I1: ref-grounding — enforced on EVERY outcome (not just OK), presence-based
    # (not count). grounding.ground_refs has already overwritten ans.refs with the
    # authoritative VM-derived set before verify runs.
    unresolved = [r for r in ans.refs if isinstance(r, str) and r.startswith("$")]
    if unresolved:
        return False, f"I1: unresolved refs {unresolved!r} on {ans.outcome} answer"
    required_vals, missing_src = _project_required_refs(intent, ans.outcome, env)
    if missing_src:
        return False, (f"I1: required ref source(s) {missing_src!r} did not resolve on "
                       f"{ans.outcome} answer (resolve-before-cite)")
    absent = [v for v in required_vals if v not in ans.refs]
    if absent:
        return False, (f"I1: required ref(s) {absent!r} absent from "
                       f"{ans.outcome} answer")

    # I3: independent security re-check from the frozen IntentSpec (defense in depth).
    # Gate: skip identity-only deny_when predicates when not protected — mirrors
    # decide.py:security_deny so decide↔verify never diverge on gated constraints.
    for c in intent.constraints:
        if not (c.security and c.deny_when is not None):
            continue
        if _is_identity_only(c.deny_when) and not protected:
            continue
        if evaluate(c.deny_when, env):
            if ans.outcome != "OUTCOME_DENIED_SECURITY":
                return False, (f"I3: security constraint {c.anchor!r} deny_when holds "
                               f"but outcome is {ans.outcome!r}, not DENIED_SECURITY")

    # I3 reverse: a DENIED_SECURITY outcome must be justified by a declared security
    # deny_when that holds. When the intent declares security deny_when predicates and
    # NONE hold, the denial is a spurious over-refusal -> fail. When NO security
    # deny_when is declared, the model's denial is not second-guessed (the predicate
    # machinery is simply not in play).
    # Gate: gated identity-only constraints (not protected) are excluded from the
    # justification set — a DENIED justified only by them is a spurious over-refusal.
    # When declared constraints exist but ALL are gated, _sec is empty and we treat it
    # as "no valid justification" (same as all declared predicates not holding).
    if ans.outcome == "OUTCOME_DENIED_SECURITY":
        _all_sec = [c for c in intent.constraints if c.security and c.deny_when is not None]
        _sec = [c for c in _all_sec
                if not (_is_identity_only(c.deny_when) and not protected)]
        if _all_sec and (not _sec or not any(evaluate(c.deny_when, env) for c in _sec)):
            return False, ("I3: outcome DENIED_SECURITY but no declared security "
                           "deny_when predicate holds (spurious over-refusal)")

    # success_criteria: only the criteria for the chosen outcome must hold.
    # A valid negative outcome (e.g. OUTCOME_NONE_UNSUPPORTED) with no criteria
    # passes here; it is still gated by I2 (outcome_space) above.
    for i, crit in enumerate(intent.success_criteria.get(ans.outcome, [])):
        if not evaluate(crit, env):
            return False, f"success_criteria[{ans.outcome}][{i}] failed: {crit.model_dump()!r}"

    return True, ""
