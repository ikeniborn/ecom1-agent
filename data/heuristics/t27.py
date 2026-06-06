def run(vm, params):
    def out(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    basket_id = params.get("basket_id", "basket_250")

    # --- discovery ---
    identity = vm.exec(path="/bin/id", args=[])
    identity_txt = out(identity)

    docs_tree = vm.tree(root="/docs", level=2)

    payments_help = vm.exec(path="/bin/payments", args=["--help"])

    safe_basket = str(basket_id).replace("'", "''")
    sql = (
        "SELECT b.basket_id, b.customer_id AS basket_customer_id, b.basket_status, "
        "b.record_path AS basket_path, p.payment_id, p.record_path AS payment_path, "
        "p.customer_id AS payment_customer_id, p.payment_status, p.three_ds_status, "
        "p.three_ds_failure_reason, p.three_ds_attempts, p.three_ds_max_attempts "
        "FROM shopping_baskets b LEFT JOIN payment_transactions p "
        "ON p.basket_id = b.basket_id "
        "WHERE b.basket_id = '" + safe_basket + "';"
    )
    checkout = vm.exec(path="/bin/sql", args=[sql])
    checkout_txt = out(checkout)

    try:
        payments_policy = vm.read(path="/docs/payments.md", number=True)
    except Exception:
        payments_policy = None
    try:
        security_policy = vm.read(path="/docs/security.md", number=True)
    except Exception:
        security_policy = None

    # --- parse SQL rows ---
    row = {}
    lines = [l for l in checkout_txt.splitlines() if l.strip()]
    if lines:
        header_line = lines[0]
        delim = "|" if "|" in header_line else ("," if "," in header_line else "\t")
        headers = [h.strip() for h in header_line.split(delim)]
        for dl in lines[1:]:
            if set(dl.strip()) <= set("-+=| "):
                continue
            vals = [v.strip() for v in dl.split(delim)]
            if len(vals) >= len(headers):
                row = dict(zip(headers, vals))
                break

    payment_id = row.get("payment_id", "")
    payment_path = row.get("payment_path", "")
    basket_path = row.get("basket_path", "")
    basket_customer_id = row.get("basket_customer_id", "")
    payment_customer_id = row.get("payment_customer_id", "")
    three_ds_status = row.get("three_ds_status", "")
    three_ds_failure_reason = row.get("three_ds_failure_reason", "")
    three_ds_attempts = row.get("three_ds_attempts", "")
    three_ds_max_attempts = row.get("three_ds_max_attempts", "")

    # --- ownership guard (resolve actor from /bin/id, never trust placeholder) ---
    actor = identity_txt.strip()
    owner = basket_customer_id or payment_customer_id
    if actor and owner and owner not in actor and actor not in owner:
        import re as _re
        toks = _re.findall(r"[A-Za-z0-9_\-]+", actor)
        if owner not in toks:
            vm.answer(
                message=(
                    "Cannot recover checkout for " + str(basket_id) + ": caller identity ("
                    + actor + ") is not the confirmed owner (" + str(owner)
                    + ") of the basket/payment. Refusing state change for payment safety."
                ),
                outcome="OUTCOME_DENIED_SECURITY",
                refs=[p for p in [payment_path, basket_path, "/docs/payments.md", "/docs/security.md"] if p],
            )
            return

    # --- ops: re-trigger 3DS authentication (never bypass) ---
    # emit the retry call unconditionally; tool enforces max-attempts refusal
    retry_args = ["retry-3ds", "--payment-id", payment_id]
    recovery = vm.exec(path="/bin/payments", args=retry_args)
    recovery_txt = out(recovery).strip()

    msg = (
        "Checkout recovery for " + str(basket_id) + " (payment " + str(payment_id) + "). "
        "3DS had failed (status=" + str(three_ds_status) + ", reason=" + str(three_ds_failure_reason)
        + ", attempts " + str(three_ds_attempts) + "/" + str(three_ds_max_attempts) + "). "
        "Safe recovery = re-trigger 3DS authentication challenge via payments tool — NOT bypass. "
        "If attempts already at max, retry refused; customer must start fresh authorization. "
        "Result: " + recovery_txt + ". Payment safety preserved per policy."
    )

    refs = []
    if payment_path:
        refs.append(payment_path)
    if basket_path:
        refs.append(basket_path)
    refs.append("/docs/payments.md")
    refs.append("/docs/security.md")

    vm.answer(message=msg, outcome="OUTCOME_OK", refs=refs)
