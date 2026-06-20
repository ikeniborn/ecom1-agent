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
    """A full run_pipeline over MockVMSpy yields a v2 trace exercising INTENT, PLAN,
    LINT, INTERPRET, VERIFY gates, vm_call (logged by MockVMSpy), and ANSWER — every
    llm_call phase named (no 'llm')."""
    import json

    from agent import trace
    from agent.trace import TraceLogger
    import agent.reason as reason
    from agent.ir_models import (AnswerShape, AnswerTemplateIR, DecisionTree,
                                 IntentSpec, PlanIR, Step)
    from agent.mock_vm_spy import MockVMSpy, fixture_key
    import agent.pipeline as pipeline

    intent = IntentSpec(objective="count", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
                        answer_shape=AnswerShape(), success_criteria={}, required_refs={})
    plan = PlanIR(
        discovery=[Step(rpc="Exec", args={"path": "/bin/sql", "stdin": "SELECT 1 AS n"},
                        bind="r")],
        decision=DecisionTree(branches=[], default_label="d"),
        answer={"d": AnswerTemplateIR(message="done", outcome="OUTCOME_OK", refs=[])},
    )
    monkeypatch.setattr(reason, "run_intent", lambda *a, **k: intent)
    monkeypatch.setattr(reason, "run_plan", lambda *a, **k: plan)

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
    assert {"PLAN", "INTERPRET", "VERIFY", "ANSWER"} <= step_types
    # vm_call logged by MockVMSpy under INTERPRET
    assert any(r["type"] == "vm_call" and r["step_type"] == "INTERPRET" for r in recs)
    # gate records present with reasons
    gates = [r for r in recs if r["type"] == "gate"]
    assert any(g["step_type"] == "LINT" for g in gates)
    assert any(g["step_type"] == "VERIFY" for g in gates)
    # no llm_call left at the literal 'llm' phase
    assert all(r.get("phase") != "llm" for r in recs if r["type"] == "llm_call")
    # seq strictly monotonic and gap-free
    seqs = [r["seq"] for r in recs]
    assert seqs == list(range(len(seqs)))
