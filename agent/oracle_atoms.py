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
    validated_by: str      # manual | grader | grader-oracle
    validated_at: str
    status: str            # active | candidate
    embedding_hash: str = ""
    source_task: str = ""   # task_id the candidate was distilled from (promote gate)
    polarity: str = "method"   # method | anti_pattern
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
        known["source_task"] = d.get("source_task") or ""
        known["polarity"] = d.get("polarity") or "method"
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


def build_oracle_block(oracle_atoms) -> str:
    """Render retrieved knowledge atoms for the PLAN prompt, split by polarity."""
    if not oracle_atoms:
        return ""
    methods = [a for a in oracle_atoms if getattr(a, "polarity", "method") != "anti_pattern"]
    antis = [a for a in oracle_atoms if getattr(a, "polarity", "method") == "anti_pattern"]
    lines: list[str] = []
    if methods:
        lines.append("## VALIDATED KNOWLEDGE — APPLY (verified methods)")
        for a in methods:
            lines.append(f"- ({', '.join(a.domain)}) {a.content.strip()}")
    if antis:
        lines.append("## ANTI-PATTERNS — AVOID (known failure causes)")
        for a in antis:
            lines.append(f"- ({', '.join(a.domain)}) {a.content.strip()}")
    return "\n".join(lines)
