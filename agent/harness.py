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


_HANDLERS = {
    "security_first": check_security_first,
}


def handler_for(kind):
    """Return the pure handler for a check `kind`, or None. An unknown kind is skipped
    with a logged warning by the dispatcher — adding a kind is a deliberate code change."""
    return _HANDLERS.get(kind)
