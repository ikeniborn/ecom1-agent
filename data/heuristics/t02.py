def run(vm, params):
    brand = params["brand"]
    series = params["series"]
    model = params["model"]
    tool_type = params["tool_type"]

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    sql = (
        "SELECT pv.product_sku, pv.product_name, pv.record_path "
        "FROM product_variants pv "
        "JOIN product_variant_properties pvp "
        "ON pvp.product_sku = pv.product_sku "
        "AND pvp.property_key = 'tool_type' "
        "AND pvp.property_value_text = " + q(tool_type) + " "
        "WHERE pv.brand = " + q(brand) + " "
        "AND pv.series = " + q(series) + " "
        "AND pv.model = " + q(model) + " "
        "AND pv.product_name LIKE '%Hammer Measuring and Cutting Tool%';"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "")
    if not stdout and isinstance(result, dict):
        stdout = result.get("stdout", "")
    stdout = stdout or ""

    rows = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        delim = "," if "," in line else ("|" if "|" in line else ",")
        fields = [f.strip() for f in line.split(delim)]
        if len(fields) < 3:
            continue
        if fields[0] == "product_sku" and fields[-1] == "record_path":
            continue
        sku = fields[0]
        path = fields[-1]
        name = delim.join(fields[1:-1]).strip()
        rows.append({"product_sku": sku, "product_name": name, "record_path": path})

    match = rows[0] if rows else None

    if match:
        message = (
            "<YES> Found " + match["product_name"] + " (" + match["product_sku"]
            + ") at " + match["record_path"]
            + " \u2014 in the Bahco Workshop BAH 3VZ-SPH Hammer Measuring and Cutting Tool line with tool_type measuring tape."
        )
        refs = [match["record_path"]]
    else:
        message = "<NO> No Bahco Workshop BAH 3VZ-SPH Hammer Measuring and Cutting Tool with tool_type measuring tape exists in catalog."
        refs = []

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
