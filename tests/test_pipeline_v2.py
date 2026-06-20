from agent.pipeline import _is_retryable_vm_error


def test_is_retryable_vm_error_covers_ecom_not_found():
    """The ECOM runtime phrases a missing file/record as 'read failed: not found'.
    On a read-only plan that must be retryable so the loop LEARNs + retries rather
    than dead-ending at clarification (regression: t02 broke at cycle 5/10).
    """
    # ECOM phrasing — the regression case.
    assert _is_retryable_vm_error("read failed: not found") is True
    # POSIX-style phrasings the gate already intended to cover.
    assert _is_retryable_vm_error("[INVALID_ARGUMENT] no such file or directory") is True
    assert _is_retryable_vm_error("path does not exist") is True
    assert _is_retryable_vm_error("/docs is a directory") is True
    # Network transients stay retryable.
    assert _is_retryable_vm_error("The read operation timed out") is True
    # Non-deterministic / genuinely fatal errors stay non-retryable.
    assert _is_retryable_vm_error("permission denied") is False
    assert _is_retryable_vm_error("internal server error") is False


def test_log_gate_auto_emits_gate(tmp_path):
    import json
    from agent import trace
    from agent.trace import TraceLogger

    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    trace.set_cycle(2)
    try:
        trace.log_gate_auto("LINT", True, "")
        trace.log_gate_auto("VERIFY", False, "I1: unresolved refs")
    finally:
        trace.set_trace(None)
        t.close()
    gates = [json.loads(l) for l in p.read_text().splitlines()
             if l.strip() and json.loads(l)["type"] == "gate"]
    kinds = {(g["step_type"], g["passed"]) for g in gates}
    assert ("LINT", True) in kinds and ("VERIFY", False) in kinds


def test_run_pipeline_emits_full_v2_trace(tmp_path, monkeypatch):
    """Full run_pipeline over MockVMSpy yields a complete v2 trace: real INTENT + PLAN
    llm_call records (named phases, never 'llm'), LINT/INTERPRET/VERIFY gates, vm_call
    under INTERPRET (MockVMSpy), ANSWER, seq gap-free. The LLM is stubbed at the
    funnel's single-model seam so the REAL run_intent/run_plan run and emit real
    llm_call records (with step_type) — only the network call is faked."""
    import json

    from agent import trace
    from agent.trace import TraceLogger
    import agent.llm as llm
    from agent.mock_vm_spy import MockVMSpy, fixture_key
    import agent.pipeline as pipeline

    _INTENT_JSON = json.dumps({
        "objective": "count rows", "desired_outcome": "OUTCOME_OK",
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "params": {}, "constraints": [], "success_criteria": {},
        "answer_shape": {"msg_skeleton": ""}, "required_refs": {},
    })
    _PLAN_JSON = json.dumps({
        "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT 1 AS n"}, "bind": "r"}],
        "rowsets": [], "compute": [],
        "decision": {"branches": [], "default_label": "d"}, "ops": [],
        "answer": {"d": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}},
        "custom_extract": [],
    })

    def fake_single(system, user_msg, model, cfg, **kw):
        text = system if isinstance(system, str) else "".join(
            b.get("text", "") for b in system if isinstance(b, dict))
        return _PLAN_JSON if "PHASE: PLAN" in text else _INTENT_JSON

    monkeypatch.setenv("ECOM_MODEL", "stub-model")
    monkeypatch.setenv("ECOM_ORACLE_ENABLED", "0")
    monkeypatch.setattr(llm, "_call_raw_single_model", fake_single)

    fixtures = {fixture_key("Exec", "/bin/sql", ["SELECT 1 AS n"]): {"stdout": "n\n1\n"}}
    vm = MockVMSpy(fixtures)

    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    try:
        pipeline.run_pipeline(vm, instruction="count rows", task_id="t01",
                              agents_md_text="", facts=None)
    finally:
        trace.set_trace(None)
        t.close()

    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    step_types = {r.get("step_type") for r in recs if "step_type" in r}
    assert {"INTENT", "PLAN", "INTERPRET", "VERIFY", "ANSWER"} <= step_types
    # vm_call logged by MockVMSpy under INTERPRET
    assert any(r["type"] == "vm_call" and r["step_type"] == "INTERPRET" for r in recs)
    # gate records present (LINT + VERIFY); NO 'PLAN' gate (PLAN is an LLM phase)
    gates = [r for r in recs if r["type"] == "gate"]
    gate_types = {g["step_type"] for g in gates}
    assert "LINT" in gate_types and "VERIFY" in gate_types
    assert "PLAN" not in gate_types
    # every llm_call phase is named (never the literal 'llm')
    assert all(r.get("phase") != "llm" for r in recs if r["type"] == "llm_call")
    # at least the INTENT + PLAN llm_calls exist with their step_types
    llm_phases = {r["step_type"] for r in recs if r["type"] == "llm_call"}
    assert {"INTENT", "PLAN"} <= llm_phases
    # seq strictly monotonic and gap-free
    seqs = [r["seq"] for r in recs]
    assert seqs == list(range(len(seqs)))
