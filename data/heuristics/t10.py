def run(vm, params):
    kind_name = params["kind_name"]
    safe_kind = kind_name.replace("'", "''")
    sql = (
        "SELECT COUNT(*) AS product_count "
        "FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = '" + safe_kind + "';"
    )
    result = vm.exec(path="/bin/sql", args=[], stdin=sql)
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")
    count = 0
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        token = ln.split("|")[0].strip()
        if token.lstrip("-").isdigit():
            count = int(token)
            break
    message = "<COUNT:%d>" % count
    vm.answer(message=message, outcome="OUTCOME_OK", refs=[])
