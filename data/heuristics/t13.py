import csv
import io


def run(vm, params):
    def q(v):
        s = str(v)
        return "'" + s.replace("'", "''") + "'"

    def get_stdout(result):
        out = getattr(result, "stdout", None)
        if out is None and isinstance(result, dict):
            out = result.get("stdout", "")
        return out or ""

    def parse_csv(text):
        text = text or ""
        if not text.strip():
            return [], []
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return [], []
        return rows[0], rows[1:]

    def col_index(header, name, default):
        try:
            return header.index(name)
        except (ValueError, AttributeError):
            return default

    city = params["city"]
    store_pattern = params["store_pattern"]
    fam_festool = params["fam_festool"]
    fam_heco = params["fam_heco"]
    fam_ajax = params["fam_ajax"]
    storage_type = params["storage_type"]
    fastener_threaded = params["fastener_threaded"]
    fastener_bolt = params["fastener_bolt"]
    diameter = params["diameter"]
    cleaner_degreaser = params["cleaner_degreaser"]
    cleaner_floor = params["cleaner_floor"]
    min_available = params["min_available"]

    # --- discovery: resolve downtown store ---
    discovery_sql = (
        "SELECT store_id, record_path, store_name, city, is_open "
        "FROM stores WHERE city = " + q(city) +
        " AND store_name LIKE " + q(store_pattern) + ";"
    )
    store_res = vm.exec(path="/bin/sql", args=[discovery_sql], stdin="")
    store_header, store_data = parse_csv(get_stdout(store_res))
    store_rp_idx = col_index(store_header, "record_path", 1)
    store_paths = []
    for r in store_data:
        if len(r) > store_rp_idx and r[store_rp_idx].strip():
            store_paths.append(r[store_rp_idx].strip())

    # --- ops: qualifying variants with availability >= min_available ---
    ops_sql = (
        "WITH lj_store AS (\n"
        "  SELECT store_id FROM stores\n"
        "  WHERE city = " + q(city) + " AND store_name LIKE " + q(store_pattern) + "\n"
        "),\n"
        "target_skus AS (\n"
        "  SELECT pv.product_sku, pv.record_path\n"
        "  FROM product_variants pv\n"
        "  JOIN product_families pf ON pv.product_family_id = pf.product_family_id\n"
        "  WHERE\n"
        "    (pf.product_family_name = " + q(fam_festool) + "\n"
        "       AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = 'storage_type' AND p.property_value_text = " + q(storage_type) + "))\n"
        "    OR (pf.product_family_name = " + q(fam_heco) + "\n"
        "       AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = 'fastener_type' AND p.property_value_text = " + q(fastener_threaded) + "))\n"
        "    OR (pf.product_family_name = " + q(fam_heco) + "\n"
        "       AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = 'fastener_type' AND p.property_value_text = " + q(fastener_bolt) + ")\n"
        "       AND EXISTS (SELECT 1 FROM product_variant_properties p2 WHERE p2.product_sku = pv.product_sku AND p2.property_key = 'diameter_mm' AND p2.property_value_number = " + str(diameter) + "))\n"
        "    OR (pf.product_family_name = " + q(fam_ajax) + "\n"
        "       AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = 'cleaner_type' AND p.property_value_text = " + q(cleaner_degreaser) + "))\n"
        "    OR (pf.product_family_name = " + q(fam_ajax) + "\n"
        "       AND EXISTS (SELECT 1 FROM product_variant_properties p WHERE p.product_sku = pv.product_sku AND p.property_key = 'cleaner_type' AND p.property_value_text = " + q(cleaner_floor) + "))\n"
        ")\n"
        "SELECT ts.product_sku, ts.record_path, si.available_today_quantity\n"
        "FROM target_skus ts\n"
        "JOIN store_inventory si ON si.product_sku = ts.product_sku\n"
        "JOIN lj_store ls ON ls.store_id = si.store_id\n"
        "WHERE si.available_today_quantity >= " + str(min_available) + ";"
    )
    avail_res = vm.exec(path="/bin/sql", args=[ops_sql], stdin="")
    avail_header, avail_data = parse_csv(get_stdout(avail_res))
    avail_rp_idx = col_index(avail_header, "record_path", 1)
    avail_sku_idx = col_index(avail_header, "product_sku", 0)

    available_paths = []
    distinct_skus = set()
    for r in avail_data:
        if len(r) > avail_rp_idx and r[avail_rp_idx].strip():
            p = r[avail_rp_idx].strip()
            if p not in available_paths:
                available_paths.append(p)
        if len(r) > avail_sku_idx and r[avail_sku_idx].strip():
            distinct_skus.add(r[avail_sku_idx].strip())

    available_count = len(distinct_skus) if distinct_skus else len(avail_data)

    refs = []
    for p in store_paths:
        if p not in refs:
            refs.append(p)
    for p in available_paths:
        if p not in refs:
            refs.append(p)

    message = "Count: " + str(available_count)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
