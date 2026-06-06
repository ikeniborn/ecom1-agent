def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    def stdout_of(r):
        if r is None:
            return ""
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def safe_exec(path, args=None, stdin=""):
        try:
            return vm.exec(path=path, args=args or [], stdin=stdin)
        except Exception:
            return None

    def parse(text):
        lines = [l for l in text.splitlines() if l.strip() != ""]
        if not lines:
            return []
        first = lines[0]
        delim = "|" if "|" in first else ("," if "," in first else None)
        if delim is None:
            return []
        header = [h.strip() for h in first.split(delim)]
        rows = []
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(delim)]
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
        rows = []
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(delim)]
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts)))
        return rows

    def is_open_val(v):
        return str(v).strip().lower() not in ("0", "false", "f", "no", "", "none")

    city = params["city"]
    fam = [params["fam1"], params["fam2"], params["fam3"], params["fam4"], params["fam5"], params["fam6"]]
    brand = [params["brand1"], params["brand2"], params["brand3"], params["brand4"], params["brand5"], params["brand6"]]
    min_qty = params["min_qty"]

    def prop_text(key, val):
        return ("EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku=pv.product_sku "
                "AND p.property_key=" + q(key) + " AND LOWER(TRIM(p.property_value_text))=LOWER(TRIM(" + q(val) + ")))")

    def prop_num(key, val):
        return ("EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku=pv.product_sku "
                "AND p.property_key=" + q(key) + " AND p.property_value_number=" + str(val) + ")")

    def branch(fam_name, brand_name, preds):
        cond = ("LOWER(TRIM(pf.product_family_name))=LOWER(TRIM(" + q(fam_name) + ")) "
                "AND LOWER(TRIM(pv.brand))=LOWER(TRIM(" + q(brand_name) + "))")
        for pr in preds:
            cond += " AND " + pr
        return ("SELECT pv.product_sku, pv.record_path FROM product_variants pv "
                "JOIN product_families pf ON pv.product_family_id=pf.product_family_id WHERE " + cond)

    identity = safe_exec("/bin/id")

    store_sql = ("SELECT store_id, record_path, store_name, is_open FROM stores "
                 "WHERE LOWER(TRIM(city))=LOWER(TRIM(" + q(city) + "));")
    store_res = safe_exec("/bin/sql", args=[store_sql])
    store_rows = parse(stdout_of(store_res))

    open_rows = [r for r in store_rows if is_open_val(r.get("is_open", ""))]
    central = [r for r in open_rows if "central" in str(r.get("store_name", "")).lower()]
    if central:
        chosen = central[0]
    elif len(open_rows) == 1:
        chosen = open_rows[0]
    elif open_rows:
        chosen = open_rows[0]
    else:
        chosen = None

    store_id = chosen.get("store_id") if chosen else None
    store_path = chosen.get("record_path") if chosen else None

    if store_id is not None and str(store_id).strip() != "":
        target_cte = "SELECT store_id, record_path AS store_path FROM stores WHERE store_id=" + q(store_id)
    else:
        target_cte = ("SELECT store_id, record_path AS store_path FROM stores "
                      "WHERE LOWER(TRIM(city))=LOWER(TRIM(" + q(city) + ")) "
                      "AND LOWER(TRIM(store_name)) LIKE '%central%' AND is_open=1")

    branches = [
        branch(fam[0], brand[0], [prop_text("fitting_type", params["p1_fitting"]), prop_num("diameter_mm", params["p1_diam"])]),
        branch(fam[1], brand[1], [prop_num("voltage_v", params["p2_volt"]), prop_text("battery_platform", params["p2_batt"]), prop_text("kit_contents", params["p2_kit"])]),
        branch(fam[2], brand[2], [prop_text("tool_type", params["p3_tool"])]),
        branch(fam[3], brand[3], [prop_text("screw_type", params["p4_screw"]), prop_num("diameter_mm", params["p4_diam"])]),
        branch(fam[4], brand[4], [prop_text("machine_type", params["p5_machine"]), prop_num("voltage_v", params["p5_volt"]), prop_num("power_w", params["p5_power"])]),
        branch(fam[5], brand[5], [prop_num("volume_ml", params["p6_vol"]), prop_text("viscosity", params["p6_visc"])]),
    ]
    matched_cte = " UNION ALL ".join(branches)

    matches_sql = ("WITH target_store AS (" + target_cte + "), matched AS (" + matched_cte + ") "
                   "SELECT m.product_sku, m.record_path, ts.store_path, "
                   "COALESCE(si.available_today_quantity,0) AS available_today_quantity, "
                   "CASE WHEN COALESCE(si.available_today_quantity,0) >= " + str(min_qty) + " THEN 1 ELSE 0 END AS qualifies "
                   "FROM matched m CROSS JOIN target_store ts "
                   "LEFT JOIN store_inventory si ON si.store_id=ts.store_id AND si.product_sku=m.product_sku "
                   "ORDER BY m.product_sku;")

    matches_res = safe_exec("/bin/sql", args=[matches_sql])
    match_rows = parse(stdout_of(matches_res))

    qualifying_paths = []
    seen = set()
    for r in match_rows:
        if str(r.get("qualifies", "")).strip() in ("1", "1.0", "true", "True"):
            rp = r.get("record_path", "")
            if rp and rp not in seen:
                seen.add(rp)
                qualifying_paths.append(rp)
        if not store_path:
            sp = r.get("store_path", "")
            if sp:
                store_path = sp

    qualifying_count = len(qualifying_paths)

    refs = []
    if store_path:
        refs.append(store_path)
    refs.extend(qualifying_paths)

    message = str(qualifying_count) + " products"
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
