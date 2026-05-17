"""Prompt loading utilities."""
from __future__ import annotations

from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent.parent / "data" / "prompts"
_CONFIG_DIR = Path(__file__).parent.parent / "data" / "config"

_BLOCKS: dict[str, str] = {}


def _load_all() -> None:
    if not _PROMPTS_DIR.exists():
        return
    for f in _PROMPTS_DIR.glob("*.md"):
        _BLOCKS[f.stem] = f.read_text(encoding="utf-8")


_load_all()


def load_prompt(name: str) -> str:
    """Return prompt block by file stem name. Returns '' if not found."""
    return _BLOCKS.get(name, "")


def load_task_blocks(task_type: str) -> list[str]:
    """Return list of prompt block stems for given task_type from data/config/task_blocks.yaml."""
    cfg_file = _CONFIG_DIR / "task_blocks.yaml"
    if not cfg_file.exists():
        return []
    try:
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        return list(cfg.get(task_type, cfg.get("default", [])))
    except Exception:
        return []
