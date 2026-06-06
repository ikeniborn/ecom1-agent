def run(vm, params):
    def lit(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = params["brand"]
    family = params["family"]
    machine_type = params["machine_type"]
    voltage = params["voltage"]
    city = params["city"]

    def inline(sql):
        sql = sql.replace(":machine_type", lit(machine_type))
        sql = sql.replace(":voltage", str(int(voltage)))
        sql = sql.replace(":brand", lit(brand))
        sql = sql.replace(":family", lit(family))
        sql = sql.replace(":city", lit(city))
        return sql

    detail_sql = (
        "WITH target AS (\n"
        "  SELECT pv.product_sku, pv.record_path AS product_path\n"
        "  FROM product_variants pv\n"
        "  JOIN product_families pf ON pf.product_family_id = pv.product_family_id\n"
        "  JOIN product_variant_properties mp ON mp.product_sku = pv.product_sku AND mp.property_key = 'machine_type' AND mp.property_value_text = :machine_type\n"
        "  JOIN product_variant_properties vp ON vp.product_sku = pv.product_sku AND vp.property_key = 'voltage_v' AND vp.property_value_number = :voltage\n"
        "  WHERE pv.brand = :brand AND pf.product_family_name = :family\n"
        ")\n"
        "SELECT s.store_id, s.record_path AS store_path, t.product_sku, t.product_path, si.available_today_quantity\n"
        "FROM target t\n"
        "JOIN store_inventory si ON si.product_sku = t.product_sku\n"
        "JOIN stores s ON s.store_id = si.store_id\n"
        "WHERE s.city = :city AND s.is_open = 1 AND si.available_today_quantity > 0\n"
        "ORDER BY s.store_id;"
    )

    agg_sql = (
        "WITH target AS (\n"
        "  SELECT pv.product_sku\n"
        "  FROM product_variants pv\n"
        "  JOIN product_families pf ON pf.product_family_id = pv.product_family_id\n"
        "  JOIN product_variant_properties mp ON mp.product_sku = pv.product_sku AND mp.property_key = 'machine_type' AND mp.property_value_text = :machine_type\n"
        "  JOIN product_variant_properties vp ON vp.product_sku = pv.product_sku AND vp.property_key = 'voltage_v' AND vp.property_value_number = :voltage\n"
        "  WHERE pv.brand = :brand AND pf.product_family_name = :family\n"
        ")\n"
        "SELECT COALESCE(SUM(si.available_today_quantity),0) AS total_units\n"
        "FROM target t\n"
        "JOIN store_inventory si ON si.product_sku = t.product_sku\n"
        "JOIN stores s ON s.store_id = si.store_id\n"
        "WHERE s.city = :city AND s.is_open = 1;"
    )

    def stdout_of(result):
        return getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    rows_res = vm.exec(path="/bin/sql", args=[], stdin=inline(detail_sql))
    rows = stdout_of(rows_res)

    total_res = vm.exec(path="/bin/sql", args=[], stdin=inline(agg_sql))
    _ = stdout_of(total_res)

    lines = [ln for ln in rows.splitlines() if ln.strip() != ""]
    data_lines = lines[1:] if lines else []

    store_paths = []
    product_path = None
    total = 0
    for ln in data_lines:
        cols = ln.split(",")
        if len(cols) < 5:
            continue
        store_path = cols[1].strip()
        product_path = cols[3].strip()
        try:
            qty = int(cols[4].strip())
        except ValueError:
            qty = 0
        store_paths.append(store_path)
        total += qty

    if not store_paths or product_path is None:
        vm.answer(
            message="No available units found for the requested variant in open Vienna stores.",
            outcome="OUTCOME_NONE_UNSUPPORTED",
            refs=[],
        )
        return

    refs = []
    seen = set()
    for sp in store_paths:
        if sp not in seen:
            seen.add(sp)
            refs.append(sp)
    refs.append(product_path)

    vm.answer(
        message="report count %d" % total,
        outcome="OUTCOME_OK",
        refs=refs,
    )
