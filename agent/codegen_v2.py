"""CODEGEN phase v2 — translates a tool_plan to a Python `run(vm, params)` module."""
from __future__ import annotations

import os

from .json_extract import _extract_json_from_text
from .learned_store import _format_entry
from .llm import _resolve_model_for_phase
from .models import CodegenOutput, DesignOutput
from .prompt import load_prompt


def _call_llm_raw(*args, **kwargs):
    """Indirect through agent.pipeline so test patches on `agent.pipeline.call_llm_raw` apply."""
    from . import pipeline as _pipeline
    return _pipeline.call_llm_raw(*args, **kwargs)


class CodegenError(RuntimeError):
    pass


_MAX_TOKENS_CODEGEN = int(os.environ.get("MAX_TOKENS_CODEGEN", "8192"))


def _design_to_tool_plan_json(d: DesignOutput) -> str:
    return d.model_dump_json(indent=2)


def run_codegen(
    design: DesignOutput,
    learn_ctx: list[dict],
    prev_error: str | None,
    token_out: dict | None = None,
) -> CodegenOutput:
    """Translate `design.tool_plan` into a Python module. Returns CodegenOutput or raises."""
    guide = load_prompt("codegen") or "# PHASE: CODEGEN"

    system: list[dict] = [
        {"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}},
    ]

    parts = [
        f"TOOL_PLAN:\n{_design_to_tool_plan_json(design)}",
    ]
    if learn_ctx:
        def _fmt(e):
            if isinstance(e, dict):
                return _format_entry(e)
            return f"  - {e}"
        rule_lines = "\n".join(_fmt(e) for e in learn_ctx)
        parts.append(f"LEARNED_RULES (active):\n{rule_lines}")
    if prev_error:
        parts.append(f"PREVIOUS_ERROR:\n{prev_error}")

    user_msg = "\n\n".join(parts)

    model = _resolve_model_for_phase("codegen", os.environ.get("MODEL", ""))
    raw = _call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_CODEGEN, token_out=token_out)
    if not raw:
        raise CodegenError("CODEGEN LLM returned empty response")

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict) or "script_code" not in obj:
        raise CodegenError(f"CODEGEN: could not parse script_code from response; head: {raw[:200]!r}")

    return CodegenOutput(script_code=obj["script_code"])
