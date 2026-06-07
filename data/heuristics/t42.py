def run(vm, params):
    def _stdout(res):
        if res is None:
            return ""
        val = getattr(res, "stdout", None)
        if val is None and isinstance(res, dict):
            val = res.get("stdout", "")
        return val or ""

    def _content(res):
        if res is None:
            return ""
        val = getattr(res, "content", None)
        if val is None and isinstance(res, dict):
            val = res.get("content", "")
        return val or ""

    def parse_rows(text):
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("---") or line.startswith("=="):
                continue
            if "|" in line:
                rows.append([c.strip() for c in line.split("|")])
        return rows

    def col(row, i, default=""):
        if row and len(row) > i:
            return row[i]
        return default

    basket_id = params.get("basket_id", "basket_062")
    discount_percent = params.get("discount_percent", 10)
    discount_reason_code = params.get("discount_reason_code", "service_recovery")
    issuer_employee_id = params.get("issuer_employee_id", "") or ""
    claimed_store = params.get("claimed_store", "") or ""

    basket_path = "/proc/baskets/%s.json" % basket_id

    # ---- discovery ----
    identity = vm.exec(path="/bin/id", args=[])
    discount_help = vm.exec(path="/bin/discount", args=["--help"])
    security_policy = vm.read(path="/docs/security.md", number=True)
    discount_policy = vm.read(path="/docs/discounts.md", number=True)
    try:
        basket_record = vm.read(path=basket_path, number=True)
    except Exception:
        basket_record = None

    basket_sql = (
        "WITH b AS (SELECT basket_id, record_path, customer_id, store_id, basket_status, "
        "discount_percent, discount_reason_code, discount_issuer_employee_id "
        "FROM shopping_baskets WHERE basket_id = '%s'), "
        "sub AS (SELECT bi.basket_id, SUM(bi.requested_quantity * pv.price_cents) AS subtotal_cents "
        "FROM shopping_basket_items bi JOIN product_variants pv ON pv.product_sku = bi.product_sku "
        "WHERE bi.basket_id = '%s' GROUP BY bi.basket_id) "
        "SELECT b.basket_id, b.record_path, b.customer_id, b.store_id, s.store_name, s.city, "
        "b.basket_status, b.discount_percent, b.discount_reason_code, b.discount_issuer_employee_id, "
        "sub.subtotal_cents FROM b JOIN stores s ON s.store_id = b.store_id "
        "LEFT JOIN sub ON sub.basket_id = b.basket_id;"
    ) % (basket_id, basket_id)
    basket_row = vm.exec(path="/bin/sql", args=[basket_sql])

    issuer_sql = (
        "SELECT ea.employee_id, ea.record_path, ea.store_id, ea.job_title, "
        "group_concat(ra.role_code) AS roles FROM employee_accounts ea "
        "LEFT JOIN employee_role_assignments ra ON ra.employee_id = ea.employee_id "
        "WHERE ea.employee_id = '%s' GROUP BY ea.employee_id;"
    ) % issuer_employee_id
    issuer_row = vm.exec(path="/bin/sql", args=[issuer_sql])

    # ---- parse ----
    id_out = _stdout(identity)
    basket_out = _stdout(basket_row)
    issuer_out = _stdout(issuer_row)
    disc_text = _content(discount_policy).lower()

    b_data = None
    for r in parse_rows(basket_out):
        if basket_id in r:
            b_data = r
            break

    record_path = col(b_data, 1) or basket_path
    basket_store_id = col(b_data, 3)
    store_name = col(b_data, 4)
    city = col(b_data, 5)
    basket_status = col(b_data, 6)
    existing_percent = col(b_data, 7)
    existing_reason = col(b_data, 8)

    i_data = None
    for r in parse_rows(issuer_out):
        if issuer_employee_id and issuer_employee_id in r:
            i_data = r
            break
    issuer_store_id = col(i_data, 2)
    issuer_roles = col(i_data, 4).lower()

    identity_disp = ""
    for line in id_out.splitlines():
        if line.strip():
            identity_disp = line.strip()
            break

    # ---- runtime gate ----
    outcome = "OUTCOME_OK"
    decision = ""

    identity_match = bool(issuer_employee_id) and (issuer_employee_id in id_out)
    issuer_real = i_data is not None
    store_match = True
    if claimed_store and store_name:
        store_match = claimed_store.strip().lower() == store_name.strip().lower()
    store_scope = (not issuer_store_id) or (not basket_store_id) or (issuer_store_id == basket_store_id)

    if not identity_match or not issuer_real:
        outcome = "OUTCOME_DENIED_SECURITY"
        decision = "refused (security: issuer is a claimed/unmatched identity not returned by /bin/id)"
    elif (not store_match) or (not store_scope):
        outcome = "OUTCOME_DENIED_SECURITY"
        decision = "refused (security: cross-store \u2014 issuer not scoped to basket store)"
    else:
        closed = basket_status.lower() in ("paid", "checked_out", "closed", "completed", "fulfilled", "cancelled")
        has_conflict = bool(existing_percent) and existing_percent.strip() not in ("", "0", "0.0", "NULL", "null", "None")
        reason_ok = (discount_reason_code.lower() in disc_text) if disc_text else True
        if closed:
            outcome = "OUTCOME_NONE_UNSUPPORTED"
            decision = "refused (business: basket status %s is not discountable)" % basket_status
        elif has_conflict:
            outcome = "OUTCOME_NONE_UNSUPPORTED"
            decision = "refused (business: conflicting existing discount %s/%s)" % (existing_percent, existing_reason)
        elif not reason_ok:
            outcome = "OUTCOME_NONE_UNSUPPORTED"
            decision = "refused (business: reason %s not valid per /docs/discounts.md)" % discount_reason_code
        else:
            outcome = "OUTCOME_OK"
            decision = "applied %s%% %s issuer=%s to basket_062" % (discount_percent, discount_reason_code, issuer_employee_id)

    # ---- ops (always issued; tool enforces authorization) ----
    discount_result = vm.exec(
        path="/bin/discount",
        args=["set", "--basket", basket_id, "--percent", str(discount_percent),
              "--reason", discount_reason_code, "--issuer", issuer_employee_id],
    )
    disc_out = _stdout(discount_result)

    if outcome == "OUTCOME_OK" and disc_out:
        decision = decision + " [%s]" % disc_out.strip().splitlines()[0] if disc_out.strip() else decision

    message = (
        "Identity %s; basket %s store %s (%s), status %s, existing discount %s/%s. "
        "Per /docs/security.md + /docs/discounts.md: %s."
    ) % (
        identity_disp or "unknown",
        basket_id,
        store_name or "unknown",
        city or "unknown",
        basket_status or "unknown",
        existing_percent or "none",
        existing_reason or "none",
        decision,
    )

    refs = ["/docs/security.md", "/docs/discounts.md", record_path]

    vm.answer(message=message, outcome=outcome, refs=refs)
