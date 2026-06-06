def run(vm, params):
    def get_stdout(result):
        s = getattr(result, "stdout", None)
        if s is None and isinstance(result, dict):
            s = result.get("stdout", "")
        return s or ""

    def q(v):
        return str(v).replace("'", "''")

    store_city = params.get("store_city", "Vienna")
    store_name_like = params.get("store_name_like", "%Praterstern%")
    min_available = params.get("min_available", 4)

    # ---- discovery 1: resolve store ----
    store_sql = (
        "SELECT store_id, record_path, store_name, city FROM stores "
        "WHERE LOWER(TRIM(city))=LOWER('" + q(store_city) + "') "
        "AND store_name LIKE '" + store_name_like + "';"
    )
    store = vm.exec(path="/bin/sql", args=[store_sql])
    _store_out = get_stdout(store)

    families = [
        params.get("p1_family"),
        params.get("p2_family"),
        params.get("p3_family"),
        params.get("p4_family"),
        params.get("p5_family"),
        params.get("p6_family"),
    ]
    fam_list = ",".join("'" + q(f) + "'" for f in families if f)

    # ---- discovery 2: inspect candidate variant properties ----
    props_sql = (
        "SELECT pf.product_family_name, pv.product_sku, p.property_key, "
        "p.property_value_text, p.property_value_number "
        "FROM product_families pf "
        "JOIN product_variants pv ON pv.product_family_id=pf.product_family_id "
        "JOIN product_variant_properties p ON p.product_sku=pv.product_sku "
        "WHERE pf.product_family_name IN (" + fam_list + ") "
        "ORDER BY pf.product_family_name, pv.product_sku, p.property_key;"
    )
    props_meta = vm.exec(path="/bin/sql", args=[props_sql])
    _props_out = get_stdout(props_meta)

    # ---- helpers to build variant-resolution predicates ----
    def txt_prop(key, val):
        return (
            "EXISTS(SELECT 1 FROM product_variant_properties p "
            "WHERE p.product_sku=pv.product_sku "
            "AND LOWER(TRIM(p.property_key))=LOWER('" + q(key) + "') "
            "AND LOWER(TRIM(p.property_value_text))=LOWER('" + q(val) + "'))"
        )

    def num_prop(keys, num, unit):
        n = str(num)
        texts = [n, n + " " + unit, n + unit, n + ".0 " + unit]
        keylist = ",".join("'" + q(k) + "'" for k in keys)
        textlist = ",".join("LOWER('" + q(t) + "')" for t in texts)
        return (
            "EXISTS(SELECT 1 FROM product_variant_properties p "
            "WHERE p.product_sku=pv.product_sku "
            "AND LOWER(TRIM(p.property_key)) IN (" + keylist + ") "
            "AND (p.property_value_number=" + n + " "
            "OR CAST(p.property_value_number AS TEXT)='" + n + "' "
            "OR LOWER(TRIM(p.property_value_text)) IN (" + textlist + ")))"
        )

    def branch(family, clauses):
        return (
            "SELECT pv.product_sku, pv.record_path FROM product_variants pv "
            "JOIN product_families pf ON pf.product_family_id=pv.product_family_id "
            "WHERE LOWER(TRIM(pf.product_family_name))=LOWER('" + q(family) + "') AND "
            + " AND ".join(clauses)
        )

    branches = [
        branch(params.get("p1_family"), [
            txt_prop("color_family", params.get("p1_color_family", "Gray")),
            num_prop(["length_m", "length", "cable_length_m"], params.get("p1_length_m", 2), "m"),
        ]),
        branch(params.get("p2_family"), [
            txt_prop("adhesive_type", params.get("p2_adhesive_type", "threadlocker")),
            txt_prop("color_family", params.get("p2_color_family", "Brown")),
        ]),
        branch(params.get("p3_family"), [
            txt_prop("cleaner_type", params.get("p3_cleaner_type", "glass cleaner")),
            num_prop(["volume_ml", "volume"], params.get("p3_volume_ml", 750), "ml"),
            txt_prop("surface", params.get("p3_surface", "glass")),
        ]),
        branch(params.get("p4_family"), [
            txt_prop("product_type", params.get("p4_product_type", "concrete sealer")),
            txt_prop("color_family", params.get("p4_color_family", "Blue")),
            txt_prop("finish", params.get("p4_finish", "satin")),
        ]),
        branch(params.get("p5_family"), [
            txt_prop("color_family", params.get("p5_color_family", "Gray")),
            txt_prop("size", params.get("p5_size", "L")),
            txt_prop("fit", params.get("p5_fit", "slim")),
        ]),
        branch(params.get("p6_family"), [
            txt_prop("tool_type", params.get("p6_tool_type", "socket wrench")),
            num_prop(["length_mm", "length"], params.get("p6_length_mm", 125), "mm"),
        ]),
    ]

    t_cte = " UNION ALL ".join(branches)
    min_n = str(min_available)

    available_sql = (
        "WITH s AS (SELECT store_id FROM stores "
        "WHERE LOWER(TRIM(city))=LOWER('" + q(store_city) + "') "
        "AND store_name LIKE '" + store_name_like + "'), "
        "t AS (" + t_cte + ") "
        "SELECT t.product_sku, t.record_path, si.available_today_quantity "
        "FROM t "
        "JOIN store_inventory si ON si.product_sku=t.product_sku "
        "JOIN s ON s.store_id=si.store_id "
        "WHERE si.available_today_quantity >= " + min_n + ";"
    )
    available = vm.exec(path="/bin/sql", args=[available_sql])
    out = get_stdout(available)

    # ---- parse record_path(s) of available products ----
    seen = set()
    record_paths = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        if "|" in ln:
            cells = [c.strip() for c in ln.split("|")]
        else:
            cells = [c.strip() for c in ln.split(",")]
        for c in cells:
            if c.startswith("/"):
                if c not in seen:
                    seen.add(c)
                    record_paths.append(c)
                break

    count = len(record_paths)
    message = "result " + str(count)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=record_paths)
