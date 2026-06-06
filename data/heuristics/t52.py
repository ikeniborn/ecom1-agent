import re


def run(vm, params):
    def _get(obj, name, default=""):
        v = getattr(obj, name, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(name, None)
        return default if v is None else v

    def _stdout(res):
        return _get(res, "stdout", "") or ""

    def _list_entries(res):
        for name in ("entries", "items", "files", "names"):
            v = getattr(res, name, None)
            if v is None and isinstance(res, dict):
                v = res.get(name, None)
            if callable(v):
                continue
            if isinstance(v, (list, tuple)):
                return list(v)
        return []

    uploads_dir = params.get("uploads_dir", "/uploads")

    # --- discovery 1: List /uploads ---
    uploads_listing = vm.list(path=uploads_dir)
    entries = _list_entries(uploads_listing)

    receipt_path = None
    for e in entries:
        # entry may be a message with .path/.name/.kind or a plain string
        if isinstance(e, str):
            nm = e
            kind = ""
            pth = nm if nm.startswith("/") else uploads_dir.rstrip("/") + "/" + nm
        else:
            nm = _get(e, "name", "") or _get(e, "path", "")
            kind = str(_get(e, "kind", ""))
            pth = _get(e, "path", "") or (uploads_dir.rstrip("/") + "/" + nm)
        base = nm.rsplit("/", 1)[-1]
        is_file = ("FILE" in kind.upper()) or ("." in base)
        if not is_file:
            continue
        if receipt_path is None:
            receipt_path = pth
        if "receipt" in base.lower():
            receipt_path = pth
            break

    if receipt_path is None and entries:
        e0 = entries[0]
        if isinstance(e0, str):
            receipt_path = e0 if e0.startswith("/") else uploads_dir.rstrip("/") + "/" + e0
        else:
            receipt_path = _get(e0, "path", "") or (uploads_dir.rstrip("/") + "/" + _get(e0, "name", ""))
    if receipt_path is None:
        receipt_path = uploads_dir.rstrip("/") + "/receipt.txt"

    # --- discovery 2: Read receipt ---
    receipt = vm.read(path=receipt_path, number=True)
    receipt_text = _get(receipt, "content", "") or _get(receipt, "text", "") or ""

    # --- parse line items: SKU, qty, old unit price (cents) ---
    sku_re = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)+")
    line_items = []  # (sku, qty, old_unit_cents)
    seen = set()
    for raw in receipt_text.splitlines():
        line = re.sub(r"^\s*\d+\s*[|:]?\s*", "", raw)  # strip line-number prefix
        m = sku_re.search(line)
        if not m:
            continue
        sku = m.group(0)
        rest = line[m.end():]
        qm = re.search(r"(\d+)\s*[xX\u00d7]", rest)
        qty = int(qm.group(1)) if qm else 1
        prices = re.findall(r"\d+[.,]\d{2}", rest)
        if not prices:
            continue
        unit = prices[0].replace(",", ".")
        old_unit_cents = int(round(float(unit) * 100))
        key = (sku, qty, old_unit_cents)
        if key in seen:
            continue
        seen.add(key)
        line_items.append((sku, qty, old_unit_cents))

    skus = sorted({li[0] for li in line_items})

    def sql_lit(s):
        return "'" + str(s).replace("'", "''") + "'"

    # --- discovery 3: current prices from catalog ---
    if skus:
        in_list = ", ".join(sql_lit(s) for s in skus)
        prices_sql = (
            "SELECT product_sku, product_name, price_cents, price_currency "
            "FROM product_variants WHERE product_sku IN (" + in_list + ");"
        )
    else:
        prices_sql = (
            "SELECT product_sku, product_name, price_cents, price_currency "
            "FROM product_variants WHERE 1=0;"
        )
    current_prices = vm.exec(path="/bin/sql", args=[prices_sql], stdin=prices_sql)

    # --- ops: comparison via inlined VALUES ---
    old_total_cents = 0
    new_total_cents = 0
    diff_cents = 0
    within = False
    if line_items:
        values = ", ".join(
            "(" + sql_lit(sku) + ", " + str(qty) + ", " + str(oc) + ")"
            for (sku, qty, oc) in line_items
        )
        comp_sql = (
            "WITH receipt(product_sku, qty, old_unit_cents) AS (VALUES " + values + "), "
            "today AS (SELECT r.product_sku, r.qty, r.old_unit_cents, "
            "COALESCE(v.price_cents, 0) AS new_unit_cents "
            "FROM receipt r LEFT JOIN product_variants v ON v.product_sku = r.product_sku) "
            "SELECT SUM(qty*old_unit_cents) AS old_total_cents, "
            "SUM(qty*new_unit_cents) AS new_total_cents, "
            "SUM(qty*new_unit_cents) - SUM(qty*old_unit_cents) AS diff_cents, "
            "CASE WHEN ABS(SUM(qty*new_unit_cents) - SUM(qty*old_unit_cents)) <= 100 "
            "THEN 1 ELSE 0 END AS within_one_eur FROM today;"
        )
        comparison = vm.exec(path="/bin/sql", args=[comp_sql], stdin=comp_sql)
        out = _stdout(comparison).strip()
        rows = [ln for ln in out.splitlines() if ln.strip()]
        data_row = rows[-1] if rows else ""
        cells = [c.strip() for c in re.split(r"[|\t]", data_row) if c.strip() != ""]
        nums = []
        for c in cells:
            try:
                nums.append(int(float(c)))
            except ValueError:
                pass
        if len(nums) >= 4:
            old_total_cents, new_total_cents, diff_cents, w = nums[0], nums[1], nums[2], nums[3]
            within = bool(w)
        elif len(nums) >= 3:
            old_total_cents, new_total_cents, diff_cents = nums[0], nums[1], nums[2]
            within = abs(diff_cents) <= 100
    else:
        comp_sql = "SELECT 0 AS old_total_cents, 0 AS new_total_cents, 0 AS diff_cents, 1 AS within_one_eur;"
        comparison = vm.exec(path="/bin/sql", args=[comp_sql], stdin=comp_sql)
        within = True

    old_eur = old_total_cents / 100.0
    new_eur = new_total_cents / 100.0
    diff_eur = diff_cents / 100.0
    token = "<YES>" if within else "<NO>"

    message = (
        "Old receipt " + receipt_path + " total (excl VAT) = " + ("%.2f" % old_eur) + " EUR; "
        "today's catalog total (excl VAT) = " + ("%.2f" % new_eur) + " EUR; "
        "difference = " + ("%.2f" % diff_eur) + " EUR. Within 1 EUR: " + token + "."
    )

    refs = [receipt_path, "/proc/catalog"]
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
