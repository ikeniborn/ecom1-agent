import csv
import io


def run(vm, params):
    def get_stdout(result):
        return getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    def esc(v):
        return str(v).replace("'", "''")

    brand = params.get("brand", "Raaco")
    model = params.get("model", "3CS-7A9")
    st1 = params.get("storage_type_1", "shelving unit")
    st2 = params.get("storage_type_2", "stacking box")

    # Discovery 1 (Exec): identity. Only /bin/sql is guaranteed at runtime; guard failure.
    try:
        identity = vm.exec(path="/bin/id", args=[], stdin="")
    except Exception:
        identity = None

    # Discovery 2 (Exec /bin/sql): locate base product + all its storage_type values.
    # /bin/sql does NOT accept :name bindings -> inline values as quoted literals.
    # Broaden with LIKE on model/product_name so the base product resolves in one query.
    # Use a non-comma GROUP_CONCAT separator so CSV parsing never splits storage_types.
    b = esc(brand)
    m = esc(model)
    sql = (
        "SELECT pv.product_sku, pv.record_path, pv.product_name, pv.brand, pv.series, pv.model, "
        "GROUP_CONCAT(CASE WHEN pvp.property_key = 'storage_type' THEN pvp.property_value_text END, ' / ') AS storage_types "
        "FROM product_variants pv "
        "LEFT JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "WHERE (pv.brand LIKE '%" + b + "%' OR pv.product_name LIKE '%" + b + "%') "
        "AND (pv.model LIKE '%" + m + "%' OR pv.product_name LIKE '%" + m + "%') "
        "GROUP BY pv.product_sku, pv.record_path, pv.product_name, pv.brand, pv.series, pv.model;"
    )
    base_product_result = vm.exec(path="/bin/sql", args=[sql], stdin="")
    out = get_stdout(base_product_result)

    # Parse CSV: leading header row, comma-delimited, columns mapped by header name.
    rows = []
    reader = csv.reader(io.StringIO(out))
    all_rows = [r for r in reader if r and any((c or "").strip() for c in r)]
    if all_rows:
        header = [h.strip() for h in all_rows[0]]
        idx = {name: i for i, name in enumerate(header)}

        def col(r, name):
            i = idx.get(name, -1)
            return r[i].strip() if 0 <= i < len(r) else ""

        for r in all_rows[1:]:
            rows.append({
                "product_sku": col(r, "product_sku"),
                "record_path": col(r, "record_path"),
                "product_name": col(r, "product_name"),
                "brand": col(r, "brand"),
                "series": col(r, "series"),
                "model": col(r, "model"),
                "storage_types": col(r, "storage_types"),
            })

    # refs: every matched row's record_path (never drop, never invent).
    refs = []
    for row in rows:
        rp = row.get("record_path", "")
        if rp and rp not in refs:
            refs.append(rp)

    if rows:
        primary = rows[0]
        sku = primary["product_sku"] or "(unknown)"
        record_path = primary["record_path"]
        storage_types = primary["storage_types"] or "none"
        message = (
            "Checked catalogue: Raaco Professional CarryLite 3CS-7A9 Shelving and Cabinet exists as SKU "
            + sku + " (" + record_path + "), but storage type recorded is " + storage_types
            + " only \u2014 no variant carries both '" + st1 + "' and '" + st2 + "'. "
            + "Extra catalogue claim absent. <NO> Checked SKU: " + sku + "."
        )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
    else:
        message = (
            "Checked catalogue: no base product matching Raaco Professional CarryLite 3CS-7A9 "
            "Shelving and Cabinet was located, so the dual storage-type claim ('"
            + st1 + "' and '" + st2 + "') is not present. <NO>"
        )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
