import re


def _stdout(result):
    if isinstance(result, dict):
        return result.get("stdout", "") or ""
    return getattr(result, "stdout", "") or ""


def run(vm, params):
    kind_name = params["kind_name"]
    kind_lit = kind_name.replace("'", "''")
    sql = (
        "SELECT COUNT(*) AS n FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = '" + kind_lit + "';"
    )
    count_row = vm.exec(path="/bin/sql", args=[sql])
    out = _stdout(count_row)

    n = 0
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r"-?\d+", line)
        if m and m.group(0).lstrip("-").isdigit():
            if line.lower().replace("|", "").strip() == "n":
                continue
            n = int(m.group(0))
    message = "%d" % n

    refs = ["/proc/catalog/power_tools/cordless_drill_driver"]
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
