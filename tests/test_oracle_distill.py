from unittest.mock import patch
from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom


def _o(tmp_path):
    p = tmp_path / "atoms.yaml"
    p.write_text("[]")
    return KnowledgeOracle(atoms=[], atoms_path=p,
                           embed_fn=lambda t, model, base_url=None: [[1.0]] * len(t))


def test_distill_adds_candidate_without_seed_values(tmp_path):
    o = _o(tmp_path)
    fake = {"id": "new-method", "description": "d", "domain": ["sql"],
            "content": "general method text"}
    with patch("agent.oracle.call_llm_json", return_value=fake):
        atom = o.distill(design_intent="x", error="boom", script_code="code")
    assert atom.status == "candidate"
    assert any(a.id == "new-method" and a.status == "candidate" for a in o.atoms)


def test_promote_sets_active(tmp_path):
    o = _o(tmp_path)
    o.atoms.append(Atom(id="c", description="d", domain=[], content="x",
                        source="distilled", validated_by="", validated_at="",
                        status="candidate", embedding_hash=""))
    o.promote("c", validated_by="grader", validated_at="2026-06-05")
    a = next(a for a in o.atoms if a.id == "c")
    assert a.status == "active" and a.validated_by == "grader"
