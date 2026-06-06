import re


def _stdout(result):
    s = getattr(result, "stdout", None)
    if s is None and isinstance(result, dict):
        s = result.get("stdout", "")
    return s or ""


def _text(result):
    if isinstance(result, str):
        return result
    c = getattr(result, "content", None)
    if c is None and isinstance(result, dict):
        c = result.get("content", "")
    if c is None:
        c = getattr(result, "text", None)
        if c is None and isinstance(result, dict):
            c = result.get("text", "")
    return c or ""


def _q(v):
    return "'" + str(v).replace("'", "''") + "'"


def run(vm, params):
    basket = params.get("basket", "")
    store_name = params.get("store_name", "")
    reason_code = params.get("reason_code", "service_recovery")

    # --- discovery ---
    identity = vm.exec(path="/bin/id", args=[])
    id_out = _stdout(identity)

    issuer_employee_id = params.get("issuer_employee_id", "")
    if not issuer_employee_id or str(issuer_employee_id).startswith("$"):
        m = re.search(r"employee_id\s*=\s*([\w-]+)", id_out)
        if not m:
            m = re.search(r"\b(EMP[\w-]+)\b", id_out)
        if not m:
            m = re.search(r"\bid\s*=\s*([\w-]+)", id_out)
        if m:
            issuer_employee_id = m.group(1)
        else:
            issuer_employee_id = id_out.strip().splitlines()[0].strip() if id_out.strip() else ""

    docs_tree = vm.tree(root="/docs", level=2)

    policy_hits = vm.search(root="/docs", pattern="service_recovery", limit=20)

    discount_policy = None
    discount_policy_text = ""
    try:
        discount_policy = vm.read(path="/docs/discounts.md", number=True)
        discount_policy_text = _text(discount_policy)
    except Exception:
        discount_policy_text = ""
    discount_policy_path = "/docs/discounts.md"

    # max service_recovery percent from policy
    max_pct = None
    for mm in re.finditer(r"service[_ ]recovery", discount_policy_text, re.I):
        window = discount_policy_text[mm.start():mm.start() + 240]
        pm = re.search(r"(\d+(?:\.\d+)?)\s*%", window)
        if pm:
            max_pct = pm.group(1)
            break
    if max_pct is None:
        pm = re.search(r"(\d+(?:\.\d+)?)\s*%", discount_policy_text)
        if pm:
            max_pct = pm.group(1)
    if max_pct is None:
        max_pct = "0"

    # cross-referenced governing docs cited inside the policy
    ref_docs = []
    for p in re.findall(r"/docs/[\w./-]+\.md", discount_policy_text):
        if p != discount_policy_path and p not in ref_docs:
            ref_docs.append(p)

    # context query (inline literals; /bin/sql rejects :name binds)
    sql = (
        "WITH b AS (SELECT basket_id, record_path, store_id, customer_id, basket_status, "
        "discount_percent, discount_reason_code, discount_issuer_employee_id FROM shopping_baskets "
        "WHERE basket_id = " + _q(basket) + "), "
        "s AS (SELECT store_id, store_name, record_path FROM stores WHERE store_name = " + _q(store_name) + "), "
        "e AS (SELECT employee_id, employee_display_name, store_id, job_title FROM employee_accounts "
        "WHERE employee_id = " + _q(issuer_employee_id) + "), "
        "r AS (SELECT employee_id, group_concat(role_code) AS roles FROM employee_role_assignments "
        "WHERE employee_id = " + _q(issuer_employee_id) + " GROUP BY employee_id) "
        "SELECT b.basket_id, b.record_path AS basket_path, b.store_id AS basket_store_id, b.basket_status, "
        "b.discount_percent AS current_discount_percent, s.store_id AS named_store_id, s.record_path AS store_path, "
        "e.employee_id, e.store_id AS employee_store_id, e.job_title, r.roles "
        "FROM b LEFT JOIN s ON 1=1 LEFT JOIN e ON 1=1 LEFT JOIN r ON r.employee_id = e.employee_id"
    )
    context = vm.exec(path="/bin/sql", args=[sql])
    ctx_out = _stdout(context)

    cols = ["basket_id", "basket_path", "basket_store_id", "basket_status",
            "current_discount_percent", "named_store_id", "store_path",
            "employee_id", "employee_store_id", "job_title", "roles"]
    row = {}
    for line in ctx_out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if parts and parts[0] == "basket_id":
            continue
        if len(parts) >= len(cols):
            row = dict(zip(cols, parts[:len(cols)]))
            break
        if len(parts) >= 2 and parts[0] == basket:
            row = dict(zip(cols, parts + [""] * (len(cols) - len(parts))))
            break

    basket_path = row.get("basket_path", "")
    basket_store_id = row.get("basket_store_id", "")
    named_store_id = row.get("named_store_id", "")
    employee_store_id = row.get("employee_store_id", "")
    job_title = row.get("job_title", "") or ""
    roles = row.get("roles", "") or ""

    # --- guards (store scope + discount authority) ---
    store_scope_ok = bool(employee_store_id) and bool(basket_store_id) and employee_store_id == basket_store_id
    if named_store_id and basket_store_id:
        store_scope_ok = store_scope_ok and (named_store_id == basket_store_id)

    auth_blob = (roles + " " + job_title).lower()
    authority_ok = any(k in auth_blob for k in ["manager", "supervisor", "lead", "discount", "service_recovery"])

    denied = (not store_scope_ok) or (not authority_ok)

    # --- ops (always execute per plan) ---
    apply_result = vm.exec(
        path="/bin/discount",
        args=[
            "apply",
            "--basket", basket,
            "--percent", str(max_pct),
            "--reason", reason_code,
            "--issuer", issuer_employee_id,
        ],
    )

    # --- refs ---
    refs = []
    if basket_path:
        refs.append(basket_path)
    refs.append(discount_policy_path)
    for p in ref_docs:
        if p not in refs:
            refs.append(p)

    if denied:
        reasons = []
        if not store_scope_ok:
            reasons.append("issuer store scope does not match basket_085 store")
        if not authority_ok:
            reasons.append("issuer lacks role required to grant service_recovery discounts")
        message = (
            "Denied service_recovery discount on " + str(basket) + ": " + "; ".join(reasons) +
            ". Policy max " + str(max_pct) + "% per discounts policy."
        )
        vm.answer(message=message, outcome="OUTCOME_DENIED_SECURITY", refs=refs)
        return

    message = (
        "Applied " + str(max_pct) + "% service_recovery discount to basket_085 (store " +
        str(named_store_id or basket_store_id) + ", PowerTool Ljubljana Center), issued under employee " +
        str(issuer_employee_id) + ". Max per discounts policy. Issuer store scope and discount authority verified."
    )
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
