# agent/reason.py
"""INTENT + PLAN LLM phases. The model emits data (IntentSpec / PlanIR), never code."""
from __future__ import annotations

import os
from typing import Any

from .oracle_atoms import build_oracle_block
from .ir_models import IntentSpec, PlanIR
from .json_extract import _extract_json_from_text
from .learned_store import _format_entry
from .llm import _resolve_model_for_phase
from .prompt import load_prompt

_MAX_TOKENS_INTENT = int(os.environ.get("MAX_TOKENS_INTENT", "4096"))
_MAX_TOKENS_PLAN = int(os.environ.get("MAX_TOKENS_PLAN", "8192"))


class IntentError(RuntimeError):
    pass


class PlanError(RuntimeError):
    pass


def _call_llm_raw(*args, **kwargs):
    from . import pipeline as _pipeline
    return _pipeline.call_llm_raw(*args, **kwargs)


def _facts_sufficiency(facts: Any) -> list[str]:
    """gather_status keys whose value is not 'ok' (empty or error) — P8 signal."""
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    status = facts.get("gather_status", {}) if isinstance(facts, dict) else {}
    return [k for k, v in status.items() if v != "ok"]


def _facts_block(facts: Any) -> str:
    if facts is None:
        return ""
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    parts = []
    for key in ("agents_md", "schema", "sample_rows", "docs_inventory",
                "policies", "identity", "target_records", "path_listings",
                "gather_status"):
        val = facts.get(key) if isinstance(facts, dict) else None
        if val:
            parts.append(f"## {key}\n{val if isinstance(val, str) else val}")
    block = "PRE-PHASE FACTS:\n" + "\n\n".join(str(p) for p in parts)
    nonok = _facts_sufficiency(facts)
    if nonok:
        status = facts.get("gather_status", {}) if isinstance(facts, dict) else {}
        block += "\n\nFACT_STATUS (non-ok): " + ", ".join(f"{k}={status.get(k)}" for k in nonok)
    return block


def run_intent(facts, instruction: str, token_out: dict | None = None) -> IntentSpec:
    guide = load_prompt("intent") or "# PHASE: INTENT"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
    user = "\n\n".join(p for p in [_facts_block(facts), f"INSTRUCTION:\n{instruction}"] if p)
    model = _resolve_model_for_phase("intent", os.environ.get("MODEL", ""))
    raw = _call_llm_raw(system, user, model, {}, max_tokens=_MAX_TOKENS_INTENT, token_out=token_out, phase="INTENT")
    if not raw:
        raise IntentError("INTENT LLM returned empty response")
    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise IntentError(f"INTENT: could not parse JSON; head: {raw[:200]!r}")
    try:
        return IntentSpec(**obj)
    except Exception as e:
        raise IntentError(f"INTENT: validation failed: {e}") from e


def run_plan(intent: IntentSpec, facts, learn_ctx: list[dict], prev_error: str | None,
             token_out: dict | None = None, oracle_atoms: list | None = None,
             observed: list[str] | None = None) -> PlanIR:
    guide = load_prompt("plan") or "# PHASE: PLAN"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
    parts = []
    ob = build_oracle_block(oracle_atoms)
    if ob:
        parts.append(ob)
    parts.append(f"INTENT_SPEC:\n{intent.model_dump_json(indent=2)}")
    parts.append(_facts_block(facts))
    if learn_ctx:
        parts.append("LEARNED_RULES (active):\n" + "\n".join(_format_entry(e) for e in learn_ctx))
    if observed:
        parts.append("OBSERVED_RPC_OUTPUTS:\n" + "\n".join(observed))
    if prev_error:
        parts.append(f"PREVIOUS_ERROR:\n{prev_error}")
    user = "\n\n".join(p for p in parts if p)
    model = _resolve_model_for_phase("plan", os.environ.get("MODEL", ""))
    raw = _call_llm_raw(system, user, model, {}, max_tokens=_MAX_TOKENS_PLAN, token_out=token_out, phase="PLAN")
    if not raw:
        raise PlanError("PLAN LLM returned empty response")
    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise PlanError(f"PLAN: could not parse JSON; head: {raw[:200]!r}")
    try:
        return PlanIR(**obj)
    except Exception as e:
        raise PlanError(f"PLAN: validation failed: {e}") from e
