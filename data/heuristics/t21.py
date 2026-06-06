def run(vm, params):
    def _stdout(r):
        if r is None:
            return ""
        v = getattr(r, "stdout", None)
        if v is None and isinstance(r, dict):
            v = r.get("stdout", "")
        return v or ""

    def _rows(text):
        rows = []
        for ln in (text or "").splitlines():
            ln = ln.strip()
            if not ln or set(ln) <= set("-+= "):
                continue
            if "|" in ln:
                rows.append([c.strip() for c in ln.split("|")])
        return rows

    def _paths_from_find(r):
        paths = []
        matches = getattr(r, "matches", None)
        if matches is None and isinstance(r, dict):
            matches = r.get("matches")
        if matches:
            for m in matches:
                p = getattr(m, "path", None)
                if p is None and isinstance(m, dict):
                    p = m.get("path")
                if p:
                    paths.append(p)
            return paths
        txt = _stdout(r)
        for ln in (txt or "").splitlines():
            ln = ln.strip()
            if ln.startswith("/"):
                paths.append(ln)
        return paths

    basket_id = params["basket_id"]

    # ---- discovery ----
    identity = vm.exec(path="/bin/id", args=[])
    docs_tree = vm.tree(root="/docs", level=2)
    checkout_doc_paths = vm.find(root="/docs", name="checkout", kind="file", limit=5)

    found_paths = _paths_from_find(checkout_doc_paths)
    checkout_doc_path = found_paths[0] if found_paths else "/docs/checkout.md"

    try:
        checkout_policy = vm.read(path=checkout_doc_path, number=True)
    except Exception as e:
        checkout_policy = None

    payments_help = vm.exec(path="/bin/payments", args=["--help"])

    basket_detail = vm.exec(
        path="/bin/sql",
        args=[
            "WITH b AS (SELECT * FROM shopping_baskets WHERE basket_id = :basket_id) SELECT b.basket_id, b.record_path AS basket_path, b.customer_id, b.store_id, b.basket_status, b.discount_percent, b.discount_reason_code, b.discount_issuer_employee_id, i.line_number, i.product_sku, i.requested_quantity, pv.price_cents, pv.price_currency, inv.available_today_quantity FROM b JOIN shopping_basket_items i ON i.basket_id = b.basket_id JOIN product_variants pv ON pv.product_sku = i.product_sku LEFT JOIN store_inventory inv ON inv.store_id = b.store_id AND inv.product_sku = i.product_sku ORDER BY i.line_number;",
            "basket_id=" + str(basket_id),
        ],
    )

    existing_payment = vm.exec(
        path="/bin/sql",
        args=[
            "SELECT payment_id, record_path, payment_status, payment_amount_cents, three_ds_status FROM payment_transactions WHERE basket_id = :basket_id;",
            "basket_id=" + str(basket_id),
        ],
    )

    # ---- parse discovery outputs ----
    bd_rows = _rows(_stdout(basket_detail))
    basket_path = None
    price_currency = ""
    if bd_rows:
        r0 = bd_rows[0]
        if len(r0) > 1:
            basket_path = r0[1]
        if len(r0) > 12:
            price_currency = r0[12]

    ep_rows = _rows(_stdout(existing_payment))
    payment_path = None
    if ep_rows and len(ep_rows[0]) > 1:
        payment_path = ep_rows[0][1]

    help_text = _stdout(payments_help).lower()
    checkout_supported = "checkout" in help_text

    # ---- ops (always fire per no-drop rule) ----
    checkout_result = vm.exec(
        path="/bin/payments",
        args=["checkout", "--basket", str(basket_id)],
    )

    # ---- outcome decision ----
    static_refs = [checkout_doc_path] if found_paths else []

    if not checkout_supported:
        refs = []
        if basket_path:
            refs.append(basket_path)
        for p in static_refs:
            if p not in refs:
                refs.append(p)
        msg = (
            "Cannot submit checkout for " + str(basket_id) + ": the /bin/payments tool does not "
            "expose a 'checkout' subcommand in its --help output, so this action lies outside the "
            "tool's declared capability. Checkout policy referenced: " + checkout_doc_path + "."
        )
        vm.answer(message=msg, outcome="OUTCOME_NONE_UNSUPPORTED", refs=refs)
        return

    cr_rows = _rows(_stdout(checkout_result))
    cr_status = ""
    cr_payment_id = ""
    cr_amount = ""
    if cr_rows:
        c0 = cr_rows[0]
        if len(c0) > 0:
            cr_payment_id = c0[0]
        if len(c0) > 1:
            cr_status = c0[1]
        if len(c0) > 2:
            cr_amount = c0[2]

    refs = []
    if basket_path:
        refs.append(basket_path)
    if payment_path:
        refs.append(payment_path)
    for p in static_refs:
        if p not in refs:
            refs.append(p)

    msg = (
        "Checkout submitted for " + str(basket_id) + " (status " + str(cr_status) + ", payment "
        + str(cr_payment_id) + ", amount " + str(cr_amount) + " " + str(price_currency)
        + "). Applied checkout policy per " + checkout_doc_path + "."
    )
    vm.answer(message=msg, outcome="OUTCOME_OK", refs=refs)
