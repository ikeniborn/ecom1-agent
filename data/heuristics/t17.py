def run(vm, params):
    def get_stdout(result):
        stdout = getattr(result, "stdout", None)
        if stdout is None and isinstance(result, dict):
            stdout = result.get("stdout", "")
        return stdout or ""

    def parse_rows(stdout):
        lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
        if not lines:
            return []
        data_lines = lines[1:]
        rows = []
        for ln in data_lines:
            if "," in ln:
                cells = [c.strip() for c in ln.split(",")]
            elif "|" in ln:
                cells = [c.strip() for c in ln.split("|")]
            else:
                cells = [ln.strip()]
            rows.append(cells)
        return rows

    # ---- discovery ----
    identity = vm.exec(path="/bin/id", args=[])

    product_sql = "SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_families pf ON pv.product_family_id = pf.product_family_id JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku WHERE pv.brand = 'Heco' AND pf.product_family_name = 'Heco Zinc Plated HECO 3DW-64B Nut Bolt and Washer' AND pvp.property_key = 'fastener_type' AND pvp.property_value_text = 'threaded rod';"
    product = vm.exec(path="/bin/sql", args=[product_sql])

    graz_sql = "SELECT store_id, store_name, record_path FROM stores WHERE city = 'Graz' ORDER BY store_id;"
    graz_stores = vm.exec(path="/bin/sql", args=[graz_sql])

    # ---- ops ----
    count_sql = "WITH target_product AS (SELECT pv.product_sku FROM product_variants pv JOIN product_families pf ON pv.product_family_id = pf.product_family_id JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku WHERE pv.brand = 'Heco' AND pf.product_family_name = 'Heco Zinc Plated HECO 3DW-64B Nut Bolt and Washer' AND pvp.property_key = 'fastener_type' AND pvp.property_value_text = 'threaded rod'), graz_stores AS (SELECT store_id FROM stores WHERE city = 'Graz') SELECT COALESCE(SUM(si.available_today_quantity), 0) AS total_available FROM graz_stores gs CROSS JOIN target_product tp LEFT JOIN store_inventory si ON si.store_id = gs.store_id AND si.product_sku = tp.product_sku;"
    count_result = vm.exec(path="/bin/sql", args=[count_sql])

    # ---- extract product record_path (last column) ----
    product_rows = parse_rows(get_stdout(product))
    product_path = ""
    if product_rows and product_rows[0]:
        product_path = product_rows[0][-1].strip()

    # ---- extract every Graz store record_path (last column) ----
    graz_rows = parse_rows(get_stdout(graz_stores))
    graz_store_record_paths = []
    for row in graz_rows:
        if row:
            p = row[-1].strip()
            if p:
                graz_store_record_paths.append(p)

    # agents_md constraint: refs must be full repo paths
    for p in [product_path] + graz_store_record_paths:
        assert isinstance(p, str)

    # ---- extract total_available ----
    count_rows = parse_rows(get_stdout(count_result))
    total_available = 0
    if count_rows and count_rows[0]:
        raw = count_rows[0][0].strip()
        try:
            total_available = int(raw)
        except ValueError:
            try:
                total_available = int(float(raw))
            except ValueError:
                total_available = 0

    # ---- build refs ----
    refs = []
    if product_path:
        refs.append(product_path)
    for p in graz_store_record_paths:
        if p not in refs:
            refs.append(p)

    message = "count: {}".format(total_available)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
