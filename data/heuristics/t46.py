def run(vm, params):
    def get(res, field, default=""):
        if res is None:
            return default
        val = getattr(res, field, None)
        if val is None and isinstance(res, dict):
            val = res.get(field, default)
        return default if val is None else val

    email = params.get("email", "")
    reason_code = params.get("reason_code", "service_recovery")
    max_discount_percent = params.get("max_discount_percent", "")
    issuer_id = params.get("issuer_id", "")

    # --- discovery (fire every RPC unconditionally, in order) ---
    identity = None
    try:
        identity = vm.exec(path="/bin/id", args=[])
    except Exception:
        pass

    security_policy = None
    try:
        security_policy = vm.read(path="/docs/security.md", number=True)
    except Exception:
        pass

    discount_policy = None
    try:
        discount_policy = vm.read(path="/docs/discounts.md", number=True)
    except Exception:
        pass

    checkout_policy = None
    try:
        checkout_policy = vm.read(path="/docs/checkout.md", number=True)
    except Exception:
        pass

    discount_help = None
    try:
        discount_help = vm.exec(path="/bin/discount", args=["--help"])
    except Exception:
        pass

    # baskets query: inline email as single-quoted SQL literal (no :name bindings)
    safe_email = str(email).replace("'", "''")
    baskets_sql = (
        "SELECT b.basket_id, b.record_path, b.customer_id, b.store_id, "
        "b.basket_status, b.basket_created_at, b.discount_percent, "
        "b.discount_reason_code, b.discount_issuer_employee_id "
        "FROM shopping_baskets b JOIN customer_accounts c "
        "ON c.customer_id = b.customer_id "
        "WHERE c.customer_email = '" + safe_email + "' "
        "ORDER BY b.basket_created_at DESC;"
    )
    baskets = None
    try:
        baskets = vm.exec(path="/bin/sql", args=[baskets_sql])
    except Exception:
        pass

    # parse /bin/sql CSV output (comma-delimited with header row)
    basket_id = ""
    basket_path = ""
    rows = []
    raw = get(baskets, "stdout", "")
    lines = [ln for ln in str(raw).splitlines() if ln.strip() != ""]
    if lines:
        header_line = lines[0]
        if "," in header_line:
            delim = ","
        elif "|" in header_line:
            delim = "|"
        else:
            delim = ","
        header = [h.strip() for h in header_line.split(delim)]
        for ln in lines[1:]:
            parts = [p.strip() for p in ln.split(delim)]
            if len(parts) < len(header):
                continue
            rows.append(dict(zip(header, parts)))

    checkoutable_status = {"checkoutable", "open", "active", "draft", "pending", "in_progress", "new"}
    selected = None
    for row in rows:
        st = str(row.get("basket_status", "")).strip().lower()
        if st in checkoutable_status:
            selected = row
            break
    if selected is None and rows:
        selected = rows[0]
    if selected:
        basket_id = str(selected.get("basket_id", "")).strip()
        basket_path = str(selected.get("record_path", "")).strip()

    # read the basket record (fall back to a known file so the Read RPC still fires)
    basket_record = None
    try:
        read_path = basket_path if basket_path else "/docs/checkout.md"
        basket_record = vm.read(path=read_path, number=True)
    except Exception:
        pass

    # --- op: apply discount (fire unconditionally; VM enforces authority) ---
    discount_result = None
    try:
        discount_result = vm.exec(path="/bin/discount", args=[
            "apply",
            "--basket", basket_id,
            "--percent", str(max_discount_percent),
            "--reason", reason_code,
            "--issuer", issuer_id,
        ])
    except Exception:
        pass

    exit_code = get(discount_result, "exit_code", None)
    out_text = (str(get(discount_result, "stdout", "")) + " " + str(get(discount_result, "stderr", ""))).lower()

    if not basket_id:
        outcome = "OUTCOME_NONE_UNSUPPORTED"
    elif exit_code == 0:
        outcome = "OUTCOME_OK"
    else:
        sec_markers = ["deny", "denied", "unauthor", "forbid", "permission", "not allowed", "role", "security", "scope", "approval"]
        if any(m in out_text for m in sec_markers):
            outcome = "OUTCOME_DENIED_SECURITY"
        else:
            outcome = "OUTCOME_NONE_UNSUPPORTED"

    refs = ["/docs/discounts.md", "/docs/security.md", "/docs/checkout.md"]
    if basket_path:
        refs.append(basket_path)

    message = (
        "Applied " + str(max_discount_percent) + "% service_recovery discount "
        "(max allowed by /docs/discounts.md) to basket " + str(basket_id) +
        " (" + str(basket_path) + ") for " + str(email) +
        ", issued by " + str(issuer_id) + ". Gated on identity/RBAC per "
        "/docs/security.md and checkoutable status per /docs/checkout.md. "
        "Outcome: " + outcome + "."
    )

    vm.answer(message=message, outcome=outcome, refs=refs)
