def run(vm, params):
    sql = (
        "WITH target_product AS ( SELECT pv.product_sku, pv.record_path FROM product_variants pv JOIN product_families pf ON pf.product_family_id = pv.product_family_id WHERE pv.brand = 'Philips' AND pf.product_family_name LIKE '%Philips Professional Hue 3JS-MSN LED Bulb%' AND pv.product_sku IN ( SELECT product_sku FROM product_variant_properties WHERE property_key = 'wattage' AND property_value_text = '10 W' INTERSECT SELECT product_sku FROM product_variant_properties WHERE property_key = 'luminous_flux' AND property_value_text = '470 lm' ) LIMIT 1 ), vienna_stores AS ( SELECT store_id, record_path FROM stores WHERE city = 'Vienna' ) SELECT (SELECT record_path FROM target_product) AS product_path, vs.record_path AS store_path, COALESCE(si.available_today_quantity, 0) AS available_today, ( SELECT SUM(COALESCE(si2.available_today_quantity, 0)) FROM vienna_stores vs2 LEFT JOIN store_inventory si2 ON si2.store_id = vs2.store_id AND si2.product_sku = (SELECT product_sku FROM target_product) ) AS total_available FROM vienna_stores vs LEFT JOIN store_inventory si ON si.store_id = vs.store_id AND si.product_sku = (SELECT product_sku FROM target_product)"
    )
    inventory_rows = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(inventory_rows, "stdout", "") or (inventory_rows.get("stdout", "") if isinstance(inventory_rows, dict) else "")
    lines = stdout.strip().split("\n")
    refs = []
    total_available = None
    product_path_seen = False
    store_paths = []
    if lines:
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) >= 4:
                product_path = parts[0].strip()
                store_path = parts[1].strip()
                row_total = parts[3].strip()
                if product_path and not product_path_seen:
                    refs.append(product_path)
                    product_path_seen = True
                if store_path:
                    store_paths.append(store_path)
                if total_available is None and row_total:
                    total_available = row_total
    refs.extend(store_paths)
    if total_available is None:
        total_available = "0"
    vm.answer(message=f"{total_available} total", outcome="OUTCOME_OK", refs=refs)
