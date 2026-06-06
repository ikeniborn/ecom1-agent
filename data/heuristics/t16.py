def run(vm, params):
    def lit(v):
        if v is None:
            return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    def _stdout(r):
        return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")

    def _rows(text):
        lines = [l for l in (text or "").splitlines() if l.strip() != ""]
        if len(lines) <= 1:
            return []
        return [l.split(",") for l in lines[1:]]

    # --- Discovery 1: resolve central Salzburg store by city scope ---
    store_city = params["store_city"]
    store_sql = "SELECT store_id, store_name, city, record_path FROM stores WHERE city = " + lit(store_city) + ";"
    store = vm.exec(path="/bin/sql", args=[store_sql])
    store_rows = _rows(_stdout(store))

    store_id = ""
    store_record_path = ""
    hint = str(params.get("store_name_hint", "")).lower()
    if store_rows:
        chosen = None
        if len(store_rows) == 1:
            chosen = store_rows[0]
        else:
            for row in store_rows:
                name = row[1].lower() if len(row) > 1 else ""
                if hint and hint in name:
                    chosen = row
                    break
            if chosen is None:
                chosen = store_rows[0]
        if chosen:
            store_id = chosen[0].strip() if len(chosen) > 0 else ""
            store_record_path = chosen[3].strip() if len(chosen) > 3 else ""

    # --- Discovery 2: count matched SKUs with available_today_quantity >= min_qty ---
    min_qty = params["min_qty"]
    specs = [
        (1, params["p1_family"], "size", params["p1_size"], "color_family", params["p1_color_family"], None, None),
        (2, params["p2_family"], "power_source", params["p2_power_source"], "bar_length_cm", params["p2_bar_length_cm"], "battery_platform", params["p2_battery_platform"]),
        (3, params["p3_family"], "product_type", params["p3_product_type"], "color_family", params["p3_color_family"], None, None),
        (4, params["p4_family"], "storage_type", params["p4_storage_type"], "color_family", params["p4_color_family"], None, None),
        (5, params["p5_family"], "size", params["p5_size"], "color_family", params["p5_color_family"], None, None),
        (6, params["p6_family"], "color_family", params["p6_color_family"], "finish", params["p6_finish"], "volume_ml", params["p6_volume_ml"]),
    ]
    value_rows = []
    for s in specs:
        idx, fam, k1, v1, k2, v2, k3, v3 = s
        value_rows.append("(%d, %s, %s, %s, %s, %s, %s, %s)" % (
            idx, lit(fam), lit(k1), lit(v1), lit(k2), lit(v2), lit(k3), lit(v3)))
    values_clause = ", ".join(value_rows)

    count_sql = (
        "WITH specs(idx, family, k1, v1, k2, v2, k3, v3) AS (VALUES " + values_clause + "), "
        "matched AS ("
        "SELECT s.idx, pv.product_sku FROM specs s "
        "JOIN product_families pf ON pf.product_family_name = s.family "
        "JOIN product_variants pv ON pv.product_family_id = pf.product_family_id "
        "WHERE EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = s.k1 AND p.property_value_text = s.v1) "
        "AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = s.k2 AND p.property_value_text = s.v2) "
        "AND (s.k3 IS NULL OR EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = s.k3 AND p.property_value_text = s.v3))"
        ") "
        "SELECT COUNT(*) AS available_count FROM matched m "
        "JOIN store_inventory si ON si.product_sku = m.product_sku "
        "WHERE si.store_id = " + lit(store_id) + " AND si.available_today_quantity >= " + str(min_qty) + ";"
    )
    count_result = vm.exec(path="/bin/sql", args=[count_sql])
    count_rows = _rows(_stdout(count_result))

    available_count = 0
    if count_rows and len(count_rows[0]) > 0:
        cell = count_rows[0][0].strip()
        try:
            available_count = int(cell)
        except (ValueError, TypeError):
            available_count = 0

    refs = []
    if store_record_path:
        refs.append(store_record_path)

    message = "Count: %d" % available_count
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
