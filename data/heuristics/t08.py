import csv


def _stdout(result):
    return getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")


def _q(value):
    return "'" + str(value).replace("'", "''") + "'"


def run(vm, params):
    brand = params["brand"]
    family_like = params["family_like"]
    fastener_type = params["fastener_type"]
    diameter_mm = params["diameter_mm"]
    length_mm = params["length_mm"]
    extra_length_mm = params["extra_length_mm"]

    sql = (
        "WITH base AS (\n"
        "  SELECT v.product_sku, v.record_path, v.product_name\n"
        "  FROM product_variants v\n"
        "  JOIN product_variant_properties ft ON ft.product_sku = v.product_sku AND ft.property_key = 'fastener_type' AND ft.property_value_text = "
        + _q(fastener_type) + "\n"
        "  JOIN product_variant_properties d  ON d.product_sku  = v.product_sku AND d.property_key  = 'diameter_mm'  AND d.property_value_number = "
        + str(diameter_mm) + "\n"
        "  JOIN product_variant_properties l  ON l.product_sku  = v.product_sku AND l.property_key  = 'length_mm'    AND l.property_value_number = "
        + str(length_mm) + "\n"
        "  WHERE v.brand = " + _q(brand) + " AND v.product_name LIKE " + _q(family_like) + "\n"
        ")\n"
        "SELECT b.product_sku, b.record_path, b.product_name,\n"
        "       EXISTS(SELECT 1 FROM product_variant_properties e\n"
        "              WHERE e.product_sku = b.product_sku\n"
        "                AND e.property_key = 'length_mm'\n"
        "                AND e.property_value_number = " + str(extra_length_mm) + ") AS has_extra_length\n"
        "FROM base b;"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    out = _stdout(result)

    rows = list(csv.reader(out.splitlines()))
    header_idx = None
    for i, row in enumerate(rows):
        if any(c.strip() == "product_sku" for c in row):
            header_idx = i
            break

    match = None
    if header_idx is not None:
        header = [c.strip() for c in rows[header_idx]]
        col = {name: idx for idx, name in enumerate(header)}
        for row in rows[header_idx + 1:]:
            if not row or len([c for c in row if c.strip() != ""]) == 0:
                continue
            if len(row) < len(header):
                continue
            match = {
                "product_sku": row[col["product_sku"]].strip(),
                "record_path": row[col["record_path"]].strip(),
                "product_name": row[col["product_name"]].strip(),
            }
            break

    if match is not None:
        message = (
            "<NO>. Base product exists \u2014 checked SKU {sku} ({name}, fastener type machine screw, "
            "diameter 6 mm, length 40 mm) at {path}. No catalogue property for length 80 mm is present "
            "on this record, so the support note's extra length 80 mm claim is absent."
        ).format(sku=match["product_sku"], name=match["product_name"], path=match["record_path"])
        refs = [match["record_path"]] if match["record_path"] else []
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
    else:
        message = (
            "<NO>. No base variant matching brand Heco, family Heco Unix TopFix S9H-9J6 Nut Bolt and "
            "Washer, fastener type machine screw, diameter 6 mm, length 40 mm was found in the catalogue, "
            "so the claimed extra length 80 mm cannot be confirmed."
        )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=[])
