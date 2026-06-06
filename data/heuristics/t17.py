def run(vm, params):
    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    def stdout_of(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def parse_rows(text):
        lines = [ln for ln in text.splitlines() if ln.strip() != ""]
        if not lines:
            return []
        data = lines[1:]
        return [ln.split(",") for ln in data]

    brand = params["brand"]
    family = params["family"]
    kind = params["kind"]
    storage_type = params["storage_type"]
    city = params["city"]

    target_cte = (
        "SELECT pv.product_sku FROM product_variants pv "
        "JOIN product_families pf ON pf.product_family_id = pv.product_family_id "
        "JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "WHERE pv.brand = " + q(brand) + " "
        "AND pf.product_family_name = " + q(family) + " "
        "AND pv.product_kind_id = " + q(kind) + " "
        "AND pvp.property_key = 'storage_type' "
        "AND pvp.property_value_text = " + q(storage_type)
    )

    product_sql = (
        "SELECT pv.product_sku, pv.record_path FROM product_variants pv "
        "JOIN product_families pf ON pf.product_family_id = pv.product_family_id "
        "JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "WHERE pv.brand = " + q(brand) + " "
        "AND pf.product_family_name = " + q(family) + " "
        "AND pv.product_kind_id = " + q(kind) + " "
        "AND pvp.property_key = 'storage_type' "
        "AND pvp.property_value_text = " + q(storage_type) + ";"
    )
    product = vm.exec(path="/bin/sql", args=[product_sql])

    store_rows_sql = (
        "WITH target AS (" + target_cte + ") "
        "SELECT s.store_id, s.record_path, COALESCE(si.available_today_quantity, 0) AS available_today "
        "FROM stores s LEFT JOIN store_inventory si "
        "ON si.store_id = s.store_id AND si.product_sku = (SELECT product_sku FROM target) "
        "WHERE s.city = " + q(city) + " ORDER BY s.store_id;"
    )
    store_rows = vm.exec(path="/bin/sql", args=[store_rows_sql])

    total_sql = (
        "WITH target AS (" + target_cte + ") "
        "SELECT COALESCE(SUM(COALESCE(si.available_today_quantity, 0)), 0) AS total "
        "FROM stores s LEFT JOIN store_inventory si "
        "ON si.store_id = s.store_id AND si.product_sku = (SELECT product_sku FROM target) "
        "WHERE s.city = " + q(city) + ";"
    )
    total = vm.exec(path="/bin/sql", args=[total_sql])

    product_rows = parse_rows(stdout_of(product))
    product_path = None
    if product_rows and len(product_rows[0]) >= 2:
        product_path = product_rows[0][-1].strip()

    srows = parse_rows(stdout_of(store_rows))
    store_paths = []
    for row in srows:
        if len(row) >= 2:
            p = row[1].strip()
            if p:
                store_paths.append(p)

    total_rows = parse_rows(stdout_of(total))
    total_value = "0"
    if total_rows and len(total_rows[0]) >= 1:
        total_value = total_rows[0][-1].strip()

    refs = []
    if product_path:
        refs.append(product_path)
    refs.extend(store_paths)

    message = "{} total".format(total_value)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
