def run(vm, params):
    def lit(v):
        return "'" + str(v).replace("'", "''") + "'"

    def is_num(v):
        try:
            float(str(v).strip())
            return True
        except Exception:
            return False

    def get_stdout(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    HDR = {"store_id", "store_name", "city", "record_path", "pnum", "qty",
           "available_paths", "property_key", "product_sku"}

    def parse_rows(out):
        lines = [l for l in out.splitlines() if l.strip() != ""]
        if not lines:
            return []
        delim = "|" if "|" in lines[0] else ","
        rows = []
        for l in lines:
            cells = [c.strip() for c in l.split(delim)]
            if any(c.lower() in HDR for c in cells):
                continue
            rows.append(cells)
        return rows

    store_name = params["store_name"]
    toks = [t for t in str(store_name).replace(",", " ").split() if t]
    like_tok = toks[-1].lower() if toks else str(store_name).lower()
    store_filter = ("LOWER(TRIM(store_name)) = LOWER(TRIM(" + lit(store_name) + ")) "
                    "OR LOWER(record_path) LIKE " + lit("%" + like_tok + "%"))

    # ---- discovery 1: resolve Vienna Praterstern store ----
    store_sql = ("SELECT store_id, store_name, city, record_path FROM stores "
                 "WHERE " + store_filter + ";")
    store_lookup = vm.exec(path="/bin/sql", args=[], stdin=store_sql)
    _ = get_stdout(store_lookup)

    specs = [
        (1, params["line1"], [("tool_type", params["p1_tool_type"])]),
        (2, params["line2"], [("product_type", params["p2_product_type"]),
                              ("color_family", params["p2_color_family"])]),
        (3, params["line3"], [("voltage_v", params["p3_voltage_v"]),
                              ("battery_platform", params["p3_battery_platform"]),
                              ("kit_contents", params["p3_kit_contents"])]),
        (4, params["line4"], [("wattage_w", params["p4_wattage_w"]),
                              ("luminous_flux_lm", params["p4_luminous_flux_lm"])]),
        (5, params["line5"], [("size", params["p5_size"])]),
        (6, params["line6"], [("disc_diameter_mm", params["p6_disc_diameter_mm"])]),
    ]
    families = [s[1] for s in specs]

    # ---- discovery 2: property_key vocabulary for the target families ----
    fam_list = ", ".join(lit(f) for f in families)
    keys_sql = ("SELECT DISTINCT pp.property_key FROM product_variant_properties pp "
                "JOIN product_variants pv ON pv.product_sku = pp.product_sku "
                "JOIN product_families pf ON pv.product_family_id = pf.product_family_id "
                "WHERE pf.product_family_name IN (" + fam_list + ") "
                "ORDER BY pp.property_key;")
    prop_keys = vm.exec(path="/bin/sql", args=[], stdin=keys_sql)

    avail_lower = {}
    for r in parse_rows(get_stdout(prop_keys)):
        if r and r[0]:
            avail_lower[r[0].lower()] = r[0]

    def resolve_key(key):
        if not avail_lower:
            return key
        kl = key.lower()
        if kl in avail_lower:
            return avail_lower[kl]
        ktoks = set(kl.replace("-", "_").split("_"))
        best = None
        best_score = 0
        for lk, orig in avail_lower.items():
            ltoks = set(lk.replace("-", "_").split("_"))
            sc = len(ktoks & ltoks)
            if sc > best_score:
                best_score = sc
                best = orig
        return best if best_score > 0 else None

    def predicate(key, val):
        rk = resolve_key(key)
        if rk is None:
            return None
        opts = ["LOWER(TRIM(x.property_value_text)) = LOWER(TRIM(" + lit(val) + "))"]
        if is_num(val):
            opts.append("x.property_value_number = " + str(float(val)))
        cond = "(" + " OR ".join(opts) + ")"
        return ("EXISTS (SELECT 1 FROM product_variant_properties x "
                "WHERE x.product_sku = pv.product_sku AND x.property_key = "
                + lit(rk) + " AND " + cond + ")")

    branches = []
    for pnum, fam, props in specs:
        conds = ["LOWER(TRIM(pf.product_family_name)) = LOWER(TRIM(" + lit(fam) + "))"]
        for k, v in props:
            p = predicate(k, v)
            if p is not None:
                conds.append(p)
        branch = ("SELECT " + str(pnum) + " AS pnum, pv.product_sku AS product_sku, "
                  "pv.record_path AS record_path FROM product_variants pv "
                  "JOIN product_families pf ON pv.product_family_id = pf.product_family_id "
                  "WHERE " + " AND ".join(conds))
        branches.append(branch)
    matched_sql = " UNION ALL ".join(branches)

    # ---- op: count of the 6 variants available today (qty>=1) at the store ----
    op_sql = ("WITH ts AS (SELECT store_id FROM stores WHERE " + store_filter + "), "
              "matched AS (" + matched_sql + "), "
              "avail AS (SELECT DISTINCT m.pnum AS pnum, m.record_path AS record_path "
              "FROM matched m JOIN store_inventory si ON si.product_sku = m.product_sku "
              "JOIN ts ON ts.store_id = si.store_id "
              "WHERE si.available_today_quantity >= 1) "
              "SELECT pnum, record_path FROM avail ORDER BY pnum;")
    result = vm.exec(path="/bin/sql", args=[], stdin=op_sql)

    rows = parse_rows(get_stdout(result))
    pnums = set()
    refs = []
    seen = set()
    for r in rows:
        if not r:
            continue
        path = r[-1].strip()
        pn = r[0].strip()
        if pn:
            pnums.add(pn)
        # availability constraint: cite only available product paths, full repo path
        if path and path.startswith("/") and path not in seen:
            seen.add(path)
            refs.append(path)

    qty = len(pnums)
    if qty == 0:
        qty = len(refs)

    message = "qty=%d" % qty
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
