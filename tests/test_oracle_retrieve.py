from agent.oracle_atoms import Atom
from agent.oracle import KnowledgeOracle


def _atom(i, desc, dom):
    return Atom(id=i, description=desc, domain=dom, content="C:" + desc,
                source="investigation", validated_by="manual",
                validated_at="2026-06-05", status="active", embedding_hash="")


def test_cosine_orders_by_similarity():
    atoms = [_atom("sql", "sql binds", ["sql"]),
             _atom("vat", "vat ex-vat pricing", ["pricing"])]
    emap = {"C:sql binds": [1.0, 0.0], "C:vat ex-vat pricing": [0.0, 1.0]}

    def fake_embed(texts, model, base_url=None):
        return [emap.get(t, [0.0, 1.0]) for t in texts]  # query -> [0,1] (vat)

    o = KnowledgeOracle(atoms=atoms, embed_fn=fake_embed)
    out = o._cosine_topn("how to compute ex-VAT total", n=2)
    assert out[0].id == "vat"


def test_candidate_atoms_excluded():
    atoms = [_atom("a", "x", []),
             Atom(id="b", description="y", domain=[], content="c",
                  source="s", validated_by="manual", validated_at="d",
                  status="candidate", embedding_hash="")]
    o = KnowledgeOracle(atoms=atoms, embed_fn=lambda t, model, base_url=None: [[1.0]] * len(t))
    assert all(a.status == "active" for a in o._active())
    assert [a.id for a in o._active()] == ["a"]


def test_retrieve_falls_back_to_tags_when_embed_down():
    atoms = [_atom("sql", "sql binds", ["sql"]), _atom("vat", "vat", ["pricing"])]

    def boom(texts, model, base_url=None):
        raise RuntimeError("ollama down")

    o = KnowledgeOracle(atoms=atoms, embed_fn=boom)
    out = o.retrieve("sql query help", k=1, rank_fn=None)
    assert out and out[0].id == "sql"
