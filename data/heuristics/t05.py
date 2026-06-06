def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = params["brand"]
    series = params["series"]
    model = params["model"]
    fastener_type = params["fastener_type"]
    length_mm = params["length_mm"]

    def get_stdout(result):
        return getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    def parse_rows(stdout):
        text = (stdout or "").strip()
        if not text:
            return []
        lines = text.splitlines()
        if not lines:
            return []
        header = [h.strip() for h in lines[0].split(",")]
        rows = []
        for line in lines[1:]:
            if not line.strip():
                continue
            cells = [c.strip() for c in line.split(",")]
            row = {}
            for i, col in enumerate(header):
                row[col] = cells[i] if i < len(cells) else ""
            rows.append(row)
        return rows

    match_sql = (
        "WITH fam AS (SELECT product_sku, record_path, product_name FROM product_variants "
        "WHERE brand=" + q(brand) + " AND series=" + q(series) + " AND model=" + q(model) + "), "
        "ft AS (SELECT product_sku FROM product_variant_properties "
        "WHERE property_key='fastener_type' AND property_value_text=" + q(fastener_type) + "), "
        "ln AS (SELECT product_sku FROM product_variant_properties "
        "WHERE property_key='length_mm' AND property_value_number=" + str(length_mm) + ") "
        "SELECT f.product_sku, f.record_path, f.product_name FROM fam f "
        "JOIN ft ON ft.product_sku=f.product_sku JOIN ln ON ln.product_sku=f.product_sku;"
    )
    match_result = vm.exec(path="/bin/sql", args=[match_sql])
    match_rows = parse_rows(get_stdout(match_result))

    family_sql = (
        "SELECT v.product_sku, v.record_path, v.product_name, "
        "p.property_value_text AS fastener_type, q.property_value_number AS length_mm "
        "FROM product_variants v "
        "LEFT JOIN product_variant_properties p ON p.product_sku=v.product_sku AND p.property_key='fastener_type' "
        "LEFT JOIN product_variant_properties q ON q.product_sku=v.product_sku AND q.property_key='length_mm' "
        "WHERE v.brand=" + q(brand) + " AND v.series=" + q(series) + " AND v.model=" + q(model) + " "
        "ORDER BY v.product_sku;"
    )
    family_result = vm.exec(path="/bin/sql", args=[family_sql])
    family_rows = parse_rows(get_stdout(family_result))

    if match_rows:
        row = match_rows[0]
        matched_sku = row.get("product_sku", "")
        matched_path = row.get("record_path", "")
        message = (
            "<YES> The HECO 3DW-64B Nut Bolt and Washer family (" + brand + " " + series + " " + model +
            ") includes variant SKU " + matched_sku + " with fastener_type 'threaded rod' and length 20 mm at " +
            matched_path + "."
        )
        refs = [matched_path] if matched_path else []
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
        return

    if family_rows:
        checked = family_rows[0]
        checked_sku = checked.get("product_sku", "")
        checked_path = checked.get("record_path", "")
        message = (
            "<NO> The HECO 3DW-64B Nut Bolt and Washer family (" + brand + " " + series + " " + model +
            ") exists, but no catalogue variant carries fastener_type 'threaded rod' with length 20 mm. "
            "Checked SKU " + checked_sku + " at " + checked_path + " does not match that claim."
        )
        refs = [checked_path] if checked_path else []
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
        return

    message = (
        "<NO> No product_variant in the " + brand + " " + series + " " + model +
        " family exists in the catalogue, so the claimed threaded rod / 20 mm variant cannot be confirmed."
    )
    vm.answer(message=message, outcome="OUTCOME_OK", refs=[])
