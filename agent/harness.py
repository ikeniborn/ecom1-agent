"""Learnable lint registry: a CLOSED set of code-backed check `kind` handlers over a
data-driven catalogue (data/harness/checks.yaml).

The engine (handlers + the interpreter.lint dispatcher) is deterministic code and the
trust anchor; the catalogue is data that grows by validated promotion (F8). Handlers
are PURE: each takes (plan, check_spec) and returns a list of violation messages — they
never raise and never call vm.answer. interpreter.lint decides block-vs-warn from the
spec's status/severity. A new *kind* is a code change (rare); new *instances* of an
existing kind are learnable data (common).
"""
from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from .primitives import PRIMITIVES

_DEFAULT_CHECKS = Path(__file__).resolve().parent.parent / "data" / "harness" / "checks.yaml"


def load_checks(path=None) -> list[dict]:
    """Read the check-spec catalogue. Missing/corrupt file -> [] (lint degrades to a
    no-op, never crashes)."""
    p = Path(path or _DEFAULT_CHECKS)
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    except Exception as exc:
        print(f"[lint] checks.yaml load failed: {exc} — lint disabled")
        return []
    return [d for d in data if isinstance(d, dict)]


def save_checks(checks: list[dict], path=None) -> None:
    p = Path(path or _DEFAULT_CHECKS)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(checks, sort_keys=False, allow_unicode=True, width=100),
                 encoding="utf-8")


# --- kind handlers: (plan, spec) -> list[str] (pure; never raise) ----------

def check_security_first(plan, spec) -> list[str]:
    """H3 migrated: delegate to the interpreter's pure security-first check (single
    source of truth) and convert its raise into a violation list."""
    from .interpreter import lint_security_first, InterpretError
    try:
        lint_security_first(plan)
        return []
    except InterpretError as e:
        return [str(e)]


def _ref_root(arg):
    """'$first_row.field' -> 'first_row'; '$rows' -> 'rows'; non-ref -> None."""
    if isinstance(arg, str) and arg.startswith("$"):
        return arg[1:].split(".", 1)[0]
    return None


def check_primitive_contract(plan, spec) -> list[str]:
    """A list-consuming primitive must not consume a binding produced by a scalar/dict
    producer (forbid_source). Catches the run-15:08 first->column mismatch at plan time."""
    prim = spec.get("prim")
    arg_index = int(spec.get("arg_index", 0))
    forbid = set(spec.get("forbid_source") or [])
    msg = spec.get("message") or f"'{prim}' contract violation"
    produced_by = {cs.into: cs.prim for cs in plan.compute}
    out: list[str] = []
    for cs in plan.compute:
        if cs.prim != prim or arg_index >= len(cs.args):
            continue
        root = _ref_root(cs.args[arg_index])
        if root is not None and produced_by.get(root) in forbid:
            out.append(msg)
    return out


def check_primitive_exists(plan, spec) -> list[str]:
    out: list[str] = []
    for cs in plan.compute:
        if cs.prim not in PRIMITIVES:
            out.append(f"unknown primitive {cs.prim!r} (compute -> {cs.into})")
    return out


def _positional_arity(prim: str):
    fn = PRIMITIVES.get(prim)
    if fn is None:
        return None
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return None
    return sum(1 for p in params
               if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
               and p.default is p.empty)


def check_primitive_arity(plan, spec) -> list[str]:
    out: list[str] = []
    for cs in plan.compute:
        n = _positional_arity(cs.prim)
        if n is not None and len(cs.args) != n:
            out.append(f"primitive {cs.prim!r} takes {n} arg(s), plan supplies {len(cs.args)}")
    return out


def check_sql_stdin(plan, spec) -> list[str]:
    """A /bin/sql Exec must deliver SQL on stdin (args delivery is nondeterministic — the
    tool intermittently returns its usage banner). Seeded severity: error; the pre-lint
    repair (interpreter.repair_sql_stdin) normalises args->stdin before lint, so this only
    fires on a plan that still carries SQL in args with empty stdin after repair."""
    msg = spec.get("message") or "deliver SQL via /bin/sql stdin (args is nondeterministic)"
    out: list[str] = []
    for st in list(plan.discovery) + list(plan.ops):
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            stdin = str(st.args.get("stdin") or "").strip()
            if not stdin and st.args.get("args"):
                out.append(msg)
    return out


_HANDLERS = {
    "security_first": check_security_first,
    "primitive_contract": check_primitive_contract,
    "primitive_exists": check_primitive_exists,
    "primitive_arity": check_primitive_arity,
    "sql_stdin": check_sql_stdin,
}


def handler_for(kind):
    """Return the pure handler for a check `kind`, or None. An unknown kind is skipped
    with a logged warning by the dispatcher — adding a kind is a deliberate code change."""
    return _HANDLERS.get(kind)
