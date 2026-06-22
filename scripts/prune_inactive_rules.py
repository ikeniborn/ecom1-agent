"""Phase 0 prune: drop inactive (status != 'active'), non-pinned entries from
data/learned/*.yaml. Behaviour-neutral — learned_store.load_entries() loads only
active entries, so inactive rules never reach runtime. Pinned entries always survive.
The git commit IS the archive (history retains pruned content); no legacy/ copy.

Usage:
    uv run python scripts/prune_inactive_rules.py            # prune all data/learned/*.yaml
    uv run python scripts/prune_inactive_rules.py --dry-run  # report counts only
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_LEARNED_DIR = Path(__file__).resolve().parent.parent / "data" / "learned"


def prune_entries(data: dict) -> tuple[dict, int]:
    """Return (pruned_data, dropped_count). Keep an entry iff status == 'active' OR
    pinned is truthy. All non-`entries` keys (task_id, last_run, ...) pass through."""
    entries = data.get("entries", []) or []
    kept = [e for e in entries
            if e.get("status") == "active" or e.get("pinned")]
    dropped = len(entries) - len(kept)
    out = dict(data)
    out["entries"] = kept
    return out, dropped


def prune_file(path: Path, dry_run: bool = False) -> int:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pruned, dropped = prune_entries(data)
    if dropped and not dry_run:
        path.write_text(
            yaml.safe_dump(pruned, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
    return dropped


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    total = 0
    files = sorted(_LEARNED_DIR.glob("*.yaml"))
    for p in files:
        d = prune_file(p, dry_run=dry_run)
        if d:
            print(f"{'[dry] ' if dry_run else ''}{p.name}: dropped {d}")
        total += d
    print(f"{'[dry] ' if dry_run else ''}Total dropped across {len(files)} files: {total}")


if __name__ == "__main__":
    main()
