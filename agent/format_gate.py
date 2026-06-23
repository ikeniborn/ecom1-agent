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


_MONEY_SKELETON_RE = re.compile(r"^EUR\s+[\{\}\w.]+$")   # bare 'EUR <amount>' only
_MONEY_REGEX_RE = re.compile(r"EUR\s*\\d")               # anchored EUR-cents success regex
_COUNT_MARK_RE = re.compile(r"%d|<\s*COUNT|\[\s*QTY|<\s*QTY|qty\s*=|count\s*:", re.I)
_COUNT_SLOT_ONLY_RE = re.compile(r"^\s*\{([^{}]+)\}\s*$")


def _outcome_regexes(intent, outcome: str) -> list[str]:
    """The regex_match patterns a verify success_criterion applies to the answer message
    for `outcome` (lhs $answer.message or the legacy $answer.msg)."""
    out: list[str] = []
    for crit in (getattr(intent, "success_criteria", {}) or {}).get(outcome, []):
        op = getattr(crit, "op", None)
        lhs = getattr(crit, "lhs", None)
        rhs = getattr(crit, "rhs", None)
        if op == "regex_match" and lhs in ("$answer.message", "$answer.msg") and isinstance(rhs, str):
            out.append(rhs)
    return out


def _is_count_slot_only(skeleton: str) -> bool:
    m = _COUNT_SLOT_ONLY_RE.match(skeleton or "")
    return bool(m and re.search(r"count|qty|total|num", m.group(1), re.I))


def detect_shape(intent, answer_shape, outcome: str, value=None) -> str:
    """The typed shape to reshape into: explicit answer_shape.kind wins; otherwise infer
    from the skeleton + success_criteria regex. Returns one of
    money/boolean/count/table/quote/free. Conservative — anything unrecognised is 'free'
    (passthrough). Over-detecting money is the only unsafe case and is guarded by the
    bare-EUR / anchored-regex signals."""
    kind = (getattr(answer_shape, "kind", "") or "").strip().lower()
    if kind in {"money", "boolean", "count", "table", "quote", "free"}:
        return kind
    skel = (getattr(answer_shape, "msg_skeleton", "") or "").strip()
    rxs = _outcome_regexes(intent, outcome)
    if _BOOL_TOK_RE.search(skel) or any(_BOOL_TOK_RE.search(rx) for rx in rxs):
        return "boolean"
    if _MONEY_SKELETON_RE.match(skel) or any(_MONEY_REGEX_RE.search(rx) for rx in rxs):
        return "money"
    if _COUNT_MARK_RE.search(skel) or _is_count_slot_only(skel):
        return "count"
    return "free"


def already_exact(message: str, intent, answer_shape, outcome: str) -> bool:
    """True when the message already satisfies every declared answer-message regex for
    the outcome (short-circuit: leave a correct surface untouched)."""
    rxs = _outcome_regexes(intent, outcome)
    return bool(rxs) and all(re.search(rx, message or "") for rx in rxs)


def _is_preserved_outcome(outcome: str) -> bool:
    """Negative/terminal outcomes whose message is never reshaped (spec: 'preserve
    non-OK messages'). OK-like custom outcomes (e.g. OUTCOME_DIFFERENCE_EXCEEDS) are
    formatted."""
    o = outcome or ""
    return o.startswith("OUTCOME_NONE") or "DENIED" in o


def _format_for_shape(shape, message, intent, answer_shape, agents_md, value, rows) -> str:
    skel = getattr(answer_shape, "msg_skeleton", "") or ""
    if shape == "money":
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else _extract_eur_number(message)
        return format_eur(num) if num is not None else ""
    if shape == "boolean":
        yes_tok, no_tok = bool_tokens(agents_md, answer_shape)
        return _canonicalize_bool(message, yes_tok, no_tok, skel)
    if shape == "count":
        n = _coerce_int(value, message)
        return _render_count(skel, n) if n is not None else ""
    if shape == "table":
        return _render_table(rows or [], list(getattr(answer_shape, "columns", []) or []))
    if shape == "quote":
        return _render_quote(rows or [], list(getattr(answer_shape, "columns", []) or []))
    return ""


def format_answer(message: str, intent, answer_shape, agents_md, *,
                  outcome: str = "OUTCOME_OK", value=None, rows=None) -> str:
    """Reshape an OK-like answer message into its exact surface contract. Best-effort:
    a preserved (negative) outcome, a free-text shape, an already-exact message, or any
    failure returns the message unchanged. Never raises.

    The 4 positional params are the spec's signature; outcome/value/rows are keyword-only
    additions (outcome gates the passthrough; value/rows are the interpreter-carried typed
    data the gate renders from)."""
    try:
        if _is_preserved_outcome(outcome):
            return message
        cleaned = _strip_outcome_prefix(message)
        if already_exact(cleaned, intent, answer_shape, outcome):
            return cleaned
        shape = detect_shape(intent, answer_shape, outcome, value)
        if shape == "free":
            return cleaned
        out = _format_for_shape(shape, cleaned, intent, answer_shape, agents_md, value, rows)
        return out or cleaned
    except Exception as e:                       # never corrupt the answer
        print(f"[format_gate] skipped ({e}); keeping original message")
        return message
