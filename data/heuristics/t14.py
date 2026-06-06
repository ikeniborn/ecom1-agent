import csv, io, re


def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    def sub(sql):
        return re.sub(r':([A-Za-z_][A-Za-z0-9_]*)', lambda m: q(params[m.group(1)]), sql)

    def out(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def parse(text):
        text = (text or "").strip()
        if not text:
            return [], []
        rr = list(csv.reader(io.StringIO(text)))
        if not rr:
            return [], []
        return rr[0], rr[1:]

    # Discovery: resolve store by name (project all columns so we can locate a path-like field)
    disc_sql = sub("SELECT * FROM stores WHERE store_name = :store_name;")
    store = vm.exec(path="/bin/sql", args=[], stdin=disc_sql)
    s_hdr, s_rows = parse(out(store))

    store_path = ""
    if s_rows:
        for cell in s_rows[0]:
            if isinstance(cell, str) and cell.startswith("/"):
                store_path = cell
                break

    # Ops: count product lines with >= min_qty available today at resolved store
    count_sql = sub(
        "WITH s AS (SELECT store_id FROM stores WHERE store_name = :store_name), "
        "line(idx, fam, k, v) AS (VALUES (1,:fam1,:k1,:v1),(2,:fam2,:k2,:v2),(3,:fam3,:k3,:v3),(4,:fam4,:k4,:v4),(6,:fam6,:k6,:v6)), "
        "single_match AS (SELECT l.idx, COALESCE(SUM(i.available_today_quantity),0) AS qty "
        "FROM line l JOIN product_families f ON f.product_family_name = l.fam "
        "JOIN product_variants v ON v.product_family_id = f.product_family_id "
        "JOIN product_variant_properties pr ON pr.product_sku = v.product_sku AND pr.property_key = l.k AND pr.property_value_text = l.v "
        "JOIN store_inventory i ON i.product_sku = v.product_sku AND i.store_id IN (SELECT store_id FROM s) "
        "GROUP BY l.idx), "
        "philips_match AS (SELECT 5 AS idx, COALESCE(SUM(i.available_today_quantity),0) AS qty "
        "FROM product_families f JOIN product_variants v ON v.product_family_id = f.product_family_id "
        "JOIN product_variant_properties p1 ON p1.product_sku = v.product_sku AND p1.property_key = :k5a AND p1.property_value_number = CAST(:v5a AS REAL) "
        "JOIN product_variant_properties p2 ON p2.product_sku = v.product_sku AND p2.property_key = :k5b AND p2.property_value_number = CAST(:v5b AS REAL) "
        "JOIN store_inventory i ON i.product_sku = v.product_sku AND i.store_id IN (SELECT store_id FROM s) "
        "WHERE f.product_family_name = :fam5), "
        "all_match AS (SELECT idx, qty FROM single_match UNION ALL SELECT idx, qty FROM philips_match) "
        "SELECT COUNT(*) AS available_count FROM all_match WHERE qty >= CAST(:min_qty AS INTEGER);"
    )
    result = vm.exec(path="/bin/sql", args=[], stdin=count_sql)
    r_hdr, r_rows = parse(out(result))

    count = 0
    if r_rows and r_rows[0]:
        try:
            count = int(str(r_rows[0][0]).strip())
        except (ValueError, TypeError):
            count = r_rows[0][0]

    if not s_rows:
        vm.answer(message="No store matched the requested name.", outcome="OUTCOME_NONE_CLARIFICATION", refs=[])
        return

    refs = [store_path] if store_path else []
    vm.answer(message="Count: %s" % count, outcome="OUTCOME_OK", refs=refs)
