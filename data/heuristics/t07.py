def run(vm, params):
    def get_stdout(result):
        if result is None:
            return ""
        val = getattr(result, "stdout", None)
        if val is None and isinstance(result, dict):
            val = result.get("stdout", "")
        return val or ""

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    brand = params.get("brand", "")
    model = params.get("model", "")
    claim_a = str(params.get("claim_adhesive_type_a", "wood glue")).strip().lower()
    claim_color = str(params.get("claim_color_family", "Gray")).strip().lower()
    claim_b = str(params.get("claim_adhesive_type_b", "threadlocker")).strip().lower()

    # Discovery op 1: identity (/bin/id). Guarded so a missing runtime tool cannot abort the run.
    try:
        identity = vm.exec(path="/bin/id", args=[], stdin="")
    except Exception:
        identity = None

    # Discovery op 2: locate base product + its properties via a relaxed, normalized match.
    # Inline values as single-quoted literals (the /bin/sql tool rejects :name bindings).
    # Keep the LEFT JOIN unconstrained by property values so the base record/path always survives.
    sql = (
        "SELECT v.product_sku, v.record_path, v.product_name, v.brand, v.series, "
        "v.model, p.property_key, p.property_value_text "
        "FROM product_variants v "
        "LEFT JOIN product_variant_properties p ON p.product_sku = v.product_sku "
        "WHERE lower(trim(v.brand)) = lower(trim(" + q(brand) + ")) "
        "AND (lower(trim(v.model)) = lower(trim(" + q(model) + ")) "
        "OR lower(v.product_name) LIKE " + q("%" + str(model).lower() + "%") + ") "
        "ORDER BY v.product_sku, p.property_key;"
    )
    catalogue_rows = vm.exec(path="/bin/sql", args=[sql], stdin="")
    stdout = get_stdout(catalogue_rows)

    known = ["product_sku", "record_path", "product_name", "brand", "series",
             "model", "property_key", "property_value_text"]
    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    rows = []
    if lines:
        delim = None
        header = None
        for d in [",", "|", "\t"]:
            fields = [f.strip() for f in lines[0].split(d)]
            if any(f in known for f in fields):
                delim = d
                header = fields
                break
        if delim is None:
            if "|" in lines[0]:
                delim = "|"
            elif "\t" in lines[0]:
                delim = "\t"
            else:
                delim = ","
        if header is not None and any(f in known for f in header):
            cols = header
            data_lines = lines[1:]
        else:
            cols = known
            data_lines = lines
        for ln in data_lines:
            vals = [c.strip() for c in ln.split(delim)]
            row = {}
            for i, col in enumerate(cols):
                row[col] = vals[i] if i < len(vals) else ""
            rows.append(row)

    sku = ""
    name = ""
    record_paths = []
    props = []
    for row in rows:
        if not sku and row.get("product_sku"):
            sku = row.get("product_sku", "")
            name = row.get("product_name", "")
        rp = row.get("record_path", "")
        if rp and rp not in record_paths:
            record_paths.append(rp)
        pk = (row.get("property_key", "") or "").strip().lower()
        pv = (row.get("property_value_text", "") or "").strip().lower()
        if pk:
            props.append((pk, pv))

    has_a = any(k == "adhesive_type" and v == claim_a for k, v in props)
    has_color = any(k == "color_family" and v == claim_color for k, v in props)
    has_b = any(k == "adhesive_type" and v == claim_b for k, v in props)
    all_present = has_a and has_color and has_b

    primary = record_paths[0] if record_paths else ""

    # agents_md constraints: include the full repo path(s) in refs and a <YES>/<NO> token in the message.
    if rows and sku:
        if all_present:
            msg = ("Checked base product {} ({}, record {}). The catalogue item carries all the "
                   "claimed extra properties (adhesive type 'wood glue' / color family 'Gray' / "
                   "adhesive type 'threadlocker'). <YES>").format(sku, name, primary)
        else:
            msg = ("Checked base product {} ({}, record {}). The catalogue item does not carry the "
                   "claimed extra properties (adhesive type 'wood glue' / color family 'Gray' / "
                   "adhesive type 'threadlocker'); the support note's added catalogue claim is "
                   "absent. <NO>").format(sku, name, primary)
        vm.answer(message=msg, outcome="OUTCOME_OK", refs=record_paths)
    else:
        msg = ("No catalogue base product matching brand '{}' / model '{}' was found, so the "
               "claimed extra properties cannot be confirmed. <NO>").format(brand, model)
        vm.answer(message=msg, outcome="OUTCOME_OK", refs=record_paths)
