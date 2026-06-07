def run(vm, params):
    # Discovery: inspect database schema
    schema = vm.exec(
        path="/bin/sql",
        args=["SELECT name, sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type, name;"],
        stdin=""
    )

    # Ops: count products in Adhesive or Glue categories
    qty = vm.exec(
        path="/bin/sql",
        args=["SELECT COUNT(*) AS qty FROM products WHERE category IN ('Adhesive', 'Glue');"],
        stdin=""
    )

    def get_field(obj, field, default=""):
        if hasattr(obj, field):
            val = getattr(obj, field)
            return val if val is not None else default
        if isinstance(obj, dict):
            val = obj.get(field, default)
            return val if val is not None else default
        return default

    qty_stdout = get_field(qty, "stdout")
    qty_exit = get_field(qty, "exit_code", 0)
    if qty_exit is None:
        qty_exit = 0

    qty_value = None
    if qty_exit == 0 and qty_stdout:
        for line in qty_stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            for part in line.split("|"):
                part = part.strip()
                if part.isdigit():
                    qty_value = int(part)
                    break
            if qty_value is not None:
                break

    if qty_exit != 0 or not qty_stdout.strip() or qty_value is None:
        if qty_exit != 0 or not qty_stdout.strip():
            vm.answer(
                message="Failed to execute product count query.",
                outcome="OUTCOME_NONE_UNSUPPORTED",
                refs=[]
            )
        else:
            vm.answer(
                message="Could not parse aggregate count from query output.",
                outcome="OUTCOME_NONE_CLARIFICATION",
                refs=[]
            )
    else:
        vm.answer(
            message=f"<QTY: {qty_value}>",
            outcome="OUTCOME_OK",
            refs=[]
        )
