import re


def run(vm, params):
    archive_path = params.get("archive_tsv", "/archive/payment_batch_export_ZnZMNJceH3.tsv")

    def content_of(r):
        c = getattr(r, "content", None)
        if c is None and isinstance(r, dict):
            c = r.get("content", "")
        return c or ""

    def strip_gutter(line):
        m = re.match(r'^\s*\d+[\t|:](.*)$', line)
        if m:
            return m.group(1)
        return line

    # discovery
    try:
        tsv_stat = vm.stat(path=archive_path)
    except Exception:
        tsv_stat = None
    try:
        archive_listing = vm.list(path="/archive")
    except Exception:
        archive_listing = None
    tsv_content = vm.read(path=archive_path, number=True)
    try:
        fraud_hits = vm.search(root="/archive", pattern="(?i)fraud", limit=200)
    except Exception:
        fraud_hits = None

    # ops
    fraud_rows = vm.read(path=archive_path, number=True)

    raw = content_of(fraud_rows) or content_of(tsv_content)
    lines = [strip_gutter(l) for l in raw.split("\n")]
    lines = [l for l in lines if l.strip() != ""]

    refs = []
    total_cents = 0
    if lines:
        header = lines[0]
        if "\t" in header:
            delim = "\t"
        elif "," in header:
            delim = ","
        else:
            delim = None

        def split_row(l):
            if delim is None:
                return re.split(r'\s{2,}|\t', l)
            return l.split(delim)

        cols = [c.strip() for c in split_row(header)]
        low = [c.lower() for c in cols]

        def find_col(preds):
            for p in preds:
                for i, name in enumerate(low):
                    try:
                        if p(name):
                            return i
                    except Exception:
                        pass
            return -1

        amount_idx = find_col([
            lambda n: n == "amount",
            lambda n: "amount" in n,
            lambda n: n in ("amt", "total", "value", "price", "sum"),
            lambda n: "amt" in n or "total" in n or "value" in n or "price" in n,
        ])
        rowid_idx = find_col([
            lambda n: n in ("rowid", "row_id", "row id"),
            lambda n: n.replace(" ", "").replace("_", "") == "rowid",
            lambda n: n == "id",
            lambda n: "rowid" in n.replace(" ", "").replace("_", ""),
            lambda n: n == "row",
            lambda n: n.endswith("id"),
        ])
        fraud_idx = find_col([
            lambda n: "fraud" in n,
        ])

        TRUTHY = {"1", "true", "yes", "y", "t", "fraud", "fraudulent", "flagged", "flag", "suspicious"}
        FALSY = {"", "0", "false", "no", "n", "f", "none", "null", "legit", "clean", "ok", "valid"}

        def is_fraud(cells):
            if fraud_idx != -1 and fraud_idx < len(cells):
                v = cells[fraud_idx].strip().lower()
                if "fraud" in v:
                    return True
                if v in TRUTHY:
                    return True
                if v in FALSY:
                    return False
                return v != ""
            return any("fraud" in c.lower() for c in cells)

        def to_cents(s):
            s = re.sub(r'[^0-9.\-]', '', s.strip())
            if s in ("", "-", "."):
                return 0
            try:
                return int(round(float(s) * 100))
            except Exception:
                return 0

        for l in lines[1:]:
            cells = [c.strip() for c in split_row(l)]
            if not is_fraud(cells):
                continue
            if rowid_idx != -1 and rowid_idx < len(cells):
                rid = cells[rowid_idx].strip()
            else:
                rid = cells[0].strip() if cells else ""
            if rid == "":
                continue
            ref = archive_path + "#row=" + rid
            if ref not in refs:
                refs.append(ref)
            if amount_idx != -1 and amount_idx < len(cells):
                total_cents += to_cents(cells[amount_idx])

    euros = total_cents // 100
    cents = total_cents % 100
    message = "EUR %d.%02d" % (euros, cents)

    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
