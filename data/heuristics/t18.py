def run(vm, params):
    import re, csv, io

    def sql_literal(v):
        return "'" + str(v).replace("'", "''") + "'"

    def bind_sql(sql):
        # /bin/sql rejects :name bind args -> inline as quoted SQL literals.
        # Replace longest names first; \b prevents :product_kind/:product_type overlap.
        names = ["product_kind", "product_type", "brand", "line", "city"]
        for n in names:
            if n in params and params[n] is not None:
                sql = re.sub(r':' + n + r'\b', sql_literal(params[n]), sql)
        return sql

    def get_stdout(result):
        s = getattr(result, "stdout", None)
        if s is None and isinstance(result, dict):
            s = result.get("stdout", "")
        return s or ""

    def parse_rows(stdout):
        reader = csv.reader(io.StringIO(stdout))
        raw = [r for r in reader if any((c or "").strip() for c in r)]
        if not raw:
            return []
        header = [h.strip() for h in raw[0]]
        out = []
        for r in raw[1:]:
            out.append({header[i]: (r[i].strip() if i < len(r) else "") for i in range(len(header))})
        return out

    def root(p):
        p = (p or "").strip()
        if p and not p.startswith("/"):
            p = "/" + p
        return p

    # --- discovery: resolve the single matched product variant ---
    product_sql = bind_sql("SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_families pf ON pv.product_family_id = pf.product_family_id JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pv.brand = :brand AND pf.product_family_name = :line AND pk.product_kind_name = :product_kind AND EXISTS (SELECT 1 FROM product_variant_properties pvp WHERE pvp.product_sku = pv.product_sku AND pvp.property_value_text = :product_type);")
    product_res = vm.exec(path="/bin/sql", stdin=product_sql)
    product = parse_rows(get_stdout(product_res))

    # --- discovery: enumerate ALL Graz stores directly (scope, not gated on prod CTE) ---
    stores_sql = bind_sql("SELECT store_id, record_path FROM stores WHERE city = :city ORDER BY store_id;")
    stores_res = vm.exec(path="/bin/sql", stdin=stores_sql)
    stores = parse_rows(get_stdout(stores_res))

    # --- op: per-store availability + total over every Graz store (incl. 0) ---
    ops_sql = bind_sql("WITH prod AS (SELECT pv.product_sku, pv.record_path AS product_path FROM product_variants pv JOIN product_families pf ON pv.product_family_id = pf.product_family_id JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pv.brand = :brand AND pf.product_family_name = :line AND pk.product_kind_name = :product_kind AND EXISTS (SELECT 1 FROM product_variant_properties pvp WHERE pvp.product_sku = pv.product_sku AND pvp.property_value_text = :product_type)) SELECT s.store_id, s.record_path AS store_path, p.product_sku, p.product_path, COALESCE(si.available_today_quantity,0) AS available_today, (SELECT COALESCE(SUM(COALESCE(si2.available_today_quantity,0)),0) FROM stores s2 CROSS JOIN prod p2 LEFT JOIN store_inventory si2 ON si2.store_id = s2.store_id AND si2.product_sku = p2.product_sku WHERE s2.city = :city) AS total FROM stores s CROSS JOIN prod p LEFT JOIN store_inventory si ON si.store_id = s.store_id AND si.product_sku = p.product_sku WHERE s.city = :city ORDER BY s.store_id;")
    result_res = vm.exec(path="/bin/sql", stdin=ops_sql)
    result = parse_rows(get_stdout(result_res))

    # matched product record_path
    product_paths = [root(r.get("record_path", "")) for r in product if r.get("record_path", "").strip()]
    product_path = product_paths[0] if product_paths else ""

    # every Graz store record_path (include zero-availability branches)
    store_paths = [root(r.get("record_path", "")) for r in stores if r.get("record_path", "").strip()]

    # total available_today across Graz stores
    total_raw = result[0].get("total", "0") if result else "0"
    try:
        total = int(float(total_raw))
    except (ValueError, TypeError):
        total = total_raw

    refs = []
    for p in store_paths:
        if p and p not in refs:
            refs.append(p)
    if product_path and product_path not in refs:
        refs.append(product_path)

    message = "{} total".format(total)
    return vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
