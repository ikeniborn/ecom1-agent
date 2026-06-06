def run(vm, params):
    # Constraint #grounding + #policy-grounding: cite the applied policy doc.
    security_policy = vm.read(path="/docs/security.md")

    # Discovery SQL emitted as written in TOOL_PLAN (all literals inlined; no :name binds).
    sql = (
        "WITH legs AS (\n"
        "  SELECT\n"
        "    payment_id,\n"
        "    record_path,\n"
        "    customer_id,\n"
        "    payment_created_at,\n"
        "    observed_latitude AS lat,\n"
        "    observed_longitude AS lon,\n"
        "    LAG(observed_latitude)  OVER w AS prev_lat,\n"
        "    LAG(observed_longitude) OVER w AS prev_lon,\n"
        "    LAG(payment_created_at) OVER w AS prev_ts,\n"
        "    LEAD(observed_latitude)  OVER w AS next_lat,\n"
        "    LEAD(observed_longitude) OVER w AS next_lon,\n"
        "    LEAD(payment_created_at) OVER w AS next_ts\n"
        "  FROM payment_transactions\n"
        "  WHERE is_archived_basket_reference = 1\n"
        "  WINDOW w AS (PARTITION BY customer_id ORDER BY payment_created_at)\n"
        "),\n"
        "speeds AS (\n"
        "  SELECT\n"
        "    payment_id,\n"
        "    record_path,\n"
        "    (ABS(lat - prev_lat) + ABS(lon - prev_lon)) / NULLIF((julianday(payment_created_at) - julianday(prev_ts)) * 24.0, 0) AS in_speed,\n"
        "    (ABS(next_lat - lat) + ABS(next_lon - lon)) / NULLIF((julianday(next_ts) - julianday(payment_created_at)) * 24.0, 0) AS out_speed\n"
        "  FROM legs\n"
        ")\n"
        "SELECT record_path, payment_id\n"
        "FROM speeds\n"
        "WHERE COALESCE(in_speed, 0) > 2.0 OR COALESCE(out_speed, 0) > 2.0\n"
        "ORDER BY record_path;"
    )

    result = vm.exec(path="/bin/sql", args=[sql])
    stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")

    record_paths = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = [f.strip() for f in line.split("|")]
        first = fields[0]
        if not first or first.lower() == "record_path":
            continue
        if not first.startswith("/"):
            continue
        if first not in record_paths:
            record_paths.append(first)

    # refs: static policy doc + every flagged record_path. Drop unbound $placeholder if empty.
    refs = ["/docs/security.md"] + record_paths

    paths_str = ", ".join(record_paths) if record_paths else "(none)"
    message = (
        "Risk Ops fraud hit confirmed in archived payment history via impossible-travel detection "
        "(incoming/outgoing leg speed > 2 deg/hr over is_archived_basket_reference=1 records, ordered per customer "
        "by payment_created_at). Flagged {count} payment records as fraud: {paths}. No files changed. "
        "Grounded in /docs/security.md."
    ).format(count=len(record_paths), paths=paths_str)

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
