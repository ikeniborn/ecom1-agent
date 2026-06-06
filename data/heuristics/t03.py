def run(vm, params):
    # discovery 1: identity
    identity = vm.exec(path="/bin/id", args=[])

    sql = (
        "WITH matches AS (SELECT pv.product_sku, pv.record_path, pv.product_name, "
        "pf.product_family_name, st.property_value_text AS sealant_type, "
        "cf.property_value_text AS color_family FROM product_variants pv "
        "JOIN product_families pf ON pf.product_family_id = pv.product_family_id "
        "JOIN product_variant_properties st ON st.product_sku = pv.product_sku "
        "AND st.property_key = 'sealant_type' AND st.property_value_text = :sealant_type "
        "JOIN product_variant_properties cf ON cf.product_sku = pv.product_sku "
        "AND cf.property_key = 'color_family' AND cf.property_value_text = :color_family "
        "WHERE pv.brand = :brand AND pf.product_family_name = :line) "
        "SELECT m.product_sku, m.record_path, m.product_name, m.product_family_name, "
        "m.sealant_type, m.color_family, COALESCE(SUM(si.available_today_quantity), 0) AS available_today "
        "FROM matches m LEFT JOIN store_inventory si ON si.product_sku = m.product_sku "
        "GROUP BY m.product_sku, m.record_path, m.product_name, m.product_family_name, "
        "m.sealant_type, m.color_family;"
    )

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    # Inline literal, quoted parameter values directly into the SQL string;
    # /bin/sql ignores positional args for :name binding (learned rules r003/in-session).
    sql = sql.replace(":sealant_type", q(params["sealant_type"]))
    sql = sql.replace(":color_family", q(params["color_family"]))
    sql = sql.replace(":brand", q(params["brand"]))
    sql = sql.replace(":line", q(params["line"]))

    # discovery 2: run query via stdin (statement read from stdin)
    matches = vm.exec(path="/bin/sql", args=[], stdin=sql)
    stdout = getattr(matches, "stdout", "") or (matches.get("stdout", "") if isinstance(matches, dict) else "")

    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]

    available_paths = []
    has_available = False

    if len(lines) >= 1:
        header = lines[0]
        if "|" in header:
            delim = "|"
        elif "," in header:
            delim = ","
        elif "\t" in header:
            delim = "\t"
        else:
            delim = None

        def split_row(line):
            if delim is None:
                return [c.strip() for c in line.split()]
            return [c.strip() for c in line.split(delim)]

        cols = split_row(header)
        try:
            rp_idx = cols.index("record_path")
        except ValueError:
            rp_idx = 1
        try:
            av_idx = cols.index("available_today")
        except ValueError:
            av_idx = len(cols) - 1

        for line in lines[1:]:
            fields = split_row(line)
            if len(fields) <= max(rp_idx, av_idx):
                continue
            rp = fields[rp_idx]
            av_raw = fields[av_idx]
            try:
                av = float(av_raw)
            except (ValueError, TypeError):
                av = 0
            if av > 0:
                has_available = True
                if rp:
                    available_paths.append(rp)

    # dedupe preserving order
    available_paths = list(dict.fromkeys(available_paths))

    token = "<YES>" if (has_available and available_paths) else "<NO>"

    if has_available and available_paths:
        message = (
            token + " Catalog carries an available Pattex sealant in the '"
            + str(params["line"]) + "' line with sealant type '"
            + str(params["sealant_type"]) + "' and color family '"
            + str(params["color_family"]) + "'. Available match(es) at full repo path: "
            + ", ".join(available_paths) + "."
        )
        refs = available_paths
    else:
        message = (
            token + " No available Pattex sealant in the '"
            + str(params["line"]) + "' line with sealant type '"
            + str(params["sealant_type"]) + "' and color family '"
            + str(params["color_family"]) + "' is carried; no available match to reference."
        )
        refs = []

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
