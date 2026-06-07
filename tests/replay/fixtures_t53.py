from agent.mock_vm_spy import fixture_key

# receipt_path mirrors the path the old script derives from the /uploads listing
# (the only FILE entry whose name contains "receipt").
PARAMS = {"uploads_dir": "/uploads", "threshold_eur": 3,
          "receipt_path": "/uploads/receipt.txt"}

# Receipt parses (via the old script's _parse_receipt) to a single line item:
# ('ABC-1234', qty=2, old_unit_cents=549).
_RECEIPT = "ABC-1234 2 5.49\n"

# Discovery price-lookup SQL (byte-identical to the old script's generated text).
_SQL_PRICES = ("WITH receipt(product_sku, qty) AS (VALUES ('ABC-1234',2)) "
               "SELECT pv.product_sku, pv.product_name, pv.price_cents, "
               "pv.price_currency, r.qty, pv.record_path "
               "FROM receipt r JOIN product_variants pv "
               "ON pv.product_sku = r.product_sku;")

# Comparison SQL (byte-identical). Its stdout fixes the three totals the old
# script reads positionally: old=1099, today=1326, diff=227 (all <= 300 => <YES>,
# and each /100 is %.2f / str() identical: 10.99, 13.26, 2.27).
_SQL_CMP = ("WITH receipt(product_sku, qty, old_unit_cents) AS "
            "(VALUES ('ABC-1234',2,549)) "
            "SELECT SUM(r.qty * r.old_unit_cents) AS old_total_cents, "
            "SUM(r.qty * pv.price_cents) AS today_total_cents, "
            "ABS(SUM(r.qty * pv.price_cents) - SUM(r.qty * r.old_unit_cents)) "
            "AS diff_cents "
            "FROM receipt r JOIN product_variants pv "
            "ON pv.product_sku = r.product_sku;")
_CMP_STDOUT = ("old_total_cents|today_total_cents|diff_cents\n"
               "1099|1326|227")

FIXTURES = {
    fixture_key("List", "/uploads"): {"entries": [{"name": "receipt.txt", "kind": "FILE"}]},
    fixture_key("Read", "/uploads/receipt.txt"): {"content": _RECEIPT},
    fixture_key("Exec", "/bin/sql", [_SQL_PRICES]): {"stdout": "product_sku|product_name|price_cents|price_currency|qty|record_path"},
    fixture_key("Exec", "/bin/sql", [_SQL_CMP]): {"stdout": _CMP_STDOUT},
}
