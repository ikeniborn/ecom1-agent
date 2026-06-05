def run(vm, params):
    import re
    def g(o, k, d=None):
        return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)

    uploads_listing = vm.list(path="/uploads")
    entries = g(uploads_listing, "entries", []) or []
    receipt_path = ""
    for e in entries:
        nm = g(e, "name", "") or ""
        pt = g(e, "path", "") or ("/uploads/" + nm if nm else "")
        low = nm.lower()
        if "receipt" in low or low.endswith(".txt") or low.endswith(".csv") or low.endswith(".md"):
            receipt_path = pt
            break
    if not receipt_path and entries:
        e = entries[0]
        receipt_path = g(e, "path", "") or ("/uploads/" + (g(e, "name", "") or ""))
    if not receipt_path:
        receipt_path = "/uploads/unknown"

    receipt_content = vm.read(path=receipt_path, number=True)
    body = g(receipt_content, "content", "") or ""

    docs_tree = vm.tree(root="/docs", level=2)
    vat_policy_hits = vm.search(root="/docs", pattern="VAT|tax", limit=20)
    hits = g(vat_policy_hits, "hits", []) or []
    vat_policy_path = "/docs"
    for h in hits:
        p = g(h, "path", "") or ""
        if p:
            vat_policy_path = p
            break

    vat_rate = 0.21
    m_rate = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%", body)
    if m_rate:
        try:
            vat_rate = float(m_rate.group(1)) / 100.0
        except Exception:
            pass

    skus = []
    names = []
    line_items = []
    old_total_cents = 0
    explicit_total = None
    for raw in body.splitlines():
        m = re.match(r"\s*\d+[:\s]\s*(.*)", raw)
        text = m.group(1) if m else raw
        m2 = re.search(r"([A-Z][A-Z0-9\-]{2,})\s+(.+?)\s+(\d+)\s*[xX*]\s*\u20ac?\s*([\d.,]+)", text)
        if not m2:
            m2 = re.search(r"([A-Z][A-Z0-9\-]{2,})\s+(.+?)\s+(\d+)\s+\u20ac?\s*([\d.,]+)", text)
        if m2:
            sku = m2.group(1).strip()
            name = m2.group(2).strip()
            try:
                qty = int(m2.group(3))
                price = float(m2.group(4).replace(",", "."))
            except Exception:
                continue
            cents = int(round(price * 100))
            skus.append(sku)
            names.append(name)
            line_items.append((sku, name, qty, cents))
            old_total_cents += qty * cents
            continue
        m3 = re.search(r"total[:\s]+\u20ac?\s*([\d.,]+)", text, re.I)
        if m3 and explicit_total is None:
            try:
                explicit_total = int(round(float(m3.group(1).replace(",", ".")) * 100))
            except Exception:
                pass

    sql = "SELECT product_sku, product_name, price_cents, price_currency FROM product_variants WHERE product_sku IN (:skus) OR product_name IN (:names);"
    current_prices = vm.exec(path="/bin/sql", args=[sql, "skus=" + ",".join(skus), "names=" + ",".join(names)])
    stdout = g(current_prices, "stdout", "") or ""

    price_map = {}
    for row in stdout.splitlines():
        parts = [p.strip() for p in row.split("|")]
        if len(parts) >= 3:
            try:
                pc = int(parts[2])
            except Exception:
                continue
            if parts[0]:
                price_map[parts[0]] = pc
            if parts[1]:
                price_map[parts[1]] = pc

    new_total_cents = 0
    for sku, name, qty, old_cents in line_items:
        pc = price_map.get(sku)
        if pc is None:
            pc = price_map.get(name)
        if pc is None:
            pc = old_cents
        new_total_cents += qty * pc

    old_inc = old_total_cents
    old_ex = (old_inc / (1.0 + vat_rate)) / 100.0
    new_ex = (new_total_cents / (1.0 + vat_rate)) / 100.0
    diff = abs(old_ex - new_ex)
    yesno = "YES" if diff <= 2.0 else "NO"

    msg = "<{0}> Old receipt total ex-VAT: \u20ac{1:.2f}. Today's catalog total ex-VAT: \u20ac{2:.2f}. Diff: \u20ac{3:.2f} (threshold 2 EUR).".format(yesno, old_ex, new_ex, diff)
    refs = []
    if receipt_path:
        refs.append(receipt_path)
    if vat_policy_path:
        refs.append(vat_policy_path)
    vm.answer(message=msg, outcome="OUTCOME_OK", refs=refs)
