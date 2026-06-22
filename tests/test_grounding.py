from agent.grounding import extract_entity_tokens


def test_extracts_sku_dash_id_token():
    toks = extract_entity_tokens("Does STO-2R84BSHQ exist in the catalog?", "")
    assert "STO-2R84BSHQ" in toks


def test_extracts_short_sku_token():
    toks = extract_entity_tokens("check SKU-FK availability", "")
    assert "SKU-FK" in toks


def test_extracts_prefixed_entity_id():
    toks = extract_entity_tokens("refund basket_12 for cust_016", "")
    assert "basket_12" in toks
    assert "cust_016" in toks


def test_scans_both_task_text_and_message():
    toks = extract_entity_tokens("task mentions STO-2R84BSHQ", "answer cites SKU-FK")
    assert "STO-2R84BSHQ" in toks and "SKU-FK" in toks


def test_dedupes_and_preserves_order():
    toks = extract_entity_tokens("SKU-FK then SKU-FK again", "SKU-FK")
    assert toks.count("SKU-FK") == 1


def test_ignores_lowercase_schema_words():
    # 'record_path' / 'product_sku' are schema words, not entity ids — must NOT match.
    toks = extract_entity_tokens("select record_path, product_sku from product_variants", "")
    assert toks == []
