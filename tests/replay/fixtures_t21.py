from agent.mock_vm_spy import fixture_key

PARAMS = {"basket_id": "basket_154", "basket_path": "/proc/baskets/basket_154.json"}

# Caller identity: a customer with NO role field, so the old script's
# `id_role or "n/a"` collapses to the literal "n/a" (keeps the IR message free
# of a role-extraction step the primitive set can't express).
_ID_STDOUT = "customer_id=cust_77"

# Basket-lines SQL projection (11 pipe-separated columns, header + one data row).
# Column order mirrors the old script's positional parse:
#   0 basket_id | 1 record_path | 2 customer_id | 3 store_id | 4 basket_status |
#   5 discount_percent | 6 discount_issuer_employee_id | 7 line_number |
#   8 product_sku | 9 requested_quantity | 10 available_today_quantity
# issuer empty (no claimed approval) + req(2) <= avail(5) => old script OK branch.
_SQL = (
    "SELECT b.basket_id, b.record_path, b.customer_id, b.store_id, "
    "b.basket_status, b.discount_percent, b.discount_issuer_employee_id, "
    "i.line_number, i.product_sku, i.requested_quantity, "
    "inv.available_today_quantity FROM shopping_baskets b "
    "JOIN shopping_basket_items i ON i.basket_id = b.basket_id "
    "LEFT JOIN store_inventory inv ON inv.store_id = b.store_id "
    "AND inv.product_sku = i.product_sku WHERE b.basket_id = :basket_id "
    "ORDER BY i.line_number;"
)
_SQL_BIND = "basket_id=basket_154"
_SQL_STDOUT = (
    "basket_id|record_path|customer_id|store_id|basket_status|"
    "discount_percent|issuer|line_number|product_sku|req|avail\n"
    "basket_154|/proc/baskets/basket_154.json|cust_77|store_1|open|"
    "0||1|SKU-1|2|5"
)

# /bin/checkout basket_154 -> clean submission, exit 0.
_CHECKOUT_STDOUT = "submitted"

FIXTURES = {
    fixture_key("Exec", "/bin/id", []): {"stdout": _ID_STDOUT},
    fixture_key("Read", "/docs/security.md"): {"content": "security policy"},
    fixture_key("Read", "/docs/checkout.md"): {"content": "checkout policy"},
    fixture_key("Exec", "/bin/checkout", ["--help"]): {"stdout": "usage: checkout BASKET"},
    fixture_key("Stat", PARAMS["basket_path"]): {"stdout": ""},
    fixture_key("Read", PARAMS["basket_path"]): {"content": "{}"},
    fixture_key("Exec", "/bin/sql", [_SQL, _SQL_BIND]): {"stdout": _SQL_STDOUT},
    fixture_key("Exec", "/bin/checkout", ["basket_154"]): {"stdout": _CHECKOUT_STDOUT, "exit_code": 0},
}
