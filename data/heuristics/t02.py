import csv
import io

def run(vm, params):
    # Bind parameters
    brand = params["brand"]
    series = params["series"]
    model = params["model"]
    product_name_like = params["product_name_like"]
    color = params["color"]

    # Discovery: /bin/id (no-op, but required)
    id_context = vm.exec(path="/bin/id")

    # Discovery: tree on /docs with level 2
    docs_tree = vm.tree(root="/docs", level=2)

    # Discovery: SQL query for product path
    sql_query_discovery = (
        "SELECT pv.record_path\n"
        "FROM product_variants pv\n"
        "JOIN product_variant_properties pvp ON pv.product_sku = pvp.product_sku\n"
        "WHERE pv.brand = :brand\n"
        "  AND pv.series = :series\n"
        "  AND pv.model = :model\n"
        "  AND pv.product_name LIKE :product_name_like\n"
        "  AND pvp.property_key = 'color_family'\n"
        "  AND pvp.property_value_text = :color\n"
        "LIMIT 1;"
    )
    stdin_lines = [sql_query_discovery, "", f"brand={brand}", f"series={series}", f"model={model}", f"product_name_like={product_name_like}", f"color={color}"]
    stdin_content = "\n".join(stdin_lines)
    product_path_result = vm.exec(path="/bin/sql", args=[], stdin=stdin_content)
    stdout = getattr(product_path_result, "stdout", "")
    if isinstance(product_path_result, dict):
        stdout = product_path_result.get("stdout", "")
    product_path = ""
    if stdout.strip():
        reader = csv.reader(io.StringIO(stdout.strip()), delimiter="|")
        rows = list(reader)
        if len(rows) >= 2:  # Skip header
            product_path = rows[1][0].strip() if rows[1] else ""

    # Ops: Check existence and get answer message
    sql_query_check = (
        "SELECT CASE\n"
        "  WHEN EXISTS(\n"
        "    SELECT 1\n"
        "    FROM product_variants pv\n"
        "    JOIN product_variant_properties pvp ON pv.product_sku = pvp.product_sku\n"
        "    WHERE pv.brand = :brand\n"
        "      AND pv.series = :series\n"
        "      AND pv.model = :model\n"
        "      AND pv.product_name LIKE :product_name_like\n"
        "      AND pvp.property_key = 'color_family'\n"
        "      AND pvp.property_value_text = :color\n"
        "  ) THEN '<YES> Product found: ' || (\n"
        "    SELECT pv.record_path\n"
        "    FROM product_variants pv\n"
        "    JOIN product_variant_properties pvp ON pv.product_sku = pvp.product_sku\n"
        "    WHERE pv.brand = :brand\n"
        "      AND pv.series = :series\n"
        "      AND pv.model = :model\n"
        "      AND pv.product_name LIKE :product_name_like\n"
        "      AND pvp.property_key = 'color_family'\n"
        "      AND pvp.property_value_text = :color\n"
        "    LIMIT 1\n"
        "  )\n"
        "  ELSE '<NO> No matching product in catalogue'\n"
        "END AS answer_msg;"
    )
    stdin_lines_check = [
        sql_query_check,
        "",
        f"brand={brand}",
        f"series={series}",
        f"model={model}",
        f"product_name_like={product_name_like}",
        f"color={color}"
    ]
    stdin_content_check = "\n".join(stdin_lines_check)
    result_raw_result = vm.exec(path="/bin/sql", args=[], stdin=stdin_content_check)
    result_raw_stdout = getattr(result_raw_result, "stdout", "")
    if isinstance(result_raw_result, dict):
        result_raw_stdout = result_raw_result.get("stdout", "")
    result_raw = result_raw_stdout.strip() if result_raw_stdout else "<NO> No matching product in catalogue"

    # Build refs list
    refs = ["/proc/catalog/"]
    if product_path:
        refs.append(product_path)

    # Answer
    vm.answer(message=result_raw, outcome="OUTCOME_OK", refs=refs)
