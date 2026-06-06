def run(vm, params):
    def esc(v):
        return str(v).replace("'", "''")

    def sql_exec(sql):
        result = vm.exec(path="/bin/sql", args=[sql])
        stdout = getattr(result, "stdout", "")
        if not stdout and isinstance(result, dict):
            stdout = result.get("stdout", "")
        return stdout or ""

    def parse_rows(stdout):
        lines = [l for l in stdout.splitlines() if l.strip() != ""]
        if len(lines) <= 1:
            return []
        rows = []
        for line in lines[1:]:
            rows.append([c.strip() for c in line.split(",")])
        return rows

    brand = esc(params["brand"])
    series = esc(params["series"])
    model = esc(params["model"])
    anchor = esc(params["anchor_type"])
    city = esc(params["city"])

    # Discovery 1: resolve product SKU + record path
    product_sql = (
        "SELECT v.product_sku, v.record_path FROM product_variants v "
        "JOIN product_variant_properties p ON p.product_sku = v.product_sku "
        "WHERE v.brand = '%s' AND v.series = '%s' AND v.model = '%s' "
        "AND p.property_key = 'anchor_type' AND p.property_value_text = '%s';"
    ) % (brand, series, model, anchor)
    product_rows = parse_rows(sql_exec(product_sql))
    product_sku = ""
    product_path = ""
    if product_rows:
        first = product_rows[0]
        if len(first) >= 1:
            product_sku = first[0]
        if len(first) >= 2:
            product_path = first[1]

    # Discovery 2: enumerate every open Graz store (incl. 0-availability)
    stores_sql = (
        "SELECT store_id, record_path FROM stores "
        "WHERE city = '%s' AND is_open = 1 ORDER BY store_id;"
    ) % city
    stores_rows = parse_rows(sql_exec(stores_sql))
    graz_store_paths = [r[1] for r in stores_rows if len(r) >= 2 and r[1]]

    # Op: sum available_today across all open Graz stores for this SKU
    sku_esc = esc(product_sku)
    total_sql = (
        "SELECT COALESCE(SUM(si.available_today_quantity), 0) AS total FROM stores s "
        "LEFT JOIN store_inventory si ON si.store_id = s.store_id AND si.product_sku = '%s' "
        "WHERE s.city = '%s' AND s.is_open = 1;"
    ) % (sku_esc, city)
    total_rows = parse_rows(sql_exec(total_sql))
    total = 0
    if total_rows and total_rows[0]:
        try:
            total = int(float(total_rows[0][0]))
        except (ValueError, IndexError):
            total = 0

    refs = []
    if product_path:
        refs.append(product_path)
    refs.extend(graz_store_paths)

    message = "answer=%d" % total
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
