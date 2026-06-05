from scripts.migrate_rules_to_atoms import dedup_by_cosine
from agent.oracle_atoms import Atom


def _a(i, vec):
    a = Atom(id=i, description=i, domain=[], content=i, source="distilled",
             validated_by="", validated_at="", status="candidate", embedding_hash="")
    a.extra["vec"] = vec
    return a


def test_dedup_merges_near_duplicates():
    atoms = [_a("a", [1.0, 0.0]), _a("b", [0.99, 0.01]), _a("c", [0.0, 1.0])]
    kept = dedup_by_cosine(atoms, threshold=0.95, vec_of=lambda a: a.extra["vec"])
    ids = {a.id for a in kept}
    assert "c" in ids
    assert len(kept) == 2  # a and b merged
