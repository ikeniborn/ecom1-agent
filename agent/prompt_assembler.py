"""LLM-assembler: builds unified_context from all prompt sources per pipeline cycle."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .llm import call_llm_raw, _resolve_model_for_phase
from .prompt import load_prompt, load_task_blocks
from .prephase import PrephaseResult, _format_schema_digest
from .rules_loader import RulesLoader
from .sql_security import load_security_gates

_RULES_DIR = Path(__file__).parent.parent / "data" / "rules"
_SECURITY_DIR = Path(__file__).parent.parent / "data" / "security"
_LEARNED_DIR = Path(__file__).parent.parent / "data" / "learned"


@dataclass
class AssembledPrompt:
    unified_context: str


def load_learned_ctx(task_id: str) -> list[str]:
    """Load persisted learn_ctx from prior failed run, or [] if none."""
    if not task_id:
        return []
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return list(data.get("learn_ctx", []))
    except Exception:
        return []


def save_learned_ctx(task_id: str, learn_ctx: list[str]) -> None:
    """Persist learn_ctx to data/learned/{task_id}.yaml on pipeline failure."""
    if not task_id or not learn_ctx:
        return
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    path = _LEARNED_DIR / f"{task_id}.yaml"
    path.write_text(
        yaml.dump({"task_id": task_id, "learn_ctx": learn_ctx}, allow_unicode=True),
        encoding="utf-8",
    )


def clear_learned_ctx(task_id: str) -> None:
    """Delete data/learned/{task_id}.yaml on pipeline success."""
    if not task_id:
        return
    path = _LEARNED_DIR / f"{task_id}.yaml"
    path.unlink(missing_ok=True)


def _build_sources(
    task_text: str,
    task_type: str,
    prephase_result: PrephaseResult,
    learn_ctx: list[str],
) -> str:
    parts: list[str] = []

    parts.append(f"TASK_TEXT: {task_text}")
    parts.append(f"TASK_TYPE: {task_type}")

    if learn_ctx:
        parts.append("## LEARNED (highest priority)\n" + "\n".join(f"- {r}" for r in learn_ctx))

    rules_loader = RulesLoader(_RULES_DIR)
    rules_md = rules_loader.get_rules_markdown(phase="sql_plan", verified_only=True)
    if rules_md:
        parts.append(f"## RULES\n{rules_md}")

    security_gates = load_security_gates(_SECURITY_DIR)
    if security_gates:
        gate_lines = "\n".join(f"- [{g['id']}] {g.get('message', '')}" for g in security_gates)
        parts.append(f"## SECURITY\n{gate_lines}")

    block_names = load_task_blocks(task_type)
    block_texts = [load_prompt(name) for name in block_names if load_prompt(name)]
    if block_texts:
        parts.append("## PROMPT_BLOCKS\n" + "\n\n".join(block_texts))

    pre = prephase_result
    if pre.agents_md_content:
        parts.append(f"## VAULT\n{pre.agents_md_content}")

    if pre.schema_digest:
        parts.append(f"## SCHEMA_DIGEST\n{_format_schema_digest(pre.schema_digest)}")
    if pre.db_schema:
        parts.append(f"## DB_SCHEMA\n{pre.db_schema}")

    meta: list[str] = []
    if pre.current_date:
        meta.append(f"date: {pre.current_date}")
    if pre.agent_id:
        meta.append(f"customer_id: {pre.agent_id}")
    if meta:
        parts.append("## AGENT_CONTEXT\n" + "\n".join(meta))

    return "\n\n".join(parts)


def assemble_prompt(
    task_text: str,
    task_type: str,
    prephase_result: PrephaseResult,
    learn_ctx: list[str],
    model: str,
    cfg: dict,
    task_id: str = "",
) -> AssembledPrompt:
    """Call LLM assembler to produce unified_context from all sources."""
    persisted = load_learned_ctx(task_id)
    merged_ctx = list(dict.fromkeys(persisted + learn_ctx))

    assembler_guide = load_prompt("assembler")
    sources = _build_sources(task_text, task_type, prephase_result, merged_ctx)
    assembler_model = _resolve_model_for_phase("assembler", model)

    raw = call_llm_raw(
        assembler_guide or "Assemble unified context from sources.",
        sources,
        assembler_model,
        cfg,
        max_tokens=4096,
        plain_text=True,
    )

    unified = raw or sources
    return AssembledPrompt(unified_context=unified)
