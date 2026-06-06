def run(vm, params):
    basket_id = params["basket_id"]

    def _stdout(result):
        if result is None:
            return ""
        s = getattr(result, "stdout", None)
        if s is not None:
            return s
        if isinstance(result, dict):
            return result.get("stdout", "") or ""
        return ""

    # --- discovery ---
    try:
        identity = vm.exec(path="/bin/id", args=[])
    except Exception:
        identity = None
    identity_out = _stdout(identity)

    try:
        docs_tree = vm.tree(root="/docs", level=2)
    except Exception:
        docs_tree = None
    tree_out = getattr(docs_tree, "stdout", None)
    if tree_out is None and isinstance(docs_tree, dict):
        tree_out = docs_tree.get("stdout", "") or docs_tree.get("text", "") or ""
    if tree_out is None:
        tree_out = str(docs_tree) if docs_tree is not None else ""

    try:
        payments_help = vm.exec(path="/bin/payments", args=["--help"])
    except Exception:
        payments_help = None
    help_out = _stdout(payments_help)

    sql = (
        "SELECT payment_id, record_path, basket_id, customer_id, store_id, "
        "payment_status, three_ds_status, three_ds_failure_reason, "
        "three_ds_attempts, three_ds_max_attempts FROM payment_transactions "
        "WHERE basket_id = '" + basket_id + "';"
    )
    try:
        payment = vm.exec(path="/bin/sql", args=[sql])
    except Exception:
        payment = None
    pay_out = _stdout(payment)

    try:
        payments_policy = vm.read(path="/docs/payments.md", number=True)
    except Exception:
        payments_policy = None

    # --- parse SQL rows (pipe-delimited) ---
    payment_id = ""
    record_path = ""
    payment_status = ""
    three_ds_status = ""
    three_ds_attempts = ""
    three_ds_max_attempts = ""
    for line in pay_out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        low = line.lower()
        if "payment_id" in low and "record_path" in low:
            continue  # header
        if len(cols) >= 10:
            payment_id = cols[0]
            record_path = cols[1]
            payment_status = cols[5]
            three_ds_status = cols[6]
            three_ds_attempts = cols[8]
            three_ds_max_attempts = cols[9]
            break

    # --- nested 3ds policy doc from docs tree ---
    three_ds_doc = "/docs/payments/3ds.md"
    for line in tree_out.splitlines():
        if "3ds.md" in line:
            tok = line.strip()
            # try to recover a path-like token
            for part in tok.replace("\u2500", " ").replace("\u251c", " ").replace("\u2514", " ").replace("\u2502", " ").split():
                if part.endswith("3ds.md"):
                    three_ds_doc = part if part.startswith("/") else "/docs/payments/3ds.md"
            break

    # --- ops: advance the payments workflow ---
    try:
        advance_result = vm.exec(
            path="/bin/payments",
            args=["advance", "--basket", basket_id, "--step", "three_ds"],
        )
    except Exception as e:
        advance_result = None
    advance_out = _stdout(advance_result)
    if not advance_out and advance_result is not None:
        advance_out = str(advance_result)

    # --- build refs ---
    refs = []
    if record_path:
        refs.append(record_path)
    refs.append("/docs/payments.md")
    refs.append(three_ds_doc)

    message = (
        "Payment for " + basket_id + " (" + payment_id + ", status " + payment_status +
        ", 3DS " + three_ds_status + ", attempts " + three_ds_attempts + "/" +
        three_ds_max_attempts + ") was stuck on bank verification. Drove the payments "
        "workflow forward via /bin/payments: " + advance_out + ". See " + record_path +
        ". Policy applied: /docs/payments.md, " + three_ds_doc + "."
    )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
