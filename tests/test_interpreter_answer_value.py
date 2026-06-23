from agent.interpreter import _resolve_answer_value, _resolve_answer_rows, CapturedAnswer
from agent.ir_models import AnswerShape


def test_captured_answer_has_value_and_rows_defaults():
    cap = CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[])
    assert cap.value is None and cap.rows == []


def test_resolve_value_single_numeric_slot():
    shape = AnswerShape(msg_skeleton="EUR {amt}")
    assert _resolve_answer_value(shape, {"amt": 12.5}) == 12.5


def test_resolve_value_numeric_string_slot():
    shape = AnswerShape(msg_skeleton="qty={count}")
    assert _resolve_answer_value(shape, {"count": "9"}) == 9.0


def test_resolve_value_dotted_slot():
    shape = AnswerShape(msg_skeleton="EUR {row0.amt}")
    assert _resolve_answer_value(shape, {"row0": {"amt": "3.5"}}) == 3.5


def test_resolve_value_none_when_multiple_numeric_slots():
    # ambiguous (two numbers) -> None; the gate falls back to message-parse.
    shape = AnswerShape(msg_skeleton="EUR {euros}.{cents}")
    assert _resolve_answer_value(shape, {"euros": 12, "cents": 50}) is None


def test_resolve_value_none_when_non_numeric():
    shape = AnswerShape(msg_skeleton="Product {name}")
    assert _resolve_answer_value(shape, {"name": "Widget"}) is None


def test_resolve_value_never_raises():
    assert _resolve_answer_value(None, {}) is None


def test_resolve_rows_from_declared_binding():
    shape = AnswerShape(kind="table", rows_from="rows")
    rows = [{"a": 1}]
    assert _resolve_answer_rows(shape, {"rows": rows}) == rows


def test_resolve_rows_empty_when_not_declared_or_not_list():
    assert _resolve_answer_rows(AnswerShape(), {"rows": [{"a": 1}]}) == []
    assert _resolve_answer_rows(AnswerShape(rows_from="rows"), {"rows": "notalist"}) == []
