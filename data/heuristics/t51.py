import re

def run(vm, params):
    def fld(o, k, d=""):
        if isinstance(o, dict):
            return o.get(k, d)
        return getattr(o, k, d)

    TR = str.maketrans({"O": "0", "I": "1", "S": "5", "B": "8", "Z": "2"})
    def canon(s):
        return s.upper().translate(TR)

    # discovery 1: List /uploads/ (normalize list vs wrapper-dict)
    listing = vm.list(path="/uploads/")
    if isinstance(listing, list):
        entries = listing
    elif isinstance(listing, dict):
        entries = listing.get("entries") or listing.get("items") or listing.get("files") or []
    else:
        entries = []

    receipt_path = ""
    for e in entries:
        if isinstance(e, str):
            name, path, kind = e, "", ""
        else:
            name = fld(e, "name", "")
            path = fld(e, "path", "")
            kind = fld(e, "kind", "")
        full = path or ("/uploads/" + name)
        ku = str(kind).upper()
        is_file = ("FILE" in ku) or ("." in name)
        if is_file and "DIR" not in ku:
            receipt_path = full
            break
    if not receipt_path and entries:
        e0 = entries[0]
        if isinstance(e0, str):
            receipt_path = "/uploads/" + e0
        else:
            receipt_path = fld(e0, "path", "") or ("/uploads/" + fld(e0, "name", ""))

    # discovery 2: Read the resolved receipt FILE (never a directory)
    content = ""
    try:
        receipt = vm.read(path=receipt_path, number=True)
        content = fld(receipt, "content", "") or fld(receipt, "text", "")
    except Exception:
        content = ""

    lines = content.splitlines()
    items = []
    old_ex = 0.0
    sub_found = False
    SKIP = ("TERM", "POS", "REF", "VAT", "TAX", "CHG", "TOT", "SUB")
    for raw in lines:
        l = re.sub(r'^\s*\d+\s*[\t:|\u2502]\s*', '', raw)
        u = l.upper()
        if not sub_found and re.search(r'SUB\s*T[O0]TAL', u):
            nums = re.findall(r'\d+[.,]\d{2}', l)
            if nums:
                old_ex = float(nums[-1].replace(",", "."))
                sub_found = True
        m = re.search(r'[A-Z0-9]{3}-[A-Z0-9]+', u)
        if not m:
            continue
        sku = m.group(0)
        if sku.split("-")[0] in SKIP:
            continue
        qm = re.match(r'\s*(\d+)\b', l)
        qty = int(qm.group(1)) if qm else 1
        items.append((qty, sku))

    # discovery 3: catalogue lookup via inline single-quoted SKU literals (raw + canonical)
    lits = set()
    for _, sku in items:
        lits.add(sku.replace("'", "''"))
        lits.add(canon(sku).replace("'", "''"))
    in_list = ",".join("'" + s + "'" for s in sorted(lits)) or "''"
    sql = ("SELECT product_sku, record_path, price_cents, price_currency "
           "FROM product_variants WHERE product_sku IN (" + in_list + ");")
    out = ""
    try:
        res = vm.exec(path="/bin/sql", args=[sql])
        out = fld(res, "stdout", "")
    except Exception:
        out = ""

    price_map = {}
    rows = [r for r in out.splitlines() if r.strip()]
    if rows:
        if "product_sku" in rows[0].lower():
            hdr = rows[0]
            delim = "," if "," in hdr else ("|" if "|" in hdr else "\t")
            cols = [c.strip().lower() for c in hdr.split(delim)]
            si = cols.index("product_sku") if "product_sku" in cols else 0
            pi = cols.index("price_cents") if "price_cents" in cols else 2
            data = rows[1:]
        else:
            delim = "," if "," in rows[0] else ("|" if "|" in rows[0] else "\t")
            si, pi = 0, 2
            data = rows
        for r in data:
            p = r.split(delim)
            if len(p) <= max(si, pi):
                continue
            try:
                price_map[canon(p[si].strip())] = int(float(p[pi].strip()))
            except Exception:
                continue

    # compute today_ex: every line item; discontinued SKU contributes 0
    today_ex = 0.0
    for qty, sku in items:
        cents = price_map.get(canon(sku))
        if cents is not None:
            today_ex += qty * cents / 100.0

    threshold = params.get("diff_threshold_eur", 2)
    try:
        threshold = float(threshold)
    except Exception:
        threshold = 2.0
    diff = abs(today_ex - old_ex)
    within = diff <= threshold
    if (old_ex == 0 and today_ex == 0) or not items:
        within = False
    yes_no = "YES" if within else "NO"
    within_or_over = "within" if within else "over"
    thr_txt = str(int(threshold)) if float(threshold).is_integer() else str(threshold)

    msg = ("<" + yes_no + "> Old receipt ex-VAT subtotal = " + str(round(old_ex, 2)) +
           " EUR; selling same line items at today's catalogue prices = " + str(round(today_ex, 2)) +
           " EUR (discontinued SKUs counted as 0). Difference = " + str(round(diff, 2)) +
           " EUR, which is " + within_or_over + " the " + thr_txt + " EUR threshold.")

    refs = [receipt_path] if receipt_path else []
    vm.answer(message=msg, outcome="OUTCOME_OK", refs=refs)
