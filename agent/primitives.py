"""Pure compute-primitive registry (13) + named-parser escape hatch (H2).

Each primitive is a pure function over already-resolved args. Adding a
primitive is a new registry entry, never new grammar. Parsers are the only
bounded escape hatch: (text, params) -> list[dict], dispatched by name.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .predicates import evaluate


def _to_number(s: Any) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else 0.0


def _require_rows(prim: str, rows: Any) -> list:
    """List-consuming primitives accept list[dict] (None -> empty). A scalar/dict
    (e.g. the output of `first`/`get`) is a contract error: raise a clear, actionable
    TypeError so F1's compute-wrap turns it into a retryable signal instead of a crash."""
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise TypeError(f"'{prim}' expects list[dict]; use 'get' for a single row")
    return rows


def _sum_col(rows: list[dict], col: str) -> float:
    return float(sum(_to_number(r.get(col)) for r in _require_rows("sum_col", rows)))


def _column(rows: list[dict], col: str) -> list:
    return [r.get(col) for r in _require_rows("column", rows)]


def _div(a: Any, b: Any) -> float:
    bn = _to_number(b)
    return _to_number(a) / bn if bn else 0.0


def _filter_rows(rows: list[dict], pred) -> list[dict]:
    return [r for r in _require_rows("filter_rows", rows) if evaluate(pred, dict(r))]


PRIMITIVES: dict[str, Callable[..., Any]] = {
    "abs_diff": lambda a, b: abs(_to_number(a) - _to_number(b)),
    "div": _div,
    "to_number": _to_number,
    "sum_col": _sum_col,
    "count": lambda seq: len(seq or []),
    "column": _column,
    "first": lambda seq: (seq[0] if seq else None),
    "get": lambda obj, key: (obj or {}).get(key) if isinstance(obj, dict) else None,
    # NOTE: elements must be hashable (strings, numbers); use filter_rows for rows.
    "dedupe": lambda seq: list(dict.fromkeys(seq or [])),
    "concat": lambda a, b: list(a or []) + list(b or []),
    "all_true": lambda seq: all(seq) if seq else False,
    "any_true": lambda seq: any(seq or []),
    "filter_rows": _filter_rows,
}


def run_primitive(name: str, args: list) -> Any:
    return PRIMITIVES[name](*args)


# --- Escape hatch: named parsers (bounded; t51/t53) -----------------------

_OCR_MAP = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z"})


def _fuzzy_sku_receipt(text: str, params: dict) -> list[dict]:
    """Extract SKU tokens from receipt text with OCR-confusion normalisation.

    Returns rows {raw, normalized}. Pure; values are method-grounded, not baked.
    """
    out: list[dict] = []
    for raw in re.findall(r"[A-Z0-9]{3}-[A-Z0-9]+", text.upper()):
        out.append({"raw": raw, "normalized": raw.translate(_OCR_MAP)})
    return out


PARSERS: dict[str, Callable[[str, dict], list[dict]]] = {
    "fuzzy_sku_receipt": _fuzzy_sku_receipt,
}


def run_parser(name: str, text: str, params: dict) -> list[dict]:
    return PARSERS[name](text or "", params or {})
