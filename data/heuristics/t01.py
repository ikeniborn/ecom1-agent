def run(vm, params):
    brand = str(params["brand"]).replace("'", "''")
    family_name = str(params["family_name"]).replace("'", "''")
    screw_type = str(params["screw_type"]).replace("'", "''")
    diameter_mm = str(params["diameter_mm"]).replace("'", "''")

    sql = (
        "SELECT pv.product_sku, pv.product_name, pv.record_path "
        "FROM product_variants pv "
        "JOIN product_variant_properties st ON st.product_sku = pv.product_sku "
        "AND st.property_key = 'screw_type' AND LOWER(st.property_value_text) = LOWER('" + screw_type + "') "
        "JOIN product_variant_properties dm ON dm.product_sku = pv.product_sku "
        "AND dm.property_key = 'diameter_mm' AND dm.property_value_number = " + diameter_mm + " "
        "JOIN product_families pf ON pf.product_family_id = pv.product_family_id "
        "WHERE LOWER(pv.brand) = LOWER('" + brand + "') "
        "AND LOWER(pf.product_family_name) = LOWER('" + family_name + "');"
    )

    result = vm.exec(path="/bin/sql", args=[], stdin=sql)
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    matches = []
    if lines:
        header = lines[0]
        delim = "|" if "|" in header else ("," if "," in header else "\t")
        cols = [c.strip().lower() for c in header.split(delim)]
        path_idx = cols.index("record_path") if "record_path" in cols else (len(cols) - 1)
        sku_idx = cols.index("product_sku") if "product_sku" in cols else 0
        name_idx = cols.index("product_name") if "product_name" in cols else 1
        for ln in lines[1:]:
            parts = [p.strip() for p in ln.split(delim)]
            if len(parts) < len(cols):
                continue
            matches.append({
                "product_sku": parts[sku_idx] if sku_idx < len(parts) else "",
                "product_name": parts[name_idx] if name_idx < len(parts) else "",
                "record_path": parts[path_idx] if path_idx < len(parts) else "",
            })

    refs = []
    if matches and matches[0].get("record_path"):
        refs.append(matches[0]["record_path"])

    if matches:
        message = "<YES> Heco Zinc Plated TopFix GTU-YPJ Wood and Drywall Screw with screw type 'wood screw' and diameter 3 mm is in the catalogue: " + matches[0]["record_path"]
    else:
        message = "<NO> Heco Zinc Plated TopFix GTU-YPJ Wood and Drywall Screw with screw type 'wood screw' and diameter 3 mm is not in the catalogue."

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
