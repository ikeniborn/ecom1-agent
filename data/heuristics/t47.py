def run(vm, params):
    store_id = params["store_id"]

    # discovery: required identity probe
    identity = vm.exec(path="/bin/id", args=[], stdin="")

    def q(v):
        return str(v).replace("'", "''")

    def build_sql(p):
        conds = [
            "pv.brand = '%s'" % q(p["brand"]),
            "pv.series = '%s'" % q(p["series"]),
            "pv.model = '%s'" % q(p["model"]),
            "pk.product_kind_name = '%s'" % q(p["kind"]),
        ]
        for k, val in p.get("props", {}).items():
            conds.append(
                "EXISTS (SELECT 1 FROM product_variant_properties pp WHERE pp.product_sku = pv.product_sku AND pp.property_key = '%s' AND pp.property_value_text = '%s')"
                % (q(k), q(val))
            )
        where = " AND ".join(conds)
        sql = (
            "WITH matched AS (SELECT pv.product_sku, pv.record_path FROM product_variants pv "
            "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE "
            + where
            + ") SELECT m.product_sku, m.record_path, COALESCE(si.available_today_quantity, 0) AS in_stock "
            "FROM matched m LEFT JOIN store_inventory si ON si.product_sku = m.product_sku AND si.store_id = '%s';"
            % q(store_id)
        )
        return sql

    def get_stdout(r):
        return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")

    def split_row(line):
        for delim in (",", "|", "\t"):
            parts = line.split(delim)
            if len(parts) >= 3:
                return [x.strip() for x in parts]
        return [x.strip() for x in line.split(",")]

    def parse(r):
        out = get_stdout(r)
        lines = [l for l in out.splitlines() if l.strip()]
        if len(lines) < 2:
            return None
        for line in lines[1:]:
            parts = split_row(line)
            if len(parts) >= 3 and parts[0]:
                sku = parts[0]
                path = parts[1]
                try:
                    stock = int(float(parts[2]))
                except Exception:
                    stock = 0
                return {"sku": sku, "path": path, "in_stock": stock}
        return None

    row_ids = ["FK775", "WgE71", "KQHmi", "UUzXw", "T4swK"]

    results = {}
    for rid in row_ids:
        p = params[rid]
        res = vm.exec(path="/bin/sql", args=[build_sql(p)], stdin="")
        results[rid] = parse(res)

    header = "RowID\tSKU\tin_stock\tmatch"
    lines = [header]
    refs = []
    seen = set()
    for rid in row_ids:
        p = params[rid]
        qty = p.get("quantity", 1)
        d = results.get(rid)
        if d:
            sku = d["sku"]
            stock = str(d["in_stock"])
            match = "true" if d["in_stock"] >= qty else "false"
            # reference matched AND available products only
            if d["path"] and d["in_stock"] > 0 and d["path"] not in seen:
                seen.add(d["path"])
                refs.append(d["path"])
        else:
            sku = ""
            stock = ""
            match = "false"
        lines.append(rid + "\t" + sku + "\t" + stock + "\t" + match)

    message = "\n".join(lines)
    vm.answer(message=message, outcome="OUTCOME_OK", refs=refs)
