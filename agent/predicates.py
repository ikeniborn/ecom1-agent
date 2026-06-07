"""Pure predicate engine. evaluate(PredExpr, env) -> bool; no I/O, no LLM."""
from __future__ import annotations

import re
from typing import Any

from .ir_models import BOOL_OPS, PredExpr


def resolve(value: Any, env: dict) -> Any:
    """A `$name[.path[.idx]]` string resolves from env; everything else is literal."""
    if isinstance(value, str) and value.startswith("$"):
        return _lookup_path(value[1:], env)
    return value


def _lookup_path(path: str, env: dict) -> Any:
    cur: Any = env
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            cur = getattr(cur, part, None)
    return cur


def _num(v: Any):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate(expr: PredExpr, env: dict) -> bool:
    op = expr.op
    if op in BOOL_OPS:
        if op == "and":
            return all(evaluate(a, env) for a in expr.args)
        if op == "or":
            return any(evaluate(a, env) for a in expr.args)
        return not evaluate(expr.args[0], env)  # not

    lhs = resolve(expr.lhs, env)
    if op == "nonempty":
        return bool(lhs) and (len(lhs) > 0 if hasattr(lhs, "__len__") else True)
    if op == "isnull":
        return lhs is None

    rhs = resolve(expr.rhs, env)
    if op == "eq":
        return lhs == rhs
    if op == "ne":
        return lhs != rhs
    if op in ("lt", "le", "gt", "ge"):
        ln, rn = _num(lhs), _num(rhs)
        if ln is None or rn is None:
            a, b = lhs, rhs  # fall back to direct comparison
        else:
            a, b = ln, rn
        try:
            return {"lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]
        except TypeError:
            return False
    if op == "contains_any":
        hay = lhs or []
        return any(x in hay for x in (rhs or []))
    if op == "in_set":
        return lhs in (rhs or [])
    if op == "startswith":
        return str(lhs).startswith(str(rhs))
    if op == "endswith":
        return str(lhs).endswith(str(rhs))
    if op == "regex_match":
        return re.search(str(rhs), str(lhs)) is not None
    raise ValueError(f"unhandled predicate op {op!r}")  # unreachable: validated
