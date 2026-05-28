import pytest

from agent.mock_vm_spy import MockVMSpy, fixture_key


def test_records_calls_in_order():
    vm = MockVMSpy(fixtures={})
    vm.exec(path="/bin/sql", args=[".schema baskets"])
    vm.read(path="/AGENTS.MD")
    assert vm.calls == [
        ("Exec", {"path": "/bin/sql", "args": [".schema baskets"]}),
        ("Read", {"path": "/AGENTS.MD"}),
    ]


def test_fixture_lookup_by_rpc_path_args():
    fx = {fixture_key("Exec", "/bin/sql", [".schema baskets"]): "schema-bytes"}
    vm = MockVMSpy(fixtures=fx)
    out = vm.exec(path="/bin/sql", args=[".schema baskets"])
    assert out == "schema-bytes"


def test_missing_fixture_returns_stub():
    vm = MockVMSpy(fixtures={})
    out = vm.exec(path="/bin/sql", args=["SELECT 1"])
    # stub is a deterministic empty-but-structured response
    assert out is not None


def test_answer_recorded_does_not_raise():
    vm = MockVMSpy(fixtures={})
    vm.answer(message="ok", outcome="OUTCOME_OK", refs=[])
    assert vm.calls[-1][0] == "Answer"


def test_all_rpcs_record():
    vm = MockVMSpy(fixtures={})
    vm.list(path="/proc")
    vm.tree(root="/", level=2)
    vm.find(root="/", name="*.json", limit=10)
    vm.search(root="/", pattern="foo", limit=5)
    vm.stat(path="/proc/x")
    vm.write(path="/tmp/x", content="data")
    vm.delete(path="/tmp/x")
    rpcs = [c[0] for c in vm.calls]
    assert rpcs == ["List", "Tree", "Find", "Search", "Stat", "Write", "Delete"]
