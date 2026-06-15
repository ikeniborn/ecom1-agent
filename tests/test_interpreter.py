# tests/test_interpreter.py
from agent.ir_models import IntentSpec, PlanIR
from agent.interpreter import interpret
from agent.mock_vm_spy import MockVMSpy, fixture_key

_INTENT = IntentSpec(objective="o", desired_outcome="d",
                     outcome_space=["OUTCOME_OK"],
                     answer_shape={})


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
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={},
                        required_refs={"OUTCOME_OK": [{"kind": "record_path", "source": "$row0.record_path"}]})
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        compute=[{"prim": "first", "args": ["$rows"], "into": "row0"}],
        decision={"branches": [], "default_label": "ok"},
        answer={"ok": {"message": "Found {row0.sku}", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, intent, vm)
    assert res.captured.message == "Found A"
    assert res.captured.refs == ["/proc/catalog/A.json"]


def test_refuse_after_mutation_tags_mutation_landed():
    # A Write lands on the OK branch, then the refuse invariant fires (required record_path
    # ref unresolved). The raised error must carry mutation_landed=True so the pipeline
    # routes to terminal instead of re-planning (retry unsafe).
    fx = {fixture_key("Write", "/proc/x", None): {"stdout": "", "exit_code": 0}}
    vm = MockVMSpy(fixtures=fx)
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={},
                        required_refs={"OUTCOME_OK": [{"kind": "record_path", "source": "$w.record_path"}]})
    plan = _plan(
        decision={"branches": [], "default_label": "ok"},
        ops=[{"rpc": "Write", "args": {"path": "/proc/x", "content": "y"}, "bind": "w",
              "guard_label": "ok"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    try:
        interpret(plan, intent, vm)
        assert False, "expected InterpretError"
    except InterpretError as e:
        assert e.mutation_landed is True


def test_interpret_emits_vm_call_and_answer_when_trace_attached(tmp_path):
    import json as _json

    from agent.trace import TraceLogger, set_trace

    fx = {fixture_key("Exec", "/bin/sql", ["Q"]): {"stdout": "sku|record_path\nA|/proc/catalog/A.json"}}
    vm = MockVMSpy(fixtures=fx)
    intent = IntentSpec(
        objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"], answer_shape={},
        required_refs={"OUTCOME_OK": [{"kind": "record_path", "source": "$row0.record_path"}]},
    )
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        compute=[{"prim": "first", "args": ["$rows"], "into": "row0"}],
        answer={"ok": {"message": "Found {row0.sku}", "outcome": "OUTCOME_OK", "refs": []}},
    )
    p = tmp_path / "tX.jsonl"
    t = TraceLogger(p, "tX")
    set_trace(t)
    try:
        interpret(plan, intent, vm)
    finally:
        set_trace(None)
        t.close()
    recs = [_json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    vc = next(r for r in recs if r["type"] == "vm_call")
    assert vc["rpc"] == "Exec" and vc["phase"] == "INTERPRET" and "/bin/sql" in str(vc["args"])
    ans = next(r for r in recs if r["type"] == "answer")
    assert ans["outcome"] == "OUTCOME_OK" and ans["refs"] == ["/proc/catalog/A.json"]


def test_refuse_when_runtime_ref_required_but_unresolved():
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={},
                        required_refs={"OUTCOME_OK": [{"kind": "record_path", "source": "$row0.record_path"}]})
    plan = _plan(
        compute=[{"prim": "first", "args": [[]], "into": "row0"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)


def test_refuse_when_ok_has_only_static_refs_but_runtime_required():
    # Now equivalent to: a required record_path ref resolves empty alongside a policy_doc.
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={},
                        required_refs={"OUTCOME_OK": [
                            {"kind": "policy_doc", "path": "/docs/security.md"},
                            {"kind": "record_path", "source": "$missing"},
                        ]})
    plan = _plan(answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}})
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)


def test_refs_projected_from_required_refs_per_outcome():
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]):
          {"stdout": "sku|record_path\nA|/proc/catalog/A.json"}}
    vm = MockVMSpy(fixtures=fx)
    intent = IntentSpec(
        objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
        answer_shape={},
        required_refs={"OUTCOME_OK": [
            {"kind": "policy_doc", "path": "/docs/counting.md"},
            {"kind": "record_path", "source": "$row0.record_path"},
        ]},
    )
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        compute=[{"prim": "first", "args": ["$rows"], "into": "row0"}],
        answer={"ok": {"message": "Found {row0.sku}", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, intent, vm)
    assert res.captured.refs == ["/docs/counting.md", "/proc/catalog/A.json"]


def test_required_record_path_unresolved_refuses_on_ok():
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(
        objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
        answer_shape={},
        required_refs={"OUTCOME_OK": [{"kind": "record_path", "source": "$missing"}]},
    )
    plan = _plan(answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}})
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)
