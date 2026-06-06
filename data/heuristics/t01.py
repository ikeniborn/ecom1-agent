def run(vm, params):
    import csv

    brand = params.get("brand", "")
    series = params.get("series", "")
    model = params.get("model", "")
    kind = params.get("product_kind_name", "")
    cleaner = params.get("cleaner_type", "")

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    # Broadened query: filter only on brand (case-insensitive), LEFT JOINs so the
    # rowset always enumerates in-scope variants for refs. Property + availability
    # are applied in Python post-filter. /bin/sql does not bind :name params, so the
    # one variable value is inlined as a quoted SQL literal.
    sql = (
        "SELECT pv.product_sku, pv.product_name, pv.record_path, pv.brand, "
        "pv.series, pv.model, pk.product_kind_name, "
        "COALESCE(pvp.property_value_text,'') AS cleaner_type, "
        "COALESCE(SUM(si.available_today_quantity),0) AS total_available "
        "FROM product_variants pv "
        "LEFT JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "AND pvp.property_key = 'cleaner_type' "
        "LEFT JOIN product_kinds pk ON pk.product_kind_id = pv.product_kind_id "
        "LEFT JOIN store_inventory si ON si.product_sku = pv.product_sku "
        "WHERE LOWER(pv.brand) = LOWER(" + q(brand) + ") "
        "GROUP BY pv.product_sku, pv.product_name, pv.record_path, pv.brand, "
        "pv.series, pv.model, pk.product_kind_name, cleaner_type;"
    )

    def get_stdout(result):
        return getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    def parse_rows(stdout):
        if not stdout or not stdout.strip():
            return []
        lines = [l for l in stdout.splitlines() if l.strip() != ""]
        if not lines:
            return []
        header_line = lines[0]
        delim = ","
        for cand in [",", "|", "\t"]:
            if cand in header_line:
                delim = cand
                break
        all_rows = list(csv.reader(lines, delimiter=delim))
        if not all_rows:
            return []
        header = [h.strip() for h in all_rows[0]]
        out = []
        for r in all_rows[1:]:
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            out.append({header[i]: r[i].strip() for i in range(len(header))})
        return out

    # discovery
    matches_res = vm.exec(path="/bin/sql", stdin=sql)
    matches = parse_rows(get_stdout(matches_res))

    # ops
    available_res = vm.exec(path="/bin/sql", stdin=sql)
    available_rows = parse_rows(get_stdout(available_res))

    dataset = available_rows or matches

    def norm(s):
        return "".join(ch.lower() for ch in str(s) if ch.isalnum())

    t_series = norm(series)
    t_model = norm(model)
    t_kind = str(kind).lower().strip()
    t_cleaner = str(cleaner).lower().strip()

    def to_num(s):
        try:
            return float(str(s).strip() or 0)
        except ValueError:
            return 0.0

    matched = []
    for r in dataset:
        ident = norm(
            r.get("series", "") + r.get("model", "") + r.get("product_name", "") + r.get("product_sku", "")
        )
        kind_ok = (t_kind in r.get("product_kind_name", "").lower()) if t_kind else True
        series_ok = (t_series in ident) if t_series else True
        model_ok = (t_model in ident) if t_model else True
        cleaner_ok = r.get("cleaner_type", "").lower().strip() == t_cleaner
        if kind_ok and series_ok and model_ok and cleaner_ok:
            matched.append(r)

    available = [r for r in matched if to_num(r.get("total_available", "0")) > 0]

    record_paths = []
    for r in available:
        rp = r.get("record_path", "").strip()
        if rp and rp not in record_paths:
            record_paths.append(rp)

    # pass through static (non-$) refs from answer_template.refs; none are static here
    template_refs = ["$available_record_paths"]
    static_refs = [ref for ref in template_refs if not ref.startswith("$")]
    refs = static_refs + record_paths

    line_desc = "{} {} {} {} with cleaner type {}".format(brand, series, model, kind, cleaner)

    if available:
        detail = ", ".join(
            r.get("product_name", "") + " (" + r.get("record_path", "") + ")" for r in available
        )
        msg = "<YES> \u2014 Yes, the " + line_desc + " is carried and available: " + detail
    else:
        msg = "<NO> \u2014 No available product matches the " + line_desc + " line."

    vm.answer(message=msg, outcome="OUTCOME_OK", refs=refs)
