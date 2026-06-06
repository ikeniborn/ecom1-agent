def run(vm, params):
    kind_name = params["kind_name"]
    escaped = str(kind_name).replace("'", "''")

    def get_stdout(result):
        if isinstance(result, dict):
            return result.get("stdout", "") or ""
        return getattr(result, "stdout", "") or ""

    def parse_rows(out):
        rows = []
        for raw in out.splitlines():
            line = raw.strip()
            if not line:
                continue
            if "|" in line:
                cols = [c.strip() for c in line.split("|")]
            else:
                cols = [c.strip() for c in line.split(",")]
            # skip header row
            if cols and ("record_path" in cols or "product_sku" in cols):
                continue
            rows.append(cols)
        return rows

    # discovery: confirm the product kind exists
    disc_sql = (
        "SELECT product_kind_id, product_kind_name FROM product_kinds "
        "WHERE product_kind_name = '" + escaped + "';"
    )
    matched_kinds = vm.exec(path="/bin/sql", args=[disc_sql])
    _ = get_stdout(matched_kinds)

    # ops: list every variant of that kind with its record_path
    ops_sql = (
        "SELECT pv.product_sku, pv.record_path FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = '" + escaped + "' ORDER BY pv.product_sku;"
    )
    matched_products = vm.exec(path="/bin/sql", args=[ops_sql])
    out = get_stdout(matched_products)

    rows = parse_rows(out)
    record_paths = [cols[1] for cols in rows if len(cols) >= 2 and cols[1]]
    count = len(record_paths)

    message = str(count)

    refs = ["/proc/catalog"]
    refs.extend(record_paths)

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
