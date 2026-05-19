#!/usr/bin/env python3
"""One-time migration: convert flat list data/learned/{task_id}.yaml to new entry schema.

Run once before the first pipeline run after deploying the learned knowledge redesign.
Safe to run multiple times — skips files already in new schema format.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

_LEARNED_DIR = Path(__file__).parent.parent / "data" / "learned"


def _migrate_file(path: Path) -> bool:
    """Return True if migrated, False if already in new format or skipped."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  SKIP {path.name}: parse error: {e}")
        return False

    if not isinstance(data, dict):
        print(f"  SKIP {path.name}: not a dict")
        return False

    if "entries" in data:
        print(f"  SKIP {path.name}: already migrated")
        return False

    task_id = data.get("task_id", path.stem)
    old_ctx: list[str] = data.get("learn_ctx", [])

    today = str(date.today())
    entries = [
        {
            "id": f"r{i + 1:03d}",
            "content": rule,
            "status": "active",
            "source": "learn",
            "created": today,
            "reasoning": "",
            "deactivated_reason": None,
        }
        for i, rule in enumerate(old_ctx)
        if isinstance(rule, str) and rule.strip()
    ]

    new_data = {"task_id": task_id, "entries": entries}
    path.write_text(
        yaml.dump(new_data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"  MIGRATED {path.name}: {len(entries)} entries")
    return True


def main() -> None:
    if not _LEARNED_DIR.exists():
        print(f"No learned directory at {_LEARNED_DIR} — nothing to migrate.")
        return

    files = sorted(_LEARNED_DIR.glob("*.yaml"))
    if not files:
        print("No .yaml files in data/learned/ — nothing to migrate.")
        return

    print(f"Migrating {len(files)} file(s) in {_LEARNED_DIR}:")
    migrated = sum(_migrate_file(f) for f in files)
    print(f"\nDone: {migrated}/{len(files)} file(s) migrated.")


if __name__ == "__main__":
    main()
