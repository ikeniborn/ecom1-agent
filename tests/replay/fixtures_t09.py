from agent.mock_vm_spy import fixture_key

_SQL = ("SELECT COUNT(*) AS cnt FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = 'Non-Bladed Workshop';")
PARAMS = {"kind_name": "Non-Bladed Workshop"}
FIXTURES = {fixture_key("Exec", "/bin/sql", [_SQL]): {"stdout": "cnt\n42"}}
