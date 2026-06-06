def run(vm, params):
    def q(s):
        return str(s).replace("'", "''")

    store = params["store"]
    city = params["city"]

    # discovery: resolve Lend district PowerTool store
    disc_sql = "SELECT store_id, store_name, city, record_path FROM stores WHERE store_name LIKE '%s' OR city = '%s';" % (q(store), q(city))
    vm.exec(path="/bin/sql", args=[disc_sql])

    store_subq = "SELECT store_id FROM stores WHERE store_name LIKE '%s' OR city = '%s'" % (q(store), q(city))

    def prop(alias, key, val):
        v = q(val)
        k = q(key)
        return ("%s.property_key='%s' AND (LOWER(TRIM(%s.property_value_text))=LOWER(TRIM('%s')) "
                "OR CAST(%s.property_value_number AS TEXT)='%s' "
                "OR CAST(CAST(%s.property_value_number AS INTEGER) AS TEXT)='%s')") % (alias, k, alias, v, alias, v, alias, v)

    variants = [
        {"brand": params["b1"], "fam": params["fam1"], "props": [(params["k1a"], params["v1a"]), (params["k1b"], params["v1b"])]},
        {"brand": params["b2"], "fam": params["fam2"], "props": [(params["k2a"], params["v2a"]), (params["k2b"], params["v2b"])]},
        {"brand": params["b3"], "fam": params["fam3"], "props": [(params["k3a"], params["v3a"]), (params["k3b"], params["v3b"])]},
        {"brand": params["b4"], "fam": params["fam4"], "props": [(params["k4a"], params["v4a"]), (params["k4b"], params["v4b"])]},
        {"brand": params["b5"], "fam": params["fam5"], "props": [(params["k5a"], params["v5a"]), (params["k5b"], params["v5b"])]},
        {"brand": params["b6"], "fam": params["fam6"], "props": [(params["k6a"], params["v6a"]), (params["k6b"], params["v6b"]), (params["k6c"], params["v6c"])]},
    ]

    aliases = ["pa", "pb", "pc"]
    selects = []
    for i, var in enumerate(variants, 1):
        joins = []
        for ai, kv in enumerate(var["props"]):
            a = aliases[ai]
            joins.append("JOIN product_variant_properties %s ON %s.product_sku=v.product_sku AND %s" % (a, a, prop(a, kv[0], kv[1])))
        sel = ("SELECT '%d' AS vid, v.record_path AS path FROM product_variants v "
               "JOIN product_families f ON f.product_family_id=v.product_family_id "
               "JOIN store_inventory si ON si.product_sku=v.product_sku AND si.store_id IN (%s) "
               "%s "
               "WHERE f.brand='%s' AND f.product_family_name LIKE '%s' AND si.available_today_quantity>=1") % (
               i, store_subq, " ".join(joins), q(var["brand"]), q(var["fam"]))
        selects.append(sel)

    ops_sql = " UNION ALL ".join(selects) + ";"
    result = vm.exec(path="/bin/sql", args=[ops_sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    lines = [l for l in stdout.splitlines() if l.strip()]
    vids = set()
    paths = []
    for idx, line in enumerate(lines):
        if idx == 0 and ("vid" in line.lower() and "path" in line.lower()):
            continue
        parts = line.split(",", 1)
        if len(parts) < 2:
            continue
        vid = parts[0].strip()
        p = parts[1].strip()
        if not p:
            continue
        vids.add(vid)
        if p not in paths:
            paths.append(p)

    qty = len(vids)
    msg = "qty=%d" % qty
    vm.answer(message=msg, outcome="OUTCOME_OK", refs=paths)
