def run(vm, params):
    kind_name = params["kind_name"]
    safe_kind = str(kind_name).replace("'", "''")
    sql = (
        "SELECT COUNT(*) AS cnt FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = '" + safe_kind + "';"
    )
    count_result = vm.exec(path="/bin/sql", args=[], stdin=sql)
    stdout = getattr(count_result, "stdout", "") or (count_result.get("stdout", "") if isinstance(count_result, dict) else "")

    cnt = 0
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        token = ln.split("|")[-1].strip()
        digits = "".join(ch for ch in token if (ch.isdigit() or ch == "-"))
        if digits and digits.lstrip("-").isdigit():
            cnt = int(digits)
            break

    message = "<COUNT:%d>" % cnt
    refs = []
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
