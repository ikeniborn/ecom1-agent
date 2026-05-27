import pytest
from agent.mock_vm import MockVM


def test_mock_vm_exec_returns_rows_from_params():
    vm = MockVM(
        extracted_params={"order_id": "ord_123", "customer_id": "cust_456"},
        schema_digest="orders(id, customer_id, total)\ncustomers(id, name)",
    )
    result = vm.exec(type("R", (), {"path": "/bin/sql", "args": ["SELECT * FROM orders"]})())
    assert result is not None
    assert hasattr(result, "stdout")
    import json
    rows = json.loads(result.stdout)
    assert isinstance(rows, list)


def test_mock_vm_read_returns_content():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.read(type("R", (), {"path": "/proc/orders/ord_001.json"})())
    assert result is not None
    assert hasattr(result, "content")
    assert isinstance(result.content, str)


def test_mock_vm_search_returns_matches():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.search(type("R", (), {"root": "/", "pattern": "order", "limit": 5})())
    assert hasattr(result, "matches")


def test_mock_vm_find_returns_nodes():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.find(type("R", (), {"root": "/", "name": "*.json", "limit": 5})())
    assert hasattr(result, "nodes")


def test_mock_vm_list_returns_entries():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.list(type("R", (), {"path": "/proc"})())
    assert hasattr(result, "entries")


def test_mock_vm_tree_returns_string():
    vm = MockVM(extracted_params={}, schema_digest="")
    result = vm.tree(type("R", (), {"root": "/", "level": 2})())
    assert result is not None


def test_mock_vm_answer_raises():
    vm = MockVM(extracted_params={}, schema_digest="")
    with pytest.raises(RuntimeError, match="vm.answer\\(\\) must not be called"):
        vm.answer(object())
