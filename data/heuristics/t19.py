import csv, io


def run(vm, params):
    def _stdout(res):
        s = getattr(res, "stdout", None)
        if s is None and isinstance(res, dict):
            s = res.get("stdout", "")
        return s or ""

    def _q(v):
        return "'" + str(v).replace("'", "''") + "'"

    def _parse_rows(text):
        text = (text or "").strip("\n")
        if not text.strip():
            return []
        lines = [ln for ln in text.splitlines() if ln.strip() != ""]
        if not lines:
            return []
        comma = lines[0].count(",")
        pipe = lines[0].count("|")
        if pipe > comma:
            parsed = [ln.split("|") for ln in lines]
        else:
            parsed = list(csv.reader(lines))
        if not parsed:
            return []
        header = [h.strip() for h in parsed[0]]
        out = []
        for r in parsed[1:]:
            d = {}
            for i, h in enumerate(header):
                d[h] = r[i].strip() if i < len(r) else ""
            out.append(d)
        return out

    brand = params["brand"]
    series = params["series"]
    model = params["model"]
    trap_type = params["trap_type"]
    diameter_mm = params["diameter_mm"]
    city = params["city"]
    dia = str(int(float(diameter_mm)))

    # discovery: identity
    identity = vm.exec(path="/bin/id", args=[], stdin="")

    # discovery: resolve the single product variant
    product_sql = (
        "SELECT pv.product_sku, pv.record_path, pv.product_name "
        "FROM product_variants pv "
        "JOIN product_variant_properties tt ON tt.product_sku = pv.product_sku "
        "AND tt.property_key = 'trap_type' AND tt.property_value_text = " + _q(trap_type) + " "
        "JOIN product_variant_properties dm ON dm.product_sku = pv.product_sku "
        "AND dm.property_key = 'diameter_mm' AND dm.property_value_number = " + dia + " "
        "WHERE pv.brand = " + _q(brand) + " AND pv.series = " + _q(series) +
        " AND pv.model = " + _q(model) + ";"
    )
    product = vm.exec(path="/bin/sql", args=[product_sql], stdin="")
    product_rows = _parse_rows(_stdout(product))

    # ops: per-store availability + Graz-wide total via LEFT JOIN (zero branches kept)
    result_sql = (
        "WITH prod AS (SELECT pv.product_sku, pv.record_path AS product_path "
        "FROM product_variants pv "
        "JOIN product_variant_properties tt ON tt.product_sku = pv.product_sku "
        "AND tt.property_key = 'trap_type' AND tt.property_value_text = " + _q(trap_type) + " "
        "JOIN product_variant_properties dm ON dm.product_sku = pv.product_sku "
        "AND dm.property_key = 'diameter_mm' AND dm.property_value_number = " + dia + " "
        "WHERE pv.brand = " + _q(brand) + " AND pv.series = " + _q(series) +
        " AND pv.model = " + _q(model) + ") "
        "SELECT s.store_id, s.record_path AS store_path, p.product_path, "
        "COALESCE(si.available_today_quantity, 0) AS available_today, "
        "(SELECT SUM(COALESCE(si2.available_today_quantity,0)) FROM stores s2 "
        "CROSS JOIN prod p2 LEFT JOIN store_inventory si2 "
        "ON si2.store_id = s2.store_id AND si2.product_sku = p2.product_sku "
        "WHERE s2.city = " + _q(city) + ") AS total_available "
        "FROM stores s CROSS JOIN prod p LEFT JOIN store_inventory si "
        "ON si.store_id = s.store_id AND si.product_sku = p.product_sku "
        "WHERE s.city = " + _q(city) + " ORDER BY s.store_id;"
    )
    result = vm.exec(path="/bin/sql", args=[result_sql], stdin="")
    result_rows = _parse_rows(_stdout(result))

    # short-circuit: empty CTE / no Graz stores -> not found, avoid OK with empty refs
    if not result_rows:
        vm.answer(
            message=("No matching " + brand + " " + series + " " + model + " " +
                     str(trap_type) + " " + dia + "mm shower-waste variant found in " +
                     city + "."),
            outcome="OUTCOME_NONE_UNSUPPORTED",
            refs=[],
        )
        return

    # product variant record_path
    product_path = ""
    if product_rows:
        product_path = product_rows[0].get("record_path") or product_rows[0].get("product_path") or ""
    if not product_path:
        product_path = result_rows[0].get("product_path") or ""

    # total across all Graz stores (zero-availability branches summed as 0)
    total = None
    tv = result_rows[0].get("total_available")
    if tv not in (None, ""):
        try:
            total = int(float(tv))
        except Exception:
            total = None
    if total is None:
        acc = 0
        for d in result_rows:
            try:
                acc += int(float(d.get("available_today", "0") or "0"))
            except Exception:
                pass
        total = acc

    graz_store_count = len(result_rows)

    # refs: availability constraint -> cite only AVAILABLE Graz stores, plus product
    available_store_paths = []
    for d in result_rows:
        sp = d.get("store_path") or d.get("record_path") or ""
        try:
            avail = int(float(d.get("available_today", "0") or "0"))
        except Exception:
            avail = 0
        if avail > 0 and sp and sp not in available_store_paths:
            available_store_paths.append(sp)

    refs = list(available_store_paths)
    if product_path and product_path not in refs:
        refs.append(product_path)

    message = ("qty " + str(total) + " \u2014 " + brand + " " + series + " " + model +
               " shower-waste " + dia + "mm Drain Trap and Siphon, summed across all " +
               str(graz_store_count) + " " + city +
               " PowerTool branches (zero-availability branches included).")

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
