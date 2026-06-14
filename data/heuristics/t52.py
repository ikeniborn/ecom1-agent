def run(vm, params):
    import re

    if not isinstance(params, dict):
        params = {}
    uploads_dir = params.get("uploads_dir", "/uploads/") or "/uploads/"
    try:
        threshold = float(params.get("threshold_eur", 1))
    except Exception:
        threshold = 1.0

    def canon(s):
        s = s.upper()
        m = {'O': '0', 'I': '1', 'S': '5', 'B': '8', 'Z': '2'}
        return ''.join(m.get(c, c) for c in s)

    def get_list(res, names):
        for attr in names:
            v = getattr(res, attr, None)
            if callable(v):
                continue
            if isinstance(v, (list, tuple)):
                return list(v)
        if isinstance(res, dict):
            for attr in names:
                v = res.get(attr)
                if isinstance(v, (list, tuple)):
                    return list(v)
        return []

    def get_str(obj, names):
        for attr in names:
            v = getattr(obj, attr, None)
            if isinstance(v, str) and v:
                return v
        if isinstance(obj, dict):
            for attr in names:
                v = obj.get(attr)
                if isinstance(v, str) and v:
                    return v
        if isinstance(obj, str):
            return obj
        return ""

    # 1. DISCOVERY: List uploads dir
    uploads_listing = vm.list(path=uploads_dir)
    entries = get_list(uploads_listing, ["entries", "items", "files", "nodes", "children"])

    candidates = []
    for e in entries:
        nm = get_str(e, ["name", "path"])
        if not nm:
            continue
        kind = ""
        kv = getattr(e, "kind", None)
        if kv is None and isinstance(e, dict):
            kv = e.get("kind")
        if kv is not None:
            kind = str(kv).upper()
        full = nm if nm.startswith("/") else uploads_dir.rstrip("/") + "/" + nm
        if "DIR" in kind or full.endswith("/"):
            continue
        candidates.append(full)

    receipt_path = None
    for c in candidates:
        if "receipt" in c.lower():
            receipt_path = c
            break
    if receipt_path is None:
        for c in candidates:
            if c.lower().endswith(".txt"):
                receipt_path = c
                break
    if receipt_path is None and candidates:
        receipt_path = candidates[0]
    if receipt_path is None:
        receipt_path = uploads_dir.rstrip("/") + "/receipt.txt"

    # 2. DISCOVERY: Read receipt file (never the directory)
    receipt_text = ""
    try:
        receipt = vm.read(path=receipt_path, number=False)
        receipt_text = get_str(receipt, ["content", "text", "data", "stdout"])
    except Exception:
        receipt_text = ""

    def strip_lineno(line):
        return re.sub(r'^\s*\d+\s*[:|\t]\s?', '', line)

    subtotal = None
    items = []
    fallback_sum = 0.0
    for raw in receipt_text.splitlines():
        line = strip_lineno(raw)
        compact = canon(re.sub(r'[^A-Za-z0-9]', '', line.upper()))
        if 'SUBT0TAL' in compact:
            nums = re.findall(r'\d+[.,]\d{2}', line)
            if nums:
                try:
                    subtotal = float(nums[-1].replace(',', '.'))
                except Exception:
                    pass
            continue
        tokens = re.findall(r'[A-Za-z0-9][A-Za-z0-9\-/]{2,}', line)
        sku = None
        for t in tokens:
            tu = t.upper()
            has_alpha = any(ch.isalpha() for ch in tu)
            has_digit = any(ch.isdigit() for ch in tu)
            if (has_alpha and has_digit) or ('-' in tu and len(tu) >= 4):
                sku = tu.strip('-/')
                break
        if not sku:
            continue
        qty = None
        mx = re.search(r'(\d+)\s*[xX@]', line)
        if mx:
            try:
                qty = int(mx.group(1))
            except Exception:
                qty = None
        if qty is None:
            ml = re.match(r'\s*(\d{1,3})\b(?![\d.,])', line)
            if ml:
                try:
                    qty = int(ml.group(1))
                except Exception:
                    qty = None
        if qty is None:
            qty = 1
        items.append((sku, qty))
        prices = re.findall(r'\d+[.,]\d{2}', line)
        if prices:
            try:
                fallback_sum += float(prices[-1].replace(',', '.'))
            except Exception:
                pass

    # 3. DISCOVERY: query catalogue prices via /bin/sql
    sql = "SELECT product_sku, record_path, price_cents FROM product_variants;"
    catalogue_prices = vm.exec(path="/bin/sql", args=[sql], stdin=sql)
    stdout = getattr(catalogue_prices, "stdout", "")
    if not isinstance(stdout, str):
        stdout = ""
    if not stdout and isinstance(catalogue_prices, dict):
        stdout = catalogue_prices.get("stdout", "") or ""

    cat_exact = {}
    cat_canon = {}
    for row in stdout.splitlines():
        row = row.strip()
        if not row or '|' not in row:
            continue
        parts = [p.strip() for p in row.split('|')]
        if len(parts) < 3:
            continue
        sku_v = parts[0]
        if sku_v.lower() in ('product_sku', 'sku'):
            continue
        try:
            pc = int(float(parts[2]))
        except Exception:
            continue
        skuU = sku_v.upper()
        cat_exact[skuU] = pc
        cat_canon.setdefault(canon(skuU), pc)

    today_cents = 0
    for sku, qty in items:
        skuU = sku.upper()
        if skuU in cat_exact:
            pc = cat_exact[skuU]
        elif canon(skuU) in cat_canon:
            pc = cat_canon[canon(skuU)]
        else:
            pc = 0
        today_cents += qty * pc
    today_ex = today_cents / 100.0

    old_ex = subtotal if subtotal is not None else round(fallback_sum, 2)

    today_ex_r = round(today_ex, 2)
    old_ex_r = round(old_ex, 2)
    diff_r = round(abs(today_ex - old_ex), 2)
    within = diff_r <= threshold
    tok = "<YES>" if within else "<NO>"

    thr_disp = int(threshold) if float(threshold).is_integer() else threshold

    message = (
        "Old receipt ex-VAT subtotal = %s EUR; today's catalogue ex-VAT total "
        "for the same items = %s EUR; diff = %s EUR (threshold %s EUR). %s"
        % (old_ex_r, today_ex_r, diff_r, thr_disp, tok)
    )

    refs = [receipt_path] if receipt_path else []
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
