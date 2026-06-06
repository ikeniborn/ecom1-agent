import csv
import io


def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    def _stdout(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def parse_csv(text):
        text = (text or "").strip()
        if not text:
            return []
        return list(csv.DictReader(io.StringIO(text)))

    district = params["district"]
    min_qty = int(params["min_qty"])

    # discovery: resolve the Lend district store
    disc_sql = (
        "SELECT store_id, record_path, store_name, city FROM stores "
        "WHERE city = " + q(district) +
        " OR store_name LIKE '%' || " + q(district) + " || '%' LIMIT 1;"
    )
    store = vm.exec(path="/bin/sql", args=[disc_sql])
    store_rows = parse_csv(_stdout(store))
    store_path = ""
    if store_rows:
        store_path = store_rows[0].get("record_path", "") or ""

    specs = [
        (1, params["spec1_family"], params["spec1_brand"], params["spec1_prop_key"], params["spec1_prop_val"]),
        (2, params["spec2_family"], params["spec2_brand"], params["spec2_prop_key"], params["spec2_prop_val"]),
        (3, params["spec3_family"], params["spec3_brand"], params["spec3_prop_key"], params["spec3_prop_val"]),
        (4, params["spec4_family"], params["spec4_brand"], params["spec4_prop_key"], params["spec4_prop_val"]),
        (5, params["spec5_family"], params["spec5_brand"], params["spec5_prop_key"], params["spec5_prop_val"]),
    ]
    values_clause = ", ".join(
        "({}, {}, {}, {}, {})".format(n, q(f), q(b), q(pk), q(pv))
        for (n, f, b, pk, pv) in specs
    )

    ops_sql = (
        "WITH store AS (SELECT store_id, record_path FROM stores WHERE city = " + q(district) +
        " OR store_name LIKE '%' || " + q(district) + " || '%' LIMIT 1), "
        "specs(spec_no, family_name, brand, prop_key, prop_val) AS (VALUES " + values_clause + ") "
        "SELECT s.spec_no, s.family_name, s.prop_val, pv.product_sku, pv.record_path, "
        "COALESCE(si.available_today_quantity, 0) AS avail "
        "FROM specs s "
        "JOIN product_families pf ON pf.product_family_name = s.family_name AND pf.brand = s.brand "
        "JOIN product_variants pv ON pv.product_family_id = pf.product_family_id "
        "JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "AND pvp.property_key = s.prop_key AND pvp.property_value_text = s.prop_val "
        "LEFT JOIN store_inventory si ON si.product_sku = pv.product_sku "
        "AND si.store_id = (SELECT store_id FROM store) "
        "ORDER BY s.spec_no;"
    )
    rows_res = vm.exec(path="/bin/sql", args=[ops_sql])
    rows = parse_csv(_stdout(rows_res))

    count = 0
    available_paths = []
    for row in rows:
        try:
            avail = int(float(row.get("avail", "0") or 0))
        except (ValueError, TypeError):
            avail = 0
        if avail >= min_qty:
            count += 1
            rp = row.get("record_path", "") or ""
            if rp:
                available_paths.append(rp)

    refs = []
    if store_path:
        refs.append(store_path)
    for p in available_paths:
        if p not in refs:
            refs.append(p)

    vm.answer(message="{} products".format(count), outcome="OUTCOME_OK", refs=refs)
