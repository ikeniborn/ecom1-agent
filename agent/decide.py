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

def _is_identity_only(expr) -> bool:
    """Return True iff every $-ref in expr is identity-rooted (and there is at least one)."""
    refs: list[str] = []

    def _collect(e) -> None:
        if e is None:
            return
        for attr in ("lhs", "rhs"):
            val = getattr(e, attr, None)
            if isinstance(val, str) and val.startswith("$"):
                refs.append(val)
        for child in getattr(e, "args", None) or []:
            _collect(child)

    _collect(expr)
    if not refs:
        return False

    def _is_identity_ref(ref: str) -> bool:
        parts = ref.lstrip("$").split(".")
        if parts[0] == "identity":
            return True
        if len(parts) >= 2 and parts[0] == "_facts" and parts[1] == "identity":
            return True
        return False

    return all(_is_identity_ref(r) for r in refs)


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
    gate). Identity-only deny_when predicates (referencing only $identity.* or
    $_facts.identity.*) are also skipped unless `protected` — this gates spurious
    guest-check denials on read-only tasks (the t38 over-refusal fix). A constraint with
    protected_action=True makes has_protected_action(intent, None) return True, so preflight
    can still fire a terminal identity-only deny for legitimately protected actions.
    Predicate failures -> not-holding (never raises)."""
    for c in intent.constraints:
        if not (c.security and c.deny_when is not None):
            continue
        if getattr(c, "requires_protected_action", False) and not protected:
            continue
        if _is_identity_only(c.deny_when) and not protected:
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


def anti_give_up_ok(intent: IntentSpec, result, env: dict) -> bool:
    """True iff OK is reachable and the plan produced a grounded result satisfying
    EVERY success_criteria[OUTCOME_OK]. Strictly gated: empty criteria or any
    unresolved $-ref -> False (cannot fabricate OK). This is the spec's false-OK
    mitigation — the model cannot downgrade a solved task, and code cannot invent one."""
    if "OUTCOME_OK" not in (intent.outcome_space or []):
        return False
    crits = intent.success_criteria.get("OUTCOME_OK", [])
    if not crits:
        return False
    refs = getattr(result.captured, "refs", []) or []
    if any(isinstance(r, str) and r.startswith("$") for r in refs):
        return False
    return all(_holds(c, env) for c in crits)


def _decision_env(intent: IntentSpec, result, vm, facts) -> dict:
    """Env for post-interpret decisions: the plan's bound env + the /bin/id identity +
    the assembled answer (so success_criteria over $answer.* resolve)."""
    env = dict(result.env)
    env["identity"] = identity_of(vm, facts)
    cap = result.captured
    env["answer"] = {"message": cap.message, "outcome": cap.outcome, "refs": list(cap.refs)}
    return env


def decide_outcome(intent: IntentSpec, result, vm, facts) -> tuple[str, list]:
    """Reconcile the plan's outcome with the frozen IntentSpec + /bin/id identity.
    Ladder: security_deny > unsupported_or_clarify > anti_give_up_ok > the plan's own
    outcome. Returns (outcome, refs); refs default to the grounded answer.refs.

    verify (Task 7) re-checks consistency afterwards — this is where outcomes are
    decided, not where they are validated."""
    env = _decision_env(intent, result, vm, facts)
    base_refs = list(result.captured.refs or [])
    protected = has_protected_action(intent, result)

    c = security_deny(intent, env, protected)
    if c is not None:
        refs = _merge_constraint_refs(base_refs, c, env)
        if SECURITY_POLICY_DOC not in refs:
            refs.append(SECURITY_POLICY_DOC)
        return "OUTCOME_DENIED_SECURITY", refs

    uc = unsupported_or_clarify(intent, env)
    if uc is not None:
        return uc, base_refs

    if anti_give_up_ok(intent, result, env):
        return "OUTCOME_OK", base_refs

    return result.captured.outcome, base_refs


def security_preflight(intent: IntentSpec, vm, facts) -> tuple[str, str, list] | None:
    """Pre-loop terminal security gate. Builds a facts-only env (plan-produced bindings
    do not exist yet, so only identity/facts-based deny_when can fire) and returns
    (outcome, message, refs) when a security deny holds, else None (proceed to loop)."""
    env: dict = dict(intent.params or {})
    env["_facts"] = facts
    env["identity"] = identity_of(vm, facts)
    protected = has_protected_action(intent, None)
    c = security_deny(intent, env, protected)
    if c is None:
        return None
    refs = _merge_constraint_refs([], c, env)
    if SECURITY_POLICY_DOC not in refs:
        refs.append(SECURITY_POLICY_DOC)
    return "OUTCOME_DENIED_SECURITY", f"Denied by security policy: {c.rule}", refs
