import csv
import io


def _q(v):
    return "'" + str(v).replace("'", "''") + "'"


def _stdout(result):
    if result is None:
        return ""
    s = getattr(result, "stdout", None)
    if s is None and isinstance(result, dict):
        s = result.get("stdout", "")
    return s or ""


def _parse_rows(stdout):
    text = (stdout or "").strip()
    if not text:
        return [], []
    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        return [], []
    header = [h.strip() for h in reader[0]]
    rows = reader[1:]
    return header, rows


def run(vm, params):
    brand = params["brand"]
    model = params["model"]
    screw_type = params["screw_type"]
    diameter_mm = params["diameter_mm"]
    length_mm = params["length_mm"]
    city = params["city"]

    discovery_sql = (
        "WITH target AS (\n"
        "  SELECT pv.product_sku, pv.record_path AS product_path\n"
        "  FROM product_variants pv\n"
        "  WHERE pv.brand = " + _q(brand) + "\n"
        "    AND pv.model = " + _q(model) + "\n"
        "    AND pv.product_sku IN (SELECT product_sku FROM product_variant_properties WHERE property_key='screw_type' AND property_value_text = " + _q(screw_type) + ")\n"
        "    AND pv.product_sku IN (SELECT product_sku FROM product_variant_properties WHERE property_key='diameter_mm' AND property_value_number = " + str(diameter_mm) + ")\n"
        "    AND pv.product_sku IN (SELECT product_sku FROM product_variant_properties WHERE property_key='length_mm' AND property_value_number = " + str(length_mm) + ")\n"
        ")\n"
        "SELECT s.store_id, s.record_path AS store_path, t.product_sku, t.product_path,\n"
        "       COALESCE(si.available_today_quantity, 0) AS available_today\n"
        "FROM target t\n"
        "CROSS JOIN stores s\n"
        "LEFT JOIN store_inventory si\n"
        "  ON si.store_id = s.store_id AND si.product_sku = t.product_sku\n"
        "WHERE s.city = " + _q(city) + "\n"
        "ORDER BY s.store_id;"
    )

    graz_rows = vm.exec(path="/bin/sql", args=[discovery_sql])
    d_header, d_rows = _parse_rows(_stdout(graz_rows))

    product_path = None
    store_paths = []
    if d_header:
        try:
            store_idx = d_header.index("store_path")
        except ValueError:
            store_idx = 1
        try:
            prod_idx = d_header.index("product_path")
        except ValueError:
            prod_idx = 3
        for row in d_rows:
            if not row:
                continue
            if store_idx < len(row):
                sp = row[store_idx].strip()
                if sp and sp not in store_paths:
                    store_paths.append(sp)
            if product_path is None and prod_idx < len(row):
                pp = row[prod_idx].strip()
                if pp:
                    product_path = pp

    total_sql = (
        "WITH target AS (\n"
        "  SELECT pv.product_sku, pv.record_path AS product_path\n"
        "  FROM product_variants pv\n"
        "  WHERE pv.brand = " + _q(brand) + "\n"
        "    AND pv.model = " + _q(model) + "\n"
        "    AND pv.product_sku IN (SELECT product_sku FROM product_variant_properties WHERE property_key='screw_type' AND property_value_text = " + _q(screw_type) + ")\n"
        "    AND pv.product_sku IN (SELECT product_sku FROM product_variant_properties WHERE property_key='diameter_mm' AND property_value_number = " + str(diameter_mm) + ")\n"
        "    AND pv.product_sku IN (SELECT product_sku FROM product_variant_properties WHERE property_key='length_mm' AND property_value_number = " + str(length_mm) + ")\n"
        ")\n"
        "SELECT COALESCE(SUM(COALESCE(si.available_today_quantity,0)),0) AS total_qty\n"
        "FROM target t\n"
        "CROSS JOIN stores s\n"
        "LEFT JOIN store_inventory si\n"
        "  ON si.store_id = s.store_id AND si.product_sku = t.product_sku\n"
        "WHERE s.city = " + _q(city) + ";"
    )

    total = vm.exec(path="/bin/sql", args=[total_sql])
    t_header, t_rows = _parse_rows(_stdout(total))

    total_qty = 0
    if t_rows and t_rows[0]:
        try:
            total_qty = int(float(t_rows[0][0].strip()))
        except (ValueError, IndexError):
            total_qty = 0

    refs = []
    if product_path:
        refs.append(product_path)
    refs.extend(store_paths)

    message = "qty %d" % total_qty
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
