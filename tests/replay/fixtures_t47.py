from agent.mock_vm_spy import fixture_key

# Per-row product params (mirrors the pasted-row task input). store_id is concrete
# so the old script's inlined SQL literal is byte-stable.
PARAMS = {
    "store_id": "store_1",
    "FK775": {"brand": "Bosch", "series": "Bench IXO", "model": "3JP-JOU",
              "kind": "Workshop Saw and Cutter",
              "props": {"machine_type": "table saw", "voltage_v": "230"}, "quantity": 1},
    "WgE71": {"brand": "Makita", "series": "Workshop DDF", "model": "OIE-YYP",
              "kind": "Workshop Drill Grinder and Sander",
              "props": {"machine_type": "drill press", "voltage_v": "230", "power_w": "750"},
              "quantity": 1},
    "KQHmi": {"brand": "Bahco", "series": "Comfort Grip BE", "model": "1ZR-PGS",
              "kind": "Pliers and Wrenches",
              "props": {"tool_type": "adjustable wrench"}, "quantity": 3},
    "UUzXw": {"brand": "3M", "series": "Ventilated SecureFit", "model": "2CE-B35",
              "kind": "Safety Eyewear",
              "props": {"lens_color": "Yellow"}, "quantity": 5},
    "T4swK": {"brand": "Bahco", "series": "Workshop BAH", "model": "3VZ-SPH",
              "kind": "Hammer Measuring and Cutting Tool",
              "props": {"tool_type": "measuring tape"}, "quantity": 3},
}

# Exact per-row SQL strings the old script emits (inlined single-quoted literals,
# pp alias, store_id='store_1'). Reproduced verbatim so MockVMSpy matches.
_SQL_FK775 = "WITH matched AS (SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pv.brand = 'Bosch' AND pv.series = 'Bench IXO' AND pv.model = '3JP-JOU' AND pk.product_kind_name = 'Workshop Saw and Cutter' AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'machine_type' AND pp.property_value_text = 'table saw') AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'voltage_v' AND pp.property_value_text = '230')) SELECT m.product_sku, m.record_path, COALESCE(si.available_today_quantity, 0) AS in_stock FROM matched m LEFT JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = 'store_1';"
_SQL_WgE71 = "WITH matched AS (SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pv.brand = 'Makita' AND pv.series = 'Workshop DDF' AND pv.model = 'OIE-YYP' AND pk.product_kind_name = 'Workshop Drill Grinder and Sander' AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'machine_type' AND pp.property_value_text = 'drill press') AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'voltage_v' AND pp.property_value_text = '230') AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'power_w' AND pp.property_value_text = '750')) SELECT m.product_sku, m.record_path, COALESCE(si.available_today_quantity, 0) AS in_stock FROM matched m LEFT JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = 'store_1';"
_SQL_KQHmi = "WITH matched AS (SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pv.brand = 'Bahco' AND pv.series = 'Comfort Grip BE' AND pv.model = '1ZR-PGS' AND pk.product_kind_name = 'Pliers and Wrenches' AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'tool_type' AND pp.property_value_text = 'adjustable wrench')) SELECT m.product_sku, m.record_path, COALESCE(si.available_today_quantity, 0) AS in_stock FROM matched m LEFT JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = 'store_1';"
_SQL_UUzXw = "WITH matched AS (SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pv.brand = '3M' AND pv.series = 'Ventilated SecureFit' AND pv.model = '2CE-B35' AND pk.product_kind_name = 'Safety Eyewear' AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'lens_color' AND pp.property_value_text = 'Yellow')) SELECT m.product_sku, m.record_path, COALESCE(si.available_today_quantity, 0) AS in_stock FROM matched m LEFT JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = 'store_1';"
_SQL_T4swK = "WITH matched AS (SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pv.brand = 'Bahco' AND pv.series = 'Workshop BAH' AND pv.model = '3VZ-SPH' AND pk.product_kind_name = 'Hammer Measuring and Cutting Tool' AND EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = 'tool_type' AND pp.property_value_text = 'measuring tape')) SELECT m.product_sku, m.record_path, COALESCE(si.available_today_quantity, 0) AS in_stock FROM matched m LEFT JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = 'store_1';"

# Each SQL returns one comma-delimited data row: product_sku, record_path, in_stock.
# Stock chosen >= requested quantity for every row => match=true everywhere (the
# old script's happy branch), and every distinct path > 0 stock => cited in refs.
_OUT_FK775 = "product_sku,record_path,in_stock\nSKU-FK,/proc/catalog/SKU-FK.json,4"
_OUT_WgE71 = "product_sku,record_path,in_stock\nSKU-WG,/proc/catalog/SKU-WG.json,2"
_OUT_KQHmi = "product_sku,record_path,in_stock\nSKU-KQ,/proc/catalog/SKU-KQ.json,9"
_OUT_UUzXw = "product_sku,record_path,in_stock\nSKU-UU,/proc/catalog/SKU-UU.json,7"
_OUT_T4swK = "product_sku,record_path,in_stock\nSKU-T4,/proc/catalog/SKU-T4.json,3"

FIXTURES = {
    fixture_key("Exec", "/bin/id", []): {"stdout": "user=emp_3 store=store_1"},
    fixture_key("Exec", "/bin/sql", [_SQL_FK775]): {"stdout": _OUT_FK775},
    fixture_key("Exec", "/bin/sql", [_SQL_WgE71]): {"stdout": _OUT_WgE71},
    fixture_key("Exec", "/bin/sql", [_SQL_KQHmi]): {"stdout": _OUT_KQHmi},
    fixture_key("Exec", "/bin/sql", [_SQL_UUzXw]): {"stdout": _OUT_UUzXw},
    fixture_key("Exec", "/bin/sql", [_SQL_T4swK]): {"stdout": _OUT_T4swK},
}
