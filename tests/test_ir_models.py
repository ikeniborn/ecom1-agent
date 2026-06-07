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
