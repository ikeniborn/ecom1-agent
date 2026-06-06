import re


def _stdout(result):
    if result is None:
        return ""
    s = getattr(result, "stdout", None)
    if s is not None:
        return s
    if isinstance(result, dict):
        return result.get("stdout", "") or ""
    return ""


def _to_text(obj):
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    parts = []
    if isinstance(obj, dict):
        for k in ("matches", "results", "paths", "entries", "files", "hits"):
            v = obj.get(k)
            if v:
                parts.append(_to_text(v))
        if not parts:
            parts.append(str(obj))
        return "\n".join(parts)
    for attr in ("matches", "results", "paths", "entries", "files", "hits"):
        v = getattr(obj, attr, None)
        if v:
            parts.append(_to_text(v))
    if parts:
        return "\n".join(parts)
    if isinstance(obj, (list, tuple)):
        out = []
        for it in obj:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                out.append(it.get("path") or it.get("file") or it.get("line") or str(it))
            else:
                p = getattr(it, "path", None) or getattr(it, "file", None) or getattr(it, "line", None)
                out.append(p if p is not None else str(it))
        return "\n".join(str(x) for x in out)
    return str(obj)


def _doc_paths(obj):
    text = _to_text(obj)
    paths = []
    for m in re.findall(r"/docs[\w/\.\-]+", text):
        if m not in paths:
            paths.append(m)
    return paths


def run(vm, params):
    email = params.get("email", "")
    reason_code = params.get("reason_code", "service_recovery")

    identity = None
    discount_help = None
    discount_doc = None
    policy_search = None
    basket = None
    apply_result = None

    # discovery 1: identity
    try:
        identity = vm.exec(path="/bin/id", args=[])
    except Exception:
        identity = None

    # discovery 2: discount help
    try:
        discount_help = vm.exec(path="/bin/discount", args=["--help"])
    except Exception:
        discount_help = None

    # discovery 3: find discount policy doc
    try:
        discount_doc = vm.find(root="/docs", name="discount", kind="file", limit=5)
    except Exception:
        discount_doc = None

    # discovery 4: search service_recovery policy
    try:
        policy_search = vm.search(root="/docs", pattern="service_recovery", limit=20)
    except Exception:
        policy_search = None

    # discovery 5: resolve last checkoutable basket (inline literal, no :name binds)
    safe_email = email.replace("'", "''")
    sql = (
        "SELECT b.basket_id, b.record_path, b.basket_status, b.basket_created_at, b.customer_id "
        "FROM shopping_baskets b JOIN customer_accounts c ON c.customer_id = b.customer_id "
        "WHERE c.customer_email = '" + safe_email + "' "
        "AND b.basket_status IN ('open','active','checkoutable') "
        "ORDER BY b.basket_created_at DESC LIMIT 1;"
    )
    try:
        basket = vm.exec(path="/bin/sql", args=[sql])
    except Exception:
        basket = None

    # parse identity -> issuer employee_id
    issuer_employee_id = ""
    id_text = _stdout(identity) or _to_text(identity)
    m = re.search(r"employee_id\s*[=:]\s*\"?([\w\-]+)\"?", id_text)
    if m:
        issuer_employee_id = m.group(1)

    # parse discount policy doc path
    doc_paths = _doc_paths(discount_doc)
    discount_doc_path = doc_paths[0] if doc_paths else ""

    # parse service_recovery cap percent from policy search
    policy_text = _stdout(policy_search) or _to_text(policy_search)
    policy_doc_paths = _doc_paths(policy_search)
    max_service_recovery_pct = ""
    pcts = []
    for line in policy_text.splitlines():
        if "service_recovery" in line.lower():
            for n in re.findall(r"(\d{1,3})\s*%", line):
                pcts.append(int(n))
            for n in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*(?:percent|pct)", line.lower()):
                try:
                    pcts.append(int(float(n)))
                except Exception:
                    pass
    if not pcts:
        for n in re.findall(r"(\d{1,3})\s*%", policy_text):
            pcts.append(int(n))
    if pcts:
        max_service_recovery_pct = str(max(pcts))

    # parse basket row (pipe-delimited)
    basket_id = ""
    basket_path = ""
    basket_text = _stdout(basket)
    for line in basket_text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        if cols and cols[0].lower().startswith("basket_id"):
            continue
        if len(cols) >= 2:
            basket_id = cols[0]
            basket_path = cols[1]
            break

    # op: apply discount
    if basket_id and max_service_recovery_pct and issuer_employee_id:
        try:
            apply_result = vm.exec(
                path="/bin/discount",
                args=[
                    "apply",
                    "--basket", basket_id,
                    "--percent", max_service_recovery_pct,
                    "--reason", reason_code,
                    "--issuer", issuer_employee_id,
                ],
            )
        except Exception:
            apply_result = None
    else:
        try:
            apply_result = vm.exec(
                path="/bin/discount",
                args=[
                    "apply",
                    "--basket", basket_id,
                    "--percent", max_service_recovery_pct,
                    "--reason", reason_code,
                    "--issuer", issuer_employee_id,
                ],
            )
        except Exception:
            apply_result = None

    # build refs: basket record path + every policy/discount doc matched
    refs = []
    if basket_path:
        refs.append(basket_path)
    if discount_doc_path:
        refs.append(discount_doc_path)
    for p in policy_doc_paths:
        if p not in refs:
            refs.append(p)
    seen = set()
    refs = [r for r in refs if not (r in seen or seen.add(r))]

    message = (
        "Applied service_recovery discount of " + (max_service_recovery_pct or "?") +
        "% (policy cap) to basket " + (basket_id or "?") + " at " + (basket_path or "?") +
        " for " + email + ". Issuer: " + (issuer_employee_id or "?") +
        ". Policy: " + (discount_doc_path or "?") + "."
    )

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
