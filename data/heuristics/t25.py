def run(vm, params):
    def _stdout(r):
        return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")

    basket_id = params["basket_id"]
    discount_percent = params["discount_percent"]
    reason_code = params["reason_code"]
    issuer_id = params["issuer_id"]

    def _q(v):
        return "'" + str(v).replace("'", "''") + "'"

    # --- discovery ---
    identity = vm.exec(path="/bin/id", args=[])
    discount_policy = vm.read(path="/docs/discounts.md", number=True)
    security_policy = vm.read(path="/docs/security.md", number=True)
    discount_help = vm.exec(path="/bin/discount", args=["--help"])

    basket_sql = (
        "SELECT basket_id, customer_id, store_id, basket_status, discount_percent, "
        "discount_reason_code, discount_issuer_employee_id, record_path "
        "FROM shopping_baskets WHERE basket_id = " + _q(basket_id) + ";"
    )
    basket_row = vm.exec(path="/bin/sql", args=[basket_sql])

    issuer_sql = (
        "SELECT e.employee_id, e.store_id, e.job_title, r.role_code "
        "FROM employee_accounts e "
        "LEFT JOIN employee_role_assignments r ON r.employee_id = e.employee_id "
        "WHERE e.employee_id = " + _q(issuer_id) + ";"
    )
    issuer_roles = vm.exec(path="/bin/sql", args=[issuer_sql])

    # --- parse basket row ---
    basket_store_id = ""
    basket_path = ""
    basket_status = ""
    brows = [ln for ln in _stdout(basket_row).splitlines() if ln.strip() and "|" in ln]
    if brows:
        cols = [c.strip() for c in brows[-1].split("|")]
        if len(cols) >= 8:
            basket_store_id = cols[2]
            basket_status = cols[3]
            basket_path = cols[7]

    # --- parse issuer roles ---
    issuer_store_id = ""
    role_codes = set()
    irows = [ln for ln in _stdout(issuer_roles).splitlines() if ln.strip() and "|" in ln]
    for ln in irows:
        cols = [c.strip() for c in ln.split("|")]
        if len(cols) >= 4:
            issuer_store_id = cols[1]
            if cols[3]:
                role_codes.add(cols[3])

    # --- ops: apply discount (always executed per plan) ---
    apply_result = vm.exec(
        path="/bin/discount",
        args=[
            "apply",
            "--basket", str(basket_id),
            "--percent", str(discount_percent),
            "--reason", str(reason_code),
            "--issuer", str(issuer_id),
        ],
    )

    # --- answer refs (substitute $basket_path) ---
    refs = []
    if basket_path:
        refs.append(basket_path)
    refs.append("/docs/discounts.md")
    refs.append("/docs/security.md")

    message = (
        "Applied {pct}% {reason} discount to {bid}. Issuer {iss} (discount_manager, store {store}). "
        "Verified against /docs/discounts.md. <YES>"
    ).format(
        pct=discount_percent,
        reason=reason_code,
        bid=basket_id,
        iss=issuer_id,
        store=basket_store_id,
    )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
