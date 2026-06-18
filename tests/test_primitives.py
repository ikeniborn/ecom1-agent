import pytest
from agent.primitives import PRIMITIVES, PARSERS, run_primitive, run_parser


def test_registry_has_13_primitives():
    assert len(PRIMITIVES) == 13


def test_arithmetic_primitives():
    assert run_primitive("abs_diff", [10, 3.5]) == 6.5
    assert run_primitive("div", [250, 100]) == 2.5
    assert run_primitive("div", [5, 0]) == 0.0          # guarded zero-div
    assert run_primitive("to_number", ["€ 1.234,50".replace(".", "").replace(",", ".")]) == 1234.50
    assert run_primitive("to_number", ["$12.00"]) == 12.0
    assert run_primitive("to_number", ["n/a"]) == 0.0   # non-numeric -> 0.0


def test_rowset_primitives():
    rows = [{"sku": "A", "price": "100"}, {"sku": "B", "price": "50"}]
    assert run_primitive("sum_col", [rows, "price"]) == 150.0
    assert run_primitive("count", [rows]) == 2
    assert run_primitive("column", [rows, "sku"]) == ["A", "B"]
    assert run_primitive("first", [rows]) == {"sku": "A", "price": "100"}
    assert run_primitive("first", [[]]) is None
    assert run_primitive("get", [{"k": 7}, "k"]) == 7
    assert run_primitive("get", [{"k": 7}, "missing"]) is None
    assert run_primitive("dedupe", [["a", "b", "a"]]) == ["a", "b"]
    assert run_primitive("concat", [["a"], ["b"]]) == ["a", "b"]


def test_fold_primitives():
    assert run_primitive("all_true", [[True, True, True]]) is True
    assert run_primitive("all_true", [[True, False]]) is False
    assert run_primitive("any_true", [[False, True]]) is True
    assert run_primitive("all_true", [[]]) is False  # deliberate: empty != vacuous True


def test_filter_rows_uses_predicate_engine():
    rows = [{"qty": 2}, {"qty": 0}, {"qty": 5}]
    from agent.ir_models import PredExpr
    kept = run_primitive("filter_rows", [rows, PredExpr(op="gt", lhs="$qty", rhs=0)])
    assert kept == [{"qty": 2}, {"qty": 5}]


def test_unknown_primitive_raises():
    with pytest.raises(KeyError):
        run_primitive("nope", [])


def test_parser_registry_fuzzy_sku():
    # t51 escape hatch: OCR-confusion normalisation map for receipt SKUs.
    out = run_parser("fuzzy_sku_receipt", "Line ABC-0I5B8Z total", {})
    assert isinstance(out, list)
    assert all(isinstance(r, dict) for r in out)


def test_unknown_parser_raises():
    with pytest.raises(KeyError):
        run_parser("nope", "", {})


def test_list_ops_reject_scalar_with_actionable_message():
    # F1: a list-consuming primitive handed a non-list (e.g. the output of `first`)
    # raises a clear TypeError naming the fix, not a cryptic AttributeError.
    import pytest
    with pytest.raises(TypeError, match=r"'column' expects list\[dict\]; use 'get'"):
        run_primitive("column", ["product_sku", "name"])
    with pytest.raises(TypeError, match=r"'sum_col' expects list\[dict\]"):
        run_primitive("sum_col", [{"a": 1}, "a"])
    with pytest.raises(TypeError, match=r"'filter_rows' expects list\[dict\]"):
        from agent.ir_models import PredExpr
        run_primitive("filter_rows", ["scalar", PredExpr(op="nonempty", lhs="$x")])


def test_list_ops_allow_none_as_empty():
    # None (empty rowset) stays valid -> [] / 0.0, preserving current semantics.
    assert run_primitive("column", [None, "c"]) == []
    assert run_primitive("sum_col", [None, "c"]) == 0.0
