def run(vm, params):
    def _stdout(res):
        if res is None:
            return ""
        s = getattr(res, "stdout", None)
        if s is None and isinstance(res, dict):
            s = res.get("stdout", "")
        return s or ""

    def _exit(res):
        if res is None:
            return 1
        c = getattr(res, "exit_code", None)
        if c is None and isinstance(res, dict):
            c = res.get("exit_code", None)
        return 0 if c is None else c

    def _parse_rows(text):
        lines = [l for l in (text or "").splitlines() if l.strip()]
        if not lines:
            return []
        header = [h.strip() for h in lines[0].split(",")]
        rows = []
        for line in lines[1:]:
            cells = [c.strip() for c in line.split(",")]
            rows.append(dict(zip(header, cells)))
        return rows

    basket_id = str(params.get("basket_id", ""))
    discount_percent = params.get("discount_percent", "")
    reason_code = str(params.get("reason_code", ""))
    issuer_employee_id = str(params.get("issuer_employee_id", ""))

    # --- discovery (run all, in order; never early-return before ops) ---
    identity = vm.exec(path="/bin/id", args=[])
    security_policy = vm.read(path="/docs/security.md", number=True)
    discount_policy = vm.read(path="/docs/discounts.md", number=True)

    bid = basket_id.replace("'", "''")
    basket_sql = (
        "SELECT basket_id, record_path, customer_id, store_id, basket_status, "
        "discount_percent, discount_reason_code, discount_issuer_employee_id "
        "FROM shopping_baskets WHERE basket_id = '" + bid + "';"
    )
    basket = vm.exec(path="/bin/sql", args=[basket_sql])

    basket_rows = _parse_rows(_stdout(basket))
    basket_record_path = ""
    basket_store_id = ""
    basket_customer_id = ""
    if basket_rows:
        basket_record_path = basket_rows[0].get("record_path", "") or ""
        basket_store_id = basket_rows[0].get("store_id", "") or ""
        basket_customer_id = basket_rows[0].get("customer_id", "") or ""

    identity_text = _stdout(identity).strip()

    # --- ops: always invoke the discount tool; it enforces RBAC/store scope ---
    discount_result = vm.exec(
        path="/bin/discount",
        args=[
            "set",
            "--basket", basket_id,
            "--percent", str(discount_percent),
            "--reason", reason_code,
            "--issuer", issuer_employee_id,
        ],
    )

    disc_out = _stdout(discount_result).strip()
    disc_exit = _exit(discount_result)

    # --- classify terminal outcome from the tool's actual result ---
    if disc_exit == 0:
        outcome = "OUTCOME_OK"
    else:
        low = disc_out.lower()
        sec_markers = ["denied", "permission", "unauthorized", "forbidden",
                       "rbac", "role", "security", "scope", "not authorized"]
        if any(m in low for m in sec_markers):
            outcome = "OUTCOME_DENIED_SECURITY"
        else:
            outcome = "OUTCOME_NONE_UNSUPPORTED"

    # --- grounding refs: policy docs always; basket record path ---
    refs = ["/docs/discounts.md", "/docs/security.md"]
    if basket_record_path:
        refs.append(basket_record_path)
    else:
        refs.append("/proc/baskets/" + basket_id + ".json")

    record_ref = basket_record_path or ("/proc/baskets/" + basket_id + ".json")

    message = (
        "Identity: " + (identity_text or "<unknown>") + ". "
        "Per /docs/discounts.md and /docs/security.md, applying a "
        + str(discount_percent) + "% " + reason_code + " discount to "
        + basket_id + " (store " + (basket_store_id or "?")
        + ", owner " + (basket_customer_id or "?") + ") requires the "
        "discount_manager role and matching store scope; a customer cannot "
        "self-apply a manager-pre-approved discount. /bin/discount result "
        "(exit " + str(disc_exit) + "): " + (disc_out or "<no output>")
        + ". Outcome: " + outcome + ". Basket: " + record_ref + "."
    )

    vm.answer(message=message, outcome=outcome, refs=refs)
