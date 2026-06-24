import json
from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom


def _atom(i, content):
    return Atom(id=i, description=content, domain=["sql"], content=content,
                source="investigation", validated_by="manual",
                validated_at="2026-06-05", status="active", embedding_hash="")


def _counting_embed(calls):
    def fn(texts, model, base_url=None, prefix=None):
        for t in texts:
            calls.append(t)
        return [[1.0, 0.0]] * len(texts)
    return fn


def test_atom_embedded_once_across_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_ORACLE_FLOOR", "-1")  # disable floor for this test
    emb = tmp_path / "embeddings.jsonl"
    atoms = [_atom("a", "C:alpha")]
    calls = []

    o1 = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed(calls),
                         embeddings_path=emb)
    o1.retrieve("alpha query", k=1, rank_fn=None)

    o2 = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed(calls),
                         embeddings_path=emb)
    o2.retrieve("alpha query", k=1, rank_fn=None)

    assert calls.count("C:alpha") == 1  # cached after first instance


def test_cache_persisted_to_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_ORACLE_FLOOR", "-1")
    emb = tmp_path / "embeddings.jsonl"
    atoms = [_atom("a", "C:alpha")]
    o = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed([]),
                        embeddings_path=emb)
    o.retrieve("alpha query", k=1, rank_fn=None)
    # JSONL: one {"hash","embedding"} object per line
    rows = [json.loads(ln) for ln in emb.read_text().splitlines() if ln.strip()]
    hashes = {r["hash"] for r in rows}
    from agent.oracle_atoms import content_hash
    assert content_hash("C:alpha") in hashes


def test_corrupt_cache_file_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_ORACLE_FLOOR", "-1")
    emb = tmp_path / "embeddings.jsonl"
    emb.write_text("{ this is not json")
    atoms = [_atom("a", "C:alpha")]
    o = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed([]),
                        embeddings_path=emb)
    assert o._vec_cache == {}          # graceful rebuild, no crash
    out = o.retrieve("alpha query", k=1, rank_fn=None)
    assert out and out[0].id == "a"
