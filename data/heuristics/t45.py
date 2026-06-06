def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    store_city = params["store_city"]
    store_name_like = params["store_name_like"]

    specs = [
        {"brand": params["p1_brand"], "model": params["p1_model"],
         "text": [("tool_type", params["p1_tool_type"])], "num": []},
        {"brand": params["p2_brand"], "model": params["p2_model"],
         "text": [("machine_type", params["p2_machine_type"])], "num": []},
        {"brand": params["p3_brand"], "model": params["p3_model"],
         "text": [("screw_type", params["p3_screw_type"])],
         "num": [("diameter_mm", params["p3_diameter_mm"])]},
        {"brand": params["p4_brand"], "model": params["p4_model"],
         "text": [("fitting_type", params["p4_fitting_type"]),
                  ("connection_type", params["p4_connection_type"])],
         "num": [("diameter_mm", params["p4_diameter_mm"])]},
        {"brand": params["p5_brand"], "model": params["p5_model"],
         "text": [("garment_type", params["p5_garment_type"])], "num": []},
        {"brand": params["p6_brand"], "model": params["p6_model"],
         "text": [("adhesive_type", params["p6_adhesive_type"])], "num": []},
    ]

    def variant_select(cols):
        parts = []
        for s in specs:
            conds = ["v.brand = " + q(s["brand"]), "v.model = " + q(s["model"])]
            for k, val in s["text"]:
                conds.append("EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = v.product_sku AND p.property_key = " + q(k) + " AND p.property_value_text = " + q(val) + ")")
            for k, val in s["num"]:
                conds.append("EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = v.product_sku AND p.property_key = " + q(k) + " AND p.property_value_number = " + str(val) + ")")
            parts.append("SELECT " + cols + " FROM product_variants v WHERE " + " AND ".join(conds))
        return "\nUNION ALL\n".join(parts)

    store_cte = "target_store AS (SELECT store_id FROM stores WHERE city = " + q(store_city) + " AND store_name LIKE " + q(store_name_like) + " LIMIT 1)"

    discovery_sql = (
        "WITH " + store_cte + ",\n"
        "matched AS (\n" + variant_select("v.product_sku AS product_sku, v.record_path AS record_path") + "\n)\n"
        "SELECT m.record_path AS record_path FROM matched m\n"
        "JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = (SELECT store_id FROM target_store)\n"
        "WHERE COALESCE(si.available_today_quantity, 0) > 0;"
    )
    store_probe = vm.exec(path="/bin/sql", args=[], stdin=discovery_sql)

    ops_sql = (
        "WITH " + store_cte + ",\n"
        "matched AS (\n" + variant_select("v.product_sku AS product_sku") + "\n)\n"
        "SELECT COUNT(*) AS unavailable_count FROM matched m\n"
        "LEFT JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = (SELECT store_id FROM target_store)\n"
        "WHERE COALESCE(si.available_today_quantity, 0) = 0;"
    )
    count_res = vm.exec(path="/bin/sql", args=[], stdin=ops_sql)

    def get_stdout(r):
        return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")

    refs = []
    probe_out = get_stdout(store_probe)
    for line in probe_out.splitlines():
        line = line.strip()
        if not line:
            continue
        cell = line.split(",")[0].strip().strip('"')
        if cell and cell.lower() != "record_path":
            refs.append(cell)

    count_out = get_stdout(count_res)
    unavailable_count = 0
    for line in count_out.splitlines():
        line = line.strip()
        if not line:
            continue
        cell = line.split(",")[0].strip().strip('"')
        if cell.lower() == "unavailable_count":
            continue
        try:
            unavailable_count = int(cell)
        except ValueError:
            continue

    vm.answer(message=str(unavailable_count), outcome="OUTCOME_OK", refs=refs)
