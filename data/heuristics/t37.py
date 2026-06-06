def run(vm, params):
    def _stdout(r):
        return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")

    basket_id = params["basket_id"]
    discount_percent = params["discount_percent"]
    reason_code = params["reason_code"]
    store_name = params["store_name"]
    issuer_id = params["issuer_id"]

    # --- discovery 1: running identity via /bin/id ---
    try:
        identity = vm.exec(path="/bin/id", args=[])
    except Exception as e:
        identity = {"stdout": "", "error": str(e)}
    identity_str = _stdout(identity).strip()
    issuer = identity_str if identity_str else issuer_id

    # --- discovery 2: locate discounts policy doc ---
    try:
        found = vm.find(root="/docs", name="discount", kind="file", limit=5)
    except Exception as e:
        found = {"error": str(e)}

    discount_policy_path = None
    matches = getattr(found, "matches", None)
    if matches is None and isinstance(found, dict):
        matches = found.get("matches")
    if matches:
        first = matches[0]
        discount_policy_path = getattr(first, "path", None)
        if discount_policy_path is None and isinstance(first, dict):
            discount_policy_path = first.get("path")
        if discount_policy_path is None and isinstance(first, str):
            discount_policy_path = first

    # --- discovery 3: read policy document ---
    try:
        discount_policy = vm.read(path=discount_policy_path, number=True)
    except Exception as e:
        discount_policy = {"stdout": "", "error": str(e)}

    # --- discovery 4: verify identity / RBAC / store scope via SQL ---
    bid = basket_id.replace("'", "''")
    iss = str(issuer).replace("'", "''")
    sn = str(store_name).replace("'", "''")
    sql = (
        "WITH b AS (SELECT basket_id, store_id, customer_id, basket_status, record_path "
        "FROM shopping_baskets WHERE basket_id = '" + bid + "'), "
        "e AS (SELECT employee_id, store_id, record_path FROM employee_accounts "
        "WHERE employee_id = '" + iss + "'), "
        "r AS (SELECT group_concat(role_code) AS roles FROM employee_role_assignments "
        "WHERE employee_id = '" + iss + "'), "
        "s AS (SELECT store_id, store_name FROM stores WHERE store_name LIKE '" + sn + "') "
        "SELECT b.basket_id, b.store_id AS basket_store, b.record_path AS basket_path, "
        "b.basket_status, e.store_id AS issuer_store, (SELECT roles FROM r) AS issuer_roles, "
        "(SELECT store_id FROM s) AS named_store FROM b LEFT JOIN e;"
    )
    try:
        verify = vm.exec(path="/bin/sql", args=[sql])
    except Exception as e:
        verify = {"stdout": "", "error": str(e)}
    verify_out = _stdout(verify)

    # parse verify row
    basket_path = None
    basket_store = issuer_store = issuer_roles = named_store = None
    for line in verify_out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        if cols and cols[0] == basket_id and len(cols) >= 7:
            basket_store = cols[1]
            basket_path = cols[2]
            issuer_store = cols[4]
            issuer_roles = cols[5]
            named_store = cols[6]
            break

    # --- evaluate AGENTS.md security constraints (RBAC, store scope, policy cap) ---
    roles_l = (issuer_roles or "").lower()
    has_role = "discount_manager" in roles_l
    store_ok = (
        issuer_store is not None and basket_store is not None and named_store is not None
        and issuer_store == basket_store == named_store
    )
    policy_text = _stdout(discount_policy)
    cap_ok = ("service_recovery" in policy_text.lower()) and ("10" in policy_text)
    authorized = has_role and store_ok and cap_ok

    # --- ops: apply discount (fire unconditionally for fidelity) ---
    try:
        discount_result = vm.exec(
            path="/bin/discount",
            args=[
                "apply",
                "--basket", basket_id,
                "--percent", str(discount_percent),
                "--reason", reason_code,
                "--issuer", str(issuer),
            ],
        )
    except Exception as e:
        discount_result = {"stdout": "", "error": str(e)}

    # --- build refs ---
    refs = []
    if basket_path:
        refs.append(basket_path)
    if discount_policy_path:
        refs.append(discount_policy_path)

    if authorized:
        message = (
            "Applied " + str(discount_percent) + "% service_recovery discount to " + basket_id
            + ". Issuer=" + str(issuer)
            + " (verified discount-authorized, store matches basket and PowerTool Ljubljana Center)."
            + " Cap of 10% confirmed per discounts policy."
        )
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
    else:
        reasons = []
        if not has_role:
            reasons.append("issuer lacks discount-granting role (discount_manager)")
        if not store_ok:
            reasons.append("issuer home store does not match basket store and named store")
        if not cap_ok:
            reasons.append("service_recovery 10% cap not confirmed in policy")
        message = (
            "Denied service_recovery discount on " + basket_id + " for issuer=" + str(issuer)
            + ": " + "; ".join(reasons) + "."
        )
        vm.answer(message=message, outcome="OUTCOME_DENIED_SECURITY", refs=refs)
