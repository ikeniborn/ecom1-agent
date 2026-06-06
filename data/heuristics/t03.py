def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = params["brand"]
    family_name = params["family_name"]
    anchor_type_key = params["anchor_type_key"]
    anchor_type_value = params["anchor_type_value"]

    sql = (
        "WITH match AS ("
        "SELECT pv.product_sku, pv.record_path, pv.product_name "
        "FROM product_variants pv "
        "JOIN product_families pf ON pv.product_family_id = pf.product_family_id "
        "JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "WHERE pv.brand = " + q(brand) + " "
        "AND pf.product_family_name = " + q(family_name) + " "
        "AND pvp.property_key = " + q(anchor_type_key) + " "
        "AND lower(pvp.property_value_text) = lower(" + q(anchor_type_value) + ")"
        ") SELECT product_sku, record_path, product_name FROM match;"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    match = []
    if len(lines) >= 2:
        header = lines[0]
        delim = "," if "," in header else ("|" if "|" in header else "\t")
        cols = [c.strip() for c in header.split(delim)]
        for ln in lines[1:]:
            vals = [c.strip() for c in ln.split(delim)]
            if len(vals) < len(cols):
                continue
            row = {}
            for i, c in enumerate(cols):
                row[c] = vals[i]
            match.append(row)

    if match:
        rec_path = match[0].get("record_path", "")
        product_name = match[0].get("product_name", "")
        message = (
            "<YES> The " + product_name + " (concrete anchor) from the "
            "Wurth Universal WU XLL-87U Anchor and Wall Plug line is in the "
            "catalogue at " + rec_path + "."
        )
        refs = ["/proc/catalog"]
        if rec_path:
            refs.append(rec_path)
    else:
        message = (
            "<NO> No Wurth Universal WU XLL-87U Anchor and Wall Plug with "
            "anchor type concrete anchor exists in the catalogue."
        )
        refs = ["/proc/catalog"]

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
