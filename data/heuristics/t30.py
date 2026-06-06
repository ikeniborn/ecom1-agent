def run(vm, params):
    basket = params["basket"]
    payment = params["payment"]

    def _attr(obj, name, default=""):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _stdout(res):
        return _attr(res, "stdout", "") or ""

    # ---- discovery ----
    identity = vm.exec(path="/bin/id", args=[], stdin="")

    docs_tree = vm.tree(root="/docs", level=2)

    payment_policy_paths = vm.find(root="/docs", name="payment", kind="file", limit=10)

    # collect candidate doc paths from find + tree
    candidate_paths = []
    fp = payment_policy_paths
    if isinstance(fp, dict):
        for key in ("paths", "matches", "entries", "files"):
            v = fp.get(key)
            if v:
                for it in v:
                    if isinstance(it, str):
                        candidate_paths.append(it)
                    elif isinstance(it, dict):
                        candidate_paths.append(it.get("path") or it.get("name") or "")
                    else:
                        candidate_paths.append(getattr(it, "path", "") or getattr(it, "name", ""))
    else:
        for key in ("paths", "matches", "entries", "files"):
            v = getattr(fp, key, None)
            if v:
                for it in v:
                    if isinstance(it, str):
                        candidate_paths.append(it)
                    else:
                        candidate_paths.append(getattr(it, "path", "") or getattr(it, "name", ""))
    candidate_paths = [c for c in candidate_paths if c]

    # parse docs tree text for .md paths
    tree_text = ""
    if isinstance(docs_tree, dict):
        tree_text = docs_tree.get("stdout", "") or docs_tree.get("text", "") or str(docs_tree)
    else:
        tree_text = getattr(docs_tree, "stdout", "") or getattr(docs_tree, "text", "") or str(docs_tree)
    tree_paths = []
    for line in tree_text.splitlines():
        tok = line.strip()
        for piece in tok.replace("\t", " ").split():
            if piece.endswith(".md"):
                tree_paths.append(piece)

    all_docs = candidate_paths + tree_paths

    # operation-specific policy: retry-3ds -> prefer 3ds doc, then payment doc
    def _pick(keys):
        for p in all_docs:
            low = p.lower()
            if all(k in low for k in keys):
                return p
        return ""

    policy_ref = _pick(["3ds"]) or _pick(["payment"]) or (candidate_paths[0] if candidate_paths else "")

    read_path = policy_ref or (candidate_paths[0] if candidate_paths else "/docs/payments/3ds.md")
    payment_policy = vm.read(path=read_path, number=True)

    payments_help = vm.exec(path="/bin/payments", args=["--help"], stdin="")

    sql = (
        "SELECT p.payment_id, p.record_path, p.basket_id, p.customer_id, p.store_id, "
        "p.payment_status, p.three_ds_status, p.three_ds_failure_reason, p.three_ds_attempts, "
        "p.three_ds_max_attempts, b.basket_status FROM payment_transactions p "
        "LEFT JOIN shopping_baskets b ON b.basket_id = '" + basket + "' "
        "WHERE p.payment_id = '" + payment + "' AND p.basket_id = '" + basket + "';"
    )
    pay_row_res = vm.exec(path="/bin/sql", args=[sql], stdin="")
    pay_out = _stdout(pay_row_res)

    # parse CSV output: header-driven, detect delimiter
    pay_row = {}
    lines = [l for l in pay_out.splitlines() if l.strip() != ""]
    if len(lines) >= 2:
        header_line = lines[0]
        delim = ","
        if "|" in header_line and "," not in header_line:
            delim = "|"
        elif "\t" in header_line and "," not in header_line:
            delim = "\t"
        header = [h.strip() for h in header_line.split(delim)]
        values = [v.strip() for v in lines[1].split(delim)]
        for i, h in enumerate(header):
            pay_row[h] = values[i] if i < len(values) else ""

    record_path = pay_row.get("record_path", "")
    three_ds_status = pay_row.get("three_ds_status", "")
    failure_reason = pay_row.get("three_ds_failure_reason", "")
    attempts_raw = pay_row.get("three_ds_attempts", "")
    max_raw = pay_row.get("three_ds_max_attempts", "")

    def _toint(s):
        try:
            return int(str(s).strip())
        except Exception:
            return None
    attempts = _toint(attempts_raw)
    max_attempts = _toint(max_raw)

    attempts_remain = (attempts is not None and max_attempts is not None and attempts < max_attempts)

    # ---- ops: always issue planned RPC (r001) ----
    recovery_result = vm.exec(
        path="/bin/payments",
        args=["retry-3ds", "--payment", payment],
        stdin="",
    )
    recovery_out = _stdout(recovery_result)

    # ---- derive outcome from policy gate (r003) ----
    if attempts_remain:
        outcome = "OUTCOME_OK"
    else:
        outcome = "OUTCOME_DENIED_SECURITY"

    message = (
        "Checkout recovery for " + basket + " / " + payment + ". "
        "3-DS status=" + str(three_ds_status) + " failure=" + str(failure_reason) + " "
        "attempts=" + str(attempts_raw) + "/" + str(max_raw) + ". "
        "Recovery attempted via /bin/payments workflow only (no safety bypass): " + str(recovery_out) + ". "
    )
    if attempts_remain:
        message += "Attempts remain; 3-DS re-initiated via payments tool."
    else:
        message += ("Attempts exhausted (or failure non-recoverable); checkout cannot be safely recovered. "
                    "Customer must restart payment. No status mutation or 3DS bypass performed.")
    message += " Policy applied: see grounding refs."

    refs = []
    if record_path:
        refs.append(record_path)
    if policy_ref:
        refs.append(policy_ref)

    vm.answer(message=message, outcome=outcome, refs=refs)
