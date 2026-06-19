import agent.pipeline as pipeline
from agent.ir_models import (AnswerShape, IntentSpec, PlanIR, DecisionTree,
                             AnswerTemplateIR)


def _intent():
    return IntentSpec(objective="count baskets", desired_outcome="OUTCOME_OK",
                      outcome_space=["OUTCOME_OK"], answer_shape=AnswerShape())


def _plan():
    return PlanIR(decision=DecisionTree(default_label="ok"),
                  answer={"ok": AnswerTemplateIR(message="m", outcome="OUTCOME_OK")})


def test_distill_skipped_when_flag_off(monkeypatch):
    monkeypatch.setenv("ECOM_ORACLE_DISTILL", "0")
    called = {"distill": False}
    monkeypatch.setattr(pipeline, "_distill_call",
                        lambda *a, **k: called.__setitem__("distill", True))
    pipeline._maybe_distill_and_validate(_intent(), _plan(), "t01", "OK: verified")
    assert called["distill"] is False


def test_distill_writes_candidate_and_promotes_when_validated(monkeypatch):
    monkeypatch.setenv("ECOM_ORACLE_DISTILL", "1")
    monkeypatch.setenv("ECOM_ORACLE_VALIDATE_INLINE", "1")

    class FakeAtom:
        id = "a1"

    class FakeOracle:
        def __init__(self): self.promoted = None
        def distill(self, **kw): return FakeAtom()
        def promote(self, atom_id, validated_by, validated_at):
            self.promoted = (atom_id, validated_by)

    fake = FakeOracle()
    monkeypatch.setattr(pipeline, "_new_oracle", lambda: fake)
    monkeypatch.setattr(pipeline, "validate_atom_via_grader", lambda *a, **k: True)
    pipeline._maybe_distill_and_validate(_intent(), _plan(), "t01", "OK: verified")
    assert fake.promoted == ("a1", "grader-oracle")


def test_distill_keeps_candidate_when_inline_off(monkeypatch):
    monkeypatch.setenv("ECOM_ORACLE_DISTILL", "1")
    monkeypatch.setenv("ECOM_ORACLE_VALIDATE_INLINE", "0")

    class FakeAtom: id = "a1"
    class FakeOracle:
        def __init__(self): self.promoted = None
        def distill(self, **kw): return FakeAtom()
        def promote(self, *a, **k): self.promoted = a

    fake = FakeOracle()
    monkeypatch.setattr(pipeline, "_new_oracle", lambda: fake)
    pipeline._maybe_distill_and_validate(_intent(), _plan(), "t01", "OK: verified")
    assert fake.promoted is None
