def run(vm, params):
    brand = params["brand"]
    model = params["model"]
    machine_type = params["machine_type"]
    voltage_v = str(params["voltage_v"])
    power_w = str(params["power_w"])
    capability_key = params["capability_key"]

    def lit(v):
        return "'" + str(v).replace("'", "''") + "'"

    # AGENTS.md: inventory lives only in SQL projections -> query via /bin/sql.
    # Learned: /bin/sql ignores :name bindings; inline values as quoted literals.
    # Learned: resolve base by brand/model identity (no numeric CAST property
    # filters that silently drop rows) so record_path is always populated.
    sql = (
        "SELECT v.product_sku, v.record_path, v.product_name, "
        "(SELECT COUNT(*) FROM product_variant_properties cap "
        "WHERE cap.product_sku = v.product_sku "
        "AND cap.property_key = " + lit(capability_key) + ") AS has_voice_control "
        "FROM product_variants v "
        "WHERE v.brand = " + lit(brand) + " AND v.model = " + lit(model) + ";"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "")
    if not stdout and isinstance(result, dict):
        stdout = result.get("stdout", "")
    stdout = stdout or ""

    cols = ["product_sku", "record_path", "product_name", "has_voice_control"]
    rows = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line and "," not in line:
            parts = [p.strip() for p in line.split("|")]
        else:
            parts = [p.strip() for p in line.split(",")]
        # skip header line
        if [p.lower() for p in parts] == cols:
            continue
        rows.append(parts)

    match = None
    if rows:
        parts = rows[0]
        rec = {}
        for i, name in enumerate(cols):
            rec[name] = parts[i] if i < len(parts) else ""
        match = rec

    if not match:
        vm.answer(
            message=(
                "Base product Scheppach Workshop " + model + " Compressor "
                "(machine type " + machine_type + ", " + voltage_v + " V, "
                + power_w + " W) was not found in the catalogue projections."
            ),
            outcome="OUTCOME_OK",
            refs=[],
        )
        return

    product_sku = match["product_sku"]
    record_path = match["record_path"]
    try:
        has_vc = int(str(match["has_voice_control"]).strip() or "0")
    except ValueError:
        has_vc = 0

    if has_vc > 0:
        message = (
            "<YES> Base product Scheppach Workshop " + model + " Compressor "
            "(machine type " + machine_type + ", " + voltage_v + " V, "
            + power_w + " W) exists as SKU " + product_sku
            + " and the catalogue record supports voice_control. "
            "Checked SKU: " + product_sku + " (" + record_path + ")."
        )
    else:
        message = (
            "<NO> Base product Scheppach Workshop " + model + " Compressor "
            "(machine type " + machine_type + ", " + voltage_v + " V, "
            + power_w + " W) exists as SKU " + product_sku
            + ", but the catalogue record has no voice_control capability. "
            "Checked SKU: " + product_sku + " (" + record_path + ")."
        )

    refs = [record_path] if record_path else []
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
