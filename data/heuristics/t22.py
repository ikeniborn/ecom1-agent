def run(vm, params):
    def _stdout(r):
        return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")

    # ---- discovery ----
    identity = vm.exec(path="/bin/id", args=[])
    identity_out = _stdout(identity).strip()

    # resolve customer id from identity resolver, fall back to param binding
    resolved_customer = None
    for tok in identity_out.replace("\n", " ").replace(",", " ").split():
        if tok.startswith("customer_id="):
            resolved_customer = tok.split("=", 1)[1].strip()
            break
        if tok.startswith("customer="):
            resolved_customer = tok.split("=", 1)[1].strip()
            break
    customer_id = resolved_customer or params.get("customer_id", "")

    checkout_find = vm.find(root="/docs", name="checkout", kind="file", limit=5)
    checkout_policy_path = ""
    matches = getattr(checkout_find, "matches", None)
    if matches is None and isinstance(checkout_find, dict):
        matches = checkout_find.get("matches")
    if matches:
        first = matches[0]
        checkout_policy_path = getattr(first, "path", "") or (first.get("path", "") if isinstance(first, dict) else "") or str(first)

    read_target = checkout_policy_path or "/docs"
    checkout_policy = vm.read(path=read_target, number=True)

    payments_help = vm.exec(path="/bin/payments", args=["--help"])

    sql = ("WITH b AS (SELECT basket_id, record_path, store_id, basket_status, basket_created_at "
           "FROM shopping_baskets WHERE customer_id = :customer_id) "
           "SELECT b.basket_id, b.record_path, b.store_id, b.basket_status, b.basket_created_at, "
           "bi.line_number, bi.product_sku, bi.requested_quantity, pv.price_cents, pv.price_currency, "
           "inv.available_today_quantity FROM b "
           "JOIN shopping_basket_items bi ON bi.basket_id = b.basket_id "
           "JOIN product_variants pv ON pv.product_sku = bi.product_sku "
           "LEFT JOIN store_inventory inv ON inv.store_id = b.store_id AND inv.product_sku = bi.product_sku "
           "ORDER BY b.basket_created_at DESC, bi.line_number;")
    basket = vm.exec(path="/bin/sql", args=[sql, "customer_id=" + str(customer_id)])
    basket_out = _stdout(basket).strip()

    # parse basket rows (pipe-delimited)
    rows = []
    for line in basket_out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [c.strip() for c in line.split("|")]
        if len(parts) < 11:
            continue
        if parts[0].lower() in ("basket_id",):
            continue
        rows.append(parts)

    # group by basket_id, only active (non-checked-out) baskets
    baskets = {}
    order = []
    for p in rows:
        bid, rpath, sid, status = p[0], p[1], p[2], p[3]
        st = (status or "").lower()
        if "checked" in st or st in ("complete", "completed", "paid", "closed"):
            continue
        if bid not in baskets:
            baskets[bid] = {"path": rpath, "status": status, "items": []}
            order.append(bid)
        # inventory sufficiency
        try:
            req = float(p[7]) if p[7] not in ("", "None") else 0.0
        except Exception:
            req = 0.0
        try:
            avail = float(p[10]) if p[10] not in ("", "None") else -1.0
        except Exception:
            avail = -1.0
        baskets[bid]["items"].append((req, avail))

    candidate_ids = order
    basket_id = ""
    basket_path = ""
    inventory_ok = True
    if len(candidate_ids) == 1:
        basket_id = candidate_ids[0]
        basket_path = baskets[basket_id]["path"]
        for req, avail in baskets[basket_id]["items"]:
            if avail >= 0 and avail < req:
                inventory_ok = False
                break

    identity_ok = bool(customer_id)
    policy_ok = bool(checkout_policy_path)
    unique_basket = (len(candidate_ids) == 1)

    proceed = identity_ok and unique_basket and policy_ok and inventory_ok

    # ---- ops: checkout ----
    checkout_result = vm.exec(
        path="/bin/payments",
        args=["checkout", "--basket", basket_id, "--customer", str(customer_id)],
    )
    checkout_out = _stdout(checkout_result)

    # parse payment id/status/path from checkout output
    payment_id = ""
    payment_status = ""
    payment_path = ""
    for line in checkout_out.replace(",", "\n").splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith("payment_id=") or low.startswith("payment_id:"):
            payment_id = line.split("=", 1)[-1].split(":", 1)[-1].strip()
        elif low.startswith("payment_status=") or low.startswith("status=") or low.startswith("status:"):
            payment_status = line.split("=", 1)[-1].split(":", 1)[-1].strip()
        elif low.startswith("record_path=") or low.startswith("payment_path=") or low.startswith("path="):
            payment_path = line.split("=", 1)[-1].strip()

    # ---- answer ----
    refs = []
    if basket_path:
        refs.append(basket_path)
    if payment_path:
        refs.append(payment_path)
    if checkout_policy_path:
        refs.append(checkout_policy_path)

    if proceed:
        message = ("Checkout completed for basket %s (%s). Payment %s created with status %s. "
                   "Checkout policy applied per %s."
                   % (basket_id, basket_path, payment_id, payment_status, checkout_policy_path))
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
        return

    # clarification / precondition failure
    if not identity_ok:
        msg = "Could not resolve current request identity to a customer; cannot proceed with checkout."
    elif len(candidate_ids) == 0:
        msg = "No active (non-checked-out) basket found for the current customer; nothing to check out."
    elif len(candidate_ids) > 1:
        cand = "; ".join("%s (%s)" % (b, baskets[b]["path"]) for b in candidate_ids)
        msg = ("Multiple active baskets found for the customer; clarification needed. Candidates: %s." % cand)
        for b in candidate_ids:
            if baskets[b]["path"] and baskets[b]["path"] not in refs:
                refs.insert(0, baskets[b]["path"])
    elif not inventory_ok:
        msg = ("Checkout precondition failed for basket %s (%s): insufficient inventory available today per checkout policy %s."
               % (basket_id, basket_path, checkout_policy_path))
    elif not policy_ok:
        msg = "Checkout policy document not found under /docs; cannot ground checkout preconditions."
    else:
        msg = "Checkout preconditions not satisfied."

    vm.answer(message=msg, outcome="OUTCOME_NONE_CLARIFICATION", refs=refs)
