# tests/test_data_files.py
"""Content-verification tests for data/ directory files."""
from pathlib import Path
import yaml

DATA_DIR = Path(__file__).parent.parent / "data"
RULES_DIR = DATA_DIR / "rules"
SECURITY_DIR = DATA_DIR / "security"
PROMPTS_DIR = DATA_DIR / "prompts"

EXPECTED_RULE_IDS = {
    # Restored from git
    "sql-015", "sql-016", "sql-017", "sql-031",
    "sql-sku-required", "sql-retry-divergence", "sql-count-with-sample",
    # New — from sdd.md
    "sql-discovery-patterns", "sql-discovery-fallback",
    "sql-multi-attribute-exists", "sql-store-discovery",
    "sql-inventory-projection", "sql-cart-query",
    "sql-product-line-model", "sql-not-found",
    # New — from learn.md
    "sql-learn-patterns",
    # New — from answer.md
    "sql-grounding-refs", "sql-model-name-fidelity",
    "sql-key-existence-vs-sku", "sql-missing-numeric-field",
    "sql-store-scope",
}


def _load_all_rules() -> dict:
    rules = {}
    for f in RULES_DIR.glob("*.yaml"):
        r = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(r, dict):
            rules[r["id"]] = r
    return rules


# ── Rules ────────────────────────────────────────────────────────────────────

def test_all_expected_rule_ids_present():
    loaded = _load_all_rules()
    missing = EXPECTED_RULE_IDS - set(loaded.keys())
    assert not missing, f"Missing rule IDs: {missing}"


def test_all_rules_verified_and_phase_sql_plan():
    loaded = _load_all_rules()
    for rule_id, rule in loaded.items():
        assert rule.get("verified") is True, f"{rule_id}: verified != True"
        assert rule.get("phase") == "sql_plan", f"{rule_id}: phase != sql_plan"
        assert rule.get("content"), f"{rule_id}: content is empty"


def test_rules_loader_returns_all_verified():
    from agent.rules_loader import RulesLoader
    loader = RulesLoader(RULES_DIR)
    md = loader.get_rules_markdown(phase="sql_plan", verified_only=True)
    for rule_id in EXPECTED_RULE_IDS:
        rule = _load_all_rules()[rule_id]
        first_20 = rule["content"][:20]
        assert first_20 in md, f"Rule {rule_id} content not in assembled markdown"


def test_sql015_scoped_to_products():
    rules = _load_all_rules()
    content = rules["sql-015"]["content"]
    assert "products" in content
    assert "COUNT" in content
    assert "name" in content


def test_sql017_kinds_table_and_products_fallback():
    rules = _load_all_rules()
    content = rules["sql-017"]["content"]
    assert "kinds" in content
    assert "products.name" in content


def test_sql_count_with_sample_scoped_to_products():
    rules = _load_all_rules()
    content = rules["sql-count-with-sample"]["content"]
    assert "products" in content
    assert "sku" in content
    assert "path" in content


def test_sql_discovery_patterns_like_no_ilike():
    rules = _load_all_rules()
    content = rules["sql-discovery-patterns"]["content"]
    assert "LIKE" in content
    assert "ILIKE" in content
    assert "SQLite" in content or "sqlite" in content.lower()


def test_sql_discovery_fallback_zero_rows():
    rules = _load_all_rules()
    content = rules["sql-discovery-fallback"]["content"]
    assert "0 rows" in content or "fallback" in content.lower()


def test_sql_multi_attribute_exists_subquery():
    rules = _load_all_rules()
    content = rules["sql-multi-attribute-exists"]["content"]
    assert "EXISTS" in content
    assert "product_properties" in content


def test_sql_store_discovery_store_id():
    rules = _load_all_rules()
    content = rules["sql-store-discovery"]["content"]
    assert "store_id" in content
    assert "stores" in content


def test_sql_inventory_projection_available_today():
    rules = _load_all_rules()
    content = rules["sql-inventory-projection"]["content"]
    assert "available_today" in content
    assert "store_id" in content


def test_sql_cart_query_join_pattern():
    rules = _load_all_rules()
    content = rules["sql-cart-query"]["content"]
    assert "cart_items" in content
    assert "customer_id" in content


def test_sql_product_line_model_column():
    rules = _load_all_rules()
    content = rules["sql-product-line-model"]["content"]
    assert "model" in content
    assert "series" in content


def test_sql_not_found_grounding_refs_empty():
    rules = _load_all_rules()
    content = rules["sql-not-found"]["content"]
    assert "grounding_refs" in content or "NO" in content


def test_sql_learn_patterns_join_bug():
    rules = _load_all_rules()
    content = rules["sql-learn-patterns"]["content"]
    assert "product_properties" in content
    assert "EXISTS" in content or "join" in content.lower()


def test_sql_grounding_refs_sku_mandatory():
    rules = _load_all_rules()
    content = rules["sql-grounding-refs"]["content"]
    assert "sku" in content.lower()
    assert "AUTO_REFS" in content


def test_sql_model_name_fidelity_exact():
    rules = _load_all_rules()
    content = rules["sql-model-name-fidelity"]["content"]
    assert "exact" in content.lower() or "SQL" in content


def test_sql_key_existence_vs_sku_distinct():
    rules = _load_all_rules()
    content = rules["sql-key-existence-vs-sku"]["content"]
    assert "discovery" in content.lower() or "filter" in content.lower()
    assert "sku" in content.lower()


def test_sql_missing_numeric_field_learn():
    rules = _load_all_rules()
    content = rules["sql-missing-numeric-field"]["content"]
    assert "available_today" in content or "on_hand" in content
    assert "LEARN" in content or "learn" in content.lower()


def test_sql_store_scope_city_filter():
    rules = _load_all_rules()
    content = rules["sql-store-scope"]["content"]
    assert "store_id" in content
    assert "city" in content.lower() or "filter" in content.lower()


# ── Security gates ───────────────────────────────────────────────────────────

def test_security_gates_load_both_files():
    from agent.sql_security import load_security_gates
    gates = load_security_gates(SECURITY_DIR)
    ids = {g["id"] for g in gates}
    assert "sec-write-detect-001" in ids
    assert "sec-capability-keys" in ids


def test_write_detect_pattern_blocks_sql_mutations():
    from agent.sql_security import check_sql_queries, load_security_gates
    gates = load_security_gates(SECURITY_DIR)
    mutations = [
        "INSERT INTO products VALUES (1)",
        "DELETE FROM products WHERE sku='X'",
        "DROP TABLE products",
        "UPDATE products SET name='X' WHERE sku='Y'",
        "TRUNCATE TABLE products",
        "ALTER TABLE products ADD COLUMN x TEXT",
    ]
    for sql in mutations:
        err = check_sql_queries([sql], gates)
        assert err is not None, f"Mutation not blocked: {sql}"


def test_write_detect_does_not_block_select():
    from agent.sql_security import check_sql_queries, load_security_gates
    gates = [g for g in load_security_gates(SECURITY_DIR) if g["id"] == "sec-write-detect-001"]
    err = check_sql_queries(["SELECT sku FROM products WHERE brand='Heco'"], gates)
    assert err is None


def test_capability_keys_has_message_and_terms():
    from agent.sql_security import load_security_gates
    gates = load_security_gates(SECURITY_DIR)
    gate = next(g for g in gates if g["id"] == "sec-capability-keys")
    msg = gate.get("message", "")
    assert msg, "sec-capability-keys must have a message"
    assert any(term in msg.lower() for term in ["wifi", "app", "iot", "schedul"])


# ── Prompt patches ───────────────────────────────────────────────────────────

def test_plan_aborted_identical_in_rules():
    rules = _load_all_rules()
    content = rules["sql-retry-divergence"]["content"]
    assert "PLAN_ABORTED_IDENTICAL" in content


def test_column_existence_in_rules():
    rules = _load_all_rules()
    content = rules["sql-031"]["content"]
    assert "column" in content.lower()
    assert "digest" in content.lower() or "schema" in content.lower()


def test_zero_column_table_skip_in_rules():
    rules = _load_all_rules()
    content = rules["sql-017"]["content"]
    assert "kinds" in content
    assert "products.name" in content


def test_discovery_fallback_in_rules():
    rules = _load_all_rules()
    content = rules["sql-discovery-fallback"]["content"]
    assert "0 rows" in content or "fallback" in content.lower()


def test_sdd_vague_task_gate():
    content = (PROMPTS_DIR / "sdd.md").read_text(encoding="utf-8")
    assert "10 characters" in content or "< 10" in content or "10 chars" in content


def test_answer_schema_mismatch_clarification_forbidden():
    content = (PROMPTS_DIR / "answer.md").read_text(encoding="utf-8")
    assert "schema" in content.lower()
    assert "schema-mismatch" in content or "schema mismatch" in content.lower()


def test_learn_loop_cap_in_rules():
    rules = _load_all_rules()
    content = rules["sql-016"]["content"]
    assert "learn_ctx" in content
    assert ">=2" in content or "≥2" in content or ">= 2" in content
