from agent.mock_vm_spy import fixture_key

PARAMS = {"euro_threshold": 2, "receipt_full_path": "/uploads/receipt.txt"}

# Receipt with one SKU line. NOTE: the old script's SUBTOTAL detector is dead
# code — it fuzz-normalizes letters to digits (S->5,B->8,O->0) BEFORE testing
# `'SUB' in line and 'TOTAL' in line`, which can never hold. So old_ex is
# structurally always 0.00; we mirror that constant in the plan template.
# The single receipt SKU ABC-1234 matches the catalogue exactly at 125 cents
# => today_ex = diff = 1.25, which is <= the 2 EUR threshold => <YES>.
_RECEIPT = "ABC-1234 widget\n"

# /bin/sql returns the catalogue price for the candidate SKU (comma-delimited,
# header + one row). Old script: catalogue['ABC-1234'] = 125.
_SQL_STDOUT = "product_sku,price_cents\nABC-1234,125"

FIXTURES = {
    fixture_key("List", "/uploads/"): {"items": [{"name": "receipt.txt", "kind": "FILE"}]},
    fixture_key("Read", "/uploads/receipt.txt"): {"text": _RECEIPT, "content": _RECEIPT},
    fixture_key("Search", "/uploads/"): {"matches": ["ABC-1234"]},
    fixture_key("Exec", "/bin/sql", []): {"stdout": _SQL_STDOUT},
}
