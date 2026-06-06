"""Knowledge oracle: validated atom bank + two-stage semantic retrieval."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from .oracle_atoms import Atom, load_atoms, save_atoms, content_hash
from . import llm
from .llm import call_llm_json

_DEFAULT_ATOMS = Path(__file__).resolve().parent.parent / "data" / "oracle" / "atoms.yaml"
_DEFAULT_EMBEDDINGS = Path(__file__).resolve().parent.parent / "data" / "oracle" / "embeddings.json"


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class KnowledgeOracle:
    def __init__(self, atoms=None, atoms_path=None, embed_fn=None, embeddings_path=None):
        self._path = Path(atoms_path or _DEFAULT_ATOMS)
        self.atoms = atoms if atoms is not None else load_atoms(self._path)
        self._embed = embed_fn or llm.embed_texts
        self._model = os.environ.get("EMBED_MODEL", "nomic-embed-text")
        self._emb_path = Path(embeddings_path or _DEFAULT_EMBEDDINGS)
        self._vec_cache: dict[str, list[float]] = self._load_vec_cache()

    def _load_vec_cache(self) -> dict:
        """Load persisted atom vectors. Corrupt/missing file → empty (rebuild)."""
        try:
            data = json.loads(self._emb_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_vec_cache(self) -> None:
        """Persist atom vectors. Non-critical — failure is silently ignored."""
        try:
            self._emb_path.parent.mkdir(parents=True, exist_ok=True)
            self._emb_path.write_text(json.dumps(self._vec_cache), encoding="utf-8")
        except Exception:
            pass

    def _active(self):
        return [a for a in self.atoms if a.status == "active"]

    def _embed_atom(self, a: Atom):
        h = content_hash(a.content)
        if h in self._vec_cache:
            return self._vec_cache[h]
        vec = self._embed([a.content], model=self._model, prefix="search_document")[0]
        self._vec_cache[h] = vec
        self._save_vec_cache()
        return vec

    def _cosine_topn(self, query: str, n: int):
        qv = self._embed([query], model=self._model, prefix="search_query")[0]
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

    _DISTILL_SYS = (
        "Distill a single REUSABLE coding-knowledge atom from a learned rule. "
        "Strip all run-specific values (ids, paths, skus, amounts). Return JSON "
        "{id, description, domain:[..], content}. content is a general method or fact."
    )

    def add_candidate(self, atom):
        self.atoms.append(atom)
        save_atoms(self._path, self.atoms)
        return atom

    def distill(self, design_intent, error, script_code):
        user = (f"INTENT:\n{design_intent}\n\nERROR:\n{error}\n\n"
                f"SCRIPT:\n{(script_code or '')[:4000]}\n\nReturn the atom JSON.")
        out = call_llm_json(self._DISTILL_SYS, user,
                            os.environ.get("MODEL_LEARN") or os.environ.get("MODEL", ""))
        if not isinstance(out, dict) or not out.get("content"):
            return None
        atom = Atom(id=out["id"], description=out.get("description", ""),
                    domain=list(out.get("domain") or []), content=out["content"],
                    source="distilled", validated_by="", validated_at="",
                    status="candidate", embedding_hash=content_hash(out["content"]))
        return self.add_candidate(atom)

    def promote(self, atom_id, validated_by, validated_at):
        for a in self.atoms:
            if a.id == atom_id:
                a.status = "active"
                a.validated_by = validated_by
                a.validated_at = validated_at
        save_atoms(self._path, self.atoms)
