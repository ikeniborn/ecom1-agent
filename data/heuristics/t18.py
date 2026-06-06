import csv
import io


def run(vm, params):
    brand = params["brand"]
    model = params["model"]
    product_type = params["product_type"]
    city = params["city"]

    def q(v):
        return str(v).replace("'", "''")

    def stdout_of(result):
        return getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    def parse_rows(text):
        text = (text or "").strip()
        if not text:
            return []
        reader = list(csv.reader(io.StringIO(text)))
        if not reader:
            return []
        return reader[1:]

    # discovery 1: resolve product SKU(s) + record_path for the deck-oil variant
    product_sql = (
        "SELECT pv.product_sku, pv.record_path, pk.product_kind_name, pv.product_name, "
        "pvp.property_value_text AS product_type FROM product_variants pv "
        "JOIN product_kinds pk ON pk.product_kind_id = pv.product_kind_id "
        "JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "WHERE pv.brand = '" + q(brand) + "' AND pv.product_name LIKE '%" + q(model) + "%' "
        "AND pvp.property_key = 'product_type' AND lower(pvp.property_value_text) = lower('" + q(product_type) + "');"
    )
    product = vm.exec(path="/bin/sql", args=[product_sql])
    product_rows = parse_rows(stdout_of(product))

    # discovery 2: enumerate ALL Graz stores
    stores_sql = (
        "SELECT store_id, record_path, store_name FROM stores WHERE city = '" + q(city) + "' ORDER BY store_id;"
    )
    graz_stores = vm.exec(path="/bin/sql", args=[stores_sql])
    graz_store_rows = parse_rows(stdout_of(graz_stores))

    # ops: LEFT JOIN availability over every Graz store (zero-availability included)
    availability_sql = (
        "WITH target AS (SELECT pv.product_sku, pv.record_path AS product_record_path FROM product_variants pv "
        "JOIN product_variant_properties pvp ON pvp.product_sku = pv.product_sku "
        "WHERE pv.brand = '" + q(brand) + "' AND pv.product_name LIKE '%" + q(model) + "%' "
        "AND pvp.property_key = 'product_type' AND lower(pvp.property_value_text) = lower('" + q(product_type) + "')) "
        "SELECT s.store_id, s.record_path AS store_record_path, t.product_sku, t.product_record_path, "
        "COALESCE(si.available_today_quantity, 0) AS available_today FROM stores s CROSS JOIN target t "
        "LEFT JOIN store_inventory si ON si.store_id = s.store_id AND si.product_sku = t.product_sku "
        "WHERE s.city = '" + q(city) + "' ORDER BY s.store_id;"
    )
    availability = vm.exec(path="/bin/sql", args=[availability_sql])
    avail_rows = parse_rows(stdout_of(availability))

    # Total = SUM over every Graz store (zeros included via COALESCE).
    # Constraint (availability): cite only AVAILABLE stores/products (qty>0),
    # never zero-availability rows. Constraint (references): cite full record_path.
    total = 0
    store_refs = []
    product_refs = []
    for row in avail_rows:
        if len(row) < 5:
            continue
        store_record_path = row[1].strip()
        product_record_path = row[3].strip()
        try:
            qty = int(float(row[4].strip() or 0))
        except ValueError:
            qty = 0
        total += qty
        if qty > 0:
            if store_record_path and store_record_path not in store_refs:
                store_refs.append(store_record_path)
            if product_record_path and product_record_path not in product_refs:
                product_refs.append(product_record_path)

    refs = store_refs + product_refs
    vm.answer(message="qty %d" % total, outcome="OUTCOME_OK", refs=refs)
