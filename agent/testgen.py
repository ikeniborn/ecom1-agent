"""TEST-GEN phase — single LLM call producing intent-driven acceptance tests.

Mirrors `agent/design.py`: one frozen-per-run LLM call. Input is the DESIGN
output (intent / success_criteria / answer_template / agents_md_constraints) plus
the raw instruction. Output is a `TestSpec` whose `test_sql` / `test_answer`
source strings are executed against captured runtime data by `agent.test_runner`.

The tests encode the run intent: a correct answer must turn them green before the
pipeline submits to the grader. AGENTS.MD rules reach the tests via DESIGN's
`agents_md_constraints`.
"""
from __future__ import annotations

import os

from .json_extract import _extract_json_from_text
from .llm import _resolve_model_for_phase
from .models import DesignOutput, TestSpec
from .prompt import load_prompt


def _call_llm_raw(*args, **kwargs):
    """Indirect through agent.pipeline so test patches on `agent.pipeline.call_llm_raw` apply."""
    from . import pipeline as _pipeline
    return _pipeline.call_llm_raw(*args, **kwargs)


class TestGenError(RuntimeError):
    pass


_MAX_TOKENS_TEST = int(os.environ.get("MAX_TOKENS_TEST", "2048"))


def _build_user_msg(design: DesignOutput, instruction: str) -> str:
    crit = "\n".join(f"- {c}" for c in design.success_criteria) or "(none)"
    constraints = "\n".join(
        f"- [{c.anchor}] {c.rule}" for c in design.agents_md_constraints
    ) or "(none)"
    at = design.answer_template
    answer_template = (
        f"message: {at.message}\noutcome: {at.outcome}\nrefs: {list(at.refs)}"
    )
    return (
        f"INTENT:\n{design.intent}\n\n"
        f"SUCCESS_CRITERIA:\n{crit}\n\n"
        f"ANSWER_TEMPLATE:\n{answer_template}\n\n"
        f"AGENTS_MD_CONSTRAINTS:\n{constraints}\n\n"
        f"INSTRUCTION:\n{instruction}"
    )


def run_test_gen(
    design: DesignOutput,
    instruction: str,
    token_out: dict | None = None,
) -> TestSpec:
    """Run TEST-GEN phase. Returns TestSpec or raises TestGenError.

    Frozen per task run (like DESIGN) — the tests do not change across CODEGEN
    cycles, so a red→green transition reflects the script improving, not the
    bar moving.
    """
    guide = load_prompt("test") or "# PHASE: TEST-GEN\nGenerate sql_tests and answer_tests as JSON."
    system: list[dict] = [
        {"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}},
    ]

    user_msg = _build_user_msg(design, instruction)

    model = _resolve_model_for_phase("test", os.environ.get("MODEL", ""))
    raw = _call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_TEST, token_out=token_out)
    if not raw:
        raise TestGenError("TEST-GEN LLM returned empty response")

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise TestGenError(f"TEST-GEN: could not parse JSON; head: {raw[:200]!r}")

    try:
        return TestSpec(**obj)
    except Exception as e:
        raise TestGenError(f"TEST-GEN: pydantic validation failed: {e}; obj keys: {list(obj.keys())}") from e
