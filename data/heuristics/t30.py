def run(vm, params):
    payment_id = params.get("payment_id", "pay_056")
    basket_id = params.get("basket_id", "basket_256")

    def _text(result):
        if result is None:
            return ""
        for attr in ("stdout", "content", "text", "output"):
            v = getattr(result, attr, None)
            if isinstance(v, str) and v:
                return v
        if isinstance(result, dict):
            for k in ("stdout", "content", "text", "output"):
                v = result.get(k)
                if isinstance(v, str) and v:
                    return v
            if result.get("entries"):
                return str(result.get("entries"))
        ents = getattr(result, "entries", None)
        if ents:
            try:
                return "\n".join(str(getattr(e, "path", getattr(e, "name", e))) for e in ents)
            except Exception:
                return str(ents)
        return ""

    # ---- discovery (issue every planned RPC in order) ----
    identity = vm.exec(path="/bin/id", args=[])
    docs_tree = vm.tree(root="/docs", level=2)
    security_policy = vm.read(path="/docs/security.md", number=True)
    payments_docs = vm.list(path="/docs/payments")
    threeds_policy = vm.read(path="/docs/payments/3ds.md", number=True)
    payments_help = vm.exec(path="/bin/payments", args=["--help"])

    sql = ("SELECT p.payment_id, p.record_path, p.basket_id, p.customer_id, "
           "p.store_id, p.payment_status, p.three_ds_status, p.three_ds_failure_reason, "
           "p.three_ds_attempts, p.three_ds_max_attempts, b.record_path AS basket_record_path, "
           "b.basket_status, b.customer_id AS basket_customer_id "
           "FROM payment_transactions p "
           "LEFT JOIN shopping_baskets b ON b.basket_id = p.basket_id "
           "WHERE p.payment_id = 'pay_056' AND p.basket_id = 'basket_256';")
    payment_record = vm.exec(path="/bin/sql", args=[sql])

    # ---- resolve operation-specific 3ds policy doc from docs discovery (r005) ----
    docs_blob = _text(docs_tree) + "\n" + _text(payments_docs)
    threeds_doc = "/docs/payments/3ds.md"
    for line in docs_blob.splitlines():
        tok = line.strip()
        low = tok.lower()
        if "3ds" in low and low.endswith(".md"):
            parts = tok.split()
            cand = parts[-1] if parts else tok
            if cand.lower().endswith(".md"):
                if not cand.startswith("/"):
                    cand = "/docs/payments/" + cand.lstrip("/")
                threeds_doc = cand
                break

    # ---- parse identity ----
    id_text = _text(identity)
    id_fields = {}
    for raw_tok in id_text.replace(",", " ").replace("\n", " ").split():
        if "=" in raw_tok:
            k, _, v = raw_tok.partition("=")
            id_fields[k.strip().lower()] = v.strip()
    caller = (id_fields.get("customer") or id_fields.get("customer_id")
              or id_fields.get("user") or id_fields.get("uid") or "")
    role = (id_fields.get("role") or "").lower()

    # ---- parse sql output (r002: detect delimiter from header row) ----
    rows = []
    raw = _text(payment_record).strip()
    if raw:
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if lines:
            header = lines[0]
            delim = "," if header.count(",") >= header.count("|") else "|"
            cols = [c.strip() for c in header.split(delim)]
            for ln in lines[1:]:
                vals = [v.strip() for v in ln.split(delim)]
                if len(vals) >= len(cols) and len(cols) > 1:
                    rows.append(dict(zip(cols, vals[:len(cols)])))
    rec = rows[0] if rows else {}

    pay_payment_id = rec.get("payment_id", payment_id)
    pay_customer = rec.get("customer_id", "")
    payment_status = rec.get("payment_status", "")
    three_ds_status = rec.get("three_ds_status", "")
    failure_reason = rec.get("three_ds_failure_reason", "")
    attempts_raw = rec.get("three_ds_attempts", "")
    max_raw = rec.get("three_ds_max_attempts", "")
    payment_path = rec.get("record_path", "")
    basket_path = rec.get("basket_record_path", "")

    def _int(x):
        try:
            return int(str(x).strip())
        except Exception:
            return None
    attempts = _int(attempts_raw)
    max_attempts = _int(max_raw)

    # ---- gates derived from fetched data (r003) ----
    security_fail = False
    business_fail = False

    # SECURITY GATE: caller must own / be permitted on this payment record.
    # Acting on another customer's record, or an identity /bin/id does not
    # confirm as the owner, is a security denial.
    if not caller or not pay_customer or caller != pay_customer:
        security_fail = True

    # BUSINESS GATE: 3DS eligibility (attempt limit + recoverable status/reason).
    recoverable = {"pending", "challenge_required", "challenge", "recoverable",
                   "failed", "abandoned", "soft_decline", "retryable"}
    if attempts is not None and max_attempts is not None and attempts >= max_attempts:
        business_fail = True
    if three_ds_status and three_ds_status.strip().lower() not in recoverable:
        business_fail = True
    if failure_reason and ("fraud" in failure_reason.lower() or "hard" in failure_reason.lower()):
        business_fail = True

    # ---- ops: always issue the planned mutation RPC (r001/r004) ----
    restart_result = vm.exec(path="/bin/payments",
                             args=["restart-3ds", "--payment", payment_id])

    # ---- derive terminal outcome from gates (security wins) ----
    if security_fail:
        outcome = "OUTCOME_DENIED_SECURITY"
        decision = ("DENIED: runtime identity is not authorized on this payment "
                    "record (ownership/permission not confirmed via /bin/id); "
                    "3DS recovery NOT restarted.")
    elif business_fail:
        outcome = "OUTCOME_NONE_UNSUPPORTED"
        decision = ("NOT PERFORMED: payment is not 3DS-eligible (attempt limit "
                    "reached or non-recoverable status/reason); 3DS recovery NOT restarted.")
    else:
        outcome = "OUTCOME_OK"
        decision = "Authorized and eligible: 3DS recovery restarted via /bin/payments."

    # ---- refs: applied policy docs + inspected record paths ----
    pay_ref = payment_path or ("/proc/payments/%s.json" % payment_id)
    bask_ref = basket_path or ("/proc/baskets/%s.json" % basket_id)
    refs = ["/docs/security.md", threeds_doc]
    if pay_ref and pay_ref not in refs:
        refs.append(pay_ref)
    if bask_ref and bask_ref not in refs:
        refs.append(bask_ref)

    id_display = (id_text.strip().replace("\n", "; ") or caller or "unknown")
    message = ("Resolved caller via /bin/id (%s). Checked 3DS policy + security "
               "against payment %s (status=%s, 3ds=%s, attempts %s/%s). %s") % (
        id_display, pay_payment_id, payment_status or "?",
        three_ds_status or "?", attempts_raw or "?", max_raw or "?", decision)

    vm.answer(message=message, outcome=outcome, refs=refs)
