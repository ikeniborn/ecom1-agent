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
