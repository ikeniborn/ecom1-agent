from agent.format_gate import format_eur, bool_tokens, _canonicalize_bool, _strip_outcome_prefix
from agent.ir_models import AnswerShape


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
