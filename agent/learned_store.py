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
