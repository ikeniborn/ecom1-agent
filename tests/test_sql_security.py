# tests/test_sql_security.py
import yaml
import pytest
from pathlib import Path
from agent.sql_security import check_sql_queries, check_path_access, load_security_gates

_GATES = [
    {"id": "sec-001", "pattern": "^\\s*(DROP|INSERT|UPDATE|DELETE|ALTER|CREATE)",
     "action": "block", "message": "DDL/DML prohibited"},
    {"id": "sec-002", "check": "no_where_clause",
     "action": "block", "message": "Full table scan prohibited — add WHERE clause"},
    {"id": "sec-003", "path_prefix": "/proc/catalog/",
     "action": "block", "message": "Use SQL only — direct catalog file reads prohibited"},
]


def test_ddl_drop_blocked():
    err = check_sql_queries(["DROP TABLE products"], _GATES)
    assert err is not None
    assert "sec-001" in err


def test_ddl_insert_blocked():
    err = check_sql_queries(["INSERT INTO products VALUES (1)"], _GATES)
    assert err is not None
    assert "sec-001" in err


def test_select_with_where_passes():
    err = check_sql_queries(["SELECT * FROM products WHERE type='X'"], _GATES)
    assert err is None


def test_select_without_where_blocked():
    err = check_sql_queries(["SELECT * FROM products"], _GATES)
    assert err is not None
    assert "sec-002" in err


def test_select_count_without_where_blocked():
    err = check_sql_queries(["SELECT COUNT(*) FROM products"], _GATES)
    assert err is not None
    assert "sec-002" in err


def test_explain_select_without_where_blocked():
    # EXPLAIN wraps the query — inner SELECT still has no WHERE
    # Note: EXPLAIN queries are validated before execute, not by this function
    # This tests that raw SELECT without WHERE is blocked
    err = check_sql_queries(["SELECT id FROM inventory"], _GATES)
    assert err is not None


def test_subquery_with_where_passes():
    # Outer query has WHERE; inner subquery is part of condition
    sql = "SELECT * FROM products WHERE id IN (SELECT id FROM inventory WHERE qty > 0)"
    err = check_sql_queries([sql], _GATES)
    assert err is None


def test_where_in_string_literal_not_confused():
    # "WHERE" inside a string value should not count
    sql = "SELECT * FROM products WHERE name = 'items WHERE available'"
    err = check_sql_queries([sql], _GATES)
    assert err is None


def test_multiple_queries_first_error_returned():
    queries = [
        "SELECT * FROM products WHERE type='X'",
        "DROP TABLE products",
    ]
    err = check_sql_queries(queries, _GATES)
    assert err is not None
    assert "sec-001" in err


def test_empty_queries_passes():
    assert check_sql_queries([], _GATES) is None


def test_path_catalog_blocked():
    err = check_path_access("/proc/catalog/ABC-123.json", _GATES)
    assert err is not None
    assert "sec-003" in err


def test_path_other_passes():
    err = check_path_access("/docs/readme.md", _GATES)
    assert err is None


def test_load_security_gates_from_dir(tmp_path):
    (tmp_path / "sec-001.yaml").write_text(
        'id: "sec-001"\npattern: "^\\\\s*(DROP)"\naction: block\nmessage: "DDL prohibited"'
    )
    (tmp_path / "sec-002.yaml").write_text(
        'id: "sec-002"\ncheck: "no_where_clause"\naction: block\nmessage: "Full scan prohibited"'
    )
    gates = load_security_gates(tmp_path)
    assert len(gates) == 2
    ids = {g["id"] for g in gates}
    assert ids == {"sec-001", "sec-002"}


def test_load_security_gates_empty_dir(tmp_path):
    gates = load_security_gates(tmp_path)
    assert gates == []


def test_unverified_gate_is_skipped(tmp_path):
    """Gates with verified: false are not loaded."""
    import yaml
    from agent.sql_security import load_security_gates
    (tmp_path / "sec-active.yaml").write_text(yaml.dump({
        "id": "sec-active", "pattern": "DROP", "action": "block", "message": "no drop"
    }))
    (tmp_path / "sec-unverified.yaml").write_text(yaml.dump({
        "id": "sec-unverified", "pattern": "UNION", "action": "block",
        "message": "no union", "verified": False
    }))
    gates = load_security_gates(tmp_path)
    assert len(gates) == 1
    assert gates[0]["id"] == "sec-active"


def test_has_where_clause_subquery():
    """_has_where_clause correctly detects WHERE in queries with subqueries."""
    from agent.sql_security import _has_where_clause
    assert _has_where_clause("SELECT * FROM t WHERE id IN (SELECT id FROM t2)")
    assert not _has_where_clause("SELECT * FROM t")
    assert _has_where_clause("SELECT * FROM t WHERE id IN (SELECT id FROM t2 WHERE x=1)")


def test_cte_with_where_passes():
    """CTE query with WHERE in the final SELECT passes the sec-002 gate."""
    sql = "WITH cte AS (SELECT id FROM products WHERE type='X') SELECT * FROM cte WHERE id > 0"
    err = check_sql_queries([sql], _GATES)
    assert err is None, f"CTE with WHERE should pass: {err}"


def test_where_in_double_quoted_identifier_not_confused():
    """Outer WHERE present despite double-quoted identifier containing WHERE substring."""
    sql = 'SELECT * FROM products WHERE "WHERE_clause" = 1'
    err = check_sql_queries([sql], _GATES)
    assert err is None, f"WHERE in double-quoted identifier with outer WHERE should pass: {err}"


def test_subquery_outer_has_where_passes():
    """Outer SELECT with WHERE passes even when subquery also has WHERE."""
    sql = "SELECT * FROM products WHERE id IN (SELECT id FROM inventory WHERE qty > 0)"
    err = check_sql_queries([sql], _GATES)
    assert err is None, f"Outer WHERE should pass: {err}"


def test_no_outer_where_blocked():
    """SELECT without WHERE is blocked by sec-002."""
    sql = "SELECT id FROM products"
    err = check_sql_queries([sql], _GATES)
    assert err is not None and "sec-002" in err


def test_check_retry_loop_standalone_blocks_duplicate():
    from agent.sql_security import check_retry_loop
    queries = ["SELECT COUNT(*) FROM products"]
    prior = [frozenset(queries)]
    result = check_retry_loop(queries, prior)
    assert result is not None
    assert "identical" in result.lower() or "loop" in result.lower()


def test_check_retry_loop_standalone_allows_new():
    from agent.sql_security import check_retry_loop
    queries = ["SELECT COUNT(*) FROM products"]
    result = check_retry_loop(queries, [])
    assert result is None
