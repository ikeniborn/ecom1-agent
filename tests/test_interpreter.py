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


import pytest
from agent.interpreter import lint_security_first, InterpretError


def test_decision_picks_first_true_branch():
    vm = MockVMSpy(fixtures={})
    plan = _plan(
        compute=[{"prim": "count", "args": [[1, 2]], "into": "n"}],
        decision={"branches": [{"when": {"op": "gt", "lhs": "$n", "rhs": 5}, "label": "big"},
                               {"when": {"op": "gt", "lhs": "$n", "rhs": 1}, "label": "some"}],
                  "default_label": "none"},
        answer={"big": {"message": "b", "outcome": "OUTCOME_OK", "refs": []},
                "some": {"message": "s", "outcome": "OUTCOME_OK", "refs": []},
                "none": {"message": "n", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.label == "some"


def test_security_first_lint_rejects_business_before_denied():
    plan = _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"},
                               {"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"}],
                  "default_label": "ok"},
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []},
                "deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )
    with pytest.raises(InterpretError):
        lint_security_first(plan)


def test_security_first_lint_accepts_denied_first():
    plan = _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"},
                               {"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"}],
                  "default_label": "ok"},
        answer={"deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []},
                "ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    lint_security_first(plan)  # no raise


def test_guarded_op_skipped_on_non_matching_label():
    vm = MockVMSpy(fixtures={})
    plan = _plan(
        decision={"branches": [], "default_label": "deny"},
        ops=[{"rpc": "Exec", "args": {"path": "/bin/checkout", "args": ["b1"]},
              "bind": "co", "guard_label": "ok"}],
        answer={"deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert ("Exec", {"path": "/bin/checkout", "args": ["b1"], "stdin": ""}) not in vm.calls
    assert res.mutation_landed is False


def test_guarded_op_runs_on_matching_label():
    fx = {fixture_key("Exec", "/bin/checkout", ["b1"]): {"stdout": "OK", "exit_code": 0}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        decision={"branches": [], "default_label": "ok"},
        ops=[{"rpc": "Write", "args": {"path": "/proc/x", "content": "y"},
              "bind": "w", "guard_label": "ok"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.mutation_landed is True


def test_outcome_from_exit_overrides_outcome():
    fx = {fixture_key("Exec", "/bin/checkout", ["b1"]):
          {"stdout": "line out of stock", "exit_code": 1}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        decision={"branches": [], "default_label": "ok"},
        ops=[{"rpc": "Exec", "args": {"path": "/bin/checkout", "args": ["b1"]}, "bind": "co",
              "outcome_from_exit": {"ok_outcome": "OUTCOME_OK",
                                    "keyword_buckets": [{"keywords": ["out of stock"],
                                                         "outcome": "OUTCOME_NONE_UNSUPPORTED"}],
                                    "default_outcome": "OUTCOME_NONE_UNSUPPORTED"}}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.captured.outcome == "OUTCOME_NONE_UNSUPPORTED"


def test_answer_resolves_slots_and_refs():
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]): {"stdout": "sku|record_path\nA|/proc/catalog/A.json"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        compute=[{"prim": "first", "args": ["$rows"], "into": "row0"}],
        decision={"branches": [], "default_label": "ok"},
        answer={"ok": {"message": "Found {row0.sku}", "outcome": "OUTCOME_OK",
                       "refs": ["$row0.record_path"]}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.captured.message == "Found A"
    assert res.captured.refs == ["/proc/catalog/A.json"]


def test_refuse_after_mutation_tags_mutation_landed():
    # A Write lands on the OK branch, then the refuse invariant fires (runtime ref
    # required but unresolved). The raised error must carry mutation_landed=True so
    # the pipeline routes to terminal instead of re-planning (retry unsafe).
    fx = {fixture_key("Write", "/proc/x", None): {"stdout": "", "exit_code": 0}}
    vm = MockVMSpy(fixtures=fx)
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={"required_ref_kinds": ["runtime"]})
    plan = _plan(
        decision={"branches": [], "default_label": "ok"},
        ops=[{"rpc": "Write", "args": {"path": "/proc/x", "content": "y"}, "bind": "w",
              "guard_label": "ok"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": ["$w.record_path"]}},
    )
    try:
        interpret(plan, intent, vm)
        assert False, "expected InterpretError"
    except InterpretError as e:
        assert e.mutation_landed is True


def test_refuse_when_runtime_ref_required_but_unresolved():
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={"required_ref_kinds": ["runtime"]})
    plan = _plan(
        compute=[{"prim": "first", "args": [[]], "into": "row0"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": ["$row0.record_path"]}},
    )
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)


def test_refuse_when_ok_has_only_static_refs_but_runtime_required():
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={"required_ref_kinds": ["runtime"]})
    plan = _plan(answer={"ok": {"message": "m", "outcome": "OUTCOME_OK",
                                "refs": ["/docs/security.md"]}})
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)
