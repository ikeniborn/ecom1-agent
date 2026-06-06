def run(vm, params):
    brand = str(params["brand"])
    kind = str(params["kind"])
    line = str(params["line"])
    diameter_mm = str(params["diameter_mm"])

    def esc(v):
        return v.replace("'", "''")

    sql = (
        "SELECT v.product_sku, v.record_path, v.product_name, v.price_cents, v.price_currency "
        "FROM product_variants v "
        "JOIN product_families f ON f.product_family_id = v.product_family_id "
        "JOIN product_variant_properties p ON p.product_sku = v.product_sku "
        "WHERE v.brand = '" + esc(brand) + "' "
        "AND v.product_kind_id = '" + esc(kind) + "' "
        "AND f.product_family_name = '" + esc(line) + "' "
        "AND p.property_key = 'disc_diameter_mm' "
        "AND p.property_value_number = " + esc(diameter_mm) + ";"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    class Row:
        def __init__(self, sku, record_path, product_name, price_cents, price_currency):
            self.product_sku = sku
            self.record_path = record_path
            self.product_name = product_name
            self.price_cents = price_cents
            self.price_currency = price_currency

    match = []
    header_tokens = {"product_sku", "record_path", "product_name", "price_cents", "price_currency"}
    for raw in stdout.splitlines():
        line_str = raw.strip()
        if not line_str:
            continue
        cols = [c.strip() for c in line_str.split(",")]
        if cols and cols[0] in header_tokens:
            continue
        if len(cols) < 5:
            continue
        match.append(Row(cols[0], cols[1], cols[2], cols[3], cols[4]))

    if match:
        message = (
            "<YES> Ryobi 'Ryobi Precision ONE 21I-JSQ Corded Angle Grinder' Corded Angle Grinder "
            "with disc diameter 115 mm is in catalogue: "
            + match[0].product_name + " (" + match[0].product_sku + ") at " + match[0].record_path
        )
        refs = [match[0].record_path]
    else:
        message = (
            "<NO> Ryobi 'Ryobi Precision ONE 21I-JSQ Corded Angle Grinder' Corded Angle Grinder "
            "with disc diameter 115 mm not found in catalogue."
        )
        refs = []

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
