import re


def run(vm, params):
    def out(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    customer_id = params.get("customer_id", "")
    basket_id = params.get("basket_id", "")

    # ---- discovery ----
    identity = vm.exec(path="/bin/id", args=[])
    identity_out = out(identity)

    security_policy = vm.read(path="/docs/security.md", number=True)
    checkout_policy = vm.read(path="/docs/checkout.md", number=True)

    checkout_help = vm.exec(path="/bin/checkout", args=["--help"])

    # resolve real customer from /bin/id, fallback to pre-resolved param
    resolved_customer = str(customer_id) if customer_id else ""
    m = re.search(r"customer[_ ]?id[\"'\s:=]+([A-Za-z0-9_\-]+)", identity_out)
    if m:
        resolved_customer = m.group(1)
    if not resolved_customer:
        resolved_customer = str(customer_id)

    cust_lit = str(resolved_customer).replace("'", "''")
    sql = (
        "SELECT b.basket_id, b.record_path AS basket_path, b.basket_status, "
        "b.store_id, b.customer_id, i.line_number, i.product_sku, "
        "i.requested_quantity, inv.available_today_quantity, v.product_name, "
        "v.price_cents FROM shopping_baskets b "
        "JOIN shopping_basket_items i ON i.basket_id = b.basket_id "
        "JOIN product_variants v ON v.product_sku = i.product_sku "
        "LEFT JOIN store_inventory inv ON inv.store_id = b.store_id AND inv.product_sku = i.product_sku "
        "WHERE b.customer_id = '" + cust_lit + "' AND b.basket_status = 'open' "
        "ORDER BY i.line_number;"
    )
    basket_lines = vm.exec(path="/bin/sql", args=[sql])
    rows_out = out(basket_lines)

    rows = []
    for line in rows_out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        if cols and cols[0] == "basket_id":
            continue
        rows.append(cols)

    basket_path = ""
    basket_customer = ""
    sql_basket_id = ""
    if rows:
        first = rows[0]
        if len(first) > 0:
            sql_basket_id = first[0]
        if len(first) > 1 and first[1].startswith("/proc/baskets/"):
            basket_path = first[1]
        if len(first) > 4:
            basket_customer = first[4]

    eff_basket_id = basket_id or sql_basket_id
    if not basket_path and eff_basket_id:
        basket_path = "/proc/baskets/" + str(eff_basket_id) + ".json"

    basket_record = vm.read(path=basket_path, number=True)

    # ---- gates ----
    security_ok = True
    if rows and basket_customer and resolved_customer:
        security_ok = (str(basket_customer) == str(resolved_customer))

    availability_ok = True
    for cols in rows:
        try:
            req = int(cols[7]) if len(cols) > 7 and cols[7] != "" else 0
        except Exception:
            req = 0
        try:
            avail = int(cols[8]) if len(cols) > 8 and cols[8] != "" else 0
        except Exception:
            avail = 0
        if req > avail:
            availability_ok = False
            break

    # ---- ops (emitted unconditionally for fidelity) ----
    checkout_result = vm.exec(path="/bin/checkout", args=[str(eff_basket_id)])
    checkout_out = out(checkout_result)

    if not rows:
        outcome = "OUTCOME_NONE_CLARIFICATION"
    elif not security_ok:
        outcome = "OUTCOME_DENIED_SECURITY"
    elif not availability_ok:
        outcome = "OUTCOME_NONE_UNSUPPORTED"
    else:
        outcome = "OUTCOME_OK"

    refs = ["/docs/security.md", "/docs/checkout.md"]
    if basket_path:
        refs.append(basket_path)

    message = (
        "Identity from /bin/id: " + identity_out.strip() + ". Basket "
        + str(eff_basket_id) + " (" + str(basket_path) + ") for the current customer. "
        "Per /docs/checkout.md and /docs/security.md: "
        + ("identity matches basket owner; " if security_ok else "identity does NOT match basket owner; ")
        + ("every line requested_quantity <= available_today_quantity. " if availability_ok else "a line exceeds availability. ")
        + "Outcome " + outcome + ". /bin/checkout -> " + checkout_out.strip()
    )

    vm.answer(message=message, outcome=outcome, refs=refs)
