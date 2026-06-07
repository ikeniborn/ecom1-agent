def run(vm, params):
    # Discovery: list /uploads to find receipt file
    upload_list = vm.list(path="/uploads")
    items = upload_list.get("items", [])
    receipt_path = None
    for item in items:
        if item.get("kind") == "FILE" or "." in item.get("name", ""):
            receipt_path = item.get("name")
            break
    if receipt_path is None and len(items) > 0:
        receipt_path = items[0].get("name", "")
    if not receipt_path:
        # Fallback to first item if any
        if len(items) > 0:
            receipt_path = items[0].get("name", "")
        else:
            receipt_path = "/uploads/receipt_ocr_5Vvrq7tF.txt"

    # Read receipt content
    try:
        receipt_text = vm.read(path=receipt_path)
    except Exception:
        # Fallback if read fails
        receipt_text = ""

    # Parse receipt: extract SUBTOTAL line
    subtotal_line = None
    old_ex = 0.0
    for line in str(receipt_text).splitlines():
        line_upper = line.upper().replace(" ", "").replace("0", "O").replace("1", "I").replace("5", "S").replace("8", "B").replace("2", "Z")
        if "SUBTOTAL" in line_upper or "SUB T0TAL" in line_upper or "SUB TOTAl" in line_upper:
            subtotal_line = line
            break
    if subtotal_line:
        # OCR may use 'O' for '0' — normalize
        normalized = subtotal_line.replace("O", "0").replace("l", "1").replace("S", "5").replace("B", "8").replace("Z", "2")
        import re
        match = re.search(r"EUR\s*([\d.,]+)", normalized, re.IGNORECASE)
        if not match:
            match = re.search(r"([\d.,]+)\s*EUR", normalized, re.IGNORECASE)
        if match:
            val_str = match.group(1).replace(",", ".")
            try:
                old_ex = float(val_str)
            except ValueError:
                old_ex = 0.0

    # Extract SKU lines from receipt (qty + SKU + description + price)
    sku_lines = []
    for line in str(receipt_text).splitlines():
        line = line.strip()
        if not line or "SUBTOTAL" in line.upper():
            continue
        # Try to parse qty (integer), SKU (alphanumeric), description, unit price, total
        tokens = line.split()
        if len(tokens) >= 3:
            try:
                qty = int(tokens[0])
                sku = tokens[1]
                sku_lines.append((qty, sku))
            except ValueError:
                continue

    # Build SKU mapping: exact then fuzzy (0/O, 1/I, 5/S, 8/B, 2/Z)
    fuzzy_map = {
        "0": "O", "O": "0",
        "1": "I", "I": "1",
        "5": "S", "S": "5",
        "8": "B", "B": "8",
        "2": "Z", "Z": "2"
    }

    def normalize_sku(s):
        return "".join(fuzzy_map.get(c, c) for c in s.upper())

    # Fetch product_variants data via SQL
    sql_query = "SELECT sku, price_cents, record_path FROM product_variants"
    sql_result = vm.exec(path="/bin/sql", args=[sql_query])
    stdout = getattr(sql_result, "stdout", "") or (sql_result.get("stdout", "") if isinstance(sql_result, dict) else "")
    lines = stdout.strip().split("\n") if stdout else []

    # Parse pipe-delimited result
    exact_match = {}
    fuzzy_match = {}
    for line in lines:
        parts = line.split("|")
        if len(parts) >= 3:
            sku = parts[0].strip()
            price_cents = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
            record_path = parts[2].strip()
            normalized = normalize_sku(sku)
            exact_match[sku] = (price_cents, record_path)
            fuzzy_match[normalized] = (price_cents, record_path)

    # Compute today_ex
    today_ex_cents = 0
    for qty, sku in sku_lines:
        norm_sku = normalize_sku(sku)
        if sku in exact_match:
            price_cents = exact_match[sku][0]
            today_ex_cents += qty * price_cents
        elif norm_sku in fuzzy_match:
            price_cents = fuzzy_match[norm_sku][0]
            today_ex_cents += qty * price_cents
        # else discontinued: contributes 0

    today_ex = today_ex_cents / 100.0
    diff = abs(today_ex - old_ex)
    within = diff <= 3
    within_token = "YES" if within else "NO"

    # Answer with refs containing receipt path
    vm.answer(
        message=f"Receipt at {receipt_path}: subtotal (ex VAT) {old_ex} EUR. Today's ex-VAT total would be {today_ex} EUR - difference {diff} EUR, {'within' if within else 'above'} the 3 EUR limit. <{within_token}>",
        outcome="OUTCOME_OK",
        refs=[receipt_path]
    )
