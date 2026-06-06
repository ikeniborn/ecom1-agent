def run(vm, params):
    kind_name = params["kind_name"]
    safe_kind = str(kind_name).replace("'", "''")
    sql = (
        "SELECT COUNT(*) AS product_count "
        "FROM product_variants v "
        "JOIN product_kinds k ON v.product_kind_id = k.product_kind_id "
        "WHERE k.product_kind_name = '" + safe_kind + "';"
    )
    count_result = vm.exec(path="/bin/sql", args=[], stdin=sql)
    stdout = getattr(count_result, "stdout", "") or (count_result.get("stdout", "") if isinstance(count_result, dict) else "")

    product_count = 0
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        cell = ln.split("|")[-1].strip() if "|" in ln else ln.strip()
        try:
            product_count = int(cell)
            break
        except ValueError:
            digits = "".join(ch for ch in cell if ch.isdigit())
            if digits:
                product_count = int(digits)
                break

    message = "<COUNT:%d>" % product_count
    vm.answer(message=message, outcome="OUTCOME_OK", refs=["/proc/catalog"])
