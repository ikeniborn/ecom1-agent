def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = params["brand"]
    line = params["line"]
    color_family = params["color_family"]
    base_type = params["base_type"]

    sql = (
        "WITH base AS (SELECT v.product_sku, v.record_path, v.product_name "
        "FROM product_variants v WHERE v.brand = " + q(brand) + " "
        "AND v.product_name LIKE '%' || " + q(line) + " || '%'), "
        "props AS (SELECT b.product_sku, b.record_path, b.product_name, "
        "MAX(CASE WHEN p.property_key IN ('color_family','colour_family','color') "
        "THEN p.property_value_text END) AS color_family, "
        "MAX(CASE WHEN p.property_key IN ('base_type','base','paint_base') "
        "THEN p.property_value_text END) AS base_type "
        "FROM base b LEFT JOIN product_variant_properties p "
        "ON p.product_sku = b.product_sku "
        "GROUP BY b.product_sku, b.record_path, b.product_name) "
        "SELECT product_sku, record_path, product_name, color_family, base_type, "
        "CASE WHEN LOWER(color_family) = LOWER(" + q(color_family) + ") "
        "AND LOWER(base_type) = LOWER(" + q(base_type) + ") THEN 1 ELSE 0 END AS claim_match "
        "FROM props ORDER BY claim_match DESC;"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "")
    if not stdout and isinstance(result, dict):
        stdout = result.get("stdout", "")
    stdout = stdout or ""

    cols = ["product_sku", "record_path", "product_name", "color_family", "base_type", "claim_match"]
    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]

    def pick_delim(line):
        if "|" in line:
            return "|"
        if "," in line:
            return ","
        if "\t" in line:
            return "\t"
        return None

    rows = []
    if lines:
        delim = pick_delim(lines[0])
        start = 0
        if delim is not None:
            first = [c.strip() for c in lines[0].split(delim)]
            if any(c in cols for c in first):
                start = 1
        for ln in lines[start:]:
            if delim is not None:
                parts = [c.strip() for c in ln.split(delim)]
            else:
                parts = [ln.strip()]
            row = {}
            for i, name in enumerate(cols):
                row[name] = parts[i] if i < len(parts) else ""
            rows.append(row)

    if not rows:
        vm.answer(
            message=("<NO> \u2014 No catalogue record found for base product line '" + str(line) +
                     "' (brand " + str(brand) + "); cannot confirm color family 'Clear' + water-based base."),
            outcome="OUTCOME_OK",
            refs=[],
        )
        return

    match_row = None
    for r in rows:
        if str(r.get("claim_match", "0")).strip() == "1":
            match_row = r
            break

    base = rows[0]
    base_path = base.get("record_path", "")
    refs = [base_path] if base_path else []

    if match_row is not None:
        mpath = match_row.get("record_path", "")
        refs = [mpath] if mpath else refs
        message = ("<YES> \u2014 Base product line '" + str(line) + "' exists (SKU " +
                   str(match_row.get("product_sku", "")) + ", color_family=" +
                   str(match_row.get("color_family", "")) + ", base_type=" +
                   str(match_row.get("base_type", "")) + ") and carries the claimed combination "
                   "color family 'Clear' + water-based base. Checked record: " + str(mpath) + ".")
    else:
        message = ("<NO> \u2014 Base product line '" + str(line) + "' exists (SKU " +
                   str(base.get("product_sku", "")) + ", color_family=" +
                   str(base.get("color_family", "")) + ", base_type=" +
                   str(base.get("base_type", "")) + "), but no catalogue item in this line carries the "
                   "claimed combination color family 'Clear' + water-based base. Checked record: " +
                   str(base_path) + ".")

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
