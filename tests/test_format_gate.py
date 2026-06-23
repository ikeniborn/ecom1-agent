from agent.format_gate import (
    format_eur, bool_tokens, _canonicalize_bool, _strip_outcome_prefix,
    _render_count, _render_table, _render_quote,
    _extract_int, _extract_eur_number, _coerce_int,
)
from agent.ir_models import AnswerShape


def test_render_count_printf():
    assert _render_count("qty=%d", 5) == "qty=5"
    assert _render_count("<COUNT:%d>", 3) == "<COUNT:3>"
    assert _render_count("Total: %d", 12) == "Total: 12"


def test_render_count_single_slot():
    assert _render_count("<COUNT:{count}>", 7) == "<COUNT:7>"
    assert _render_count("count: {count}", 0) == "count: 0"


def test_render_count_empty_when_ambiguous_multi_slot():
    assert _render_count("{a} of {b}", 5) == ""


def test_render_table_header_then_rows():
    rows = [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 5}]
    assert _render_table(rows, ["sku", "qty"]) == "sku\tqty\nA\t2\nB\t5"


def test_render_table_empty_when_no_columns_or_rows():
    assert _render_table([{"a": 1}], []) == ""
    assert _render_table([], ["a"]) == ""


def test_render_quote_rows_only_no_header():
    rows = [{"sku": "A", "qty": 2}]
    assert _render_quote(rows, ["sku", "qty"]) == "A\t2"


def test_extract_int_first_integer():
    assert _extract_int("there are 5 items") == 5
    assert _extract_int("<COUNT:42>") == 42
    assert _extract_int("nothing here") is None


def test_extract_eur_number_prefers_eur_adjacent():
    assert _extract_eur_number("EUR 12.5") == 12.5


def test_coerce_int_prefers_value_then_message():
    assert _coerce_int(5, "ignored") == 5
    assert _coerce_int(5.0, "ignored") == 5
    assert _coerce_int(None, "qty=9") == 9
    assert _coerce_int(True, "qty=9") == 9   # bool is not a count value -> fall to message


def test_bool_tokens_default():
    assert bool_tokens("", AnswerShape(msg_skeleton="<NO> (SKU: {sku})")) == ("<YES>", "<NO>")


def test_bool_tokens_custom_from_agents_md():
    md = "## Format\nyes_token: AFFIRM\nno_token: REJECT\n"
    assert bool_tokens(md, AnswerShape()) == ("AFFIRM", "REJECT")


def test_canonicalize_prepends_no_from_skeleton_polarity():
    # skeleton declares <NO>; message lacks any token -> prepend <NO>, keep the prose.
    out = _canonicalize_bool("SKU: ABC not found", "<YES>", "<NO>", "<NO> (SKU: {sku})")
    assert out == "<NO> SKU: ABC not found"


def test_canonicalize_prepends_yes_from_message_polarity():
    # no skeleton token; message reads affirmative -> prepend <YES>.
    out = _canonicalize_bool("yes it matches the spec", "<YES>", "<NO>", "{verdict} (SKU: {sku})")
    assert out.startswith("<YES> ")


def test_canonicalize_noop_when_token_already_present():
    # already carries a canonical token -> return "" (caller keeps the message as-is).
    assert _canonicalize_bool("<NO> (SKU: ABC)", "<YES>", "<NO>", "<NO> (SKU: {sku})") == ""


def test_canonicalize_noop_when_polarity_ambiguous():
    # no skeleton token AND no yes/no signal in the message -> "" (never fabricate).
    assert _canonicalize_bool("the product details follow", "<YES>", "<NO>", "{verdict}") == ""


def test_strip_outcome_prefix():
    assert _strip_outcome_prefix("OUTCOME_OK: 5 items") == "5 items"
    assert _strip_outcome_prefix("OUTCOME_NONE_UNSUPPORTED - nope") == "nope"
    assert _strip_outcome_prefix("plain message") == "plain message"


def test_format_eur_pads_single_digit_cents():
    assert format_eur(12.5) == "EUR 12.50"


def test_format_eur_integer_value():
    assert format_eur(12) == "EUR 12.00"


def test_format_eur_string_value():
    assert format_eur("0.5") == "EUR 0.50"


def test_format_eur_half_up_rounding():
    # 1.005 -> 1.01 under half-up (the grader's expectation), not banker's rounding.
    assert format_eur("1.005") == "EUR 1.01"


def test_format_eur_already_two_digits():
    assert format_eur(1234.56) == "EUR 1234.56"


def test_format_eur_empty_on_unparseable():
    assert format_eur("twelve") == ""
    assert format_eur(None) == ""


def test_format_eur_empty_on_negative():
    # negative euros are unexpected -> caller keeps the original message.
    assert format_eur(-3.2) == ""
