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


from agent.format_gate import detect_shape, already_exact, _outcome_regexes
from agent.ir_models import IntentSpec, AnswerShape


def _intent(skeleton="", criteria=None, kind="", columns=None, rows_from=""):
    return IntentSpec(
        objective="o", desired_outcome="OUTCOME_OK", outcome_space=["OUTCOME_OK"],
        constraints=[], success_criteria=criteria or {},
        answer_shape={"msg_skeleton": skeleton, "kind": kind,
                      "columns": columns or [], "rows_from": rows_from},
        required_refs={})


def test_detect_explicit_kind_wins():
    it = _intent(skeleton="anything", kind="table", columns=["a"])
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "table"


def test_detect_boolean_from_skeleton_token():
    it = _intent(skeleton="<NO> (SKU: {sku})")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "boolean"


def test_detect_money_from_bare_eur_skeleton():
    it = _intent(skeleton="EUR {total_euros}.{total_cents_two_digits}")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "money"


def test_detect_money_from_anchored_regex():
    it = _intent(skeleton="{amount}",
                 criteria={"OUTCOME_OK": [{"op": "regex_match", "lhs": "$answer.message",
                                           "rhs": r"^EUR \d+\.\d{2}$"}]})
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "money"


def test_detect_money_does_not_fire_on_eur_prose():
    # t51-class: EUR appears mid-prose -> NOT money (reshaping would corrupt the answer).
    it = _intent(skeleton="The total price difference is {d} EUR, which is {c} the threshold.")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "free"


def test_detect_count_printf_and_markers_and_count_slot():
    assert detect_shape(_intent("qty=%d"), AnswerShape(msg_skeleton="qty=%d"), "OUTCOME_OK") == "count"
    assert detect_shape(_intent("<COUNT:{count}>"), AnswerShape(msg_skeleton="<COUNT:{count}>"), "OUTCOME_OK") == "count"
    assert detect_shape(_intent("count: {count}"), AnswerShape(msg_skeleton="count: {count}"), "OUTCOME_OK") == "count"
    assert detect_shape(_intent("{count}"), AnswerShape(msg_skeleton="{count}"), "OUTCOME_OK") == "count"


def test_detect_free_for_plain_prose():
    it = _intent(skeleton="The product {name} (SKU: {sku}) is in the catalogue.")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "free"


def test_already_exact_true_when_message_matches_required_regex():
    it = _intent(criteria={"OUTCOME_OK": [{"op": "regex_match", "lhs": "$answer.message",
                                           "rhs": r"^EUR \d+\.\d{2}$"}]})
    assert already_exact("EUR 12.50", it, it.answer_shape, "OUTCOME_OK") is True
    assert already_exact("EUR 12.5", it, it.answer_shape, "OUTCOME_OK") is False


def test_already_exact_false_when_no_regex_declared():
    it = _intent(skeleton="qty=%d")
    assert already_exact("qty=5", it, it.answer_shape, "OUTCOME_OK") is False


def test_outcome_regexes_reads_msg_and_message_lhs():
    it = _intent(criteria={"OUTCOME_OK": [
        {"op": "regex_match", "lhs": "$answer.msg", "rhs": "^<NO> .+$"},
        {"op": "nonempty", "lhs": "$answer.message"}]})
    assert _outcome_regexes(it, "OUTCOME_OK") == ["^<NO> .+$"]
