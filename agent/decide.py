"""Deterministic outcome-decision layer (0 LLM): the model proposes a plan; code
disposes the outcome. Sourced from the frozen IntentSpec (constraints +
success_criteria + outcome_space) and the live VM identity (/bin/id) — never from
PLAN's free choice. Best-effort: a mis-typed predicate degrades to "does not hold"
and is logged, never raised (a bad constraint falls back to the model's outcome
rather than crashing the task)."""
from __future__ import annotations

from .ir_models import Constraint, IntentSpec
from .predicates import evaluate, resolve

# Mirrors pipeline._SECURITY_POLICY_REF: a security denial always applies the
# security policy, so the grader requires it in refs even for refusals.
SECURITY_POLICY_DOC = "/docs/security.md"


def _holds(expr, env: dict) -> bool:
    """Guarded predicate evaluation: None or any failure -> False (logged)."""
    if expr is None:
        return False
    try:
        return bool(evaluate(expr, env))
    except Exception as e:
        print(f"[decide] predicate eval failed ({e}); treating as not-holding")
        return False


def identity_of(vm, facts) -> dict:
    """The VM identity (/bin/id), preferring the pre-phase-parsed facts.identity and
    falling back to a fresh /bin/id exec. A claimed authority in the task text is
    never an identity. Never raises -> {} on total failure."""
    ident = getattr(facts, "identity", None)
    if ident is None and isinstance(facts, dict):
        ident = facts.get("identity")
    if ident:
        return dict(ident)
    try:
        from .orchestrator import _parse_identity
        out = vm.exec(path="/bin/id")
        stdout = out.get("stdout", "") if isinstance(out, dict) else getattr(out, "stdout", "")
        return _parse_identity(stdout)
    except Exception:
        return {}


def has_protected_action(intent: IntentSpec, result=None) -> bool:
    """True when the task carries a protected action: a mutation already landed, or a
    constraint INTENT marked protected_action. Gates the injection blast-radius —
    pasted override text forces denial only when a protected action is in play."""
    if result is not None and getattr(result, "mutation_landed", False):
        return True
    return any(getattr(c, "protected_action", False) for c in intent.constraints)


def security_deny(intent: IntentSpec, env: dict, protected: bool) -> Constraint | None:
    """First security constraint whose deny_when holds, else None. A constraint marked
    requires_protected_action is skipped unless `protected` (the injection blast-radius
    gate). Predicate failures -> not-holding (never raises)."""
    for c in intent.constraints:
        if not (c.security and c.deny_when is not None):
            continue
        if getattr(c, "requires_protected_action", False) and not protected:
            continue
        if _holds(c.deny_when, env):
            return c
    return None


def _merge_constraint_refs(base: list, c: Constraint, env: dict) -> list:
    """Append a deciding constraint's anchored refs (RefSpec) to base, deduped.
    policy_doc -> literal path; record_path -> resolve($source, env) when it lands."""
    out = list(base)
    for r in getattr(c, "refs", []) or []:
        if r.kind == "policy_doc" and r.path:
            v = r.path
        elif r.kind == "record_path":
            rv = resolve(r.source, env)
            v = str(rv) if rv not in (None, "") else None
        else:
            v = None
        if v and v not in out:
            out.append(v)
    return out


def unsupported_or_clarify(intent: IntentSpec, env: dict) -> str | None:
    """Deterministic negative-outcome split. Terminal-state conditions
    (unsupported_when) outrank genuine ambiguity (clarify_when). Returns an outcome
    only if it is in the declared outcome_space, else None."""
    space = intent.outcome_space or []
    for c in intent.constraints:
        if _holds(getattr(c, "unsupported_when", None), env):
            if "OUTCOME_NONE_UNSUPPORTED" in space:
                return "OUTCOME_NONE_UNSUPPORTED"
    for c in intent.constraints:
        if _holds(getattr(c, "clarify_when", None), env):
            if "OUTCOME_NONE_CLARIFICATION" in space:
                return "OUTCOME_NONE_CLARIFICATION"
    return None
