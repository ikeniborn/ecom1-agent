import os
from agent.llm import _resolve_model_for_phase, _think_for_phase


def test_investigate_phase_is_fast_tier(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.delenv("ECOM_MODEL_INVESTIGATE", raising=False)
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "fast-model"
    assert _think_for_phase("INVESTIGATE") is False


def test_investigate_phase_override_wins(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.setenv("ECOM_MODEL_INVESTIGATE", "explicit-model")
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "explicit-model"


from agent.investigate import Note, Brief, render_brief


def test_brief_accumulates_notes_and_env():
    brief = Brief()
    brief.notes.append(Note(goal="find incident", tool="exec",
                            args={"path": "/bin/sql"}, observation_digest="3 rows",
                            lesson="incident id lives in fraud_reports",
                            refs_found=["/payments/p_1.json"]))
    brief.env["incident_id"] = "INC-7"
    assert len(brief.notes) == 1
    assert brief.env["incident_id"] == "INC-7"


def test_render_brief_is_compact_and_contains_env_and_lessons():
    brief = Brief()
    brief.notes.append(Note(goal="g", tool="read", args={"path": "/docs/x.md"},
                            observation_digest="policy says N=2", lesson="use N=2",
                            refs_found=[]))
    brief.env["governing_doc"] = "/docs/x.md"
    out = render_brief(brief)
    assert "INVESTIGATION_BRIEF" in out
    assert "use N=2" in out               # lesson surfaced
    assert "governing_doc" in out         # env surfaced
    assert "/docs/x.md" in out


def test_render_brief_empty_is_falsy_marker():
    assert render_brief(Brief()) == ""


# --- Task 3: read-only whitelist + tool dispatch ---
import pytest
from agent.investigate import is_readonly, run_tool, ToolRejected
from agent.mock_vm_spy import MockVMSpy, fixture_key


def test_is_readonly_allows_reads_and_select():
    assert is_readonly("read", {"path": "/docs/x.md"})
    assert is_readonly("tree", {"root": "/docs"})
    assert is_readonly("exec", {"path": "/bin/sql", "stdin": "SELECT * FROM t"})


def test_is_readonly_rejects_mutations():
    assert not is_readonly("write", {"path": "/x", "content": "y"})
    assert not is_readonly("delete", {"path": "/x"})
    assert not is_readonly("exec", {"path": "/bin/sql", "stdin": "UPDATE t SET a=1"})
    assert not is_readonly("exec", {"path": "/bin/rm", "args": ["-rf", "/"]})  # arbitrary binary rejected


def test_is_readonly_allows_bin_id():
    # /bin/id is a read-only identity probe (no SQL, no mutation)
    assert is_readonly("exec", {"path": "/bin/id"})
    assert is_readonly("exec", {"path": "/bin/id", "stdin": ""})
    assert is_readonly("exec", {"path": "/BIN/ID"})            # case-normalised
    assert is_readonly("exec", {"path": "/bin/id", "stdin": "ignored by id"})


def test_run_tool_dispatches_bin_id_identity_probe():
    fx = {fixture_key("Exec", "/bin/id"): {"stdout": "user=cust_016 role=customer"}}
    vm = MockVMSpy(fx)
    out = run_tool(vm, "exec", {"path": "/bin/id"})
    assert "cust_016" in out
    assert vm.calls and vm.calls[-1][0] == "Exec"
    # dispatched the real /bin/id binary, NOT coerced to /bin/sql
    assert vm.calls[-1][1].get("path") == "/bin/id"


def test_run_tool_executes_read_only_and_records():
    # MockVMSpy records/keys RPCs CAPITALIZED ("Read"), though vm.read() is the method.
    fx = {fixture_key("Read", "/docs/x.md"): {"content": "# Policy\nN=2"}}
    vm = MockVMSpy(fx)
    out = run_tool(vm, "read", {"path": "/docs/x.md"})   # investigator tool name is lowercase
    assert "N=2" in out
    assert vm.calls and vm.calls[-1][0] == "Read"


def test_run_tool_rejects_mutation():
    vm = MockVMSpy({})
    with pytest.raises(ToolRejected):
        run_tool(vm, "write", {"path": "/x", "content": "y"})
    assert not any(c[0] == "Write" for c in vm.calls)   # never dispatched


def test_is_readonly_rejects_cte_wrapped_dml():
    assert not is_readonly("exec", {"path": "/bin/sql",
                                    "stdin": "WITH x AS (DELETE FROM t RETURNING id) SELECT * FROM x"})


def test_is_readonly_rejects_multi_statement():
    assert not is_readonly("exec", {"path": "/bin/sql", "stdin": "SELECT 1; DROP TABLE t"})


def test_is_readonly_allows_single_trailing_semicolon():
    assert is_readonly("exec", {"path": "/bin/sql", "stdin": "SELECT * FROM t;"})


def test_is_readonly_normalises_sql_binary_path_case():
    assert is_readonly("exec", {"path": "/BIN/SQL", "stdin": "SELECT 1"})


from agent.investigate import tool_signature, is_stalled


def test_tool_signature_normalises_sql_whitespace_and_case():
    a = tool_signature("exec", {"path": "/bin/sql", "stdin": "SELECT  *\nFROM t"})
    b = tool_signature("exec", {"path": "/bin/sql", "stdin": "select * from t"})
    assert a == b


def test_is_stalled_on_empty_result():
    assert is_stalled(result="", signature="read:/docs/x.md", seen_signatures=set())


def test_is_stalled_on_repeated_signature():
    assert is_stalled(result="rows", signature="read:/docs/x.md",
                      seen_signatures={"read:/docs/x.md"})


def test_not_stalled_on_fresh_nonempty():
    assert not is_stalled(result="rows", signature="read:/docs/y.md",
                          seen_signatures={"read:/docs/x.md"})


from agent.investigate import sufficient
from agent.ir_models import IntentSpec, RefSpec


def _intent_with_refs():
    return IntentSpec(
        objective="cite fraud payments",
        desired_outcome="OUTCOME_OK",
        outcome_space=["OUTCOME_OK"],
        answer_shape={},
        required_refs={"OUTCOME_OK": [
            RefSpec(kind="policy_doc", path="/docs/security.md"),
            RefSpec(kind="record_path", source="$row.record_path"),
        ]},
    )


def test_sufficient_false_when_refs_unbound():
    assert not sufficient(_intent_with_refs(), env={})


def test_sufficient_true_when_all_refs_grounded():
    env = {"policy_doc:/docs/security.md": True, "row.record_path": "/payments/p_1.json"}
    assert sufficient(_intent_with_refs(), env=env)


def test_sufficient_true_when_only_policy_doc_grounded_record_path_ungrounded():
    # L3: record_path is PLAN-produced — sufficient() must not block on it.
    intent = IntentSpec(
        objective="cite fraud payments",
        desired_outcome="OUTCOME_OK",
        outcome_space=["OUTCOME_OK"],
        answer_shape={},
        required_refs={"OUTCOME_OK": [
            RefSpec(kind="policy_doc", path="/docs/security.md"),
            RefSpec(kind="record_path", source="$row.record_path"),
        ]},
    )
    env = {"policy_doc:/docs/security.md": True}   # record_path NOT in env
    assert sufficient(intent, env) is True


def test_sufficient_true_when_no_required_refs():
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
    assert sufficient(intent, env={})


def test_sufficient_true_when_only_record_path_refs():
    """required_refs with ONLY a PLAN-produced record_path ref must not block the
    investigator (record_path is groundable only by a PLAN rowset, never by reads)."""
    intent = IntentSpec(
        objective="x", desired_outcome="OUTCOME_OK", outcome_space=["OUTCOME_OK"],
        answer_shape={},
        required_refs={"OUTCOME_OK": [RefSpec(kind="record_path", source="$row.record_path")]},
    )
    assert sufficient(intent, env={}) is True


import agent.investigate as inv


def test_router_parses_tool_choice(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda system, user, phase, escalate: {
                            "tool": "read", "args": {"path": "/docs/security.md"},
                            "why": "need the governing rule"})
    act = inv.router(_intent_with_refs(), Brief(), atoms=[], escalate=False)
    assert act["tool"] == "read"
    assert act["args"]["path"] == "/docs/security.md"


def test_router_emits_done(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda system, user, phase, escalate: {"done": True})
    act = inv.router(_intent_with_refs(), Brief(), atoms=[], escalate=False)
    assert act.get("done") is True


def test_digest_returns_note_fields(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda system, user, phase, escalate: {
                            "observation_digest": "security.md requires citing record_path",
                            "lesson": "cite the payment record_path",
                            "env_updates": {"policy_doc:/docs/security.md": True},
                            "refs_found": []})
    note, env_updates = inv.digest(goal="read policy", tool="read",
                                   args={"path": "/docs/security.md"},
                                   observation="# Security…", escalate=False)
    assert note.lesson == "cite the payment record_path"
    assert env_updates["policy_doc:/docs/security.md"] is True


def test_escalate_switches_model(monkeypatch):
    seen = {}
    def fake_raw(system, user_msg, model, cfg, **kw):
        seen["model"] = model
        return '{"done": true}'
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-m")
    monkeypatch.setenv("ECOM_MODEL_REASON", "reason-m")
    monkeypatch.setattr(inv, "call_llm_raw", fake_raw)
    inv._call_json("sys", "user", phase="INVESTIGATE", escalate=True)
    assert seen["model"] == "reason-m"   # escalation forces the reason tier


def test_fast_tier_used_when_not_escalating(monkeypatch):
    seen = {}
    def fake_raw(system, user_msg, model, cfg, **kw):
        seen["model"] = model
        seen["think"] = kw.get("think")
        return '{"done": true}'
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-m")
    monkeypatch.setenv("ECOM_MODEL_REASON", "reason-m")
    monkeypatch.delenv("ECOM_MODEL_INVESTIGATE", raising=False)
    monkeypatch.setattr(inv, "call_llm_raw", fake_raw)
    inv._call_json("sys", "user", phase="INVESTIGATE", escalate=False)
    assert seen["model"] == "fast-m"     # non-escalate hot path uses the fast tier
    assert seen["think"] is False        # fast tier → think off


def test_investigate_stops_on_sufficiency(monkeypatch):
    intent = _intent_with_refs()
    fx = {fixture_key("Read", "/docs/security.md"): {"content": "cite record_path"}}
    vm = MockVMSpy(fx)
    # router asks to read the policy, then would loop; digest grounds both refs at once.
    monkeypatch.setattr(inv, "router",
                        lambda i, b, atoms, escalate: {"tool": "read", "args": {"path": "/docs/security.md"}})
    monkeypatch.setattr(inv, "digest",
                        lambda goal, tool, args, observation, escalate: (
                            Note(tool=tool, args=args, lesson="cite it"),
                            {"policy_doc:/docs/security.md": True, "row.record_path": "/payments/p_1.json"}))
    brief = inv.investigate(vm, intent, seed=None, oracle=None, max_steps=6)
    assert brief.env["row.record_path"] == "/payments/p_1.json"
    assert len(brief.notes) == 1            # stopped right after sufficiency met


def test_investigate_respects_budget(monkeypatch):
    # Single ungrounded policy_doc ref — sufficient() stays False until budget exhausted.
    # (record_path refs are PLAN-produced and are skipped by sufficient(); this test uses
    # only a policy_doc so the budget mechanism is not masked by ref-kind skipping.)
    intent = IntentSpec(
        objective="cite fraud payments",
        desired_outcome="OUTCOME_OK",
        outcome_space=["OUTCOME_OK"],
        answer_shape={},
        required_refs={"OUTCOME_OK": [
            RefSpec(kind="policy_doc", path="/docs/security.md"),
        ]},
    )
    # distinct non-empty results per step: no empty-stall, no repeated-signature stall;
    # reads go to /docs/0.md, /docs/1.md, /docs/2.md — NOT /docs/security.md, so
    # _ground_doc_refs never grounds the policy_doc and sufficient() stays False.
    fx = {fixture_key("Read", f"/docs/{i}.md"): {"content": f"data{i}"} for i in range(3)}
    vm = MockVMSpy(fx)
    monkeypatch.setattr(inv, "router",
                        lambda i, b, atoms, escalate: {"tool": "read", "args": {"path": f"/docs/{len(b.notes)}.md"}})
    monkeypatch.setattr(inv, "digest",
                        lambda goal, tool, args, observation, escalate: (Note(tool=tool, args=args), {}))
    brief = inv.investigate(vm, intent, seed=None, oracle=None, max_steps=3)
    assert len(brief.notes) == 3            # stopped at budget


def test_investigate_escalates_on_empty(monkeypatch):
    intent = _intent_with_refs()
    vm = MockVMSpy({})                       # every read returns empty -> stall -> escalate
    calls = []
    monkeypatch.setattr(inv, "router",
                        lambda i, b, atoms, escalate: (calls.append(("router", escalate)) or
                                                       {"tool": "read", "args": {"path": "/docs/x.md"}}))
    monkeypatch.setattr(inv, "digest",
                        lambda goal, tool, args, observation, escalate: (
                            calls.append(("digest", escalate)) or (Note(tool=tool, args=args), {})))
    inv.investigate(vm, intent, seed=None, oracle=None, max_steps=1)
    assert any(c == ("digest", True) for c in calls)   # empty result escalated the digest


def test_investigate_never_raises_on_step_error(monkeypatch):
    intent = _intent_with_refs()
    vm = MockVMSpy({})
    def boom(*a, **k):
        raise RuntimeError("router blew up")
    monkeypatch.setattr(inv, "router", boom)
    brief = inv.investigate(vm, intent, seed=None, oracle=None, max_steps=2)
    assert isinstance(brief, Brief)               # returned gracefully, did not raise
    assert any("step error" in n.lesson for n in brief.notes)


def test_investigate_steps_appear_in_trace(monkeypatch, tmp_path):
    import json
    from agent import trace
    logpath = tmp_path / "t.jsonl"
    logger = trace.TraceLogger(path=logpath, task_id="tT")   # real ctor: (path, task_id)
    trace.set_trace(logger)
    try:
        intent = _intent_with_refs()
        vm = MockVMSpy({fixture_key("Read", "/docs/security.md"): {"content": "cite record_path"}})
        monkeypatch.setattr(inv, "router",
                            lambda i, b, atoms, escalate: {"tool": "read", "args": {"path": "/docs/security.md"}})
        monkeypatch.setattr(inv, "digest",
                            lambda goal, tool, args, observation, escalate: (
                                Note(tool=tool, lesson="x"),
                                {"policy_doc:/docs/security.md": True, "row.record_path": "/p.json"}))
        inv.investigate(vm, intent, seed=None, oracle=None, max_steps=2)
    finally:
        logger.close()
        trace.set_trace(None)
    records = [json.loads(l) for l in logpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    vm_calls = [r for r in records if r.get("type") == "vm_call"]
    assert vm_calls, "investigator VM call not captured in trace"
    assert any(r.get("rpc") == "Read" for r in vm_calls)
    assert any(r.get("step_type") == "INVESTIGATE" for r in vm_calls)   # tagged as the investigate phase


def test_investigate_data_paths_inert_when_flag_off(monkeypatch):
    # data_paths=None (flag off) -> no probe, router decides immediately, no data_paths env
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
    vm = MockVMSpy({})
    monkeypatch.setattr(inv, "router", lambda i, b, atoms, escalate: {"done": True})
    brief = inv.investigate(vm, intent, max_steps=6)
    assert "data_paths" not in brief.env
    assert not any(c[0] == "List" for c in vm.calls)


def test_investigate_emits_stop_trace(tmp_path, monkeypatch):
    import json
    from agent import trace
    logpath = tmp_path / "t.jsonl"
    logger = trace.TraceLogger(path=logpath, task_id="tT")
    trace.set_trace(logger)
    try:
        intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                            outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
        vm = MockVMSpy({fixture_key("List", "/proc/payments"): {"entries": "p_1.json"}})
        monkeypatch.setattr(inv, "router", lambda i, b, atoms, escalate: {"done": True})
        monkeypatch.setattr(inv, "digest",
                            lambda goal, tool, args, observation, escalate: (Note(tool=tool), {}))
        inv.investigate(vm, intent, max_steps=6)
    finally:
        logger.close(); trace.set_trace(None)
    recs = [json.loads(l) for l in logpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    stop = [r for r in recs if r.get("type") == "investigate_stop"]
    assert stop, "no investigate_stop record emitted"
    assert stop[-1]["data_paths_total"] == 0
    assert stop[-1]["data_paths_probed"] == 0
    assert stop[-1]["reason"] == "sufficient"
