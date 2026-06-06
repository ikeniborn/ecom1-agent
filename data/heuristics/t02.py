def run(vm, params):
    brand = params["brand"]
    series = params["series"]
    model = params["model"]
    kind_name = params["kind_name"]
    color_family = params["color_family"]
    length_m = params["length_m"]
    length_text = params["length_text"]

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    # /bin/sql rejects :name bindings (exit_code 1 'missing named argument').
    # Inline param values as single-quoted SQL string literals instead.
    sql = (
        "SELECT v.product_sku, v.product_name, v.brand, v.series, v.model, v.record_path "
        "FROM product_variants v "
        "JOIN product_kinds k ON k.product_kind_id = v.product_kind_id "
        "WHERE v.brand = " + q(brand) + " AND v.series = " + q(series) + " "
        "AND v.model = " + q(model) + " "
        "AND k.product_kind_name = " + q(kind_name) + " "
        "AND EXISTS (SELECT 1 FROM product_variant_properties pc "
        "WHERE pc.product_sku = v.product_sku AND pc.property_key = 'color_family' "
        "AND LOWER(pc.property_value_text) = LOWER(" + q(color_family) + ")) "
        "AND EXISTS (SELECT 1 FROM product_variant_properties pl "
        "WHERE pl.product_sku = v.product_sku AND pl.property_key LIKE '%length%' "
        "AND (pl.property_value_number = " + str(length_m) + " "
        "OR LOWER(pl.property_value_text) = LOWER(" + q(length_text) + ")));"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    matches = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        delim = "|" if "|" in line else ","
        fields = [f.strip() for f in line.split(delim)]
        low = [f.lower() for f in fields]
        if "record_path" in low or "product_sku" in low:
            continue
        sku = fields[0] if fields else ""
        path = ""
        for f in fields:
            if f.startswith("/"):
                path = f
                break
        if not path and fields:
            path = fields[-1]
        if sku or path:
            matches.append({"product_sku": sku, "record_path": path})

    if matches:
        desc = brand + " " + series + " " + model + " " + kind_name + " in " + color_family + ", " + length_text
        message = "<YES> The " + desc + " (" + matches[0]["product_sku"] + ") is in the catalogue."
        refs = [m["record_path"] for m in matches if m["record_path"]]
    else:
        message = ("<NO> No " + brand + " " + series + " " + model + " " + kind_name +
                   " with color family " + color_family + " and length " + length_text +
                   " is in the catalogue.")
        refs = []

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
