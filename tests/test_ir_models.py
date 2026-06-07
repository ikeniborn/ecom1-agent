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
    "answer_shape": {"msg_skeleton": "{cnt}", "required_ref_kinds": ["static"]},
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
    assert spec.success_criteria[0].op == "nonempty"
    assert spec.answer_shape.required_ref_kinds == ["static"]


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
