# tests/test_interpreter.py
from agent.ir_models import IntentSpec, PlanIR
from agent.interpreter import interpret
from agent.mock_vm_spy import MockVMSpy, fixture_key

_INTENT = IntentSpec(objective="o", desired_outcome="d",
                     outcome_space=["OUTCOME_OK"],
                     answer_shape={"required_ref_kinds": ["static"]})


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def test_discovery_runs_in_order_and_binds():
    sql = "SELECT COUNT(*) AS cnt FROM x"
    fx = {fixture_key("Exec", "/bin/sql", [sql]): {"stdout": "cnt\n7"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(discovery=[{"rpc": "Exec",
                             "args": {"path": "/bin/sql", "args": [sql]}, "bind": "raw"}])
    res = interpret(plan, _INTENT, vm)
    assert ("Exec", {"path": "/bin/sql", "args": [sql], "stdin": ""}) in vm.calls
    assert res.env["raw"] is not None
    assert res.sql_results == ["cnt\n7"]


def test_rowset_pipe_delim_with_col_resolve():
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]): {"stdout": "sku|price\nA|100\nB|50"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows",
                  "columns": [{"into": "price", "candidates": ["price", "price_cents"]}]}],
    )
    res = interpret(plan, _INTENT, vm)
    assert res.env["rows"] == [{"sku": "A", "price": "100"}, {"sku": "B", "price": "50"}]


def test_compute_steps_chain():
    vm = MockVMSpy(fixtures={})
    plan = _plan(
        compute=[
            {"prim": "abs_diff", "args": [10, 3], "into": "diff"},
            {"prim": "div", "args": ["$diff", 2], "into": "half"},
        ],
    )
    res = interpret(plan, _INTENT, vm)
    assert res.env["diff"] == 7 and res.env["half"] == 3.5


def test_custom_extract_writes_rowset():
    fx = {fixture_key("Read", "/uploads/r.txt", None): {"content": "ABC-0I5"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        discovery=[{"rpc": "Read", "args": {"path": "/uploads/r.txt"}, "bind": "receipt"}],
        custom_extract=[{"name": "fuzzy_sku_receipt", "input": "receipt", "into": "skus"}],
    )
    res = interpret(plan, _INTENT, vm)
    assert isinstance(res.env["skus"], list) and res.env["skus"]
    assert "normalized" in res.env["skus"][0]
