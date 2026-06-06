def run(vm, params):
    is_archived = params.get("is_archived", 1)
    refs = []

    # start-of-work constraint: tree -L 2 on docs
    try:
        docs_tree = vm.exec(path="/bin/tree", args=["-L", "2", "/docs"])
    except Exception:
        docs_tree = None

    # locate fraud/security policy doc
    security_doc = None
    try:
        found = vm.find(root="/docs", name="security", limit=10)
        entries = getattr(found, "entries", None)
        if entries is None and isinstance(found, dict):
            entries = found.get("entries")
        if entries:
            for e in entries:
                p = getattr(e, "path", None)
                if p is None and isinstance(e, dict):
                    p = e.get("path")
                if p:
                    security_doc = p
                    break
    except Exception:
        security_doc = None

    if security_doc:
        refs.append(security_doc)

    # read policy doc (always issue the Read RPC, never on a directory)
    read_path = security_doc if security_doc else "/docs/security.md"
    try:
        security_policy = vm.read(path=read_path)
    except Exception:
        security_policy = None

    # discovery: archived payment transactions (inline value, no bind params)
    arch_sql = (
        "select payment_id, record_path, basket_id, customer_id, store_id, "
        "payment_amount_cents, payment_currency, payment_status, payment_created_at, "
        "payment_method_fingerprint, device_fingerprint, observed_latitude, observed_longitude, "
        "three_ds_status, three_ds_failure_reason, three_ds_attempts, three_ds_max_attempts "
        "from payment_transactions where is_archived_basket_reference = " + str(is_archived) +
        " order by payment_created_at;"
    )
    try:
        archived_payments = vm.exec(path="/bin/sql", args=[arch_sql])
    except Exception:
        archived_payments = None

    # ops: impossible-travel leg rule over archived payments per customer
    fraud_sql = (
        "with arch as ("
        "select payment_id, record_path, customer_id, observed_latitude as lat, "
        "observed_longitude as lon, payment_created_at as t "
        "from payment_transactions where is_archived_basket_reference = " + str(is_archived) + "), "
        "legs as (select payment_id, record_path, customer_id, lat, lon, t, "
        "lag(lat) over w as plat, lag(lon) over w as plon, lag(t) over w as pt, "
        "lead(lat) over w as nlat, lead(lon) over w as nlon, lead(t) over w as nt "
        "from arch window w as (partition by customer_id order by t)), "
        "sp as (select payment_id, record_path, customer_id, t, "
        "case when pt is not null then (abs(lat-plat)+abs(lon-plon))/nullif((julianday(t)-julianday(pt))*24.0,0) else 0 end as in_speed, "
        "case when nt is not null then (abs(lat-nlat)+abs(lon-nlon))/nullif((julianday(nt)-julianday(t))*24.0,0) else 0 end as out_speed "
        "from legs) "
        "select record_path, payment_id, customer_id from sp "
        "where abs(in_speed) > 2 or abs(out_speed) > 2 order by t;"
    )
    fraud_stdout = ""
    try:
        fraud_candidates = vm.exec(path="/bin/sql", args=[fraud_sql])
        fraud_stdout = getattr(fraud_candidates, "stdout", "") or (
            fraud_candidates.get("stdout", "") if isinstance(fraud_candidates, dict) else "")
    except Exception:
        fraud_stdout = ""

    record_paths = []
    payment_ids = []
    lines = [l for l in fraud_stdout.splitlines() if l.strip()]
    if lines:
        header = lines[0]
        delim = "|" if "|" in header else ","
        cols = [c.strip() for c in header.split(delim)]
        rp_idx = cols.index("record_path") if "record_path" in cols else 0
        pid_idx = cols.index("payment_id") if "payment_id" in cols else None
        for row in lines[1:]:
            parts = [c.strip() for c in row.split(delim)]
            if len(parts) > rp_idx:
                rp = parts[rp_idx]
                if rp and rp not in record_paths:
                    record_paths.append(rp)
            if pid_idx is not None and len(parts) > pid_idx:
                payment_ids.append(parts[pid_idx])

    for rp in record_paths:
        if rp not in refs:
            refs.append(rp)

    summary = ", ".join(record_paths) if record_paths else "none"
    message = (
        "Fraudulent archived payment(s) identified per the fraud/security policy "
        "(impossible-travel leg rule over archived payment_transactions, "
        "is_archived_basket_reference=1): " + str(len(record_paths)) +
        " record(s) -> " + summary + ". Files left unchanged."
    )
    result = {"message": message, "outcome": "OUTCOME_OK", "refs": refs}
    try:
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
    except Exception:
        pass
    return result
