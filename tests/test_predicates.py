from agent.ir_models import PredExpr
from agent.predicates import resolve, evaluate


def _env():
    return {
        "x": 5, "name": "basket_069", "role": "guest",
        "rows": [{"sku": "ABC", "qty": 2}, {"sku": "DEF", "qty": 0}],
        "tags": ["vip", "manager-pre-approved"],
        "empty": [], "none": None,
    }


def test_resolve_literal_passes_through():
    assert resolve(5, {}) == 5
    assert resolve("hello", {}) == "hello"


def test_resolve_ref_and_dotted_and_index():
    e = _env()
    assert resolve("$x", e) == 5
    assert resolve("$rows.0.sku", e) == "ABC"
    assert resolve("$missing.deep", e) is None


def test_eq_ne():
    e = _env()
    assert evaluate(PredExpr(op="eq", lhs="$x", rhs=5), e)
    assert evaluate(PredExpr(op="ne", lhs="$x", rhs=6), e)


def test_numeric_comparisons_coerce_strings():
    e = {"a": "10", "b": 2}
    assert evaluate(PredExpr(op="gt", lhs="$a", rhs="$b"), e)
    assert evaluate(PredExpr(op="le", lhs="$b", rhs=2), e)
    assert evaluate(PredExpr(op="lt", lhs="$b", rhs="$a"), e)
    assert evaluate(PredExpr(op="ge", lhs="$a", rhs=10), e)


def test_nonempty_and_isnull():
    e = _env()
    assert evaluate(PredExpr(op="nonempty", lhs="$rows"), e)
    assert not evaluate(PredExpr(op="nonempty", lhs="$empty"), e)
    assert evaluate(PredExpr(op="isnull", lhs="$none"), e)


def test_contains_any_in_set_string_ops_regex():
    e = _env()
    assert evaluate(PredExpr(op="contains_any", lhs="$tags",
                             rhs=["manager-pre-approved", "override"]), e)
    assert evaluate(PredExpr(op="in_set", lhs="$role", rhs=["guest", "customer"]), e)
    assert evaluate(PredExpr(op="startswith", lhs="$name", rhs="basket_"), e)
    assert evaluate(PredExpr(op="endswith", lhs="$name", rhs="069"), e)
    assert evaluate(PredExpr(op="regex_match", lhs="$name", rhs=r"basket_\d+"), e)


def test_and_or_not():
    e = _env()
    expr = PredExpr(op="and", args=[
        PredExpr(op="eq", lhs="$role", rhs="guest"),
        PredExpr(op="not", args=[PredExpr(op="isnull", lhs="$x")]),
    ])
    assert evaluate(expr, e)
    assert evaluate(PredExpr(op="or", args=[
        PredExpr(op="eq", lhs="$role", rhs="manager"),
        PredExpr(op="eq", lhs="$x", rhs=5),
    ]), e)
