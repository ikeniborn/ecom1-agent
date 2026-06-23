"""Deterministic output-format gate (0 LLM): reshape answer.message into the exact
surface contract — EUR %d.%02d, <YES>/<NO> (or the tenant's /AGENTS.MD tokens), the
task's count format, or TSV for table/quote. The model proposes content; this code
shapes the surface.

Best-effort: format_answer and every helper never raise — any failure, a negative
outcome, or a shape it cannot confidently reshape returns the original message. The
gate never corrupts a message that was already correct (the muxx exoskeleton pattern,
mirroring agent/grounding.py and agent/decide.py).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_SLOT_RE = re.compile(r"\{([^{}]+)\}")   # mirrors interpreter._SLOT_RE
_BOOL_TOK_RE = re.compile(r"<\s*(?:YES|NO)\s*>", re.I)
_AGENTS_YES_RE = re.compile(r"(?im)^\s*(?:yes[_ ]?token|affirmative)\s*[:=]\s*(\S+)")
_AGENTS_NO_RE = re.compile(r"(?im)^\s*(?:no[_ ]?token|negative)\s*[:=]\s*(\S+)")
_OUTCOME_PREFIX_RE = re.compile(r"^\s*OUTCOME_[A-Z_]+\s*[:\-]?\s*")

# Polarity markers — conservative; ambiguous text yields no polarity (keep original).
_YES_RE = re.compile(r"<\s*yes\s*>|\byes\b|\bin the catalogue\b|\bmatches\b|\bconfirmed\b", re.I)
_NO_RE = re.compile(r"<\s*no\s*>|\bno\b|\bnot\b|\bcannot\b|\bno match\b|\bdenied\b|\bdoes not\b", re.I)


def format_eur(value) -> str:
    """Render a euro amount as 'EUR <int>.<2-digit cents>' (the grader's
    ^EUR \\d+\\.\\d{2}$). Half-up rounding to cents. Best-effort: '' on any failure
    (caller keeps the original message)."""
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return ""
    if d.is_nan() or d.is_infinite() or d < 0:
        return ""
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"EUR {d:.2f}"


def _strip_outcome_prefix(message: str) -> str:
    """Strip a wrongly-prepended 'OUTCOME_*:' / 'OUTCOME_* -' prefix (normalize-only)."""
    return _OUTCOME_PREFIX_RE.sub("", message or "", count=1)


def bool_tokens(agents_md, answer_shape) -> tuple[str, str]:
    """The tenant's (yes, no) tokens. Default '<YES>'/'<NO>'; a custom pair declared in
    /AGENTS.MD ('yes_token: X' / 'no_token: Y') overrides. No per-task values."""
    yes_tok, no_tok = "<YES>", "<NO>"
    my = _AGENTS_YES_RE.search(agents_md or "")
    mn = _AGENTS_NO_RE.search(agents_md or "")
    if my:
        yes_tok = my.group(1)
    if mn:
        no_tok = mn.group(1)
    return yes_tok, no_tok


def _polarity_from(text: str):
    """True (affirmative) / False (negative) / None (ambiguous) from text markers."""
    t = text or ""
    yes, no = bool(_YES_RE.search(t)), bool(_NO_RE.search(t))
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


def _canonicalize_bool(message: str, yes_tok: str, no_tok: str, skeleton: str) -> str:
    """Ensure the canonical yes/no token is present (additive, never destructive).
    Returns '' when no change is warranted (token already present, or polarity cannot
    be determined) so the caller keeps the original message."""
    if yes_tok in (message or "") or no_tok in (message or ""):
        return ""
    polarity = _polarity_from(skeleton)
    if polarity is None:
        polarity = _polarity_from(message)
    if polarity is None:
        return ""
    tok = yes_tok if polarity else no_tok
    body = _strip_outcome_prefix(message).strip()
    return f"{tok} {body}".strip() if body else tok


_INT_RE = re.compile(r"-?\d+")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_EUR_NUM_RE = re.compile(r"EUR\s*(-?\d+(?:\.\d+)?)", re.I)


def _extract_int(text: str):
    """First integer in the text, else None."""
    m = _INT_RE.search(text or "")
    return int(m.group(0)) if m else None


def _extract_eur_number(text: str):
    """A euro amount parsed from a message: the number adjacent to 'EUR' if present,
    else the first number, else None."""
    m = _EUR_NUM_RE.search(text or "")
    if m:
        return float(m.group(1))
    m = _NUM_RE.search(text or "")
    return float(m.group(0)) if m else None


def _coerce_int(value, message: str):
    """The integer a count answer should render: a carried int/integral-float value
    (never a bool), else the first integer parsed from the message."""
    if isinstance(value, bool):
        value = None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return _extract_int(message)


def _render_count(skeleton: str, n: int) -> str:
    """Substitute the integer into the count contract (answer_shape.msg_skeleton): a
    printf '%d' or a single '{slot}'. Ambiguous (multi-slot, no %d) -> '' (caller keeps
    the original)."""
    s = skeleton or ""
    if "%d" in s:
        return s.replace("%d", str(int(n)), 1)
    slots = _SLOT_RE.findall(s)
    if len(slots) == 1:
        return s.replace("{" + slots[0] + "}", str(int(n)))
    return ""


def _cell(row, col: str) -> str:
    v = row.get(col, "") if isinstance(row, dict) else getattr(row, col, "")
    return "" if v is None else str(v)


def _render_table(rows, columns) -> str:
    """TSV with a header row. '' when rows or columns are empty (caller keeps original)."""
    if not rows or not columns:
        return ""
    out = ["\t".join(columns)]
    for r in rows:
        out.append("\t".join(_cell(r, c) for c in columns))
    return "\n".join(out)


def _render_quote(rows, columns) -> str:
    """TSV rows WITHOUT a header. '' when rows or columns are empty."""
    if not rows or not columns:
        return ""
    return "\n".join("\t".join(_cell(r, c) for c in columns) for r in rows)
