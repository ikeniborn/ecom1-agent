def run(vm, params):
    email = params["email"]
    store_id = params["store_id"]
    issuer_employee_id = params["issuer_employee_id"]
    discount_percent = params.get("discount_percent", 10)
    reason_code = params.get("reason_code", "service_recovery")

    def _stdout(r):
        v = getattr(r, "stdout", None)
        if v is None and isinstance(r, dict):
            v = r.get("stdout", "")
        return v or ""

    def _paths_from_find(r):
        out = []
        candidates = []
        if isinstance(r, (list, tuple)):
            candidates = list(r)
        else:
            for attr in ("entries", "results", "matches", "files", "nodes"):
                v = getattr(r, attr, None)
                if isinstance(v, (list, tuple)):
                    candidates = list(v)
                    break
            if not candidates and isinstance(r, dict):
                for attr in ("entries", "results", "matches", "files", "nodes"):
                    v = r.get(attr)
                    if isinstance(v, (list, tuple)):
                        candidates = list(v)
                        break
        for c in candidates:
            p = None
            if isinstance(c, str):
                p = c
            else:
                p = getattr(c, "path", None)
                if p is None and isinstance(c, dict):
                    p = c.get("path")
            if isinstance(p, str) and p:
                out.append(p)
        return out

    # --- discovery ---
    identity = vm.exec(path="/bin/id", args=[])
    discount_help = vm.exec(path="/bin/discount", args=["--help"])

    policy_candidates = vm.find(root="/docs", name="discount", kind="file", limit=5)
    policy_paths = _paths_from_find(policy_candidates)
    policy_path = policy_paths[0] if policy_paths else "/docs"

    policy_doc = vm.read(path=policy_path, number=True)

    sql = (
        "WITH cust AS (SELECT customer_id FROM customer_accounts WHERE customer_email = '"
        + email
        + "'), rbac AS (SELECT 1 AS ok FROM employee_role_assignments WHERE employee_id = '"
        + str(issuer_employee_id)
        + "' AND role_code = 'discount_manager') "
        "SELECT b.basket_id, b.record_path, b.customer_id, b.store_id, b.basket_status, b.basket_created_at, "
        "(SELECT ok FROM rbac) AS has_discount_role "
        "FROM shopping_baskets b JOIN cust c ON c.customer_id = b.customer_id "
        "WHERE b.store_id = '"
        + str(store_id)
        + "' AND b.basket_status = 'checkoutable' "
        "ORDER BY b.basket_created_at DESC LIMIT 1;"
    )
    basket = vm.exec(path="/bin/sql", args=[sql])
    rows_text = _stdout(basket)

    basket_id = ""
    basket_path = ""
    has_role = ""
    for line in rows_text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        low = cols[0].lower()
        if low in ("basket_id",) or "basket_id" in low:
            continue
        basket_id = cols[0]
        if len(cols) > 1:
            basket_path = cols[1]
        if len(cols) > 6:
            has_role = cols[6]
        break

    authorized = str(has_role).strip() in ("1", "true", "True")

    # --- ops (always emitted for fidelity) ---
    discount_result = vm.exec(
        path="/bin/discount",
        args=[
            "set",
            "--basket",
            basket_id,
            "--percent",
            str(discount_percent),
            "--reason",
            reason_code,
            "--issuer",
            str(issuer_employee_id),
        ],
    )

    refs = []
    if basket_path:
        refs.append(basket_path)
    if policy_paths:
        for p in policy_paths:
            if p not in refs:
                refs.append(p)

    if not authorized or not basket_id:
        msg = (
            "Could not apply discount: "
            + ("issuer lacks discount_manager role" if not authorized else "no checkoutable basket found")
            + " for " + email + " in store " + str(store_id) + "."
        )
        vm.answer(message=msg, outcome="OUTCOME_DENIED_SECURITY", refs=refs)
        return

    message = (
        "Applied " + str(discount_percent) + "% service_recovery discount to basket "
        + str(basket_id) + " (latest checkoutable basket of " + email + " in store "
        + str(store_id) + "), issuer " + str(issuer_employee_id) + ". Basket: "
        + basket_path + ". Policy: " + (policy_paths[0] if policy_paths else policy_path) + "."
    )
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
