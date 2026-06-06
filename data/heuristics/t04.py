def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = q(params["brand"])
    model = q(params["model"])
    mask_type = q(params["mask_type"])
    protection_class = q(params["protection_class"])
    size = q(params["size"])

    # /bin/sql rejects :name bind args -> inline values as single-quoted SQL literals.
    # Compare properties with LOWER(TRIM()) so case/whitespace drift does not hide a present variant.
    sql = (
        "SELECT pv.product_sku, pv.record_path, pv.product_name, pv.brand, pv.series, pv.model "
        "FROM product_variants pv "
        "WHERE LOWER(TRIM(pv.brand)) = LOWER(TRIM(" + brand + ")) "
        "AND LOWER(TRIM(pv.model)) = LOWER(TRIM(" + model + ")) "
        "AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku "
        "AND p.property_key = 'mask_type' AND LOWER(TRIM(p.property_value_text)) = LOWER(TRIM(" + mask_type + "))) "
        "AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku "
        "AND p.property_key = 'protection_class' AND LOWER(TRIM(p.property_value_text)) = LOWER(TRIM(" + protection_class + "))) "
        "AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku "
        "AND p.property_key = 'size' AND LOWER(TRIM(p.property_value_text)) = LOWER(TRIM(" + size + ")));"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    rows = []
    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    if lines:
        header = lines[0]
        delim = "|" if "|" in header else ","
        cols = [c.strip() for c in header.split(delim)]
        lower_cols = [c.lower() for c in cols]
        if "record_path" in lower_cols or "product_sku" in lower_cols:
            path_idx = lower_cols.index("record_path") if "record_path" in lower_cols else None
            sku_idx = lower_cols.index("product_sku") if "product_sku" in lower_cols else None
            for ln in lines[1:]:
                parts = [c.strip() for c in ln.split(delim)]
                row = {}
                if path_idx is not None and path_idx < len(parts):
                    row["record_path"] = parts[path_idx]
                if sku_idx is not None and sku_idx < len(parts):
                    row["product_sku"] = parts[sku_idx]
                rows.append(row)

    refs = [r["record_path"] for r in rows if r.get("record_path")]

    if rows:
        match = rows[0]
        message = (
            "<YES> The respiratory protection variant Moldex Pro Classic 9B0-CGL "
            "(mask type disposable respirator, protection class basic, size one size) is in the catalogue: "
            + str(match.get("product_sku", "")) + " at " + str(match.get("record_path", "")) + "."
        )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
    else:
        message = "<NO> No such variant exists in the catalogue."
        vm.answer(message=message, outcome="OUTCOME_OK", refs=[])
