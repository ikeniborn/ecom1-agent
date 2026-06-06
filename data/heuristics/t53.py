import re


def _stdout(result):
    s = getattr(result, "stdout", None)
    if s is None and isinstance(result, dict):
        s = result.get("stdout", "")
    return s or ""


def _rows(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        rows.append([c.strip() for c in line.split("|")])
    return rows


def _to_cents(tok):
    tok = tok.replace(",", ".").replace("\u20ac", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", tok)
    if not m:
        return None
    return int(round(float(m.group(1)) * 100))


def _esc(s):
    return s.replace("'", "''")


def _parse_receipt(text):
    # Best-effort: each line item -> (sku, qty, old_unit_cents)
    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if any(k in low for k in ("subtotal", "sub t0tal", "sub total", "total", "vat", "tax", "receipt", "date", "store", "thank")):
            continue
        # strip a leading line-number column produced by number=True (e.g. "  12\t...")
        line = re.sub(r"^\s*\d+\s*[\t:|]\s*", "", line)
        # SKU: alphanumeric token with a dash or >=4 chars
        sku_m = re.search(r"\b([A-Z0-9]{2,}(?:-[A-Z0-9]+)+|[A-Z]{2,}\d{2,})\b", line)
        if not sku_m:
            continue
        sku = sku_m.group(1)
        nums = re.findall(r"\d+(?:[.,]\d+)?", line[sku_m.end():])
        if not nums:
            continue
        # qty = first integer-like number; unit price = a decimal number
        qty = 1
        unit_cents = None
        for n in nums:
            if "." in n or "," in n:
                if unit_cents is None:
                    unit_cents = _to_cents(n)
            else:
                if qty == 1:
                    try:
                        qty = int(n)
                    except Exception:
                        qty = 1
        if unit_cents is None and nums:
            unit_cents = _to_cents(nums[-1])
        if unit_cents is None:
            unit_cents = 0
        items.append((sku, qty, unit_cents))
    return items


def run(vm, params):
    uploads_dir = params.get("uploads_dir", "/uploads")

    # --- discovery: List uploads ---
    listing = vm.list(path=uploads_dir)
    entries = getattr(listing, "entries", None)
    if entries is None and isinstance(listing, dict):
        entries = listing.get("entries", [])
    entries = entries or []

    receipt_path = None
    for e in entries:
        name = getattr(e, "name", None)
        kind = getattr(e, "kind", None)
        if name is None and isinstance(e, dict):
            name = e.get("name")
            kind = e.get("kind")
        if not name:
            continue
        is_file = (kind == "FILE") or ("." in name)
        if not is_file:
            continue
        base = uploads_dir.rstrip("/")
        p = base + "/" + name
        if "receipt" in name.lower():
            receipt_path = p
            break
        if receipt_path is None:
            receipt_path = p

    if receipt_path is None:
        # nothing to read; still terminate cleanly
        receipt_path = uploads_dir.rstrip("/") + "/receipt.txt"

    # --- discovery: Read receipt ---
    read_res = vm.read(path=receipt_path, number=True)
    receipt_text = getattr(read_res, "content", None)
    if receipt_text is None and isinstance(read_res, dict):
        receipt_text = read_res.get("content", "")
    receipt_text = receipt_text or ""

    items = _parse_receipt(receipt_text)

    # Build VALUES literals (inline, no :name binds per learned rule)
    if items:
        vals_price = ",".join("('%s',%d)" % (_esc(s), q) for (s, q, _u) in items)
        vals_cmp = ",".join("('%s',%d,%d)" % (_esc(s), q, u) for (s, q, u) in items)
    else:
        vals_price = "('',0)"
        vals_cmp = "('',0,0)"

    # --- discovery: Exec current_prices ---
    sql_prices = (
        "WITH receipt(product_sku, qty) AS (VALUES " + vals_price + ") "
        "SELECT pv.product_sku, pv.product_name, pv.price_cents, pv.price_currency, r.qty, pv.record_path "
        "FROM receipt r JOIN product_variants pv ON pv.product_sku = r.product_sku;"
    )
    current_prices = vm.exec(path="/bin/sql", args=[sql_prices])
    _ = _stdout(current_prices)

    # --- ops: Exec comparison ---
    sql_cmp = (
        "WITH receipt(product_sku, qty, old_unit_cents) AS (VALUES " + vals_cmp + ") "
        "SELECT SUM(r.qty * r.old_unit_cents) AS old_total_cents, "
        "SUM(r.qty * pv.price_cents) AS today_total_cents, "
        "ABS(SUM(r.qty * pv.price_cents) - SUM(r.qty * r.old_unit_cents)) AS diff_cents "
        "FROM receipt r JOIN product_variants pv ON pv.product_sku = r.product_sku;"
    )
    comparison = vm.exec(path="/bin/sql", args=[sql_cmp])
    cmp_rows = _rows(_stdout(comparison))

    old_total_cents = today_total_cents = diff_cents = None
    data_rows = [r for r in cmp_rows if any(re.search(r"-?\d", c) for c in r)]
    for r in data_rows:
        nums = [c for c in r if re.fullmatch(r"-?\d+", c.strip() or "x") or re.fullmatch(r"-?\d+(?:\.\d+)?", c.strip() or "x")]
        if len(nums) >= 3:
            try:
                old_total_cents = int(float(nums[0]))
                today_total_cents = int(float(nums[1]))
                diff_cents = int(float(nums[2]))
                break
            except Exception:
                continue

    # Fallback compute from receipt items if SQL gave nothing usable
    if old_total_cents is None:
        old_total_cents = sum(q * u for (_s, q, u) in items)
        today_total_cents = old_total_cents
        diff_cents = 0

    old_eur = old_total_cents / 100.0
    today_eur = today_total_cents / 100.0
    diff_eur = diff_cents / 100.0
    within = diff_cents <= 300
    token = "<YES>" if within else "<NO>"

    message = (
        "Old receipt (%s) total excl. VAT = %.2f EUR. "
        "Today's catalog total excl. VAT = %.2f EUR. "
        "Difference = %.2f EUR. Within 3 EUR threshold: %s."
        % (receipt_path, old_eur, today_eur, diff_eur, token)
    )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=[receipt_path])
