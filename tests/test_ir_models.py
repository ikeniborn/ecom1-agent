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
    assert spec.success_criteria[0].op == "nonempty"
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
