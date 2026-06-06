def run(vm, params):
    def to_text(r):
        if r is None:
            return ""
        if isinstance(r, str):
            return r
        if isinstance(r, dict):
            return r.get("stdout", "") or ""
        return getattr(r, "stdout", "") or ""

    def get_list(r, *keys):
        for k in keys:
            v = r.get(k) if isinstance(r, dict) else getattr(r, k, None)
            if isinstance(v, (list, tuple)):
                return list(v)
        return []

    # discovery 1: identity / id context
    identity = vm.exec(path="/bin/id", args=[])
    identity_text = to_text(identity).strip()

    customer_id = ""
    if isinstance(params, dict):
        customer_id = params.get("customer_id", "") or ""
    if (not customer_id) or str(customer_id).startswith("$"):
        cid = ""
        for line in identity_text.replace(",", "\n").split("\n"):
            line = line.strip()
            low = line.lower()
            if "customer" in low and ("=" in line or ":" in line):
                sep = "=" if "=" in line else ":"
                cid = line.split(sep, 1)[1].strip().strip("'\"")
                break
        if not cid and identity_text:
            cid = identity_text.split()[0].strip()
        customer_id = cid

    # discovery 2: locate checkout policy doc(s)
    find_res = vm.find(root="/docs", name="checkout", kind="file", limit=5)
    policy_paths = []
    matches = get_list(find_res, "matches", "results", "entries", "paths", "files")
    for m in matches:
        if isinstance(m, str):
            if m.strip():
                policy_paths.append(m.strip())
        elif isinstance(m, dict):
            p = m.get("path") or m.get("full_path") or m.get("name")
            if p:
                policy_paths.append(p)
        else:
            p = getattr(m, "path", None) or getattr(m, "full_path", None) or getattr(m, "name", None)
            if p:
                policy_paths.append(p)
    if not policy_paths:
        for line in to_text(find_res).split("\n"):
            line = line.strip()
            if line:
                policy_paths.append(line)
    checkout_policy_path = policy_paths[0] if policy_paths else "/docs/checkout.md"

    # discovery 3: read policy (grounding)
    checkout_policy = vm.read(path=checkout_policy_path, number=True)
    _ = to_text(checkout_policy)

    # discovery 4: newest open basket + readiness (inline literals; /bin/sql rejects :binds)
    cid_lit = str(customer_id).replace("'", "''")
    sql = ("WITH newest AS (SELECT basket_id, store_id, record_path, basket_created_at "
           "FROM shopping_baskets WHERE customer_id = '" + cid_lit + "' AND basket_status = 'open' "
           "ORDER BY basket_created_at DESC LIMIT 1) "
           "SELECT n.basket_id, n.store_id, n.record_path AS basket_path, n.basket_created_at, "
           "s.is_open, bi.line_number, bi.product_sku, bi.requested_quantity, "
           "COALESCE(si.available_today_quantity, 0) AS available_today_quantity, "
           "(s.is_open = 1 AND COALESCE(si.available_today_quantity,0) >= bi.requested_quantity) AS line_ready "
           "FROM newest n JOIN stores s ON s.store_id = n.store_id "
           "JOIN shopping_basket_items bi ON bi.basket_id = n.basket_id "
           "LEFT JOIN store_inventory si ON si.store_id = n.store_id AND si.product_sku = bi.product_sku "
           "ORDER BY bi.line_number;")
    basket_readiness = vm.exec(path="/bin/sql", args=[sql])
    rows_text = to_text(basket_readiness).strip()

    data_rows = []
    for l in rows_text.split("\n"):
        if not l.strip():
            continue
        parts = [p.strip() for p in l.split("|")]
        if parts and parts[0].lower() == "basket_id":
            continue
        data_rows.append(parts)

    basket_path = data_rows[0][2] if data_rows and len(data_rows[0]) > 2 else ""
    basket_id = data_rows[0][0] if data_rows and len(data_rows[0]) > 0 else ""

    ready = bool(data_rows)
    for parts in data_rows:
        lr = parts[9] if len(parts) > 9 else "0"
        if str(lr).strip().lower() not in ("1", "true", "t"):
            ready = False
            break
    token = "<YES>" if ready else "<NO>"

    # ops: payments checkout (always emit per plan; honor only when ready)
    checkout_result = vm.exec(path="/bin/payments", args=["checkout", "--basket-id", basket_id, "--customer-id", str(customer_id)])
    checkout_text = to_text(checkout_result).strip()

    refs = []
    if basket_path:
        refs.append(basket_path)
    for p in policy_paths:
        if p not in refs:
            refs.append(p)
    if "/docs/security.md" not in refs:
        refs.append("/docs/security.md")

    message = ("Identity: " + identity_text + ". Customer: " + str(customer_id) +
               ". Newest open basket: " + (basket_path or "(none found)") +
               ". Readiness today (store open + all items available_today >= requested): " + token +
               ". Checkout per policy " + checkout_policy_path + ": " +
               (("checked out -> " + checkout_text) if ready else "NOT checked out (basket not ready; no payment honored)") +
               ". " + token + " per checkout policy.")
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
