"""Offline harness->oracle bridge orchestration: hot-check selection + per-check
distil->validate->promote routing."""
import scripts.harness_to_oracle as hb
from agent.oracle_atoms import Atom


def _check(id_, kind="primitive_contract", src="t01", msg="m"):
    return {"id": id_, "kind": kind, "source_task": src, "message": msg, "status": "active"}


def test_select_hot_checks_threshold_rank_cap():
    stats = {"chk_a": {"fires": 5}, "chk_b": {"fires": 2}, "chk_c": {"fires": 10},
             "orphan": {"fires": 9}}                       # orphan not in checks -> excluded
    checks = [_check("chk_a"), _check("chk_b"), _check("chk_c")]
    hot = hb.select_hot_checks(stats, checks, min_fires=3, max_atoms=2)
    assert [c["id"] for c in hot] == ["chk_c", "chk_a"]    # ranked desc, capped at 2, chk_b below min


def _candidate_atom(id_="cand1", status="candidate"):
    return Atom(id=id_, description="d", domain=[], content="c", source="distilled",
                validated_by="", validated_at="", status=status)


class _FakeOracle:
    def __init__(self, atom):
        self._atom = atom
        self.promoted = []
        self.distilled = False
    def distill(self, **kw):
        self.distilled = True
        self._last_kw = kw
        return self._atom
    def promote(self, atom_id, validated_by, validated_at):
        self.promoted.append(atom_id)


def test_bridge_one_promotes_on_validation(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: ("objective", "{}"))
    oracle = _FakeOracle(_candidate_atom())
    out = hb.bridge_one(_check("chk_a"), oracle, validate_fn=lambda atom, tid: True)
    assert oracle.promoted == ["cand1"]
    assert "PROMOTED" in out


def test_bridge_one_leaves_candidate_on_failed_validation(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: ("objective", "{}"))
    oracle = _FakeOracle(_candidate_atom())
    out = hb.bridge_one(_check("chk_a"), oracle, validate_fn=lambda atom, tid: False)
    assert oracle.promoted == []
    assert "candidate" in out


def test_bridge_one_skips_when_no_source_artifacts(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: (None, None))
    oracle = _FakeOracle(_candidate_atom())
    out = hb.bridge_one(_check("chk_a", src=""), oracle, validate_fn=lambda atom, tid: True)
    assert oracle.distilled is False and oracle.promoted == []
    assert "skip" in out


def test_bridge_one_skips_already_bridged(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: ("objective", "{}"))
    oracle = _FakeOracle(_candidate_atom(status="active"))   # dedup returned an active atom
    out = hb.bridge_one(_check("chk_a"), oracle, validate_fn=lambda atom, tid: True)
    assert oracle.promoted == []
    assert "already bridged" in out
