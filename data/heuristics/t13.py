import csv
import io


def _q(v):
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _inline(sql, params):
    # Replace :name placeholders with inlined SQL literals (longest name first).
    for name in sorted(params.keys(), key=len, reverse=True):
        sql = sql.replace(":" + name, _q(params[name]))
    return sql


def _stdout(result):
    return getattr(result, "stdout", "") or (
        result.get("stdout", "") if isinstance(result, dict) else ""
    )


def _rows(stdout):
    text = (stdout or "").strip()
    if not text:
        return []
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        return []
    header = all_rows[0]
    out = []
    for r in all_rows[1:]:
        if not r:
            continue
        out.append({header[i]: (r[i] if i < len(r) else "") for i in range(len(header))})
    return out


def run(vm, params):
    # Discovery 1: resolve store_id / record_path
    store_sql = _inline(
        "SELECT store_id, store_name, record_path FROM stores WHERE store_name LIKE :store;",
        params,
    )
    store = vm.exec(path="/bin/sql", args=[], stdin=store_sql)
    store_rows = _rows(_stdout(store))
    store_path = store_rows[0].get("record_path", "") if store_rows else ""

    # Discovery 2: qualifying product variant record_paths
    paths_sql = _inline(
        "WITH s AS (SELECT store_id FROM stores WHERE store_name LIKE :store) "
        "SELECT DISTINCT pv.record_path FROM product_variants pv "
        "JOIN product_families pf ON pf.product_family_id=pv.product_family_id "
        "JOIN store_inventory si ON si.product_sku=pv.product_sku "
        "JOIN s ON s.store_id=si.store_id "
        "LEFT JOIN product_variant_properties pft ON pft.product_sku=pv.product_sku AND pft.property_key='fastener_type' "
        "LEFT JOIN product_variant_properties pct ON pct.product_sku=pv.product_sku AND pct.property_key='cleaner_type' "
        "LEFT JOIN product_variant_properties pst ON pst.product_sku=pv.product_sku AND pst.property_key='storage_type' "
        "LEFT JOIN product_variant_properties psc ON psc.product_sku=pv.product_sku AND psc.property_key='screw_type' "
        "LEFT JOIN product_variant_properties pdi ON pdi.product_sku=pv.product_sku AND pdi.property_key='diameter_mm' "
        "WHERE si.available_today_quantity >= :min_qty AND ( "
        "(pf.product_family_name=:line_nbw AND pft.property_value_text=:ft_rod) OR "
        "(pf.product_family_name=:line_clean AND pct.property_value_text=:ct_floor) OR "
        "(pf.product_family_name=:line_box AND pst.property_value_text=:st_bag) OR "
        "(pf.product_family_name=:line_screw AND psc.property_value_text=:sc_wood AND pdi.property_value_number=:dia6) OR "
        "(pf.product_family_name=:line_clean AND pct.property_value_text=:ct_deg) OR "
        "(pf.product_family_name=:line_nbw AND pft.property_value_text=:ft_bolt AND pdi.property_value_number=:dia10) );",
        params,
    )
    paths_res = vm.exec(path="/bin/sql", args=[], stdin=paths_sql)
    path_rows = _rows(_stdout(paths_res))
    product_paths = [r.get("record_path", "") for r in path_rows if r.get("record_path", "")]

    # Ops: count qualifying specs
    count_sql = _inline(
        "WITH s AS (SELECT store_id FROM stores WHERE store_name LIKE :store) SELECT "
        "(CASE WHEN EXISTS (SELECT 1 FROM product_variants pv JOIN product_families pf ON pf.product_family_id=pv.product_family_id JOIN store_inventory si ON si.product_sku=pv.product_sku JOIN s ON s.store_id=si.store_id JOIN product_variant_properties p ON p.product_sku=pv.product_sku AND p.property_key='fastener_type' AND p.property_value_text=:ft_rod WHERE pf.product_family_name=:line_nbw AND si.available_today_quantity>=:min_qty) THEN 1 ELSE 0 END) + "
        "(CASE WHEN EXISTS (SELECT 1 FROM product_variants pv JOIN product_families pf ON pf.product_family_id=pv.product_family_id JOIN store_inventory si ON si.product_sku=pv.product_sku JOIN s ON s.store_id=si.store_id JOIN product_variant_properties p ON p.product_sku=pv.product_sku AND p.property_key='cleaner_type' AND p.property_value_text=:ct_floor WHERE pf.product_family_name=:line_clean AND si.available_today_quantity>=:min_qty) THEN 1 ELSE 0 END) + "
        "(CASE WHEN EXISTS (SELECT 1 FROM product_variants pv JOIN product_families pf ON pf.product_family_id=pv.product_family_id JOIN store_inventory si ON si.product_sku=pv.product_sku JOIN s ON s.store_id=si.store_id JOIN product_variant_properties p ON p.product_sku=pv.product_sku AND p.property_key='storage_type' AND p.property_value_text=:st_bag WHERE pf.product_family_name=:line_box AND si.available_today_quantity>=:min_qty) THEN 1 ELSE 0 END) + "
        "(CASE WHEN EXISTS (SELECT 1 FROM product_variants pv JOIN product_families pf ON pf.product_family_id=pv.product_family_id JOIN store_inventory si ON si.product_sku=pv.product_sku JOIN s ON s.store_id=si.store_id JOIN product_variant_properties p ON p.product_sku=pv.product_sku AND p.property_key='screw_type' AND p.property_value_text=:sc_wood JOIN product_variant_properties d ON d.product_sku=pv.product_sku AND d.property_key='diameter_mm' AND d.property_value_number=:dia6 WHERE pf.product_family_name=:line_screw AND si.available_today_quantity>=:min_qty) THEN 1 ELSE 0 END) + "
        "(CASE WHEN EXISTS (SELECT 1 FROM product_variants pv JOIN product_families pf ON pf.product_family_id=pv.product_family_id JOIN store_inventory si ON si.product_sku=pv.product_sku JOIN s ON s.store_id=si.store_id JOIN product_variant_properties p ON p.product_sku=pv.product_sku AND p.property_key='cleaner_type' AND p.property_value_text=:ct_deg WHERE pf.product_family_name=:line_clean AND si.available_today_quantity>=:min_qty) THEN 1 ELSE 0 END) + "
        "(CASE WHEN EXISTS (SELECT 1 FROM product_variants pv JOIN product_families pf ON pf.product_family_id=pv.product_family_id JOIN store_inventory si ON si.product_sku=pv.product_sku JOIN s ON s.store_id=si.store_id JOIN product_variant_properties p ON p.product_sku=pv.product_sku AND p.property_key='fastener_type' AND p.property_value_text=:ft_bolt JOIN product_variant_properties d ON d.product_sku=pv.product_sku AND d.property_key='diameter_mm' AND d.property_value_number=:dia10 WHERE pf.product_family_name=:line_nbw AND si.available_today_quantity>=:min_qty) THEN 1 ELSE 0 END) AS products;",
        params,
    )
    count_res = vm.exec(path="/bin/sql", args=[], stdin=count_sql)
    count_rows = _rows(_stdout(count_res))
    count = count_rows[0].get("products", "0") if count_rows else "0"

    refs = list(product_paths)
    if store_path:
        refs.append(store_path)

    vm.answer(message="{} products".format(count), outcome="OUTCOME_OK", refs=refs)
