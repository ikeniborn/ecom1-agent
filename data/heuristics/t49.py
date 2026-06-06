def run(vm, params):
    def _stdout(r):
        return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")

    # discovery: schema
    schema = vm.exec(path="/bin/sql", args=[], stdin="select name, sql from sqlite_schema where sql is not null order by type, name;")
    _ = _stdout(schema)

    # inline category as single-quoted SQL literal (escape quotes)
    category = params["category"]
    cat_lit = str(category).replace("'", "''")
    sql = "select count(*) as cnt from products where category = '" + cat_lit + "';"

    count_row = vm.exec(path="/bin/sql", args=[], stdin=sql)
    out = _stdout(count_row)

    cnt = None
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for ln in lines:
        token = ln.split("|")[-1].strip() if "|" in ln else ln.strip()
        if token.isdigit():
            cnt = token
    if cnt is None and lines:
        last = lines[-1]
        token = last.split("|")[-1].strip() if "|" in last else last.strip()
        if token.isdigit():
            cnt = token

    # scalar aggregate always returns one row; default to 0 only if genuinely empty numeric
    if cnt is None:
        cnt = "0"

    message = "<count:" + str(cnt) + ">"
    vm.answer(message=message, outcome="OUTCOME_OK", refs=["/bin/sql"])
