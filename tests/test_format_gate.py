from agent.format_gate import format_eur


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
