import csv, io


def run(vm, params):
    def _stdout(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def q(v):
        return "'" + str(v).replace("'", "''") + "'"

    sql = (
        "WITH st AS (SELECT store_id, store_name, record_path FROM stores WHERE store_name = :store_name), "
        "mgr AS (SELECT e.employee_id, e.employee_display_name, e.job_title, e.store_id, e.record_path, "
        "(SELECT GROUP_CONCAT(r.role_code) FROM employee_role_assignments r WHERE r.employee_id = e.employee_id) AS roles "
        "FROM employee_accounts e WHERE e.employee_display_name = :manager_name), "
        "bk AS (SELECT b.basket_id, b.store_id, b.basket_status, b.discount_percent, b.discount_reason_code, "
        "b.discount_issuer_employee_id, b.record_path FROM shopping_baskets b WHERE b.basket_id = :basket_id), "
        "sub AS (SELECT bi.basket_id, SUM(pv.price_cents * bi.requested_quantity) AS subtotal_cents "
        "FROM shopping_basket_items bi JOIN product_variants pv ON pv.product_sku = bi.product_sku "
        "WHERE bi.basket_id = :basket_id GROUP BY bi.basket_id) "
        "SELECT st.store_id AS store_id, st.record_path AS store_path, mgr.employee_id AS manager_id, "
        "mgr.job_title AS manager_title, mgr.store_id AS manager_store_id, mgr.roles AS manager_roles, "
        "mgr.record_path AS manager_path, bk.store_id AS basket_store_id, bk.basket_status AS basket_status, "
        "bk.record_path AS basket_path, sub.subtotal_cents AS subtotal_cents "
        "FROM st LEFT JOIN mgr ON 1=1 LEFT JOIN bk ON 1=1 LEFT JOIN sub ON 1=1;"
    )
    sql = sql.replace(":store_name", q(params["store_name"]))
    sql = sql.replace(":manager_name", q(params["manager_name"]))
    sql = sql.replace(":basket_id", q(params["basket_id"]))

    verify = vm.exec(path="/bin/sql", args=[sql])
    discount_help = vm.exec(path="/bin/discount", args=["--help"])
    discount_policy = vm.search(root="/docs", pattern="discount", limit=5)

    rows = list(csv.DictReader(io.StringIO(_stdout(verify))))
    row = rows[0] if rows else {}

    def g(k):
        return (row.get(k) or "").strip()

    store_id = g("store_id")
    store_path = g("store_path")
    manager_id = g("manager_id")
    manager_title = g("manager_title")
    manager_store_id = g("manager_store_id")
    manager_roles = g("manager_roles")
    manager_path = g("manager_path")
    basket_store_id = g("basket_store_id")
    basket_path = g("basket_path")
    subtotal_raw = g("subtotal_cents")
    try:
        subtotal_cents = int(float(subtotal_raw))
    except (ValueError, TypeError):
        subtotal_cents = None

    roles_set = {x.strip() for x in manager_roles.replace(";", ",").split(",") if x.strip()}
    expected = int(params.get("expected_subtotal_cents", 42700))

    g_store = bool(store_id)
    g_mgr_store = bool(manager_id) and manager_store_id == store_id
    g_roles = "store_manager" in roles_set and "discount_manager" in roles_set
    g_basket = bool(basket_store_id) and basket_store_id == store_id
    g_subtotal = subtotal_cents == expected
    all_pass = g_store and g_mgr_store and g_roles and g_basket and g_subtotal

    issuer = manager_id if manager_id else ""
    apply_result = vm.exec(path="/bin/discount", args=[
        "set", "--basket", params["basket_id"], "--percent", str(params["discount_percent"]),
        "--reason", params["reason_code"], "--issuer", issuer])
    apply_out = _stdout(apply_result).strip()

    policy_paths = []
    matches = getattr(discount_policy, "matches", None)
    if matches is None and isinstance(discount_policy, dict):
        matches = discount_policy.get("matches", [])
    for m in (matches or []):
        p = getattr(m, "path", None)
        if p is None and isinstance(m, dict):
            p = m.get("path")
        if p:
            policy_paths.append(p)

    subtotal_disp = "{:.2f}".format(subtotal_cents / 100.0) if subtotal_cents is not None else "unknown"

    if all_pass:
        outcome = "OUTCOME_OK"
        token = "<YES>"
        msg = (
            token + " " + params["manager_name"] + " (" + (manager_id or "?") + ", " + (manager_title or "?") +
            ") is store_manager for " + params["store_name"] + " (" + (store_id or "?") + "); roles: " +
            (manager_roles or "none") + ". basket_037 subtotal verified at EUR " + subtotal_disp +
            " (=EUR 427.00). Applied 5% service_recovery discount, issuer " + (manager_id or "?") +
            ". Result: " + (apply_out or "applied") + "."
        )
    else:
        outcome = "OUTCOME_DENIED_SECURITY"
        token = "<NO>"
        fails = []
        if not g_store:
            fails.append("store '" + params["store_name"] + "' not found")
        if not g_mgr_store:
            fails.append("manager store_id (" + (manager_store_id or "none") + ") != store store_id (" + (store_id or "none") + ")")
        if not g_roles:
            fails.append("manager lacks required store_manager+discount_manager roles (have: " + (manager_roles or "none") + ")")
        if not g_basket:
            fails.append("basket store_id (" + (basket_store_id or "none") + ") != store store_id (" + (store_id or "none") + ")")
        if not g_subtotal:
            fails.append("subtotal " + (subtotal_raw or "none") + " cents != expected " + str(expected) + " cents")
        msg = (
            token + " Authorization gate failed for " + params["manager_name"] + " (" + (manager_id or "?") +
            ") on " + params["store_name"] + ". Failures: " + "; ".join(fails) +
            ". Discount not validly authorized; discount tool result: " + (apply_out or "n/a") + "."
        )

    refs = []
    for p in [basket_path, store_path, manager_path] + policy_paths:
        if p and p not in refs:
            refs.append(p)

    vm.answer(message=msg, outcome=outcome, refs=refs)
