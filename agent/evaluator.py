"""Post-execution pipeline evaluator. Fail-open: any exception returns None."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .llm import call_llm_raw
from .json_extract import _extract_json_from_text
from .models import PipelineEvalOutput
from .prompt import load_prompt
from . import knowledge_loader


@dataclass
class EvalInput:
    task_text: str
    sgr_trace: list[dict]
    cycles: int
    final_outcome: str
    task_id: str = ""
    task_type: str = "sql"
    prephase: dict = field(default_factory=dict)
    learn_ctx: list[str] = field(default_factory=list)


def _compute_eval_metrics(
    task_text: str,
    agents_md_index: dict,
    executed_queries: list[str],
    schema_digest: dict,
    sql_plan_outputs: list,
) -> dict:
    """Compute agents_md_coverage and schema_grounding. Returns dict with both floats."""
    # agents_md_coverage — match sections whose content OR key contains a task word (>3 chars)
    task_words = {w.lower() for w in task_text.split() if len(w) > 3}
    index_terms_in_task = {
        k for k, lines in agents_md_index.items()
        if any(w in (" ".join(lines) + " " + k).lower() for w in task_words)
    }
    refs_used: set[str] = set()
    for plan in sql_plan_outputs:
        if hasattr(plan, "agents_md_refs"):
            refs_used.update(plan.agents_md_refs)
    if index_terms_in_task:
        coverage = len(index_terms_in_task & refs_used) / len(index_terms_in_task)
    else:
        coverage = 1.0

    # schema_grounding
    known_cols: set[str] = set()
    for table_info in schema_digest.get("tables", {}).values():
        for col in table_info.get("columns", []):
            known_cols.add(col.get("name", ""))
    known_cols.discard("")

    table_col_refs = []
    for q in executed_queries:
        table_col_refs.extend(re.findall(r'\b\w+\.(\w+)\b', q))

    if table_col_refs and known_cols:
        grounding = sum(1 for c in table_col_refs if c in known_cols) / len(table_col_refs)
    else:
        grounding = 1.0

    return {"agents_md_coverage": coverage, "schema_grounding": grounding}


def run_evaluator(
    eval_input: EvalInput,
    model: str,
    cfg: dict,
) -> PipelineEvalOutput | None:
    """Evaluate pipeline trace. Returns PipelineEvalOutput or None on any failure."""
    try:
        return _run(eval_input, model, cfg)
    except Exception as e:
        print(f"[evaluator] non-fatal error: {e}")
        return None


def _run(eval_input: EvalInput, model: str, cfg: dict) -> PipelineEvalOutput | None:
    rules_md = knowledge_loader.existing_rules_text()
    security_md = knowledge_loader.existing_security_text()
    prompts_md = knowledge_loader.existing_prompts_text()

    system = _build_eval_system(
        eval_input.prephase.get("agents_md", ""),
        rules_md, security_md, prompts_md,
    )
    user_msg = json.dumps({
        "task_text": eval_input.task_text,
        "task_type": eval_input.task_type,
        "learn_ctx": eval_input.learn_ctx,
        "sgr_trace": eval_input.sgr_trace,
        "cycles": eval_input.cycles,
        "final_outcome": eval_input.final_outcome,
    }, ensure_ascii=False)

    raw = call_llm_raw(system, user_msg, model, cfg, max_tokens=2048)
    if not raw:
        return None

    parsed = _extract_json_from_text(raw)
    if not isinstance(parsed, dict):
        return None

    try:
        result = PipelineEvalOutput.model_validate(parsed)
    except Exception:
        return None

    return result


def _build_eval_system(
    agents_md: str,
    rules_md: str = "",
    security_md: str = "",
    prompts_md: str = "",
) -> str:
    parts: list[str] = []
    if agents_md:
        parts.append(f"# VAULT RULES\n{agents_md}")
    if rules_md:
        parts.append(f"# EXISTING RULES\n{rules_md}")
    if security_md:
        parts.append(f"# EXISTING SECURITY GATES\n{security_md}")
    if prompts_md:
        parts.append(f"# EXISTING PROMPT CONTENT\n{prompts_md}")
    guide = load_prompt("pipeline_evaluator")
    if guide:
        parts.append(guide)
    return "\n\n".join(parts)
