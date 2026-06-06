def run(vm, params):
    def _stdout(result):
        if isinstance(result, dict):
            return result.get("stdout", "") or ""
        return getattr(result, "stdout", "") or ""

    def _q(v):
        return "'" + str(v).replace("'", "''") + "'"

    def _parse(out):
        lines = [ln for ln in out.splitlines() if ln.strip() != ""]
        if not lines:
            return []
        header = [h.strip() for h in lines[0].split(",")]
        rows = []
        for ln in lines[1:]:
            cells = [c.strip() for c in ln.split(",")]
            if len(cells) < len(header):
                continue
            rows.append(dict(zip(header, cells)))
        return rows

    brand = params["brand"]
    line = params["line"]
    mask_type = params["mask_type"]
    protection_class = params["protection_class"]
    size = params["size"]
    city = params["city"]

    target_where = (
        "v.brand = " + _q(brand) +
        " AND f.product_family_name = " + _q(line) +
        " AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku=v.product_sku AND p.property_key='mask_type' AND p.property_value_text=" + _q(mask_type) + ")" +
        " AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku=v.product_sku AND p.property_key='protection_class' AND p.property_value_text=" + _q(protection_class) + ")" +
        " AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku=v.product_sku AND p.property_key='size' AND p.property_value_text=" + _q(size) + ")"
    )

    # discovery: resolve product
    product_sql = (
        "SELECT v.product_sku, v.record_path AS product_path "
        "FROM product_variants v JOIN product_families f ON v.product_family_id = f.product_family_id "
        "WHERE " + target_where + ";"
    )
    product_res = vm.exec(path="/bin/sql", args=[product_sql])
    product_rows = _parse(_stdout(product_res))
    product = product_rows[0] if product_rows else {}
    product_path = product.get("product_path", "")

    # ops: per-store rows via LEFT JOIN (include zero-availability stores)
    rows_sql = (
        "WITH target AS (SELECT v.product_sku, v.record_path FROM product_variants v "
        "JOIN product_families f ON v.product_family_id = f.product_family_id WHERE " + target_where + ") "
        "SELECT s.store_id, s.record_path AS store_path, t.product_sku, t.record_path AS product_path, "
        "COALESCE(i.available_today_quantity,0) AS available_today "
        "FROM stores s CROSS JOIN target t "
        "LEFT JOIN store_inventory i ON i.store_id=s.store_id AND i.product_sku=t.product_sku "
        "WHERE s.city = " + _q(city) + " ORDER BY s.store_id;"
    )
    rows_res = vm.exec(path="/bin/sql", args=[rows_sql])
    rows = _parse(_stdout(rows_res))

    # ops: total available
    total_sql = (
        "WITH target AS (SELECT v.product_sku FROM product_variants v "
        "JOIN product_families f ON v.product_family_id = f.product_family_id WHERE " + target_where + ") "
        "SELECT COALESCE(SUM(COALESCE(i.available_today_quantity,0)),0) AS total_available "
        "FROM stores s CROSS JOIN target t "
        "LEFT JOIN store_inventory i ON i.store_id=s.store_id AND i.product_sku=t.product_sku "
        "WHERE s.city = " + _q(city) + ";"
    )
    total_res = vm.exec(path="/bin/sql", args=[total_sql])
    total_rows = _parse(_stdout(total_res))
    total_available = total_rows[0].get("total_available", "0") if total_rows else "0"
    try:
        total_int = int(float(total_available))
    except (ValueError, TypeError):
        total_int = 0

    refs = []
    if product_path:
        refs.append(product_path)
    for r in rows:
        sp = r.get("store_path", "")
        if sp and sp not in refs:
            refs.append(sp)

    message = "qty {}".format(total_int)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
