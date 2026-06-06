def run(vm, params):
    kind_name = params["kind_name"]
    kind_literal = str(kind_name).replace("'", "''")
    sql = (
        "SELECT COUNT(*) AS cnt FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = '" + kind_literal + "';"
    )
    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")
    nbw_count = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        cells = [c.strip() for c in line.split("|")] if "|" in line else [line]
        for c in cells:
            if c.lstrip("-").isdigit():
                nbw_count = int(c)
                break
        if nbw_count is not None:
            break
    if nbw_count is None:
        nbw_count = 0
    message = "{}".format(nbw_count)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=["/proc/catalog"])
