def run(vm, params):
    def get_stdout(result):
        out = getattr(result, "stdout", None)
        if out is not None:
            return out
        if isinstance(result, dict):
            return result.get("stdout", "") or ""
        return ""

    def parse_rows(stdout):
        lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
        if not lines:
            return [], []
        header = [h.strip() for h in lines[0].split(",")]
        rows = []
        for ln in lines[1:]:
            rows.append([c.strip() for c in ln.split(",")])
        return header, rows

    kind_name = params["kind_name"]
    kind_literal = "'" + str(kind_name).replace("'", "''") + "'"

    # discovery: matched product variants (capture record_path for runtime refs)
    discovery_sql = (
        "SELECT pv.product_sku, pv.record_path "
        "FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = " + kind_literal + " "
        "ORDER BY pv.product_sku;"
    )
    matched_variants = vm.exec(path="/bin/sql", args=[], stdin=discovery_sql)
    m_header, m_rows = parse_rows(get_stdout(matched_variants))

    matched_variants_record_paths = []
    if m_header and "record_path" in m_header:
        idx = m_header.index("record_path")
        for row in m_rows:
            if len(row) > idx and row[idx]:
                matched_variants_record_paths.append(row[idx])

    # ops: count of matched variants
    count_sql = (
        "SELECT COUNT(*) AS product_count "
        "FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = " + kind_literal + ";"
    )
    count_row = vm.exec(path="/bin/sql", args=[], stdin=count_sql)
    c_header, c_rows = parse_rows(get_stdout(count_row))

    product_count = ""
    if c_header and "product_count" in c_header and c_rows:
        cidx = c_header.index("product_count")
        first = c_rows[0]
        if len(first) > cidx:
            product_count = first[cidx]

    if product_count == "":
        product_count = str(len(matched_variants_record_paths))

    message = "%s" % product_count
    vm.answer(message=message, outcome="OUTCOME_OK", refs=matched_variants_record_paths)
