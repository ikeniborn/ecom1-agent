"""Atom model + YAML persistence for the knowledge oracle."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml


@dataclass
class Atom:
    id: str
    description: str
    domain: list[str]
    content: str
    source: str            # investigation | distilled | verdict
    validated_by: str      # manual | grader | fidelity
    validated_at: str
    status: str            # active | candidate
    embedding_hash: str = ""
    extra: dict = field(default_factory=dict)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_atoms(path: str | Path) -> list[Atom]:
    p = Path(path)
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    atoms: list[Atom] = []
    for d in raw:
        known = {k: d.get(k) for k in (
            "id", "description", "content", "source", "validated_by",
            "validated_at", "status")}
        known["domain"] = list(d.get("domain") or [])
        known["embedding_hash"] = d.get("embedding_hash") or ""
        atoms.append(Atom(**known))
    return atoms


def save_atoms(path: str | Path, atoms: list[Atom]) -> None:
    out = []
    for a in atoms:
        d = asdict(a)
        d.pop("extra", None)
        out.append(d)
    Path(path).write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
