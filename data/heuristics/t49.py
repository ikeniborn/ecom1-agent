def run(vm, params):
    category = params["category"]

    def get_stdout(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    # --- discovery ---
    schema = vm.exec(
        path="/bin/sql",
        args=[],
        stdin="SELECT name, sql FROM sqlite_schema WHERE type='table' AND name='product_variants';",
    )
    codex_tool = vm.find(root="/bin", name="codex", kind="file", limit=1)

    # /bin/sql does not resolve :name binds reliably; inline as a quoted literal.
    cat_lit = str(category).replace("'", "''")

    # --- ops ---
    rows = vm.exec(
        path="/bin/sql",
        args=[],
        stdin="SELECT record_path FROM product_variants WHERE category = '%s';" % cat_lit,
    )
    count = vm.exec(
        path="/bin/sql",
        args=[],
        stdin="SELECT COUNT(*) AS qty FROM product_variants WHERE category = '%s';" % cat_lit,
    )

    # --- parse record paths ---
    rows_out = get_stdout(rows)
    record_paths = []
    seen = set()
    for ln in rows_out.splitlines():
        for cell in ln.split("|"):
            c = cell.strip()
            if c.startswith("/") and c not in seen:
                seen.add(c)
                record_paths.append(c)

    # --- parse scalar aggregate (guaranteed single data row) ---
    count_out = get_stdout(count)
    qty = None
    for ln in count_out.splitlines():
        for cell in ln.split("|"):
            c = cell.strip()
            if c.isdigit():
                qty = int(c)
                break
        if qty is not None:
            break
    if qty is None:
        qty = len(record_paths)

    # --- refs: static literal + every counted product's record_path ---
    refs = ["/proc/catalog"]
    refs.extend(record_paths)

    message = "<QTY: %d>" % qty
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
