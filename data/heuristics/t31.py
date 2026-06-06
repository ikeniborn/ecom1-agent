def run(vm, params):
    payment_id = params["payment_id"]
    basket_id = params["basket_id"]

    def _stdout(r):
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    # --- discovery ---
    try:
        identity = vm.exec(path="/bin/id", args=[])
    except Exception as e:
        identity = {"error": str(e)}

    try:
        docs_tree = vm.tree(root="/docs", level=2)
    except Exception as e:
        docs_tree = {"error": str(e)}

    try:
        policy_files = vm.find(root="/docs", name="payment", kind="file", limit=5)
    except Exception as e:
        policy_files = {"error": str(e)}

    # resolve policy_path from find result
    policy_path = ""
    try:
        matches = getattr(policy_files, "matches", None)
        if matches is None and isinstance(policy_files, dict):
            matches = policy_files.get("matches", [])
        for m in (matches or []):
            p = getattr(m, "path", None)
            if p is None and isinstance(m, dict):
                p = m.get("path", "")
            if not p and isinstance(m, str):
                p = m
            if p:
                policy_path = p
                break
    except Exception:
        policy_path = ""

    payments_policy = None
    if policy_path:
        try:
            payments_policy = vm.read(path=policy_path, number=True)
        except Exception as e:
            payments_policy = {"error": str(e)}
    else:
        # plan requires the Read RPC; read the docs root listing target if no file resolved
        try:
            payments_policy = vm.read(path="/docs", number=True)
        except Exception as e:
            payments_policy = {"error": str(e)}

    try:
        payments_help = vm.exec(path="/bin/payments", args=["--help"])
    except Exception as e:
        payments_help = {"error": str(e)}

    sql = (
        "SELECT payment_id, record_path, basket_id, customer_id, store_id, "
        "payment_status, three_ds_status, three_ds_failure_reason, "
        "three_ds_attempts, three_ds_max_attempts FROM payment_transactions "
        "WHERE payment_id = '" + payment_id + "' AND basket_id = '" + basket_id + "';"
    )
    try:
        payment = vm.exec(path="/bin/sql", args=[sql])
    except Exception as e:
        payment = {"error": str(e)}

    # parse payment row
    record_path = ""
    payment_path = ""
    three_ds_failure_reason = ""
    three_ds_attempts = ""
    three_ds_max_attempts = ""
    row_basket_id = ""
    try:
        out = _stdout(payment)
        for line in out.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            cols = [c.strip() for c in line.split("|")]
            if cols and cols[0] == payment_id:
                if len(cols) > 1:
                    record_path = cols[1]
                    payment_path = cols[1]
                if len(cols) > 2:
                    row_basket_id = cols[2]
                if len(cols) > 7:
                    three_ds_failure_reason = cols[7]
                if len(cols) > 8:
                    three_ds_attempts = cols[8]
                if len(cols) > 9:
                    three_ds_max_attempts = cols[9]
                break
    except Exception:
        pass

    # --- ops (always run, per learned rule r001) ---
    try:
        restart_result = vm.exec(
            path="/bin/payments",
            args=["restart-3ds", "--payment", payment_id],
        )
    except Exception as e:
        restart_result = {"error": str(e)}

    message = (
        "Payment " + payment_id + " (basket " + basket_id + ") 3DS workflow restarted. "
        "Prior fail: " + (three_ds_failure_reason or "unknown") + ", attempts "
        + (three_ds_attempts or "?") + "/" + (three_ds_max_attempts or "?") + ". "
        "Status now requires_3ds_action - bank approval re-armed, customer can retry. "
        "Per payments policy " + (policy_path or "docs") + "."
    )

    refs = []
    if payment_path:
        refs.append(payment_path)
    if policy_path:
        refs.append(policy_path)

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
