"""DESIGN phase — single LLM call producing a tool_plan from instruction + AGENTS.MD.

Per H2/H13/H15: input strictly (instruction, agents_md_text). NO learn_ctx.
DESIGN is frozen per task run; LEARN feedback only feeds CODEGEN.
"""
from __future__ import annotations

import os

from .codegen_v2 import build_oracle_block
from .json_extract import _extract_json_from_text
from .llm import _resolve_model_for_phase
from .models import DesignOutput
from .prompt import load_prompt


def _call_llm_raw(*args, **kwargs):
    """Indirect through agent.pipeline so test patches on `agent.pipeline.call_llm_raw` apply."""
    from . import pipeline as _pipeline
    return _pipeline.call_llm_raw(*args, **kwargs)


class DesignError(RuntimeError):
    pass


_MAX_TOKENS_DESIGN = int(os.environ.get("MAX_TOKENS_DESIGN", "8192"))


def run_design(
    instruction: str,
    agents_md_text: str,
    token_out: dict | None = None,
    oracle_atoms: list | None = None,
) -> DesignOutput:
    """Run DESIGN phase. Returns DesignOutput or raises DesignError.

    H2/H13/H15: signature MUST NOT accept learn_ctx. `oracle_atoms` is read-only
    validated knowledge — DESIGN stays frozen-for-the-run; this is context, not
    per-cycle state.
    """
    guide = load_prompt("design") or "# PHASE: DESIGN"

    system: list[dict] = [
        {"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}},
    ]

    parts = []
    oracle_block = build_oracle_block(oracle_atoms)
    if oracle_block:
        parts.append(oracle_block)
    parts.append(f"INSTRUCTION:\n{instruction}")
    parts.append(f"AGENTS.MD:\n{agents_md_text}")
    user_msg = "\n\n".join(parts)

    model = _resolve_model_for_phase("design", os.environ.get("MODEL", ""))
    raw = _call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_DESIGN, token_out=token_out, phase="DESIGN")
    if not raw:
        raise DesignError("DESIGN LLM returned empty response")

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise DesignError(f"DESIGN: could not parse JSON; head: {raw[:200]!r}")

    try:
        return DesignOutput(**obj)
    except Exception as e:
        raise DesignError(f"DESIGN: pydantic validation failed: {e}; obj keys: {list(obj.keys())}") from e
