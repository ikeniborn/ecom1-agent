def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = q(params["brand"])
    family = q(params["family_name"])
    machine_type = q(params["machine_type"])
    city = q(params["city"])
    voltage = str(int(params["voltage_v"]))

    sql = (
        "WITH target AS (\n"
        "  SELECT pv.product_sku, pv.record_path\n"
        "  FROM product_variants pv\n"
        "  JOIN product_families pf ON pf.product_family_id = pv.product_family_id\n"
        "  JOIN product_variant_properties mt ON mt.product_sku = pv.product_sku AND mt.property_key = 'machine_type' AND mt.property_value_text = " + machine_type + "\n"
        "  JOIN product_variant_properties vv ON vv.product_sku = pv.product_sku AND vv.property_key = 'voltage_v' AND vv.property_value_number = " + voltage + "\n"
        "  WHERE pv.brand = " + brand + " AND pf.product_family_name = " + family + "\n"
        "),\n"
        "vienna AS (\n"
        "  SELECT store_id, record_path FROM stores WHERE city = " + city + " AND is_open = 1\n"
        ")\n"
        "SELECT v.store_id,\n"
        "       v.record_path AS store_record_path,\n"
        "       t.product_sku,\n"
        "       t.record_path AS product_record_path,\n"
        "       si.available_today_quantity\n"
        "FROM vienna v\n"
        "JOIN store_inventory si ON si.store_id = v.store_id\n"
        "JOIN target t ON t.product_sku = si.product_sku\n"
        "WHERE si.available_today_quantity > 0;"
    )

    result = vm.exec(path="/bin/sql", args=[], stdin=sql)
    stdout = getattr(result, "stdout", None)
    if stdout is None:
        stdout = result.get("stdout", "") if isinstance(result, dict) else ""
    stdout = stdout or ""

    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    store_paths = []
    product_path = None
    total = 0

    if len(lines) > 1:
        header = lines[0]
        if "," in header:
            delim = ","
        elif "|" in header:
            delim = "|"
        else:
            delim = ","
        for line in lines[1:]:
            cols = [c.strip() for c in line.split(delim)]
            if len(cols) < 5:
                continue
            store_paths.append(cols[1])
            product_path = cols[3]
            try:
                total += int(cols[4])
            except (ValueError, TypeError):
                pass

    if not store_paths or product_path is None:
        vm.answer(message="result: 0", outcome="OUTCOME_NONE_UNSUPPORTED", refs=[])
        return

    seen = set()
    uniq_store_paths = []
    for p in store_paths:
        if p and p not in seen:
            seen.add(p)
            uniq_store_paths.append(p)

    refs = uniq_store_paths + [product_path]
    vm.answer(message="result: %d" % total, outcome="OUTCOME_OK", refs=refs)
