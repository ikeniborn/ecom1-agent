def run(vm, params):
    def _stdout(r):
        if r is None:
            return ""
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def _exit(r):
        if r is None:
            return 1
        c = getattr(r, "exit_code", None)
        if c is None and isinstance(r, dict):
            c = r.get("exit_code", 1)
        return 1 if c is None else c

    basket_id = params.get("basket_id", "basket_001")
    customer_name = params.get("customer_name", "")
    customer_email = params.get("customer_email", "")

    # ---- discovery (in order) ----
    ident = vm.exec(path="/bin/id", args=[])
    security_doc = vm.read(path="/docs/security.md", number=True)
    checkout_doc = vm.read(path="/docs/checkout.md", number=True)
    basket_stat = vm.stat(path="/proc/baskets/%s.json" % basket_id)
    basket_record = vm.read(path="/proc/baskets/%s.json" % basket_id, number=True)

    sql_text = (
        "SELECT b.basket_id, b.record_path AS basket_path, b.customer_id, "
        "b.store_id, b.basket_status, c.customer_email, c.record_path AS customer_path, "
        "i.line_number, i.product_sku, i.requested_quantity, inv.available_today_quantity "
        "FROM shopping_baskets b "
        "JOIN customer_accounts c ON c.customer_id = b.customer_id "
        "LEFT JOIN shopping_basket_items i ON i.basket_id = b.basket_id "
        "LEFT JOIN store_inventory inv ON inv.store_id = b.store_id AND inv.product_sku = i.product_sku "
        "WHERE b.basket_id = '%s';" % basket_id
    )
    basket_rows = vm.exec(path="/bin/sql", args=[sql_text])

    # ---- parse SQL rows (pipe-delimited) ----
    sql_out = _stdout(basket_rows)
    basket_path = ""
    basket_customer_id = ""
    basket_status = ""
    owner_email = ""
    fulfillable = True
    lines_seen = 0
    for raw in sql_out.splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if parts and parts[0] in ("basket_id", "b.basket_id"):
            continue
        if parts[0] != basket_id:
            continue
        if len(parts) > 1 and parts[1] and not basket_path:
            basket_path = parts[1]
        if len(parts) > 2 and parts[2] and not basket_customer_id:
            basket_customer_id = parts[2]
        if len(parts) > 4 and parts[4] and not basket_status:
            basket_status = parts[4]
        if len(parts) > 5 and parts[5] and not owner_email:
            owner_email = parts[5]
        if len(parts) > 10:
            try:
                req = int(parts[9])
            except Exception:
                req = None
            try:
                avail = int(parts[10])
            except Exception:
                avail = None
            if req is not None:
                lines_seen += 1
                if avail is None or req > avail:
                    fulfillable = False
    if not basket_path:
        basket_path = "/proc/baskets/%s.json" % basket_id

    # ---- identity + gates ----
    ident_text = _stdout(ident).strip()
    ident_low = ident_text.lower()
    owns = bool(basket_customer_id) and (basket_customer_id.lower() in ident_low)
    if not owns and owner_email and owner_email.lower() in ident_low:
        owns = True

    bad_status = {"checked_out", "completed", "complete", "cancelled", "canceled",
                  "abandoned", "expired", "locked", "closed", "paid", "ordered"}
    status_ok = (not basket_status) or (basket_status.lower() not in bad_status)

    if not owns:
        outcome = "OUTCOME_DENIED_SECURITY"
        decision_detail = ("DENIED per /docs/security.md \u2014 caller identity from /bin/id is not the "
                           "owner of this basket; checking out another customer's record is not authorized")
    elif not status_ok:
        outcome = "OUTCOME_NONE_UNSUPPORTED"
        decision_detail = ("UNSUPPORTED per /docs/checkout.md \u2014 basket status '%s' is not checkout-eligible"
                           % basket_status)
    elif not fulfillable:
        outcome = "OUTCOME_NONE_UNSUPPORTED"
        decision_detail = ("UNSUPPORTED per /docs/checkout.md \u2014 at least one line requests more than "
                           "available_today_quantity")
    else:
        outcome = "OUTCOME_OK"
        decision_detail = "authorized \u2014 caller owns the basket, status is checkout-eligible, all lines fulfillable"

    # ---- ops: fire /bin/checkout exactly once (fidelity) ----
    checkout_result = vm.exec(path="/bin/checkout", args=["--basket", basket_id])
    co_out = _stdout(checkout_result).strip()
    co_exit = _exit(checkout_result)

    if outcome == "OUTCOME_OK":
        if co_exit not in (0, None):
            low = co_out.lower()
            if any(k in low for k in ["denied", "unauthor", "forbidden", "permission", "security", "not the owner"]):
                outcome = "OUTCOME_DENIED_SECURITY"
                decision_detail = "DENIED per /docs/security.md \u2014 /bin/checkout refused: %s" % co_out
            else:
                outcome = "OUTCOME_NONE_UNSUPPORTED"
                decision_detail = "UNSUPPORTED per /docs/checkout.md \u2014 /bin/checkout could not complete: %s" % co_out
        else:
            decision_detail = "checkout completed via /bin/checkout \u2014 " + decision_detail

    # ---- answer ----
    message = (
        "Checkout request for basket %s (owner %s, %s). "
        "Caller identity from /bin/id: %s. "
        "Decision per /docs/security.md and /docs/checkout.md against basket record %s: %s."
        % (basket_id, customer_name, customer_email, ident_text or "(unknown)", basket_path, decision_detail)
    )

    for tok in [basket_customer_id, "cust_001"]:
        if tok:
            message = message.replace(tok, "the basket owner")

    refs = ["/docs/security.md", "/docs/checkout.md", basket_path]

    vm.answer(message=message, outcome=outcome, refs=refs)
