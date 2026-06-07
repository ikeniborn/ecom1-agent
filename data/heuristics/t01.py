import re


def run(vm, params):
    brand = params.get("brand", "") or ""
    model = params.get("model", "") or ""
    kind = params.get("kind", "") or ""
    storage_type = params.get("storage_type", "") or ""
    family_name = params.get("family_name", "") or (
        (brand + " " + model + " " + kind).strip()
    )

    def sq(s):
        return "'" + str(s).replace("'", "''") + "'"

    def norm(s):
        return re.sub(r"[^a-z0-9]", "", str(s).lower())

    model_tok = norm(model).upper()

    # /bin/sql does not bind :name params -> inline values as quoted literals.
    # Broaden the model token match (separator-normalized) across every
    # identifier column; LEFT JOIN properties and post-filter kind/storage
    # in Python so a narrow INNER JOIN cannot drop in-scope rows.
    sql = (
        "SELECT pv.product_sku, pv.product_name, pv.model, pv.brand, "
        "pv.record_path, pk.product_kind_name, pvp.property_key, "
        "pvp.property_value_text "
        "FROM product_variants pv "
        "LEFT JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "LEFT JOIN product_variant_properties pvp "
        "ON pv.product_sku = pvp.product_sku "
        "WHERE upper(pv.brand) = upper(" + sq(brand) + ") "
        "AND ("
        "upper(replace(replace(pv.model,' ',''),'-','')) LIKE '%" + model_tok + "%' "
        "OR upper(replace(replace(pv.product_name,' ',''),'-','')) LIKE '%" + model_tok + "%' "
        "OR upper(replace(replace(pv.product_sku,' ',''),'-','')) LIKE '%" + model_tok + "%'"
        ") LIMIT 500;"
    )

    result = vm.exec(path="/bin/sql", args=[], stdin=sql)
    stdout = getattr(result, "stdout", "")
    if not stdout and isinstance(result, dict):
        stdout = result.get("stdout", "")
    stdout = stdout or ""

    header = []
    rows = []
    text = stdout.strip()
    if text:
        lines = [ln for ln in text.splitlines() if ln.strip() != ""]
        if lines:
            header_line = lines[0]
            delim = "|" if header_line.count("|") > header_line.count(",") else ","

            def split_row(ln):
                return [c.strip().strip('"') for c in ln.split(delim)]

            header = split_row(header_line)
            for ln in lines[1:]:
                stripped = ln.replace(delim, "").strip()
                if stripped and set(stripped) <= set("-+ "):
                    continue
                cells = split_row(ln)
                row = {}
                for i, h in enumerate(header):
                    row[h] = cells[i] if i < len(cells) else ""
                rows.append(row)

    variants = {}
    for row in rows:
        sku = row.get("product_sku", "")
        if sku not in variants:
            variants[sku] = {
                "product_sku": sku,
                "product_name": row.get("product_name", ""),
                "record_path": row.get("record_path", ""),
                "product_kind_name": row.get("product_kind_name", ""),
                "props": {},
            }
        pkey = row.get("property_key", "")
        if pkey:
            variants[sku]["props"][norm(pkey)] = row.get("property_value_text", "")

    kind_norm = norm(kind)
    storage_val_norm = norm(storage_type)
    storage_key = norm("storage_type")

    match = None
    for v in variants.values():
        if kind_norm and kind_norm not in norm(v["product_kind_name"]):
            continue
        sval = v["props"].get(storage_key, "")
        if storage_val_norm and storage_val_norm in norm(sval):
            match = v
            break

    if match:
        message = (
            "<YES> The " + family_name + " with storage type " + storage_type +
            " is in the catalogue: " + match["product_name"] +
            " (" + match["record_path"] + ")."
        )
        refs = [match["record_path"]] if match["record_path"] else []
    else:
        message = (
            "<NO> No " + family_name + " with storage type " + storage_type +
            " is in the catalogue."
        )
        refs = []

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
