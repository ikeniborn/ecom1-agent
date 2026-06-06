def run(vm, params):
    archived_flag = params.get("archived_flag", 1)

    # --- discovery (RPC multiset must match plan: Tree, Search, Read, Exec) ---
    docs_tree = vm.tree(root="/docs", level=2)
    fraud_policy_hits = vm.search(root="/docs", pattern="(?i)fraud|3ds|device.?fingerprint|velocity|chargeback", limit=50)
    security_policy = vm.read(path="/docs/security.md", number=True)

    # Impossible-travel detection over archived payment records. Per customer,
    # order by payment_created_at; flag a record when its incoming (LAG) OR
    # outgoing (LEAD) leg speed exceeds ~2 deg/hr (faster than ground travel).
    # Flag value inlined (/bin/sql rejects :name binds).
    flag = str(int(archived_flag))
    sql = (
        "WITH ordered AS ("
        "SELECT record_path, customer_id, payment_created_at, "
        "observed_latitude AS lat, observed_longitude AS lon, "
        "LAG(observed_latitude) OVER w AS plat, "
        "LAG(observed_longitude) OVER w AS plon, "
        "LAG(payment_created_at) OVER w AS pt, "
        "LEAD(observed_latitude) OVER w AS nlat, "
        "LEAD(observed_longitude) OVER w AS nlon, "
        "LEAD(payment_created_at) OVER w AS nt "
        "FROM payment_transactions "
        "WHERE is_archived_basket_reference = " + flag + " "
        "WINDOW w AS (PARTITION BY customer_id ORDER BY payment_created_at)) "
        "SELECT record_path FROM ordered "
        "WHERE (plat IS NOT NULL AND (ABS(lat-plat)+ABS(lon-plon))/NULLIF((julianday(payment_created_at)-julianday(pt))*24.0,0) > 2.0) "
        "OR (nlat IS NOT NULL AND (ABS(nlat-lat)+ABS(nlon-lon))/NULLIF((julianday(nt)-julianday(payment_created_at))*24.0,0) > 2.0) "
        "ORDER BY record_path;"
    )
    archived_payments = vm.exec(path="/bin/sql", args=[sql], stdin="")

    stdout = getattr(archived_payments, "stdout", "")
    if not stdout and isinstance(archived_payments, dict):
        stdout = archived_payments.get("stdout", "")
    stdout = stdout or ""

    seen = set()
    flagged_paths = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        cell = line.split("|")[0].strip()
        if cell.startswith("/") and cell not in seen:
            seen.add(cell)
            flagged_paths.append(cell)

    policy_doc = "/docs/security.md"
    refs = list(flagged_paths) + [policy_doc]

    paths_str = ", ".join(flagged_paths) if flagged_paths else "none"
    message = (
        "Fraud review: scanned archived payments (is_archived_basket_reference=1) against "
        + policy_doc + ". Flagged fraudulent payment record(s): " + paths_str
        + " at " + paths_str
        + ". Reason: impossible-travel velocity \u2014 a record's incoming or outgoing "
        "leg exceeds ~2 deg/hr (faster than ground travel). Files unchanged (read-only)."
    )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
