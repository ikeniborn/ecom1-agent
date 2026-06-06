def run(vm, params):
    import csv, io

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    def _stdout(result):
        if result is None:
            return ""
        val = getattr(result, "stdout", None)
        if val is None and isinstance(result, dict):
            val = result.get("stdout", "")
        return val or ""

    def _parse_csv(text):
        text = text or ""
        if not text.strip():
            return [], []
        rows = [r for r in csv.reader(io.StringIO(text)) if r]
        if not rows:
            return [], []
        return rows[0], rows[1:]

    def cidx(h, name):
        return h.index(name) if name in h else -1

    # discovery: identity
    try:
        identity = vm.exec(path="/bin/id", args=[], stdin="")
    except Exception:
        identity = None

    # discovery: stores in the target city
    city = params["city"]
    stores_sql = ("SELECT store_id, record_path, store_name, city, is_open "
                  "FROM stores WHERE city = " + q(city) + ";")
    salzburg_stores = vm.exec(path="/bin/sql", args=[stores_sql], stdin="")
    sheader, srows = _parse_csv(_stdout(salzburg_stores))

    sid_i = cidx(sheader, "store_id")
    name_i = cidx(sheader, "store_name")
    pattern = str(params.get("store_pattern", "")).strip("%").lower()

    # resolve the central branch from discovery rows (do not re-filter literal in ops)
    chosen = None
    if name_i >= 0 and pattern:
        for r in srows:
            if len(r) > name_i and pattern in r[name_i].lower():
                chosen = r
                break
    if chosen is None and srows:
        chosen = srows[0]
    store_id = chosen[sid_i] if (chosen and sid_i >= 0 and len(chosen) > sid_i) else ""

    # build ops SQL with resolved store_id bound in directly
    def prop_exists(k, v):
        return ("EXISTS (SELECT 1 FROM product_variant_properties p "
                "WHERE p.product_sku=pv.product_sku AND p.property_key=" + q(k) +
                " AND p.property_value_text=" + q(v) + ")")

    def block(brand, line, props):
        parts = ["pv.brand=" + q(brand), "pf.product_family_name=" + q(line)]
        parts += [prop_exists(k, v) for k, v in props]
        return "(" + " AND ".join(parts) + ")"

    blocks = [
        block(params["brand1"], params["line1"], [
            (params["k_machine_type"], params["v_machine_type"]),
            (params["k_voltage"], params["v_voltage"]),
            (params["k_power"], params["v_power"]),
            (params["k_tank"], params["v_tank"]),
        ]),
        block(params["brand2"], params["line2"], [
            (params["k_tool_profile"], params["v_tool_profile2"]),
            (params["k_piece_count"], params["v_piece_count"]),
        ]),
        block(params["brand3"], params["line3"], [
            (params["k_tool_profile"], params["v_tool_profile3"]),
        ]),
        block(params["brand4"], params["line4"], [
            (params["k_product_type"], params["v_product_type"]),
        ]),
        block(params["brand5"], params["line5"], [
            (params["k_lens_color"], params["v_lens_color"]),
        ]),
        block(params["brand6"], params["line6"], [
            (params["k_power_source"], params["v_power_source"]),
        ]),
    ]
    where = " OR ".join(blocks)
    min_avail = int(params["min_available"])
    ops_sql = ("WITH matched AS (SELECT pv.product_sku, pv.record_path FROM product_variants pv "
               "JOIN product_families pf ON pf.product_family_id = pv.product_family_id WHERE " + where + ") "
               "SELECT m.product_sku, m.record_path AS record_path, si.available_today_quantity "
               "FROM matched m JOIN store_inventory si ON si.product_sku = m.product_sku "
               "WHERE si.store_id = " + q(store_id) + " AND si.available_today_quantity >= " + str(min_avail) + ";")

    available_rows = vm.exec(path="/bin/sql", args=[ops_sql], stdin="")
    oheader, orows = _parse_csv(_stdout(available_rows))
    rp_i = cidx(oheader, "record_path")
    if rp_i < 0:
        rp_i = 1

    record_paths = []
    for r in orows:
        if len(r) > rp_i and r[rp_i].strip():
            record_paths.append(r[rp_i].strip())

    count = len(orows)
    message = "result " + str(count)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=record_paths)
