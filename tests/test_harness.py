import pytest
from agent.ir_models import PlanIR
from agent import harness
from agent.interpreter import lint, InterpretError


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def _denied_after_business():
    return _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"},
                               {"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"}],
                  "default_label": "ok"},
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []},
                "deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )


def test_load_checks_missing_file_returns_empty(tmp_path):
    assert harness.load_checks(tmp_path / "nope.yaml") == []


def test_seeded_checks_parse_and_include_security_first():
    specs = harness.load_checks()                 # default repo path
    assert any(s.get("kind") == "security_first" for s in specs)


def test_check_security_first_handler_flags_bad_order():
    spec = {"id": "chk_security_first", "kind": "security_first"}
    assert harness.check_security_first(_denied_after_business(), spec)   # non-empty -> violation
    assert harness.check_security_first(_plan(), spec) == []              # clean -> no violation


def test_lint_blocks_on_active_error_violation(monkeypatch):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "security_first",
                                          "severity": "error", "status": "active"}])
    with pytest.raises(InterpretError):
        lint(_denied_after_business())
    lint(_plan())                                  # clean plan -> no raise


def test_lint_skips_unknown_kind(monkeypatch, capsys):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "no_such_kind",
                                          "severity": "error", "status": "active"}])
    lint(_plan())                                  # no raise
    assert "unknown check kind" in capsys.readouterr().out


def test_lint_candidate_is_warn_only(monkeypatch, capsys):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "security_first",
                                          "severity": "error", "status": "candidate"}])
    lint(_denied_after_business())                 # candidate never blocks
    assert "warn" in capsys.readouterr().out


def _contract_plan(prim, *args):
    # first() produces a dict-binding `r0`; the named list-op then consumes it.
    return _plan(compute=[{"prim": "first", "args": ["$rows"], "into": "r0"},
                          {"prim": prim, "args": list(args), "into": "out"}])


def test_primitive_contract_flags_listop_on_scalar_source():
    spec = {"id": "chk_column_on_scalar", "kind": "primitive_contract",
            "prim": "column", "arg_index": 0, "forbid_source": ["first", "get"],
            "message": "'column' expects list[dict]; use 'get' for a single row"}
    assert harness.check_primitive_contract(_contract_plan("column", "$r0", "name"), spec)
    # Consuming a rowset binding (not first/get output) is fine.
    good = _plan(compute=[{"prim": "column", "args": ["$rows", "name"], "into": "out"}])
    assert harness.check_primitive_contract(good, spec) == []


def test_primitive_exists_flags_unknown_prim():
    spec = {"id": "chk_primitive_exists", "kind": "primitive_exists"}
    bad = _plan(compute=[{"prim": "frobnicate", "args": ["$rows"], "into": "out"}])
    assert harness.check_primitive_exists(bad, spec)
    assert harness.check_primitive_exists(_plan(), spec) == []


def test_primitive_arity_flags_wrong_arg_count():
    spec = {"id": "chk_primitive_arity", "kind": "primitive_arity"}
    # `get` takes 2 args (obj, key); supplying 1 is an arity violation.
    bad = _plan(compute=[{"prim": "get", "args": ["$r0"], "into": "out"}])
    assert harness.check_primitive_arity(bad, spec)
    ok = _plan(compute=[{"prim": "get", "args": ["$r0", "k"], "into": "out"}])
    assert harness.check_primitive_arity(ok, spec) == []


def test_seeded_checks_include_primitive_contract_active():
    specs = {s.get("id"): s for s in harness.load_checks()}
    assert specs["chk_column_on_scalar"]["status"] == "active"
    assert specs["chk_column_on_scalar"]["severity"] == "error"


def test_sql_stdin_handler_flags_args_with_empty_stdin():
    spec = {"id": "chk_sql_stdin", "kind": "sql_stdin", "message": "deliver SQL via stdin"}
    bad = _plan(discovery=[{"rpc": "Exec",
                            "args": {"path": "/bin/sql", "args": ["SELECT 1"]}, "bind": "r"}])
    assert harness.check_sql_stdin(bad, spec)
    good = _plan(discovery=[{"rpc": "Exec",
                             "args": {"path": "/bin/sql", "args": [], "stdin": "SELECT 1"},
                             "bind": "r"}])
    assert harness.check_sql_stdin(good, spec) == []


def test_seeded_sql_stdin_is_error():
    spec = {s["id"]: s for s in harness.load_checks()}["chk_sql_stdin"]
    assert spec["severity"] == "error" and spec["status"] == "active"


def test_repair_moves_sql_args_to_stdin_then_lint_passes():
    from agent.interpreter import repair_sql_stdin, lint
    plan = _plan(discovery=[{"rpc": "Exec",
                             "args": {"path": "/bin/sql", "args": ["SELECT 1"]}, "bind": "r"}])
    repaired = repair_sql_stdin(plan)
    st = repaired.discovery[0]
    assert st.args["stdin"] == "SELECT 1" and st.args["args"] == []
    spec = {"id": "chk_sql_stdin", "kind": "sql_stdin", "message": "m"}
    assert harness.check_sql_stdin(repaired, spec) == []
    lint(repaired)


def test_sql_exact_match_flags_raw_equality_not_normalized():
    spec = {"id": "chk_sql_exact_match", "kind": "sql_exact_match", "message": "normalize"}
    bad = _plan(discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": [],
        "stdin": "SELECT record_path FROM product_variants WHERE brand = 'Bosch'"}, "bind": "r"}])
    assert harness.check_sql_exact_match(bad, spec)
    good = _plan(discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": [],
        "stdin": "SELECT record_path FROM product_variants WHERE LOWER(TRIM(brand)) LIKE '%bosch%'"}, "bind": "r"}])
    assert harness.check_sql_exact_match(good, spec) == []


# --- check_compute_on_raw_discovery_bind tests ------------------------------------

_RAW_DISCOVERY_SPEC = {"id": "chk_compute_on_raw_discovery_bind", "kind": "compute_on_raw_discovery_bind"}


def test_compute_on_raw_discovery_bind_flags_list_prim_on_unparsed_bind():
    """concat consuming a raw discovery bind (no rowset for it) must be flagged."""
    bad = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT ..."}, "bind": "raw1"}],
        rowsets=[],
        compute=[{"prim": "concat", "args": ["$raw1", "$raw1"], "into": "rows"}],
    )
    assert harness.check_compute_on_raw_discovery_bind(bad, _RAW_DISCOVERY_SPEC)


def test_compute_on_raw_discovery_bind_passes_when_rowset_parses_bind():
    """concat consuming a rowset-parsed binding must NOT be flagged."""
    good = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT ..."}, "bind": "raw1"}],
        rowsets=[{"from": "raw1", "into": "rows1", "columns": []}],
        compute=[{"prim": "concat", "args": ["$rows1", "$rows1"], "into": "rows"}],
    )
    assert harness.check_compute_on_raw_discovery_bind(good, _RAW_DISCOVERY_SPEC) == []


def test_compute_on_raw_discovery_bind_passes_for_non_list_prim():
    """get is not a list-consuming primitive — raw bind is fine for scalar access."""
    good = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT ..."}, "bind": "raw1"}],
        rowsets=[],
        compute=[{"prim": "get", "args": ["$raw1", "k"], "into": "x"}],
    )
    assert harness.check_compute_on_raw_discovery_bind(good, _RAW_DISCOVERY_SPEC) == []


def test_lint_blocks_on_active_compute_on_raw_discovery_bind(monkeypatch):
    """lint() raises InterpretError when the check is active+error and the plan is bad."""
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "compute_on_raw_discovery_bind",
                                          "severity": "error", "status": "active"}])
    bad = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT ..."}, "bind": "raw1"}],
        rowsets=[],
        compute=[{"prim": "concat", "args": ["$raw1", "$raw1"], "into": "rows"}],
    )
    good = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT ..."}, "bind": "raw1"}],
        rowsets=[{"from": "raw1", "into": "rows1", "columns": []}],
        compute=[{"prim": "concat", "args": ["$rows1", "$rows1"], "into": "rows"}],
    )
    with pytest.raises(InterpretError):
        lint(bad)
    lint(good)  # good plan must not raise
