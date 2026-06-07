import re

def run(vm, params):
    # Discovery phase
    upload_dir = vm.list(path="/uploads/")
    items = upload_dir.get("items", [])
    upload_files = [item for item in items if isinstance(item, dict) and item.get("kind") == "FILE"]
    if not upload_files:
        upload_files = [item for item in items if isinstance(item, dict) and '.' in item.get("name", "")]
    if not upload_files:
        upload_files = [item for item in items if isinstance(item, dict)]
    receipt_path = upload_files[0]["name"] if upload_files else ""
    receipt_full_path = "/uploads/" + receipt_path if receipt_path else "/uploads/"
    
    try:
        receipt_text = vm.read(path=receipt_full_path, start_line=1, end_line=0)
        if isinstance(receipt_text, dict):
            receipt_text = receipt_text.get("text", "")
    except Exception:
        receipt_text = ""
    
    sku_search = vm.search(root="/uploads/", pattern="[A-Z]{3}-[A-Z0-9]{8}", limit=100)
    if isinstance(sku_search, dict):
        sku_search = sku_search.get("matches", [])
    
    sku_search2 = vm.search(root="/uploads/", pattern="[A-Z]{3}-[A-Z0-9]+", limit=100)
    if isinstance(sku_search2, dict):
        sku_search2 = sku_search2.get("matches", [])
    
    all_skus = []
    for s in sku_search:
        if s not in all_skus:
            all_skus.append(s)
    for s in sku_search2:
        if s not in all_skus:
            all_skus.append(s)
    
    # Parse receipt SKUs
    receipt_skus = []
    for line in receipt_text.splitlines() if isinstance(receipt_text, str) else []:
        matches = re.findall(r"[A-Z]{3}-[A-Z0-9]+", line)
        for m in matches:
            if m not in receipt_skus:
                receipt_skus.append(m)
    
    # Get candidate prices from catalogue
    if all_skus:
        quoted_skus = ','.join("'" + s.replace("'", "''") + "'" for s in all_skus)
        sql_query = f"SELECT product_sku, price_cents FROM product_variants WHERE product_sku IN ({quoted_skus});"
        candidate_prices = vm.exec(path="/bin/sql", args=[], stdin=sql_query)
    else:
        candidate_prices = vm.exec(path="/bin/sql", args=[], stdin="SELECT product_sku, price_cents FROM product_variants WHERE 1=0;")
    
    # Parse SQL output
    stdout = getattr(candidate_prices, "stdout", "") or (candidate_prices.get("stdout", "") if isinstance(candidate_prices, dict) else "")
    lines = stdout.strip().split('\n') if stdout else []
    catalogue = {}
    for line in lines[1:] if len(lines) > 1 else []:
        parts = line.split(',')
        if len(parts) >= 2:
            sku = parts[0].strip()
            try:
                price_cents = int(parts[1].strip())
            except ValueError:
                continue
            catalogue[sku] = price_cents
    
    # Fuzzy mapping
    def normalize_sku(sku):
        return sku.replace('0', 'O').replace('1', 'I').replace('5', 'S').replace('8', 'B').replace('2', 'Z').upper()
    
    fuzzy_map = {}
    for sku in catalogue:
        normalized = normalize_sku(sku)
        fuzzy_map[normalized] = catalogue[sku]
    
    # Parse receipt lines and compute old_ex (SUBTOTAL)
    old_ex = 0.0
    for line in receipt_text.splitlines() if isinstance(receipt_text, str) else []:
        line_upper = line.upper().replace('O', '0').replace('I', '1').replace('S', '5').replace('B', '8').replace('Z', '2')
        if 'SUB' in line_upper and 'TOTAL' in line_upper:
            match = re.search(r'[\$€]?\s*([\d.,]+)', line)
            if match:
                try:
                    val_str = match.group(1).replace(',', '').replace('.', '')
                    old_ex = float(val_str) / 100 if '.' in match.group(1) else float(val_str)
                except ValueError:
                    pass
                break
    
    # Compute today_ex with exact + fuzzy matching, discontinued SKUs contribute 0
    today_ex = 0.0
    for sku in receipt_skus:
        normalized = normalize_sku(sku)
        if sku in catalogue:
            price = catalogue[sku]
        elif normalized in fuzzy_map:
            price = fuzzy_map[normalized]
        else:
            price = 0  # discontinued SKU contributes 0
        today_ex += price / 100
    
    # Compute difference and threshold
    threshold = params.get("euro_threshold", 2)
    diff = abs(today_ex - old_ex)
    outcome_token = "<YES>" if diff <= threshold else "<NO>"
    
    # Final answer
    message = f"Receipt subtotal (ex-VAT): {old_ex:.2f} EUR. Today's ex-VAT total: {today_ex:.2f} EUR. Difference: {diff:.2f} EUR. Within the {threshold} EUR threshold? {outcome_token}"
    vm.answer(message=message, outcome="OUTCOME_OK", refs=[receipt_full_path])
