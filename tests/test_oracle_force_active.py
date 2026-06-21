"""_active() honours ECOM_ORACLE_FORCE_ACTIVE: a candidate atom whose id is listed becomes
retrievable for one run, without mutating its persisted status."""
from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom


def _atom(id_, status):
    return Atom(id=id_, description="d", domain=[], content="c", source="distilled",
                validated_by="", validated_at="", status=status)


def test_force_active_includes_named_candidate(monkeypatch):
    o = KnowledgeOracle(atoms=[_atom("act1", "active"), _atom("cand1", "candidate")])
    monkeypatch.delenv("ECOM_ORACLE_FORCE_ACTIVE", raising=False)
    assert {a.id for a in o._active()} == {"act1"}
    monkeypatch.setenv("ECOM_ORACLE_FORCE_ACTIVE", "cand1")
    assert {a.id for a in o._active()} == {"act1", "cand1"}


def test_force_active_empty_env_is_noop(monkeypatch):
    o = KnowledgeOracle(atoms=[_atom("cand1", "candidate")])
    monkeypatch.setenv("ECOM_ORACLE_FORCE_ACTIVE", "")
    assert o._active() == []
