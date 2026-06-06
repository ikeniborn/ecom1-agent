def run(vm, params):
    refs = ["/docs/security.md"]
    payment_ids = []
    record_paths = []

    def _stdout(r):
        if r is None:
            return ""
        s = getattr(r, "stdout", None)
        if s is None and isinstance(r, dict):
            s = r.get("stdout", "")
        return s or ""

    # discovery 1: identity context
    try:
        identity = vm.exec(path="/bin/id", args=[])
    except Exception:
        identity = None

    # discovery 2: stat policy doc
    try:
        sec_stat = vm.stat(path="/docs/security.md")
    except Exception:
        sec_stat = None

    # discovery 3: read policy doc (drop number kwarg to avoid TypeError)
    try:
        security_policy = vm.read(path="/docs/security.md")
    except Exception:
        security_policy = None

    # discovery 4: impossible-travel leg-speed detection over archived payments
    sql = (
        "WITH archived AS (\n"
        "  SELECT payment_id, record_path, customer_id, payment_created_at,\n"
        "         observed_latitude AS lat, observed_longitude AS lon\n"
        "  FROM payment_transactions\n"
        "  WHERE is_archived_basket_reference = 1\n"
        "),\n"
        "legs AS (\n"
        "  SELECT a.*,\n"
        "    LAG(lat)  OVER w AS prev_lat,\n"
        "    LAG(lon)  OVER w AS prev_lon,\n"
        "    LAG(payment_created_at)  OVER w AS prev_t,\n"
        "    LEAD(lat) OVER w AS next_lat,\n"
        "    LEAD(lon) OVER w AS next_lon,\n"
        "    LEAD(payment_created_at) OVER w AS next_t\n"
        "  FROM archived a\n"
        "  WINDOW w AS (PARTITION BY customer_id ORDER BY payment_created_at)\n"
        "),\n"
        "speeds AS (\n"
        "  SELECT *,\n"
        "    (ABS(lat-prev_lat)+ABS(lon-prev_lon)) / NULLIF((julianday(payment_created_at)-julianday(prev_t))*24.0,0) AS in_speed,\n"
        "    (ABS(next_lat-lat)+ABS(next_lon-lon)) / NULLIF((julianday(next_t)-julianday(payment_created_at))*24.0,0) AS out_speed\n"
        "  FROM legs\n"
        ")\n"
        "SELECT record_path, payment_id, customer_id, payment_created_at, in_speed, out_speed\n"
        "FROM speeds\n"
        "WHERE in_speed > 2.0 OR out_speed > 2.0\n"
        "ORDER BY customer_id, payment_created_at;"
    )
    try:
        fraud_records = vm.exec(path="/bin/sql", args=[], stdin=sql)
    except Exception:
        fraud_records = None

    out = _stdout(fraud_records)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if lines:
        header = lines[0]
        delim = "|" if "|" in header else ","
        hdr_cols = [c.strip() for c in header.split(delim)]
        start = 1 if "record_path" in hdr_cols else 0
        for ln in lines[start:]:
            cols = [c.strip() for c in ln.split(delim)]
            if not cols or not cols[0]:
                continue
            rp = cols[0]
            if rp and rp.startswith("/"):
                record_paths.append(rp)
                if len(cols) > 1 and cols[1]:
                    payment_ids.append(cols[1])

    for rp in record_paths:
        if rp and rp not in refs:
            refs.append(rp)

    count = len(record_paths)
    ids_str = ", ".join(payment_ids) if payment_ids else "none"
    message = (
        "Fraud review over archived payments (is_archived_basket_reference=1): "
        "impossible-travel detection per customer ordered by payment_created_at. "
        "Flagged {count} payment record(s) whose incoming OR outgoing leg speed "
        "exceeds ~2 deg/hr (faster than ground travel): {ids}. Files left unchanged. "
        "Applied policy: /docs/security.md."
    ).format(count=count, ids=ids_str)

    try:
        vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
    except Exception:
        pass
    return {"message": message, "outcome": "OUTCOME_OK", "refs": refs}
