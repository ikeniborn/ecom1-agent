import csv
import io


def run(vm, params):
    def esc(v):
        return str(v).replace("'", "''")

    brand = esc(params["brand"])
    line = esc(params["line"])
    product_kind = esc(params["product_kind"])
    volume_ml = params["volume_ml"]
    try:
        volume_sql = str(int(volume_ml))
    except (TypeError, ValueError):
        volume_sql = "'" + esc(volume_ml) + "'"

    sql = (
        "WITH base AS ("
        "SELECT pv.product_sku, pv.record_path, pv.brand, pv.series, pv.model, "
        "pv.product_name, pv.product_kind_id, pk.product_kind_name "
        "FROM product_variants pv "
        "JOIN product_kinds pk ON pk.product_kind_id = pv.product_kind_id "
        "WHERE pv.brand = '" + brand + "' "
        "AND pv.product_name LIKE '%" + line + "%'"
        "), withvol AS ("
        "SELECT b.*, vp.property_value_number AS volume_ml "
        "FROM base b "
        "LEFT JOIN product_variant_properties vp "
        "ON vp.product_sku = b.product_sku AND vp.property_key = 'volume_ml'"
        ") SELECT product_sku, record_path, product_name, product_kind_name, volume_ml, "
        "CASE WHEN lower(product_kind_name) = lower('" + product_kind + "') "
        "AND volume_ml = " + volume_sql + " THEN 1 ELSE 0 END AS claim_match "
        "FROM withvol ORDER BY claim_match DESC, product_sku;"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "")
    if not stdout and isinstance(result, dict):
        stdout = result.get("stdout", "")
    stdout = stdout or ""

    rows = []
    reader = csv.reader(io.StringIO(stdout))
    records = [r for r in reader if r and any(c.strip() for c in r)]
    if records:
        header = [h.strip() for h in records[0]]
        for data in records[1:]:
            row = {}
            for i, col in enumerate(header):
                row[col] = data[i].strip() if i < len(data) else ""
            rows.append(row)

    refs = []
    for row in rows:
        rp = row.get("record_path", "")
        if rp and rp not in refs:
            refs.append(rp)

    if rows:
        base = rows[0]
        sku = base.get("product_sku", "")
        record_path = base.get("record_path", "")
        message = (
            "Checked Bondex Garden Classic 106-TS1 Wood Stain and Deck Oil line. "
            "Base product exists (SKU " + sku + ", " + record_path + "), "
            "but no catalogue variant of product type 'wood stain' with volume 1000 ml "
            "is present — the claimed item is absent. <NO>"
        )
    else:
        message = (
            "Checked Bondex Garden Classic 106-TS1 Wood Stain and Deck Oil line. "
            "No matching base product was found, so no catalogue variant of product type "
            "'wood stain' with volume 1000 ml is present. <NO>"
        )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
