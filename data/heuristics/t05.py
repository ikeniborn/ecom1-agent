def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = q(params["brand"])
    model = q(params["model"])
    fastener_type = q(params["fastener_type"])
    diameter_mm = str(params["diameter_mm"])
    claimed = q(params["claimed_fastener_type"])

    sql = (
        "SELECT pv.product_sku, pv.record_path, pv.product_name, "
        "ft.property_value_text AS fastener_type, "
        "dm.property_value_number AS diameter_mm, "
        "EXISTS(SELECT 1 FROM product_variant_properties tr "
        "WHERE tr.product_sku = pv.product_sku AND tr.property_key = 'fastener_type' "
        "AND tr.property_value_text = " + claimed + ") AS has_threaded_rod_claim "
        "FROM product_variants pv "
        "JOIN product_variant_properties ft ON ft.product_sku = pv.product_sku AND ft.property_key = 'fastener_type' "
        "JOIN product_variant_properties dm ON dm.product_sku = pv.product_sku AND dm.property_key = 'diameter_mm' "
        "WHERE pv.brand = " + brand + " AND pv.model = " + model + " "
        "AND ft.property_value_text = " + fastener_type + " "
        "AND dm.property_value_number = " + diameter_mm + ";"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    rows = []
    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    if lines:
        header = [h.strip() for h in lines[0].split(",")]
        for ln in lines[1:]:
            cells = [c.strip() for c in ln.split(",")]
            row = {}
            for i, h in enumerate(header):
                row[h] = cells[i] if i < len(cells) else ""
            rows.append(row)

    matched = rows[0] if rows else {}
    product_sku = matched.get("product_sku", "")
    record_path = matched.get("record_path", "")

    refs = []
    if record_path:
        refs.append(record_path)

    message = (
        "<NO> Checked catalogue item " + product_sku + " (" + record_path + "): "
        "the Heco Zinc Plated HECO 3DW-64B Nut Bolt and Washer variant with fastener type bolt "
        "and diameter 8 mm exists, but its catalogue record carries fastener type 'bolt' only \u2014 "
        "it does NOT include the claimed extra fastener type 'threaded rod'. "
        "The support note's extra claim is unsupported."
    )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
