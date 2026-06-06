def run(vm, params):
    # ----- discovery 1: identity (Exec) -----
    identity = vm.exec(path="/bin/id", args=[], stdin="")

    # ----- discovery 2: policy grounding (Read) -----
    security_policy = vm.read(path="/docs/security.md", number=True)

    # ----- discovery 3: impossible-travel leg detection over archived payments (Exec /bin/sql) -----
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
        "    LAG(payment_created_at)  OVER w AS prev_ts,\n"
        "    LEAD(lat) OVER w AS next_lat,\n"
        "    LEAD(lon) OVER w AS next_lon,\n"
        "    LEAD(payment_created_at) OVER w AS next_ts\n"
        "  FROM archived a\n"
        "  WINDOW w AS (PARTITION BY customer_id ORDER BY payment_created_at)\n"
        "),\n"
        "speeds AS (\n"
        "  SELECT *,\n"
        "    (ABS(lat - prev_lat) + ABS(lon - prev_lon)) /\n"
        "      NULLIF((julianday(payment_created_at) - julianday(prev_ts)) * 24.0, 0) AS in_speed,\n"
        "    (ABS(next_lat - lat) + ABS(next_lon - lon)) /\n"
        "      NULLIF((julianday(next_ts) - julianday(payment_created_at)) * 24.0, 0) AS out_speed\n"
        "  FROM legs\n"
        ")\n"
        "SELECT payment_id, record_path, customer_id, payment_created_at, in_speed, out_speed\n"
        "FROM speeds\n"
        "WHERE (in_speed IS NOT NULL AND in_speed > 2.0)\n"
        "   OR (out_speed IS NOT NULL AND out_speed > 2.0)\n"
        "ORDER BY customer_id, payment_created_at;"
    )
    flagged = vm.exec(path="/bin/sql", args=[sql], stdin="")

    # ----- parse tabular stdout (safe access for protobuf or dict stub) -----
    stdout = getattr(flagged, "stdout", "")
    if not stdout and isinstance(flagged, dict):
        stdout = flagged.get("stdout", "")
    stdout = stdout or ""

    lines = [ln for ln in stdout.splitlines() if ln.strip() != ""]
    record_paths = []
    payment_ids = []
    if lines:
        header = lines[0]
        # /bin/sql emits CSV (comma) with a header row; fall back to pipe if no comma present
        delim = "," if "," in header else ("|" if "|" in header else ",")
        cols = [c.strip() for c in header.split(delim)]
        rp_idx = cols.index("record_path") if "record_path" in cols else None
        pid_idx = cols.index("payment_id") if "payment_id" in cols else None
        for ln in lines[1:]:
            parts = [p.strip() for p in ln.split(delim)]
            if rp_idx is not None and rp_idx < len(parts) and parts[rp_idx]:
                record_paths.append(parts[rp_idx])
            if pid_idx is not None and pid_idx < len(parts) and parts[pid_idx]:
                payment_ids.append(parts[pid_idx])

    row_count = len(record_paths)
    payment_id_list = ", ".join(payment_ids) if payment_ids else "none"

    # static policy ref + every flagged record_path; drop $placeholder when no rows
    refs = ["/docs/security.md"] + record_paths

    message = (
        "Fraud review (archived payments, impossible-travel leg rule >~2 deg/hr): "
        "flagged {n} payment record(s): {ids}. Detection: per customer, ordered by "
        "payment_created_at, a record is marked when its incoming or outgoing travel "
        "leg exceeds ground-travel speed. Files left unchanged."
    ).format(n=row_count, ids=payment_id_list)

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
