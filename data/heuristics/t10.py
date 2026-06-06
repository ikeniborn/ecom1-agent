def run(vm, params):
    kind = params["kind"]
    kind_lit = "'" + str(kind).replace("'", "''") + "'"

    # --- discovery ---
    disc_sql = (
        "SELECT product_kind_id, product_kind_name FROM product_kinds "
        "WHERE product_kind_name = " + kind_lit + ";"
    )
    kind_match = vm.exec(path="/bin/sql", args=[disc_sql])

    # --- ops ---
    count_sql = (
        "SELECT COUNT(*) AS n FROM product_variants v "
        "JOIN product_kinds k ON v.product_kind_id = k.product_kind_id "
        "WHERE k.product_kind_name = " + kind_lit + ";"
    )
    count_row = vm.exec(path="/bin/sql", args=[count_sql])

    stdout = getattr(count_row, "stdout", "") or (
        count_row.get("stdout", "") if isinstance(count_row, dict) else ""
    )

    # parse the integer count out of the result rows
    n = "0"
    for ln in stdout.splitlines():
        s = ln.strip()
        if not s:
            continue
        cell = s.split("|")[-1].strip() if "|" in s else s
        if cell.lstrip("-").isdigit():
            n = cell

    # --- refs ---
    slug = "".join(c if (c.isalnum() or c == " ") else " " for c in str(kind)).lower()
    slug = "-".join(slug.split())
    doc_ref = "/docs/current-updates/catalogue-counting-2026-06-06-" + slug + ".md"
    refs = ["/proc/catalog", doc_ref]

    message = "%s" % n
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
