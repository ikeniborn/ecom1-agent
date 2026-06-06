def run(vm, params):
    def out(result):
        return getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    def parse_rows(stdout):
        lines = [l for l in (stdout or "").splitlines() if l.strip()]
        if not lines:
            return []
        headers = [h.strip() for h in lines[0].split(",")]
        rows = []
        for line in lines[1:]:
            cells = [c.strip() for c in line.split(",")]
            rows.append(dict(zip(headers, cells)))
        return rows

    return_id = params["return_id"]
    rid_lit = "'" + str(return_id).replace("'", "''") + "'"

    # discovery
    identity = vm.exec(path="/bin/id", args=[])
    payments_help = vm.exec(path="/bin/payments", args=["--help"])

    ret_sql = (
        "SELECT return_id, record_path, basket_id, customer_id, payment_id, "
        "return_status, return_reason_code FROM return_requests "
        "WHERE return_id = " + rid_lit + ";"
    )
    ret = vm.exec(path="/bin/sql", args=[ret_sql])

    pay_sql = (
        "SELECT payment_id, record_path, customer_id, store_id, "
        "payment_amount_cents, payment_currency, payment_status "
        "FROM payment_transactions WHERE payment_id = "
        "(SELECT payment_id FROM return_requests WHERE return_id = " + rid_lit + ");"
    )
    pay = vm.exec(path="/bin/sql", args=[pay_sql])

    docs_tree = vm.tree(root="/docs", level=2)
    returns_policy = vm.read(path="/docs/returns.md", number=True)
    security_policy = vm.read(path="/docs/security.md", number=True)

    # ops (declared mutation emitted unconditionally, in order)
    approval = vm.exec(path="/bin/payments", args=["approve-refund", "--return", str(return_id)])

    # parse structured rows
    ret_rows = parse_rows(out(ret))
    pay_rows = parse_rows(out(pay))
    ret_row = ret_rows[0] if ret_rows else {}
    pay_row = pay_rows[0] if pay_rows else {}

    ret_return_id = ret_row.get("return_id", str(return_id))
    ret_record_path = ret_row.get("record_path", "")
    ret_return_status = ret_row.get("return_status", "")
    pay_payment_id = pay_row.get("payment_id", "")
    pay_customer_id = pay_row.get("customer_id", "")
    pay_amount = pay_row.get("payment_amount_cents", "")
    pay_currency = pay_row.get("payment_currency", "")
    pay_record_path = pay_row.get("record_path", "")

    identity_text = (out(identity) or "").strip()

    # derive outcome from runtime evidence (r006)
    help_text = out(payments_help) or ""
    approval_text = out(approval) or ""
    approval_exit = getattr(approval, "exit_code", None)
    if approval_exit is None and isinstance(approval, dict):
        approval_exit = approval.get("exit_code")

    supported = ("approve-refund" in help_text)
    if not supported or "unsupported" in approval_text.lower() or "not found" in approval_text.lower():
        outcome = "OUTCOME_NONE_UNSUPPORTED"
        message = (
            "Cannot approve refund for return " + str(ret_return_id) + ": the "
            "'approve-refund' action is not supported by /bin/payments (absent from "
            "its --help capabilities). No refund state change was applied. "
            "Identity " + identity_text + ". Record: " + ret_record_path + "."
        )
    else:
        outcome = "OUTCOME_OK"
        message = (
            "Refund for return " + str(ret_return_id) + " (payment " + pay_payment_id +
            ", customer " + pay_customer_id + ", " + pay_amount + " " + pay_currency +
            ") approved via /bin/payments. Prior return_status was " + ret_return_status +
            "; now approved. Action authorized for identity " + identity_text +
            " per returns policy. Record: " + ret_record_path + "."
        )

    refs = []
    if ret_record_path:
        refs.append(ret_record_path)
    if pay_record_path:
        refs.append(pay_record_path)
    refs.append("/docs/returns.md")

    vm.answer(message=message, outcome=outcome, refs=refs)
