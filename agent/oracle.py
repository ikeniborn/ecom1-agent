"""Knowledge oracle: validated atom bank + two-stage semantic retrieval."""
from __future__ import annotations

import math
import os
from pathlib import Path

from .oracle_atoms import Atom, load_atoms, save_atoms, content_hash
from . import llm

_DEFAULT_ATOMS = Path(__file__).resolve().parent.parent / "data" / "oracle" / "atoms.yaml"


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class KnowledgeOracle:
    def __init__(self, atoms=None, atoms_path=None, embed_fn=None):
        self._path = Path(atoms_path or _DEFAULT_ATOMS)
        self.atoms = atoms if atoms is not None else load_atoms(self._path)
        self._embed = embed_fn or llm.embed_texts
        self._model = os.environ.get("EMBED_MODEL", "nomic-embed-text")
        self._vec_cache: dict[str, list[float]] = {}

    def _active(self):
        return [a for a in self.atoms if a.status == "active"]

    def _embed_atom(self, a: Atom):
        h = content_hash(a.content)
        if h in self._vec_cache:
            return self._vec_cache[h]
        vec = self._embed([a.content], model=self._model)[0]
        self._vec_cache[h] = vec
        return vec

    def _cosine_topn(self, query: str, n: int):
        qv = self._embed([query], model=self._model)[0]
        scored = []
        for a in self._active():
            sv = self._embed_atom(a)
            scored.append((_cosine(qv, sv), a))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [a for _, a in scored[:n]]

    def _tag_fallback(self, query: str, n: int):
        q = query.lower()
        scored = []
        for a in self._active():
            score = sum(1 for tag in a.domain if tag.lower() in q)
            score += sum(1 for w in a.description.lower().split() if w in q)
            scored.append((score, a))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [a for s, a in scored[:n] if s > 0]

    def retrieve(self, task_text: str, k=None, rank_fn="default"):
        if os.environ.get("ORACLE_ENABLED", "1") == "0":
            return []
        k = k or int(os.environ.get("ORACLE_K", "4"))
        topn = int(os.environ.get("ORACLE_TOPN", "10"))
        try:
            cands = self._cosine_topn(task_text, topn)
        except Exception:
            return self._tag_fallback(task_text, k)
        if not cands:
            return []
        if rank_fn is None or os.environ.get("ORACLE_RANK_ENABLED", "1") == "0":
            return cands[:k]
        if rank_fn == "default":
            from .oracle_rank import llm_rerank
            rank_fn = llm_rerank
        try:
            return rank_fn(task_text, cands, k)[:k]
        except Exception:
            return cands[:k]
