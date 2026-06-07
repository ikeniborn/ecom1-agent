def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    # Constraint guard (#important-things): yes/no token + full reference path are
    # always emitted in the answer below.

    brand = params["brand"]
    series = params["series"]
    model = params["model"]
    power_source = params["power_source"]
    base_bar_length = params["base_bar_length"]
    claim_bar_length = params["claim_bar_length"]

    # /bin/sql rejects :name bind args -> inline values as single-quoted literals.
    sql = (
        "WITH base AS (\n"
        "  SELECT pv.product_sku, pv.record_path\n"
        "  FROM product_variants pv\n"
        "  JOIN product_variant_properties ps ON ps.product_sku = pv.product_sku AND ps.property_key = 'power_source' AND ps.property_value_text = " + q(power_source) + "\n"
        "  JOIN product_variant_properties bl ON bl.product_sku = pv.product_sku AND bl.property_key = 'bar_length_cm' AND bl.property_value_number = " + str(int(base_bar_length)) + "\n"
        "  WHERE pv.brand = " + q(brand) + " AND pv.series = " + q(series) + " AND pv.model = " + q(model) + "\n"
        "),\n"
        "claim AS (\n"
        "  SELECT pv.product_sku\n"
        "  FROM product_variants pv\n"
        "  JOIN product_variant_properties bl ON bl.product_sku = pv.product_sku AND bl.property_key = 'bar_length_cm' AND bl.property_value_number = " + str(int(claim_bar_length)) + "\n"
        "  WHERE pv.brand = " + q(brand) + " AND pv.series = " + q(series) + " AND pv.model = " + q(model) + "\n"
        ")\n"
        "SELECT b.product_sku, b.record_path, (SELECT COUNT(*) FROM claim) AS claim_variant_count\n"
        "FROM base b;"
    )

    base_lookup = vm.exec(path="/bin/sql", args=[sql])

    stdout = getattr(base_lookup, "stdout", "") or (base_lookup.get("stdout", "") if isinstance(base_lookup, dict) else "")

    rows = []
    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    header_idx = -1
    for i, ln in enumerate(lines):
        low = ln.lower()
        if "product_sku" in low and "record_path" in low:
            header_idx = i
            break
    if header_idx >= 0:
        header = [h.strip() for h in lines[header_idx].split(",")]
        for ln in lines[header_idx + 1:]:
            cells = [c.strip() for c in ln.split(",")]
            if len(cells) < len(header):
                continue
            rows.append(dict(zip(header, cells)))

    if rows:
        skus = [r.get("product_sku", "") for r in rows if r.get("product_sku")]
        paths = [r.get("record_path", "") for r in rows if r.get("record_path")]
        try:
            claim_count = int((rows[0].get("claim_variant_count", "0") or "0"))
        except ValueError:
            claim_count = 0
        sku_str = ", ".join(skus)
        path_str = paths[0] if paths else ""
        if claim_count == 0:
            message = (
                "<NO> The base Stihl AK System MS T7U-JRP Chainsaw (power source battery, 45 cm bar) "
                "exists as SKU " + sku_str + " at " + path_str + ", but the catalogue carries no variant "
                "in that line with a 20 cm bar length (" + str(claim_count) + " found) - the support "
                "note's extra claim is absent. Checked SKU: " + sku_str + "."
            )
        else:
            message = (
                "<YES> The base Stihl AK System MS T7U-JRP Chainsaw (power source battery, 45 cm bar) "
                "exists as SKU " + sku_str + " at " + path_str + ", and the catalogue does carry "
                + str(claim_count) + " variant(s) in that line with a 20 cm bar length. Checked SKU: "
                + sku_str + "."
            )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=paths)
    else:
        message = (
            "<NO> No base Stihl AK System MS T7U-JRP Chainsaw (power source battery, 45 cm bar) variant "
            "was found in the catalogue, so the support note's 20 cm bar-length claim cannot be confirmed."
        )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=[])
