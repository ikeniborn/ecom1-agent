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
