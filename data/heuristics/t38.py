def run(vm, params):
    refs = []

    # 1. tree /docs
    try:
        docs_tree = vm.exec(path="/bin/tree", args=["-L", "2", "/docs"])
    except Exception:
        docs_tree = None

    # 2. search docs for fraud/incident
    try:
        fraud_hits = vm.search(root="/docs", pattern="(?i)fraud|incident", limit=50)
    except Exception:
        fraud_hits = None

    # 3. find docs named fraud (no kind per r003)
    try:
        fraud_docs = vm.find(root="/docs", name="fraud", limit=10)
    except Exception:
        fraud_docs = None

    def _entries(obj):
        if obj is None:
            return []
        for attr in ("entries", "hits", "matches", "results"):
            v = getattr(obj, attr, None)
            if v:
                return list(v)
        if isinstance(obj, dict):
            for k in ("entries", "hits", "matches", "results"):
                if obj.get(k):
                    return list(obj[k])
        return []

    def _path(e):
        return getattr(e, "path", None) or (e.get("path") if isinstance(e, dict) else None)

    fraud_doc_path = None
    for src in (fraud_docs, fraud_hits):
        for e in _entries(src):
            p = _path(e)
            if p and any(p.lower().endswith(x) for x in (".md", ".txt", ".rst", ".yaml", ".yml", ".json")):
                fraud_doc_path = p
                break
        if fraud_doc_path:
            break
    if not fraud_doc_path:
        for src in (fraud_docs, fraud_hits):
            for e in _entries(src):
                p = _path(e)
                if p:
                    fraud_doc_path = p
                    break
            if fraud_doc_path:
                break

    # 4. read policy doc (r015: never empty path)
    read_path = fraud_doc_path if fraud_doc_path else "/"
    try:
        fraud_policy = vm.read(path=read_path)
    except Exception:
        fraud_policy = None

    if fraud_doc_path:
        refs.append(fraud_doc_path)

    # extract policy markers from doc text
    policy_text = ""
    if fraud_policy is not None:
        policy_text = getattr(fraud_policy, "content", "") or getattr(fraud_policy, "text", "") or ""
        if not policy_text and isinstance(fraud_policy, dict):
            policy_text = fraud_policy.get("content", "") or fraud_policy.get("text", "")
    policy_upper = (policy_text or "").upper()

    # 5. schema check
    try:
        schema_check = vm.exec(path="/bin/sql", args=["SELECT name, sql FROM sqlite_schema WHERE name LIKE '%payment%' OR name LIKE '%incident%' OR name LIKE '%fraud%';"])
    except Exception:
        schema_check = None

    # 6. archived payments
    sql_text = "SELECT payment_id, record_path, basket_id, customer_id, store_id, payment_status, payment_created_at, payment_method_fingerprint, device_fingerprint, three_ds_status, three_ds_failure_reason FROM payment_transactions WHERE is_archived_basket_reference = 1 ORDER BY payment_created_at;"
    try:
        archived_payments = vm.exec(path="/bin/sql", args=[sql_text])
    except Exception:
        archived_payments = None

    stdout = ""
    if archived_payments is not None:
        stdout = getattr(archived_payments, "stdout", "")
        if not stdout and isinstance(archived_payments, dict):
            stdout = archived_payments.get("stdout", "")
    stdout = stdout or ""

    payment_paths = []
    payment_summaries = []
    if stdout:
        lines = [l for l in stdout.splitlines() if l.strip()]
        if lines:
            header = lines[0]
            delim = "|" if "|" in header else ","
            cols = [c.strip() for c in header.split(delim)]
            def cidx(name):
                try:
                    return cols.index(name)
                except ValueError:
                    return -1
            path_idx = cidx("record_path")
            pid_idx = cidx("payment_id")
            status_idx = cidx("payment_status")
            tds_idx = cidx("three_ds_status")
            reason_idx = cidx("three_ds_failure_reason")

            fraud_tokens = ["FRAUD", "CHARGEBACK", "BLOCKED", "BLOCKLIST", "REJECTED", "SUSPECTED", "DENIED"]

            for ln in lines[1:]:
                parts = [p.strip() for p in ln.split(delim)]
                if path_idx < 0 or len(parts) <= path_idx:
                    continue
                rp = parts[path_idx]
                if not rp:
                    continue
                pid = parts[pid_idx] if 0 <= pid_idx < len(parts) else ""
                status_v = parts[status_idx].upper() if 0 <= status_idx < len(parts) else ""
                tds_v = parts[tds_idx].upper() if 0 <= tds_idx < len(parts) else ""
                reason_v = parts[reason_idx].upper() if 0 <= reason_idx < len(parts) else ""
                row_up = (status_v + " " + tds_v + " " + reason_v).strip()
                match = any(tok in row_up for tok in fraud_tokens)
                if not match and policy_upper:
                    # match if policy doc mentions this status literal
                    for v in (status_v, tds_v, reason_v):
                        if v and len(v) > 3 and v in policy_upper:
                            match = True
                            break
                if match:
                    payment_paths.append(rp)
                    payment_summaries.append("{} @ {}".format(pid, rp))

    refs.extend(payment_paths)

    fraud_payment_list = "; ".join(payment_summaries) if payment_summaries else "none"
    message = "Fraud incident payments (archived): " + fraud_payment_list

    return vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
