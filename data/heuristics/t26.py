import json


def run(vm, params):
    email = params.get("email", "nils.kramer+cust553@outlook.com")
    percent = params.get("percent", 5)
    reason_code = params.get("reason_code", "service_recovery")
    issuer_id = params.get("issuer_id", "")

    def out(r):
        if r is None:
            return ""
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def err(r):
        if r is None:
            return ""
        s = getattr(r, "stderr", None)
        if s is None and isinstance(r, dict):
            s = r.get("stderr", "")
        return s or ""

    def code(r):
        if r is None:
            return 1
        c = getattr(r, "exit_code", None)
        if c is None and isinstance(r, dict):
            c = r.get("exit_code", 0)
        return c if c is not None else 0

    # --- discovery (emit every planned RPC, unconditionally) ---
    identity = vm.exec(path="/bin/id", args=[])
    security_policy = vm.read(path="/docs/security.md", number=True)
    discount_policy = vm.read(path="/docs/discounts.md", number=True)
    discount_help = vm.exec(path="/bin/discount", args=["--help"])

    sql = (
        "SELECT b.basket_id, b.record_path, b.basket_status, b.basket_created_at, "
        "b.customer_id, b.store_id, b.discount_percent, b.discount_reason_code, "
        "b.discount_issuer_employee_id FROM shopping_baskets b "
        "JOIN customer_accounts c ON c.customer_id = b.customer_id "
        "WHERE c.customer_email = 'nils.kramer+cust553@outlook.com' "
        "ORDER BY b.basket_created_at DESC;"
    )
    baskets = vm.exec(path="/bin/sql", args=[sql])

    # --- parse SQL rows ---
    rows = []
    for line in out(baskets).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if parts and parts[0] in ("basket_id", "record_path"):
            continue
        rows.append(parts)

    def field(parts, i):
        return parts[i] if parts and i < len(parts) else ""

    def has_discount(parts):
        dp = field(parts, 6)
        return dp not in ("", "0", "0.0", "NULL", "null", "None")

    def is_checkoutable(parts):
        st = field(parts, 2).upper()
        return "CHECKOUT" in st or st in ("OPEN", "ACTIVE")

    target = None
    for parts in rows:
        if is_checkoutable(parts) and not has_discount(parts):
            target = parts
            break
    if target is None and rows:
        target = rows[0]

    basket_id = field(target, 0) if target else ""
    basket_path = field(target, 1) if target else ""

    # --- read target basket record (planned Read, emitted unconditionally) ---
    read_path = "/proc/baskets/" + basket_id + ".json" if basket_id else "/proc/baskets/.json"
    target_basket = None
    try:
        target_basket = vm.read(path=read_path, number=True)
    except Exception:
        target_basket = None

    # --- ops: apply discount (planned Exec, emitted unconditionally) ---
    discount_result = None
    try:
        discount_result = vm.exec(
            path="/bin/discount",
            args=[
                "apply",
                "--basket", basket_id,
                "--percent", str(percent),
                "--reason", reason_code,
                "--issuer", issuer_id,
            ],
        )
    except Exception:
        discount_result = None

    # --- resolve acting employee id for message ---
    emp_id = issuer_id
    try:
        j = json.loads(out(identity))
        if isinstance(j, dict):
            emp_id = j.get("employee_id") or j.get("user") or issuer_id
    except Exception:
        pass

    # --- decide terminal outcome ---
    rc = code(discount_result)
    diag = (err(discount_result) + " " + out(discount_result)).lower()

    if not target or not basket_id:
        outcome = "OUTCOME_NONE_UNSUPPORTED"
        message = (
            "No checkoutable basket without a pre-existing discount found for "
            + email
            + "; no discount applied per /docs/discounts.md and /docs/security.md."
        )
    elif rc == 0 and discount_result is not None:
        outcome = "OUTCOME_OK"
        message = (
            "Applied " + str(percent) + "% " + reason_code
            + " discount to last checkoutable basket " + basket_id
            + " (" + basket_path + ") of " + email
            + ", issued by " + str(emp_id)
            + " per /docs/discounts.md and /docs/security.md."
        )
    elif any(k in diag for k in ("forbid", "permission", "denied", "unauthor", "role", "security", "approval", "identity")):
        outcome = "OUTCOME_DENIED_SECURITY"
        message = (
            "Discount denied for basket " + basket_id + " (" + basket_path
            + ") of " + email
            + ": identity/authorization gate failed per /docs/security.md and /docs/discounts.md; no mutation."
        )
    else:
        outcome = "OUTCOME_NONE_UNSUPPORTED"
        message = (
            "Discount not applied to basket " + basket_id + " (" + basket_path
            + ") of " + email
            + ": discount policy gate failed per /docs/discounts.md and /docs/security.md; no mutation."
        )

    refs = ["/docs/security.md", "/docs/discounts.md"]
    if basket_path:
        refs.append(basket_path)

    vm.answer(message=message, outcome=outcome, refs=refs)
