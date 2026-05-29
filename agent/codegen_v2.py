"""CODEGEN phase v2 — translates a tool_plan to a Python `run(vm, params)` module."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .json_extract import _extract_json_from_text
from .llm import call_llm_raw, _resolve_model_for_phase
from .models import CodegenOutput, DesignOutput
from .prompt import load_prompt


class CodegenError(RuntimeError):
    pass


_PROTO_REF_PATH = Path(__file__).parent.parent / "docs" / "proto-api-reference.md"
_MAX_TOKENS_CODEGEN = int(os.environ.get("MAX_TOKENS_CODEGEN", "8192"))


def _proto_reference() -> str:
    try:
        return _PROTO_REF_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _design_to_tool_plan_json(d: DesignOutput) -> str:
    return d.model_dump_json(indent=2)


def run_codegen(
    design: DesignOutput,
    learn_ctx: list[dict],
    prev_error: str | None,
) -> CodegenOutput:
    """Translate `design.tool_plan` into a Python module. Returns CodegenOutput or raises."""
    guide = load_prompt("codegen") or "# PHASE: CODEGEN"
    proto_ref = _proto_reference()

    system: list[dict] = [
        {"type": "text", "text": proto_ref, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}},
    ]

    parts = [
        f"TOOL_PLAN:\n{_design_to_tool_plan_json(design)}",
    ]
    if learn_ctx:
        def _fmt(e):
            if isinstance(e, dict):
                return f"  - [{e.get('id', '?')}] {e.get('content', '')}"
            return f"  - {e}"
        rule_lines = "\n".join(_fmt(e) for e in learn_ctx)
        parts.append(f"LEARNED_RULES (active):\n{rule_lines}")
    if prev_error:
        parts.append(f"PREVIOUS_ERROR:\n{prev_error}")

    user_msg = "\n\n".join(parts)

    model = _resolve_model_for_phase("codegen", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_CODEGEN)
    if not raw:
        raise CodegenError("CODEGEN LLM returned empty response")

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict) or "script_code" not in obj:
        raise CodegenError(f"CODEGEN: could not parse script_code from response; head: {raw[:200]!r}")

    return CodegenOutput(script_code=obj["script_code"])
