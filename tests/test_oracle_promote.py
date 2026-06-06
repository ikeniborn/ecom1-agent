import pytest
from agent.promote import load_green_suite, promote_decision


def test_load_green_suite(tmp_path):
    p = tmp_path / "green_suite.yaml"
    p.write_text(
        "- task_id: t01\n  reference: 1.0\n"
        "- task_id: t51\n  reference: 1.0\n"
    )
    suite = load_green_suite(p)
    assert suite == [("t01", 1.0), ("t51", 1.0)]


def test_load_green_suite_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_green_suite(tmp_path / "nope.yaml")


_GREEN = [("t01", 1.0), ("t51", 1.0)]


def test_promote_when_green_held_and_source_improved():
    scores = {"t01": 1.0, "t51": 1.0, "t38": 0.8}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "promote"


def test_halt_when_green_dropped():
    scores = {"t01": 1.0, "t51": 0.6, "t38": 0.9}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "halt"


def test_no_improve_when_source_flat():
    scores = {"t01": 1.0, "t51": 1.0, "t38": 0.5}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "no_improve"


def test_missing_source_score_is_no_improve():
    scores = {"t01": 1.0, "t51": 1.0}
    assert promote_decision(scores, "t38", 0.0, _GREEN) == "no_improve"


from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom
from agent.promote import run_promote


def _oracle_with_candidate(tmp_path, source_task):
    p = tmp_path / "atoms.yaml"
    p.write_text("[]")
    o = KnowledgeOracle(atoms=[], atoms_path=p,
                        embed_fn=lambda t, model, base_url=None, prefix=None: [[1.0]] * len(t),
                        embeddings_path=tmp_path / "emb.json")
    o.atoms.append(Atom(id="cand", description="d", domain=["sql"], content="x",
                        source="distilled", validated_by="", validated_at="",
                        status="candidate", embedding_hash="", source_task=source_task))
    return o


def test_run_promote_promotes_when_green_held(tmp_path):
    o = _oracle_with_candidate(tmp_path, "t38")
    green = [("t01", 1.0)]

    def run_fn(task_ids, active_atom_id):
        # baseline pass (active=None): source low; candidate pass: source up, green held
        if active_atom_id is None:
            return {"t01": 1.0, "t38": 0.5}
        return {"t01": 1.0, "t38": 0.9}

    results = run_promote(o, green, run_fn, validated_at="2026-06-06")
    assert results == [("cand", "promote")]
    a = next(a for a in o.atoms if a.id == "cand")
    assert a.status == "active" and a.validated_at == "2026-06-06"


def test_run_promote_halts_and_keeps_candidate(tmp_path):
    o = _oracle_with_candidate(tmp_path, "t38")
    green = [("t01", 1.0)]

    def run_fn(task_ids, active_atom_id):
        if active_atom_id is None:
            return {"t01": 1.0, "t38": 0.5}
        return {"t01": 0.7, "t38": 0.9}   # green regressed

    results = run_promote(o, green, run_fn, validated_at="2026-06-06")
    assert results == [("cand", "halt")]
    a = next(a for a in o.atoms if a.id == "cand")
    assert a.status == "candidate"        # unchanged
