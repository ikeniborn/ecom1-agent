def run(vm, params):
    sql = (
        "SELECT v.product_sku, v.record_path, v.product_name, v.brand, "
        "v.series, v.model, k.product_kind_name, "
        "mt.property_value_text AS machine_type, "
        "volt.property_value_number AS voltage_v, "
        "pw.property_value_number AS power_w "
        "FROM product_variants v "
        "JOIN product_kinds k ON k.product_kind_id = v.product_kind_id "
        "LEFT JOIN product_variant_properties mt ON mt.product_sku = v.product_sku AND mt.property_key = 'machine_type' "
        "LEFT JOIN product_variant_properties volt ON volt.product_sku = v.product_sku AND volt.property_key = 'voltage_v' "
        "LEFT JOIN product_variant_properties pw ON pw.product_sku = v.product_sku AND pw.property_key = 'power_w' "
        "WHERE v.brand = 'Holzmann' AND v.series = 'Compact' AND v.model = 'D 327-RR0' "
        "AND k.product_kind_name = 'Compressor and Dust Extractor' "
        "AND mt.property_value_text = 'compressor' "
        "AND volt.property_value_number = 230 "
        "AND pw.property_value_number = 3000;"
    )
    match = vm.exec(path="/bin/sql", stdin=sql)
    stdout = getattr(match, "stdout", "") or (match.get("stdout", "") if isinstance(match, dict) else "")

    def split_row(line):
        if "|" in line:
            return [c.strip() for c in line.split("|")]
        return [c.strip() for c in line.split(",")]

    record_path = None
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    if lines:
        header = split_row(lines[0])
        idx = 1
        data_lines = lines
        if "record_path" in header:
            idx = header.index("record_path")
            data_lines = lines[1:]
        for line in data_lines:
            fields = split_row(line)
            if len(fields) > idx and fields[idx]:
                record_path = fields[idx]
                break

    found = record_path is not None and record_path != ""
    refs = [record_path] if found else []

    if found:
        message = (
            "<YES> The Holzmann Compact D 327-RR0 Compressor and Dust Extractor "
            "(machine type compressor, 230 V, 3000 W) is in the catalogue: " + record_path
        )
    else:
        message = (
            "<NO> The Holzmann Compact D 327-RR0 Compressor and Dust Extractor "
            "(machine type compressor, 230 V, 3000 W) is not in the catalogue."
        )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
