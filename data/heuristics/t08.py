def run(vm, params):
    brand = params["brand"]
    model = params["model"]
    name_pattern = params["name_pattern"]
    claim_key = params["claim_property_key"]
    claim_val = params["claim_property_value"]

    def lit(v):
        return "'" + str(v).replace("'", "''") + "'"

    sql = (
        "SELECT pv.product_sku, pv.record_path, pv.product_name, pv.brand, pv.series, pv.model, "
        "pp.property_key, pp.property_value_text "
        "FROM product_variants pv "
        "LEFT JOIN product_variant_properties pp ON pp.product_sku = pv.product_sku "
        "WHERE pv.brand = " + lit(brand) + " AND pv.model = " + lit(model) + " "
        "AND pv.product_name LIKE " + lit(name_pattern) + " "
        "ORDER BY pv.product_sku, pp.property_key;"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "")
    if not stdout and isinstance(result, dict):
        stdout = result.get("stdout", "")
    stdout = stdout or ""

    def detect_delim(header):
        known = ("product_sku", "record_path")
        for d in ("|", ","):
            if d in header:
                cols = [c.strip() for c in header.split(d)]
                if any(k in cols for k in known):
                    return d
        if "|" in header:
            return "|"
        return ","

    def parse_rows(text):
        lines = [ln for ln in text.splitlines() if ln.strip() != ""]
        if not lines:
            return []
        delim = detect_delim(lines[0])
        cols = [c.strip() for c in lines[0].split(delim)]
        out = []
        for ln in lines[1:]:
            vals = [v.strip() for v in ln.split(delim)]
            out.append(dict(zip(cols, vals)))
        return out

    rows = parse_rows(stdout)

    if not rows:
        vm.answer(
            message=(
                "No catalogue variant found for brand " + str(brand) + " model " + str(model) +
                " matching pattern " + str(name_pattern) + ". Cannot verify the '" +
                str(claim_key) + " = " + str(claim_val) + "' claim."
            ),
            outcome="OUTCOME_NONE_UNSUPPORTED",
            refs=[],
        )
        return

    first = rows[0]
    sku = first.get("product_sku", "")
    record_path = first.get("record_path", "")
    product_name = first.get("product_name", "")

    props = []
    for r in rows:
        k = r.get("property_key", "")
        v = r.get("property_value_text", "")
        if k:
            props.append((k, v))

    base_attrs = "; ".join(k + " = " + v for k, v in props) if props else "no catalogue properties listed"

    claim_present = any(k == claim_key and v == claim_val for k, v in props)

    if claim_present:
        token = "<YES>"
        message = (
            token + " Base catalogue item: " + product_name + " (SKU " + sku +
            ", record " + record_path + "). Catalogue properties: " + base_attrs +
            ". The extra property '" + str(claim_key) + " = " + str(claim_val) +
            "' IS present on this variant's properties \u2014 checked SKU " + sku + "."
        )
    else:
        token = "<NO>"
        message = (
            token + " Base catalogue item exists: " + product_name + " (SKU " + sku +
            ", record " + record_path + "). Catalogue properties: " + base_attrs +
            ". The extra support-note claim '" + str(claim_key) + " = " + str(claim_val) +
            "' is NOT present on this variant's properties \u2014 checked SKU " + sku + "."
        )

    refs = [record_path] if record_path else []
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
