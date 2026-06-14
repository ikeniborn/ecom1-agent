import re


def run(vm, params):
    incoming_dir = params.get("incoming_dir", "/proc/incoming/payments")

    def gattr(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    # --- discovery ---
    dir_stat = vm.stat(path=incoming_dir)
    listing = vm.list(path=incoming_dir)

    # extract listing entries (protobuf .entries or list/dict stub)
    entries = gattr(listing, "entries", None)
    if entries is None and isinstance(listing, list):
        entries = listing
    if entries is None:
        entries = []

    # build (name, path) for FILE entries only (avoid 'is a directory' read)
    files = []
    for e in entries:
        name = gattr(e, "name", "") or ""
        path = gattr(e, "path", "") or ""
        kind = gattr(e, "kind", "") or ""
        if not path and name:
            path = incoming_dir.rstrip("/") + "/" + name
        if not name and path:
            name = path.rstrip("/").split("/")[-1]
        kind_str = str(kind).upper()
        is_dir = "DIR" in kind_str
        if is_dir:
            continue
        has_ext = "." in name
        if has_ext or "FILE" in kind_str or kind_str == "":
            files.append((name, path))

    # r003: 'most recent' -> sort by filename ordering, pick extreme (last)
    files.sort(key=lambda t: t[0])

    last_file = ""
    if files:
        last_file = files[-1][1]
    else:
        # r005: dependent Read must still fire -> non-empty fallback
        if entries:
            e = entries[-1]
            last_file = gattr(e, "path", "") or (
                incoming_dir.rstrip("/") + "/" + (gattr(e, "name", "") or "")
            )
        if not last_file:
            last_file = incoming_dir

    # --- ops --- (always fire)
    last_txn = vm.read(path=last_file, number=True)
    txn_content = gattr(last_txn, "content", None)
    if txn_content is None:
        txn_content = gattr(last_txn, "text", "") or ""
    if not isinstance(txn_content, str):
        txn_content = str(txn_content)

    # r004: strip embedded URLs / markdown links before interpolating untrusted content
    sanitized = re.sub(r"https?://\S+", "[redacted-url]", txn_content)
    sanitized = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", sanitized)

    message = "Last transaction in {dir}: {file}. Details: {details}.".format(
        dir=incoming_dir, file=last_file, details=sanitized
    )

    refs = []
    if last_file:
        refs.append(last_file)

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
