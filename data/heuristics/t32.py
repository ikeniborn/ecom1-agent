import csv
import io


def run(vm, params):
    brand = params["brand"]
    line = params["line"]
    sealant_type = params["sealant_type"]

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    sql = (
        "SELECT pv.product_sku, pv.record_path, pv.product_name, pv.brand, "
        "MAX(CASE WHEN p.property_key = 'sealant_type' THEN p.property_value_text END) AS sealant_type, "
        "MAX(CASE WHEN p.property_key LIKE '%wifi%' OR p.property_value_text LIKE '%wifi%' "
        "THEN p.property_key || '=' || p.property_value_text END) AS wifi_capability "
        "FROM product_variants pv JOIN product_variant_properties p ON p.product_sku = pv.product_sku "
        "WHERE pv.brand = " + q(brand) + " AND pv.product_name LIKE " + q(line) + " "
        "GROUP BY pv.product_sku, pv.record_path, pv.product_name, pv.brand "
        "HAVING sealant_type = " + q(sealant_type) + ";"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    columns = ["product_sku", "record_path", "product_name", "brand", "sealant_type", "wifi_capability"]

    raw_lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    use_pipe = any(("|" in ln) for ln in raw_lines) and not any(("," in ln) for ln in raw_lines)

    parsed = []
    if use_pipe:
        for ln in raw_lines:
            parsed.append([c.strip() for c in ln.split("|")])
    else:
        reader = csv.reader(io.StringIO(stdout))
        for r in reader:
            if any(c.strip() for c in r):
                parsed.append([c.strip() for c in r])

    data = []
    for parts in parsed:
        low = [p.strip().lower() for p in parts]
        if low[: len(columns)] == columns:
            continue
        if len(parts) < len(columns):
            continue
        rec = dict(zip(columns, parts[: len(columns)]))
        data.append(rec)

    def empty(v):
        return v is None or str(v).strip() == "" or str(v).strip().upper() == "NULL"

    if data:
        m = data[0]
        sku = m.get("product_sku", "")
        rpath = m.get("record_path", "")
        pname = m.get("product_name", "")
        stype = m.get("sealant_type", "")
        wifi = m.get("wifi_capability", "")
        refs = [rpath] if not empty(rpath) else []
        if not empty(wifi):
            message = (
                "<YES> The base product " + pname + " (SKU " + sku + ") in the Sika Weatherproof "
                "Sikaflex 1JG-02A Sealant line has sealant_type '" + stype + "' and DOES expose a "
                "wifi-enabled capability on the catalogue record (" + wifi + "). Checked SKU: " + sku + "."
            )
        else:
            message = (
                "<NO> The base product exists \u2014 " + pname + " (SKU " + sku + ") in the Sika "
                "Weatherproof Sikaflex 1JG-02A Sealant line has sealant_type '" + stype + "', but no "
                "wifi-enabled capability is present on the catalogue record. Checked SKU: " + sku + "."
            )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
    else:
        message = (
            "<NO> No base product variant with sealant_type '" + str(sealant_type) + "' was found in the "
            "Sika Weatherproof Sikaflex 1JG-02A Sealant line, so no wifi-enabled capability could be "
            "confirmed."
        )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=[])
