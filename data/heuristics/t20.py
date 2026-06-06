import csv
import io


def run(vm, params):
    def ql(v):
        return "'" + str(v).lower().strip().replace("'", "''") + "'"

    brand = params["brand"]
    series = params["series"]
    model = params["model"]
    kind_name = params["kind_name"]
    storage_type = params["storage_type"]
    color_family = params["color_family"]
    volume_l = params["volume_l"]
    city = params["city"]
    try:
        vol_num = int(float(volume_l))
    except (TypeError, ValueError):
        vol_num = volume_l

    sql = (
        "WITH target AS (\n"
        "  SELECT pv.product_sku, pv.record_path AS product_path\n"
        "  FROM product_variants pv\n"
        "  JOIN product_kinds pk ON pk.product_kind_id = pv.product_kind_id"
        " AND LOWER(TRIM(pk.product_kind_name)) = " + ql(kind_name) + "\n"
        "  JOIN product_variant_properties s ON s.product_sku = pv.product_sku"
        " AND s.property_key = 'storage_type'"
        " AND LOWER(TRIM(s.property_value_text)) = " + ql(storage_type) + "\n"
        "  JOIN product_variant_properties c ON c.product_sku = pv.product_sku"
        " AND c.property_key = 'color_family'"
        " AND LOWER(TRIM(c.property_value_text)) = " + ql(color_family) + "\n"
        "  JOIN product_variant_properties v ON v.product_sku = pv.product_sku"
        " AND v.property_key = 'volume_l'"
        " AND v.property_value_number = " + str(vol_num) + "\n"
        "  WHERE LOWER(TRIM(pv.brand)) = " + ql(brand) +
        " AND LOWER(TRIM(pv.series)) = " + ql(series) +
        " AND LOWER(TRIM(pv.model)) = " + ql(model) + "\n"
        ")\n"
        "SELECT st.store_id,\n"
        "       st.record_path AS store_path,\n"
        "       t.product_sku,\n"
        "       t.product_path,\n"
        "       COALESCE(inv.available_today_quantity, 0) AS available_today,\n"
        "       SUM(COALESCE(inv.available_today_quantity, 0)) OVER () AS total_available\n"
        "FROM stores st\n"
        "CROSS JOIN target t\n"
        "LEFT JOIN store_inventory inv ON inv.store_id = st.store_id AND inv.product_sku = t.product_sku\n"
        "WHERE LOWER(TRIM(st.city)) = " + ql(city) + "\n"
        "ORDER BY st.store_id;"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")
    rows = stdout

    reader = csv.reader(io.StringIO(stdout))
    all_rows = [r for r in reader if r and any(cell.strip() for cell in r)]
    header = all_rows[0] if all_rows else None
    data_rows = all_rows[1:] if all_rows else []

    def col_idx(name):
        if header is None:
            return -1
        for i, h in enumerate(header):
            if h.strip() == name:
                return i
        return -1

    si_store_path = col_idx("store_path")
    si_product_path = col_idx("product_path")
    si_total = col_idx("total_available")
    si_avail = col_idx("available_today")

    def to_int(s):
        s = (s or "").strip()
        if not s:
            return 0
        try:
            return int(float(s))
        except ValueError:
            return 0

    store_paths = []
    product_path = None
    total_available = 0

    for r in data_rows:
        av = to_int(r[si_avail]) if (si_avail != -1 and si_avail < len(r)) else 0
        if product_path is None and si_product_path != -1 and si_product_path < len(r):
            pp = r[si_product_path].strip()
            if pp:
                product_path = pp
        # availability-scope: cite only stores where the product is available today
        if av > 0 and si_store_path != -1 and si_store_path < len(r):
            sp = r[si_store_path].strip()
            if sp and sp not in store_paths:
                store_paths.append(sp)

    if si_total != -1:
        for r in data_rows:
            if si_total < len(r) and r[si_total].strip():
                total_available = to_int(r[si_total])
                break
    elif si_avail != -1:
        total_available = sum(to_int(r[si_avail]) for r in data_rows if si_avail < len(r))

    if not data_rows or product_path is None:
        vm.answer(
            message=(
                "Could not resolve the " + str(brand) + " " + str(series) + " " + str(model) +
                " " + str(kind_name) + " (" + str(storage_type) + ", " + str(color_family) +
                ", " + str(vol_num) + " l) for any " + str(city) +
                " store; no matching records found."
            ),
            outcome="OUTCOME_NONE_CLARIFICATION",
            refs=[],
        )
        return

    refs = list(store_paths)
    refs.append(product_path)

    message = (
        str(total_available) + " total \u2014 across all " + str(city) +
        " PowerTool branches (including 0-availability branches), " + str(total_available) +
        " unit(s) of the " + str(brand) + " " + str(series) + " " + str(model) +
        " " + str(kind_name) + " (" + str(storage_type) + ", " + str(color_family) +
        ", " + str(vol_num) + " l) are available today."
    )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
