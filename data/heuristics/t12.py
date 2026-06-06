import re


def run(vm, params):
    product_kind_name = params["product_kind_name"]

    # Plan SQL uses a :product_kind_name bind placeholder. The /bin/sql runtime
    # does NOT accept :name bind args (returns exit_code 1, zero rows), so inline
    # the param value as a properly-escaped single-quoted SQL string literal.
    sql_template = (
        "SELECT COUNT(*) AS product_count "
        "FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = :product_kind_name"
    )
    literal = "'" + str(product_kind_name).replace("'", "''") + "'"
    sql = sql_template.replace(":product_kind_name", literal)

    # discovery: count product variants joined to product kinds
    count_result = vm.exec(path="/bin/sql", args=[sql])

    stdout = getattr(count_result, "stdout", "") or (
        count_result.get("stdout", "") if isinstance(count_result, dict) else ""
    )

    # parse the bare integer count from pipe-delimited stdout (last integer wins;
    # the header alias 'product_count' contains no digits)
    count = 0
    nums = re.findall(r"-?\d+", stdout or "")
    if nums:
        count = int(nums[-1])

    # refs: start from any file/document paths embedded in the planned RPC stdout
    # (learned rule r003), then add the static answer_template refs.
    refs = []
    for path in re.findall(r"/[A-Za-z0-9._\-/]+\.[A-Za-z0-9]+", stdout or ""):
        if path not in refs:
            refs.append(path)
    for static_ref in ["/proc/catalog"]:
        if static_ref not in refs:
            refs.append(static_ref)

    message = "%d" % count
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
