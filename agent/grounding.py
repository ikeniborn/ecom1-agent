"""Deterministic ref-grounding (0 LLM): re-derive required /proc and /docs refs from
the VM + task text + computed answer. Best-effort — ground_refs never raises; any single
resolution failure drops that one ref. The model's declared refs are hints; this module
produces the authoritative set that replaces answer.refs (the muxx exoskeleton pattern).
"""
from __future__ import annotations

import os
import re

# Entity-id / SKU shapes (STO-2R84BSHQ, SKU-FK). Mechanism, not per-task values.
_ID_RE = re.compile(r"\b[A-Z]{2,4}-[A-Z0-9]{2,12}\b")
# Prefixed ids (basket_12, ord_45, cust_016): an allowlist of entity prefixes trims most
# schema words. It is NOT exhaustive — allowlisted prefixes still match SQL columns like
# 'order_id'/'return_reason'; such false positives are harmless because callers
# stat-validate every resolved record path against the live /proc tree (Task 2+), dropping
# tokens that do not resolve. Broad extraction + strict validation is the chosen tradeoff.
_PREFIXED_ID_RE = re.compile(
    r"\b(?:basket|order|ord|return|ret|payment|pay|invoice|inv|customer|cust|shipment|ship)"
    r"_[A-Za-z0-9]+\b",
    re.IGNORECASE,
)


# Note: agent/orchestrator.py:_extract_entity_tokens is a SEPARATE pre-phase extractor
# (quoted strings + capitalized n-grams); this one targets dash/prefixed entity IDs. Distinct roles.
def extract_entity_tokens(*texts: str) -> list[str]:
    """Entity IDs/SKUs found across the given texts (task text, answer message).
    Deterministic, order-preserving, deduped."""
    toks: list[str] = []
    for t in texts:
        for rx in (_ID_RE, _PREFIXED_ID_RE):
            for m in rx.findall(t or ""):
                if m not in toks:
                    toks.append(m)
    return toks
