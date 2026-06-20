from unittest.mock import patch
from agent.oracle_atoms import Atom
from agent.oracle_rank import llm_rerank


def _a(i):
    return Atom(id=i, description=i + " desc", domain=[], content="c",
                source="s", validated_by="manual", validated_at="d",
                status="active", embedding_hash="")


def test_rerank_keeps_ids_returned_by_llm():
    cands = [_a("alpha"), _a("beta"), _a("gamma")]
    with patch("agent.oracle_rank.call_llm_json", return_value={"keep": ["gamma", "alpha"]}):
        out = llm_rerank("task", cands, k=2)
    assert [a.id for a in out] == ["gamma", "alpha"]


def test_rerank_ignores_unknown_ids():
    cands = [_a("alpha"), _a("beta")]
    with patch("agent.oracle_rank.call_llm_json", return_value={"keep": ["zzz", "beta"]}):
        out = llm_rerank("task", cands, k=2)
    assert [a.id for a in out] == ["beta"]


def test_llm_rerank_passes_rerank_phase(monkeypatch):
    import agent.oracle_rank as orank

    captured = {}

    def fake_json(system, user_msg, model, max_tokens=1024, token_out=None, phase="llm"):
        captured["phase"] = phase
        return {"keep": []}

    monkeypatch.setattr(orank, "call_llm_json", fake_json)

    class A:
        id = "a1"
        description = "d"

    orank.llm_rerank("task", [A()], 3)
    assert captured["phase"] == "RERANK"
