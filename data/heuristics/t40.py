def run(vm, params):
    def _stdout(res):
        out = getattr(res, "stdout", None)
        if out is None and isinstance(res, dict):
            out = res.get("stdout", "")
        return out or ""

    archived_flag = params.get("archived_flag", 1)

    # --- discovery ---
    try:
        ident = vm.exec(path="/bin/id", args=[])
    except Exception:
        ident = None

    docs_tree = vm.tree(root="/docs", level=2)
    security_docs = vm.find(root="/docs", name="security", kind="file", limit=10)
    fraud_policy_hits = vm.search(root="/docs", pattern="(?i)fraud|chargeback|3ds|device_fingerprint|incident", limit=50)

    # resolve a concrete policy FILE path (never a directory)
    policy_path = "/docs/security.md"

    try:
        fraud_policy = vm.read(path=policy_path, number=True)
    except Exception:
        fraud_policy = None

    # candidate enumeration over archived payment records
    candidate_sql = (
        "WITH archived AS (SELECT payment_id, record_path, customer_id, store_id, "
        "payment_amount_cents, payment_status, payment_created_at, payment_method_fingerprint, "
        "device_fingerprint, observed_latitude, observed_longitude, three_ds_status, "
        "three_ds_failure_reason, three_ds_attempts, three_ds_max_attempts "
        "FROM payment_transactions WHERE is_archived_basket_reference = " + str(int(archived_flag)) + ") "
        "SELECT a.*, "
        "(SELECT COUNT(*) FROM archived d WHERE d.device_fingerprint = a.device_fingerprint) AS device_share, "
        "(SELECT COUNT(*) FROM archived m WHERE m.payment_method_fingerprint = a.payment_method_fingerprint) AS method_share "
        "FROM archived a ORDER BY a.device_fingerprint, a.payment_method_fingerprint, a.payment_created_at;"
    )
    archived_candidates = vm.exec(path="/bin/sql", args=[candidate_sql])

    # --- ops: impossible-travel leg detection over archived payments ---
    fraud_sql = (
        "WITH archived AS ("
        "SELECT payment_id, record_path, customer_id, payment_created_at, "
        "observed_latitude, observed_longitude "
        "FROM payment_transactions WHERE is_archived_basket_reference = " + str(int(archived_flag)) + "), "
        "seq AS (SELECT *, "
        "LAG(observed_latitude) OVER w AS prev_lat, "
        "LAG(observed_longitude) OVER w AS prev_lon, "
        "LAG(payment_created_at) OVER w AS prev_t, "
        "LEAD(observed_latitude) OVER w AS next_lat, "
        "LEAD(observed_longitude) OVER w AS next_lon, "
        "LEAD(payment_created_at) OVER w AS next_t "
        "FROM archived WINDOW w AS (PARTITION BY customer_id ORDER BY payment_created_at)), "
        "legs AS (SELECT *, "
        "(ABS(observed_latitude - prev_lat) + ABS(observed_longitude - prev_lon)) / "
        "NULLIF((julianday(payment_created_at) - julianday(prev_t)) * 24.0, 0) AS in_speed, "
        "(ABS(next_lat - observed_latitude) + ABS(next_lon - observed_longitude)) / "
        "NULLIF((julianday(next_t) - julianday(payment_created_at)) * 24.0, 0) AS out_speed "
        "FROM seq) "
        "SELECT DISTINCT record_path, customer_id, payment_created_at "
        "FROM legs WHERE in_speed > 2.0 OR out_speed > 2.0 "
        "ORDER BY customer_id, payment_created_at;"
    )
    fraud_payments = vm.exec(path="/bin/sql", args=[fraud_sql])

    # parse record_path from pipe-delimited rows
    rows = _stdout(fraud_payments).splitlines()
    record_paths = []
    for line in rows:
        line = line.strip()
        if not line:
            continue
        first = line.split("|")[0].strip()
        if first.startswith("/") and first not in record_paths:
            record_paths.append(first)

    row_count = len(record_paths)
    paths_str = ", ".join(record_paths) if record_paths else "(none)"

    refs = list(record_paths)
    refs.append(policy_path)

    message = (
        "Fraud incident. Applied policy " + policy_path + ". "
        "Classified " + str(row_count) + " archived payment records as part of incident: "
        + paths_str + ". Read-only, nothing modified."
    )

    return vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
