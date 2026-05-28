"""LLM-assembler: builds unified_context from all prompt sources per pipeline cycle."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .llm import call_llm_raw, _resolve_model_for_phase
from .prompt import load_prompt
from .prephase import PrephaseResult, _format_schema_digest

_LEARNED_DIR = Path(__file__).parent.parent / "data" / "learned"


@dataclass
class AssembledPrompt:
    unified_context: str


def load_learned_ctx(task_id: str) -> list[str]:
    """Return content of active entries from data/learned/{task_id}.yaml."""
    entries = load_learned_entries(task_id)
    return [e["content"] for e in entries if e.get("status") == "active"]


def load_learned_entries(task_id: str) -> list[dict]:
    """Return all entries (active + inactive) from data/learned/{task_id}.yaml."""
    if not task_id:
        return []
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        return list(data.get("entries", []))
    except Exception:
        return []


def load_last_run(task_id: str) -> dict | None:
    """Return last_run metadata from data/learned/{task_id}.yaml, or None."""
    if not task_id:
        return None
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data.get("last_run") or None
    except Exception:
        return None


def save_last_run(
    task_id: str,
    status: str,
    outcome: str,
    cycles_used: int,
    grounding_refs_count: int = 0,
    heuristic_valid: bool = False,
    schema_hash: str = "",
) -> None:
    """Write last_run metadata to data/learned/{task_id}.yaml."""
    if not task_id:
        return
    from datetime import date
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    else:
        data = {}
    data["task_id"] = task_id
    data["last_run"] = {
        "status": status,
        "outcome": outcome,
        "cycles_used": cycles_used,
        "grounding_refs_count": grounding_refs_count,
        "heuristic_valid": heuristic_valid,
        "schema_hash": schema_hash,
        "date": str(date.today()),
    }
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def _next_entry_id(entries: list[dict]) -> str:
    """Generate next monotonic id rNNN (never reuses existing ids)."""
    used: set[int] = set()
    for e in entries:
        eid = e.get("id", "")
        if isinstance(eid, str) and eid.startswith("r") and eid[1:].isdigit():
            used.add(int(eid[1:]))
    return f"r{(max(used, default=0) + 1):03d}"


def _apply_learn_diff(
    task_id: str,
    rule_content: str,
    reasoning: str,
    deactivate: list[str],
    deactivate_reason: str | None,
    source: str = "learn",
) -> None:
    """Append new rule entry and deactivate specified entries in data/learned/{task_id}.yaml."""
    if not task_id:
        return
    from datetime import date
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    else:
        data = {}
    entries: list[dict] = list(data.get("entries", []))
    for entry in entries:
        if entry.get("id") in deactivate:
            entry["status"] = "inactive"
            entry["deactivated_reason"] = deactivate_reason or "Deactivated by consolidation"
    _content = (rule_content or "").strip()
    _reasoning = (reasoning or "").strip()
    _MIN_CONTENT = 20
    _VALID_STARTS = ("never", "always", "use", "do not", "when", "if", "prefer")
    if len(_content) < _MIN_CONTENT or not _content.lower().startswith(_VALID_STARTS):
        return
    entries.append({
        "id": _next_entry_id(entries),
        "content": _content,
        "status": "active",
        "source": source,
        "created": str(date.today()),
        "reasoning": _reasoning,
        "deactivated_reason": None,
    })
    path.write_text(
        yaml.dump({"task_id": task_id, "entries": entries}, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def _build_sources(
    task_text: str,
    task_type: str,
    prephase_result: PrephaseResult,
    learn_ctx: list[str],
    last_run: dict | None = None,
) -> str:
    parts: list[str] = []
    parts.append(f"TASK_TEXT: {task_text}")
    parts.append(f"TASK_TYPE: {task_type}")
    if last_run:
        parts.append(
            "## LAST_RUN\n"
            f"status: {last_run.get('status', 'unknown')}\n"
            f"outcome: {last_run.get('outcome', 'unknown')}\n"
            f"cycles_used: {last_run.get('cycles_used', '?')}\n"
            f"date: {last_run.get('date', 'unknown')}"
        )
    if learn_ctx:
        parts.append("## LEARNED (highest priority)\n" + "\n".join(f"- {r}" for r in learn_ctx))
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
        meta.append(f"runtime_identity: {pre.agent_id}")
    if pre.agent_store_id:
        meta.append(f"agent_store_id: {pre.agent_store_id}")
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
    assembler_guide = load_prompt("assembler")
    last_run = load_last_run(task_id) if task_id else None
    sources = _build_sources(task_text, task_type, prephase_result, learn_ctx, last_run)
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
