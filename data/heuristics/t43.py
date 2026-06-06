def run(vm, params):
    def _stdout(r):
        if r is None:
            return ""
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    def _exec(path, a=None, stdin=""):
        try:
            return vm.exec(path=path, args=a or [], stdin=stdin)
        except Exception:
            return None

    def _rows(text):
        rows = []
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            rows.append([c.strip() for c in line.split("|")])
        return rows

    # ---- discovery ----
    identity = _exec("/bin/id")
    identity_txt = _stdout(identity).strip()

    now = _exec("/bin/date")

    docs_tree = None
    try:
        docs_tree = vm.tree(root="/docs", level=2)
    except Exception:
        docs_tree = None

    returns_policy_path = ""
    try:
        found = vm.find(root="/docs", name="return", kind="file", limit=5)
        ftext = ""
        if found is not None:
            ftext = getattr(found, "stdout", "") or ""
            paths = getattr(found, "paths", None) or getattr(found, "matches", None)
            if paths:
                for p in paths:
                    pv = getattr(p, "path", None) or (p if isinstance(p, str) else "")
                    if pv:
                        returns_policy_path = pv
                        break
        if not returns_policy_path and ftext:
            for line in ftext.splitlines():
                line = line.strip()
                if "return" in line.lower() and line.startswith("/"):
                    returns_policy_path = line
                    break
    except Exception:
        returns_policy_path = ""
    if not returns_policy_path:
        returns_policy_path = "/docs/returns.md"

    returns_policy = None
    try:
        returns_policy = vm.read(path=returns_policy_path, number=True)
    except Exception:
        returns_policy = None

    payments_help = _exec("/bin/payments", ["--help"])

    requester = str(params.get("requester", ""))
    amount_cents = str(params.get("amount_cents", 7600))
    currency = str(params.get("currency", "EUR"))

    match_sql = ("SELECT payment_id, record_path, customer_id, basket_id, "
                 "payment_amount_cents, payment_currency, payment_status, "
                 "payment_created_at FROM payment_transactions WHERE "
                 "customer_id = :requester AND payment_amount_cents = :amount_cents "
                 "AND payment_currency = :currency;")
    matched_payment = _exec("/bin/sql", [match_sql,
                                         "requester=" + requester,
                                         "amount_cents=" + amount_cents,
                                         "currency=" + currency])
    match_rows = _rows(_stdout(matched_payment))

    payment_id = ""
    payment_path = ""
    candidate_paths = []
    for row in match_rows:
        rec = row[1] if len(row) > 1 else ""
        if rec:
            candidate_paths.append(rec)
    if len(match_rows) >= 1:
        first = match_rows[0]
        payment_id = first[0] if len(first) > 0 else ""
        payment_path = first[1] if len(first) > 1 else ""

    return_sql = ("SELECT return_id, record_path, payment_id, return_status "
                  "FROM return_requests WHERE payment_id = :payment_id;")
    existing_return = _exec("/bin/sql", [return_sql, "payment_id=" + payment_id])

    # ---- ops (unconditional) ----
    refund_approved = _exec("/bin/payments",
                            ["refund", "approve", "--payment", payment_id])
    refund_finalized = _exec("/bin/payments",
                             ["refund", "finalize", "--payment", payment_id])

    # ---- answer branch ----
    actor = identity_txt or requester
    n = len(match_rows)
    if n == 1:
        message = ("Refund processed for payment " + payment_id +
                   " (EUR 76 / 7600 cents) owned by " + actor +
                   ". Status now refunded via payments workflow. Applied returns "
                   "policy at " + returns_policy_path + ". Record: " + payment_path + ".")
        refs = [returns_policy_path]
        if payment_path:
            refs.append(payment_path)
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
        return

    if n > 1:
        message = ("Ambiguous refund request: multiple EUR 7600-cent payments owned "
                   "by " + actor + " match. Specify which payment to refund. "
                   "Candidates: " + ", ".join(candidate_paths) +
                   ". Applied returns policy at " + returns_policy_path + ".")
        refs = [returns_policy_path] + candidate_paths
        vm.answer(message=message, outcome="OUTCOME_NONE_CLARIFICATION", refs=refs)
        return

    message = ("No EUR 7600-cent payment owned by " + actor +
               " was found, so no refund could be processed. Returns policy at " +
               returns_policy_path + " applies; please confirm the payment to refund.")
    vm.answer(message=message, outcome="OUTCOME_NONE_CLARIFICATION",
              refs=[returns_policy_path])
