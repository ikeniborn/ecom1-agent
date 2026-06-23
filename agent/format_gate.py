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
