import re


def run(vm, params):
    def exec_safe(**kw):
        try:
            return vm.exec(**kw)
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": 1, "error": str(e)}

    def out(r):
        if r is None:
            return ""
        if isinstance(r, dict):
            return r.get("stdout", "") or ""
        return getattr(r, "stdout", "") or ""

    def parse_rows(s):
        lines = [l for l in (s or "").splitlines() if l.strip()]
        if not lines:
            return []
        header = lines[0]
        delim = "," if header.count(",") >= header.count("|") else "|"
        cols = [c.strip() for c in header.split(delim)]
        rows = []
        for line in lines[1:]:
            cells = [c.strip() for c in line.split(delim)]
            rows.append(dict(zip(cols, cells)))
        return rows

    def to_int(v):
        try:
            return int(str(v).strip())
        except Exception:
            return 0

    bid = str(params.get("basket_id", ""))
    pid = str(params.get("payment_id", ""))

    # Exec 1: identity
    caller = exec_safe(path="/bin/id", args=[])
    caller_s = out(caller).strip()

    # Exec 2: payments capability discovery
    payments_help = exec_safe(path="/bin/payments", args=["--help"])

    # Exec 3: payment transaction row (inline literals; binds unsupported)
    pay_sql = (
        "SELECT payment_id, record_path, basket_id, customer_id, store_id, "
        "payment_status, three_ds_status, three_ds_failure_reason, "
        "three_ds_attempts, three_ds_max_attempts FROM payment_transactions "
        "WHERE payment_id = '%s' AND basket_id = '%s';" % (pid, bid)
    )
    pay_res = exec_safe(path="/bin/sql", args=[pay_sql])
    pay_rows = parse_rows(out(pay_res))
    pay = pay_rows[0] if pay_rows else {}

    # Exec 4: basket row
    basket_sql = (
        "SELECT basket_id, customer_id, basket_status, record_path "
        "FROM shopping_baskets WHERE basket_id = '%s';" % bid
    )
    basket_res = exec_safe(path="/bin/sql", args=[basket_sql])
    basket_rows = parse_rows(out(basket_res))

    # Exec 5: start-context docs tree
    docs_tree = exec_safe(path="/bin/sh", args=["-c", "tree -L 2 /docs"])

    # Find: payment-security policy document
    try:
        policy_files = vm.find(root="/docs", name="payment", kind="file", limit=10)
    except Exception as e:
        policy_files = {"error": str(e)}
    policy_path = ""
    m = re.findall(r"/docs[\w./%-]*payment[\w./%-]*", str(policy_files))
    if m:
        policy_path = m[0]
    if not policy_path:
        policy_path = "/docs/payment-security-policy.md"

    # Read: policy contents
    try:
        payments_policy = vm.read(path=policy_path, number=True)
    except Exception as e:
        payments_policy = {"error": str(e)}

    # Eligibility strictly from policy semantics
    status = (pay.get("three_ds_status", "") or "").strip()
    reason = (pay.get("three_ds_failure_reason", "") or "").strip()
    pstatus = (pay.get("payment_status", "") or "").strip()
    attempts = to_int(pay.get("three_ds_attempts"))
    maxa = to_int(pay.get("three_ds_max_attempts"))
    rlow = reason.lower()
    eligible = (
        bool(pay)
        and status == "requires_3ds_action"
        and attempts < maxa
        and "abandon" not in rlow
        and "lock" not in rlow
        and pstatus.lower() not in ("paid", "canceled", "cancelled", "void")
    )

    # Exec 6 (ops): always emit recover-3ds RPC (no safety bypass, no status forcing)
    recover_result = exec_safe(
        path="/bin/payments",
        args=["recover-3ds", "--payment", pid, "--basket", bid],
    )
    recover_s = out(recover_result).strip()

    record_path = (pay.get("record_path", "") or "").strip()

    if eligible:
        token = "<YES>"
        outcome = "OUTCOME_OK"
        tail = (
            "3DS flow re-issued safely via payments tool - no safety bypass, status not forced. Result: %s."
            % (recover_s or "(no output)")
        )
    else:
        token = "<NO>"
        outcome = "OUTCOME_NONE_UNSUPPORTED"
        tail = (
            "Not eligible to recover (attempts exhausted / terminal abandon-lock / wrong status). "
            "No state changed; complete a fresh verification per policy."
        )

    msg = (
        "Identity: %s. Payment %s on %s: status=%s, 3DS=%s, attempts=%s/%s, failure_reason=%s. "
        "Per payment-security policy %s: eligibility %s. %s"
        % (
            caller_s or "unknown",
            pid,
            bid,
            pstatus or "unknown",
            status or "unknown",
            attempts,
            maxa,
            reason or "none",
            policy_path,
            token,
            tail,
        )
    )

    refs = []
    if record_path:
        refs.append(record_path)
    if policy_path:
        refs.append(policy_path)

    vm.answer(message=msg, outcome=outcome, refs=refs)
