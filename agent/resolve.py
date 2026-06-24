"""Deterministic key-entity resolution helpers: value normalization, SQL literal
quoting, predicate relaxation, prose-param literal extraction, product resolution.

General data hygiene only — NO task-specific values. Relaxation is applied to the
SQL PLAN already wrote so an exact-match miss on an entity that EXISTS (case/unit/
whitespace skew) does not collapse to UNSUPPORTED."""
from __future__ import annotations

import re

_UNIT_SUFFIX = re.compile(r"\s*\b(?:l|ml|mm|cm|m|kg|g|v|w)\b\s*$", re.IGNORECASE)
_WS = re.compile(r"\s+")
# X = 'lit'  where X is a (optionally table-qualified) column reference
_EQ = re.compile(r"([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)\s*=\s*'((?:[^']|'')*)'")
_LEAD_NUM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")
_PROSE = re.compile(r"'((?:[^']|'')*)'")


def normalize_value(s: str) -> str:
    s = (s or "").strip().lower()
    s = _WS.sub(" ", s)
    s = _UNIT_SUFFIX.sub("", s).strip()
    return s


def sql_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def literal_from_prose(s: str) -> str:
    """Extract the quoted literal from an INTENT prose param value, else the trimmed input."""
    m = _PROSE.search(s or "")
    return (m.group(1) if m else (s or "")).strip()


def _relax_one(col: str, lit: str) -> str:
    norm = normalize_value(lit)
    text_clause = f"LOWER(TRIM({col})) = {sql_quote(norm)}"
    if col.lower().endswith("property_value_text"):
        m = _LEAD_NUM.match(lit)
        if m:
            num_col = col[: -len("property_value_text")] + "property_value_number"
            return f"({text_clause} OR {num_col} = {m.group(1)})"
    return text_clause


def relax_sql(sql: str) -> str:
    """Relax every `X = 'lit'` equality in `sql`: case/whitespace/unit-insensitive text
    match, plus a numeric-column fallback for property_value_text. No equality → unchanged."""
    def repl(m: "re.Match") -> str:
        return _relax_one(m.group(1), m.group(2))
    return _EQ.sub(repl, sql)
