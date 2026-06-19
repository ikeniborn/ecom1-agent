from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom


def _atom(id, content, status="active", polarity="method", validated_by="manual"):
    return Atom(id=id, description="d", domain=["x"], content=content, source="s",
                validated_by=validated_by, validated_at="", status=status,
                embedding_hash="", source_task="", polarity=polarity)


def _fake_embed(texts, model=None, prefix=None):
    # vector keyed by the first token -> identical content prefix => identical vector (dup)
    out = []
    for t in texts:
        key = t.split()[0].lower()
        out.append([1.0, 0.0] if key == "alpha" else [0.0, 1.0])
    return out


def test_prune_drops_candidates_and_dedups_active(tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_DEDUP_COSINE", "0.95")
    atoms = [
        _atom("a1", "alpha method one for scalar extraction"),
        _atom("a2", "alpha method two paraphrase scalar extraction"),  # dup of a1 (same vec)
        _atom("b1", "beta different knowledge entirely"),
        _atom("c1", "alpha candidate junk", status="candidate"),
    ]
    st = KnowledgeOracle(atoms=atoms, atoms_path=tmp_path / "atoms.yaml",
                     embed_fn=_fake_embed, embeddings_path=tmp_path / "emb.json")
    removed, kept = st.prune()
    ids = {a.id for a in st.atoms}
    assert "c1" not in ids                     # candidate dropped
    assert "b1" in ids                          # distinct kept
    assert ("a1" in ids) ^ ("a2" in ids)        # exactly one of the dup pair kept
    assert kept == 2 and removed == 2


def test_add_candidate_skips_near_duplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_DEDUP_COSINE", "0.95")
    st = KnowledgeOracle(atoms=[_atom("a1", "alpha existing method")],
                     atoms_path=tmp_path / "atoms.yaml", embed_fn=_fake_embed,
                     embeddings_path=tmp_path / "emb.json")
    st.add_candidate(_atom("a2", "alpha duplicate paraphrase", status="candidate"))
    assert len(st.atoms) == 1 and st.atoms[0].id == "a1"   # dup not added
    st.add_candidate(_atom("b1", "beta brand new", status="candidate"))
    assert len(st.atoms) == 2                                # distinct added
