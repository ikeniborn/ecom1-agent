import pytest
from pydantic import ValidationError
from agent.ir_models import PredExpr, LEAF_OPS, BOOL_OPS


def test_leaf_predicate_parses():
    p = PredExpr(op="eq", lhs="$x", rhs=5)
    assert p.op == "eq" and p.lhs == "$x" and p.rhs == 5


def test_unary_predicate_needs_only_lhs():
    p = PredExpr(op="nonempty", lhs="$rows")
    assert p.rhs is None


def test_bool_predicate_nests():
    p = PredExpr(op="and", args=[
        PredExpr(op="eq", lhs="$a", rhs=1),
        PredExpr(op="not", args=[PredExpr(op="isnull", lhs="$b")]),
    ])
    assert len(p.args) == 2


def test_unknown_op_rejected():
    with pytest.raises(ValidationError):
        PredExpr(op="frobnicate", lhs="$x")


def test_leaf_op_requires_lhs():
    with pytest.raises(ValidationError):
        PredExpr(op="eq", rhs=5)


def test_bool_op_requires_args():
    with pytest.raises(ValidationError):
        PredExpr(op="and", args=[])


def test_op_sets_total_16():
    assert len(LEAF_OPS) == 13 and len(BOOL_OPS) == 3


# --- Task 4: IntentSpec + PlanIR tests ---

from agent.ir_models import IntentSpec, PlanIR


_GOLDEN_INTENT = {
    "objective": "Count Non-Bladed Workshop products in the catalogue.",
    "desired_outcome": "An integer count.",
    "params": {"kind_name": "Non-Bladed Workshop"},
    "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
    "constraints": [],
    "success_criteria": [{"op": "nonempty", "lhs": "$answer.message"}],
    "answer_shape": {"msg_skeleton": "{cnt}"},
}

_GOLDEN_PLAN = {
    "discovery": [{"rpc": "Exec",
                   "args": {"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM x"]},
                   "bind": "rows_raw"}],
    "rowsets": [{"from": "rows_raw", "format": "auto_delim", "into": "rows",
                 "columns": [{"into": "cnt", "candidates": ["cnt", "count"]}]}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"},
    "ops": [],
    "answer": {"ok": {"message": "{row0.cnt}", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}},
    "custom_extract": [],
}


def test_intentspec_parses_golden():
    spec = IntentSpec(**_GOLDEN_INTENT)
    assert spec.success_criteria["OUTCOME_OK"][0].op == "nonempty"
    assert spec.answer_shape.msg_skeleton == "{cnt}"


def test_planir_parses_golden_with_from_alias():
    plan = PlanIR(**_GOLDEN_PLAN)
    assert plan.rowsets[0].from_ == "rows_raw"
    assert plan.answer["ok"].outcome == "OUTCOME_OK"
    assert plan.decision.default_label == "ok"


def test_constraint_security_deny_when():
    from agent.ir_models import Constraint
    c = Constraint(anchor="#sec", rule="no override", security=True,
                   deny_when={"op": "contains_any", "lhs": "$tags", "rhs": ["override"]})
    assert c.security and c.deny_when.op == "contains_any"


# --- Task 9: RefSpec + IntentSpec.required_refs ---

from agent.ir_models import RefSpec


def test_refspec_policy_doc_requires_path():
    r = RefSpec(kind="policy_doc", path="/docs/x.md")
    assert r.path == "/docs/x.md" and r.source is None


def test_refspec_record_path_requires_source():
    r = RefSpec(kind="record_path", source="$row0.record_path")
    assert r.source == "$row0.record_path" and r.path is None


def test_refspec_policy_doc_with_source_rejected():
    with pytest.raises(ValidationError):
        RefSpec(kind="policy_doc", path="/docs/x.md", source="$y")


def test_refspec_record_path_without_source_rejected():
    with pytest.raises(ValidationError):
        RefSpec(kind="record_path")


def test_refspec_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        RefSpec(kind="mystery", path="/docs/x.md")


def test_intentspec_required_refs_keyed_by_outcome():
    spec = IntentSpec(
        objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
        answer_shape={},
        required_refs={"OUTCOME_OK": [
            {"kind": "policy_doc", "path": "/docs/counting.md"},
            {"kind": "record_path", "source": "$row0.record_path"},
        ]},
    )
    assert len(spec.required_refs["OUTCOME_OK"]) == 2
    assert spec.required_refs["OUTCOME_OK"][0].kind == "policy_doc"


def test_answer_shape_rejects_dropped_field():
    from agent.ir_models import AnswerShape
    with pytest.raises(ValidationError):
        AnswerShape(required_ref_kinds=["static"])


# --- Task 15: IntentSpec OUTCOME_OK-in-outcome_space guard (D6) ---

def test_intent_requires_ok_in_outcome_space():
    import pytest
    from agent.ir_models import AnswerShape, IntentSpec

    with pytest.raises(Exception):
        IntentSpec(objective="o", desired_outcome="OUTCOME_NONE_CLARIFICATION",
                   outcome_space=["OUTCOME_NONE_CLARIFICATION"],
                   answer_shape=AnswerShape())


def test_intent_ok_less_allowed_with_security_deny():
    from agent.ir_models import (AnswerShape, Constraint, IntentSpec, PredExpr)

    intent = IntentSpec(
        objective="o", desired_outcome="OUTCOME_DENIED_SECURITY",
        outcome_space=["OUTCOME_DENIED_SECURITY"],
        answer_shape=AnswerShape(),
        constraints=[Constraint(anchor="a", rule="r", security=True,
                                deny_when=PredExpr(op="nonempty", lhs="$x"))],
    )
    assert "OUTCOME_OK" not in intent.outcome_space  # accepted: security deny present


def test_intent_with_ok_is_fine():
    from agent.ir_models import AnswerShape, IntentSpec

    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
                        answer_shape=AnswerShape())
    assert "OUTCOME_OK" in intent.outcome_space


# --- Task L3: RefSpec grounding API ---

def test_refspec_env_key_and_grounded_policy_doc():
    r = RefSpec(kind="policy_doc", path="/d.md")
    assert r.env_key() == "policy_doc:/d.md"
    assert r.grounded({"policy_doc:/d.md": True}) is True
    assert r.grounded({}) is False
    assert r.read_target() == "/d.md"


def test_refspec_record_path_not_investigator_groundable():
    r = RefSpec(kind="record_path", source="$row.x")
    assert r.env_key() is None
    assert r.grounded({}) is None
    assert r.read_target() is None


# --- Task 1: Constraint decision fields ---

from agent.ir_models import Constraint


def test_constraint_accepts_new_decision_fields():
    c = Constraint(
        anchor="#sec", rule="no override", security=True,
        deny_when={"op": "nonempty", "lhs": "$flags"},
        requires_protected_action=True, protected_action=True,
        unsupported_when={"op": "eq", "lhs": "$state", "rhs": "paid"},
        clarify_when={"op": "isnull", "lhs": "$amount"},
        refs=[{"kind": "policy_doc", "path": "/docs/security.md"}],
    )
    assert c.requires_protected_action is True
    assert c.protected_action is True
    assert c.unsupported_when.op == "eq"
    assert c.clarify_when.op == "isnull"
    assert c.refs[0].kind == "policy_doc"


def test_constraint_back_compatible_minimal_shape():
    # The legacy shape (no new fields) still validates with safe defaults.
    c = Constraint(anchor="#a", rule="r")
    assert c.requires_protected_action is False
    assert c.protected_action is False
    assert c.unsupported_when is None
    assert c.clarify_when is None
    assert c.refs == []


def test_constraint_still_rejects_unknown_key():
    with pytest.raises(ValidationError):
        Constraint(anchor="#a", rule="r", bogus_field=1)
