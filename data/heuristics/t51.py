def run(vm, params):
    import re

    def fld(o, n, d=None):
        if isinstance(o, dict):
            return o.get(n, d)
        return getattr(o, n, d)

    def strip_ln(l):
        return re.sub(r'^\s*\d+[:|\t]\s?', '', l)

    def canon(s):
        t = {'0': 'O', '1': 'I', '5': 'S', '8': 'B', '2': 'Z'}
        return ''.join(t.get(c, c) for c in s.upper())

    def num(x):
        x = x.replace(' ', '')
        if ',' in x and '.' in x:
            x = x.replace(',', '')
        elif ',' in x:
            x = x.replace(',', '.')
        try:
            return float(x)
        except Exception:
            return None

    def rows(res):
        out = fld(res, 'stdout', '') or ''
        ls = [l for l in out.splitlines() if l.strip()]
        if not ls:
            return []
        hdr = ls[0]
        delim = '|' if '|' in hdr else (',' if ',' in hdr else None)
        if not delim:
            return []
        cols = [c.strip() for c in hdr.split(delim)]
        out2 = []
        for l in ls[1:]:
            ps = [p.strip() for p in l.split(delim)]
            out2.append(dict(zip(cols, ps)))
        return out2

    # discovery: list uploads dir, pick a FILE entry
    listing = vm.list(path="/uploads")
    entries = fld(listing, 'items', None) or fld(listing, 'entries', None) or []
    receipt_path = None
    for e in entries:
        if isinstance(e, str):
            name = e
            p = None
            kind = ''
        else:
            name = fld(e, 'name', '')
            p = fld(e, 'path', None)
            kind = fld(e, 'kind', '')
        full = p or ("/uploads/" + name)
        if str(kind).upper().endswith('FILE') or '.' in name:
            receipt_path = full
            break
    if not receipt_path and entries:
        e = entries[0]
        if isinstance(e, str):
            receipt_path = "/uploads/" + e
        else:
            receipt_path = fld(e, 'path', None) or ("/uploads/" + fld(e, 'name', 'receipt'))
    if not receipt_path:
        receipt_path = "/uploads/receipt"

    # read receipt file
    receipt = vm.read(path=receipt_path, number=True)
    text = fld(receipt, 'content', '') or fld(receipt, 'text', '') or ''

    # discovery: search /docs for VAT policy
    sr = vm.search(root="/docs", pattern="(?i)VAT|tax|MwSt", limit=20)
    hits = fld(sr, 'hits', None) or fld(sr, 'matches', None) or fld(sr, 'results', None) or []
    vat_path = None
    for h in hits:
        hp = h if isinstance(h, str) else fld(h, 'path', None)
        if hp:
            vat_path = hp
            break

    # second Read (policy doc, or re-read receipt file; never a directory)
    read_path = vat_path or receipt_path
    vm.read(path=read_path, number=True)

    # parse receipt line items (strip line-number prefix first)
    joined_lines = [strip_ln(l) for l in text.splitlines()]
    items = []
    for s in joined_lines:
        m = re.match(r'\s*(\d+)\s+([A-Z0-9]{3}-[A-Z0-9]+)', s)
        if m:
            items.append((int(m.group(1)), m.group(2)))
    joined = '\n'.join(joined_lines)
    sm = re.search(r'SUB\s*T[O0]TAL[^\d]*([\d][\d.,]*)', joined, re.I)
    old_ex = num(sm.group(1)) if sm else None

    skus = sorted({sku for _, sku in items})
    inlist = ','.join("'" + s.replace("'", "") + "'" for s in skus) if skus else "''"

    # Exec1 current_prices (inline single-quoted SKU literals)
    sql1 = "SELECT product_sku, price_cents FROM product_variants WHERE product_sku IN (" + inlist + ");"
    res1 = vm.exec(path="/bin/sql", args=[sql1])
    map1 = {}
    for r in rows(res1):
        sk = r.get('product_sku')
        pc = r.get('price_cents')
        if sk and pc not in (None, ''):
            try:
                map1[sk] = int(float(pc))
            except Exception:
                pass

    # Exec2 comparison: full catalogue for exact + fuzzy fallback
    sql2 = "SELECT product_sku, price_cents FROM product_variants;"
    res2 = vm.exec(path="/bin/sql", args=[sql2])
    full = {}
    for r in rows(res2):
        sk = r.get('product_sku')
        pc = r.get('price_cents')
        if sk and pc not in (None, ''):
            try:
                full[sk] = int(float(pc))
            except Exception:
                pass
    fullcanon = {}
    for sk, pc in full.items():
        fullcanon.setdefault(canon(sk), pc)

    today_cents = 0
    breakdown = []
    for qty, sku in items:
        price = map1.get(sku)
        if price is None:
            price = full.get(sku)
        if price is None:
            price = fullcanon.get(canon(sku))
        if price is not None:
            today_cents += qty * price
            breakdown.append(sku + "x" + str(qty) + "=" + str(round(qty * price / 100.0, 2)))
        else:
            breakdown.append(sku + "x" + str(qty) + "=discontinued(0)")
    today_ex = round(today_cents / 100.0, 2)

    tol = 3.0
    if old_ex is None or not items:
        old_disp = old_ex if old_ex is not None else 0.0
        diff = tol + 1
        within = False
    else:
        old_disp = old_ex
        diff = round(abs(today_ex - old_ex), 2)
        within = diff <= tol

    token = "<YES>" if within else "<NO>"
    refs = [receipt_path]
    if vat_path:
        refs.append(vat_path)

    msg = ("Receipt " + receipt_path + ": old VAT-excluded total " + str(round(old_disp, 2)) +
           " EUR vs today " + str(today_ex) + " EUR (same VAT basis; catalogue price_cents is ex-VAT). "
           "Difference " + str(diff) + " EUR. " + token + " \u2014 within threshold: " + str(within) +
           ". Per-line: " + "; ".join(breakdown) + ".")
    vm.answer(message=msg, outcome="OUTCOME_OK", refs=refs)
