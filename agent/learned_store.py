"""Per-task learned knowledge store. Replaces helpers from prompt_assembler."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from .models import LearnConsolidateOutput

_LEARNED_DIR = Path(__file__).parent.parent / "data" / "learned"

_MIN_CONTENT_LEN = 20
_VALID_RULE_STARTS = ("never", "always", "use", "do not", "when", "if", "prefer")


def _read(tid: str) -> dict:
    if not tid:
        return {}
    path = _LEARNED_DIR / f"{tid}.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write(tid: str, data: dict) -> None:
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    (_LEARNED_DIR / f"{tid}.yaml").write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def _next_entry_id(entries: list[dict]) -> str:
    used = {
        int(e["id"][1:])
        for e in entries
        if isinstance(e.get("id"), str) and e["id"].startswith("r") and e["id"][1:].isdigit()
    }
    return f"r{(max(used, default=0) + 1):03d}"


def _next_verdict_id(entries: list[dict]) -> str:
    used = {
        int(e["id"][1:])
        for e in entries
        if isinstance(e.get("id"), str) and e["id"].startswith("v") and e["id"][1:].isdigit()
    }
    return f"v{(max(used, default=0) + 1):03d}"


def _format_entry(e: dict) -> str:
    """Render one learn_ctx entry for an LLM prompt. Verdict entries have
    content=None and must show their score_detail instead."""
    if e.get("source") == "verdict":
        detail = "; ".join(e.get("score_detail") or [])
        return f"  - [{e.get('id', '?')}] VERDICT score={e.get('score', '?')}: {detail}"
    return f"  - [{e.get('id', '?')}] {e.get('content', '')}"


def load_entries(tid: str) -> list[dict]:
    """Return active entries only."""
    data = _read(tid)
    return [e for e in data.get("entries", []) if e.get("status") == "active"]


def apply_learn_diff(tid: str, out: LearnConsolidateOutput) -> None:
    """Append new rule + deactivate listed ids. Skip path writes nothing."""
    if not tid or out.skip:
        return

    content = (out.rule_content or "").strip()
    if len(content) < _MIN_CONTENT_LEN or not content.lower().startswith(_VALID_RULE_STARTS):
        return

    data = _read(tid)
    entries: list[dict] = list(data.get("entries", []))

    deact_ids = set(out.deactivate_ids or [])
    for e in entries:
        if e.get("id") in deact_ids:
            e["status"] = "inactive"
            e["deactivated_reason"] = out.deactivate_reason or "superseded"

    entries.append({
        "id": _next_entry_id(entries),
        "content": content,
        "agents_md_anchor": out.agents_md_anchor,
        "reasoning": (out.reasoning or "").strip(),
        "status": "active",
        "created": str(date.today()),
        "deactivated_reason": None,
    })

    data["task_id"] = tid
    data["entries"] = entries
    _write(tid, data)


def save_last_run(
    tid: str,
    status: str,
    outcome: str,
    cycles_used: int,
) -> None:
    """Persist last_run metadata. No heuristic_valid, no schema_hash."""
    if not tid:
        return
    data = _read(tid)
    data["task_id"] = tid
    data["last_run"] = {
        "status": status,
        "outcome": outcome,
        "cycles_used": cycles_used,
        "date": str(date.today()),
    }
    _write(tid, data)


def write_verdict(
    tid: str,
    score: float,
    score_detail: list[str],
    submitted_message: str,
    submitted_outcome: str,
    submitted_refs: list[str],
) -> None:
    """Record grader feedback as a `source: verdict` entry in entries[].

    One active verdict per task: writing a new one deactivates all prior
    `source: verdict` entries. `content: null` flags this as a fact, not a
    rule — `apply_learn_diff` validation is bypassed (this writes directly).
    """
    if not tid:
        return
    data = _read(tid)
    entries: list[dict] = list(data.get("entries", []))

    for e in entries:
        if e.get("source") == "verdict" and e.get("status") == "active":
            e["status"] = "inactive"
            e["deactivated_reason"] = "superseded by newer verdict"

    entries.append({
        "id": _next_verdict_id(entries),
        "source": "verdict",
        "score": score,
        "score_detail": list(score_detail or []),
        "submitted_message": submitted_message,
        "submitted_outcome": submitted_outcome,
        "submitted_refs": list(submitted_refs or []),
        "status": "active",
        "created": str(date.today()),
        "content": None,
    })

    data["task_id"] = tid
    data["entries"] = entries
    _write(tid, data)
