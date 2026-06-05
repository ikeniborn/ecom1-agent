def run(vm, params):
    brand = params['brand']
    series = params['series']
    model = params['model']
    screw_type = params['screw_type']
    diameter_mm = str(params['diameter_mm'])

    def esc(s):
        return str(s).replace("'", "''")

    sql = (
        "SELECT pv.product_sku, pv.record_path, pv.product_name, pv.brand, pv.series, pv.model, "
        "pt.property_value_text AS screw_type, pd.property_value_number AS diameter_mm "
        "FROM product_variants pv "
        "LEFT JOIN product_variant_properties pt ON pt.product_sku = pv.product_sku AND pt.property_key = 'screw_type' "
        "LEFT JOIN product_variant_properties pd ON pd.product_sku = pv.product_sku AND pd.property_key = 'diameter_mm' "
        "WHERE LOWER(pv.brand) = LOWER('" + esc(brand) + "') "
        "AND LOWER(pv.series) = LOWER('" + esc(series) + "');"
    )

    result = vm.exec(path='/bin/sql', args=[sql])
    stdout = getattr(result, 'stdout', '') or (result.get('stdout', '') if isinstance(result, dict) else '')

    rows = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('|')
        if len(parts) < 6:
            continue
        rows.append(parts)

    match = None
    in_scope_refs = []
    for r in rows:
        sku, record_path, pname, b, s, m = r[0], r[1], r[2], r[3], r[4], r[5]
        st = r[6] if len(r) > 6 else ''
        dm = r[7] if len(r) > 7 else ''
        if record_path and record_path not in in_scope_refs:
            in_scope_refs.append(record_path)
        if (m.strip().lower() == model.strip().lower()
                and st.strip().lower() == screw_type.strip().lower()):
            try:
                if float(dm) == float(diameter_mm):
                    match = record_path
                    break
            except (ValueError, TypeError):
                if dm.strip() == diameter_mm.strip():
                    match = record_path
                    break

    if match:
        message = '<YES> Heco Zinc Plated TopFix GTU-YPJ wood screw 6mm in catalogue at ' + match + '.'
        refs = [match]
    else:
        message = '<NO> Not in catalogue.'
        refs = in_scope_refs

    vm.answer(message=message, outcome='OUTCOME_OK', refs=refs)
