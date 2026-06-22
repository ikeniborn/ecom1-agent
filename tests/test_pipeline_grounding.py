"""Phase 1 integration: ground_refs + hardened verify compose so a missing required
reference is re-derived from the VM before the answer is accepted."""
from agent.grounding import ground_refs
from agent.verify import verify
from agent.ir_models import IntentSpec
from agent.interpreter import InterpretResult, CapturedAnswer
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _intent(required_refs=None, outcome_space=None):
    return IntentSpec(
        objective="o", desired_outcome="OUTCOME_OK",
        outcome_space=outcome_space or ["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
        constraints=[], success_criteria={}, answer_shape={},
        required_refs=required_refs or {})


def _result(captured, env=None, sql_results=None):
    return InterpretResult(captured=captured, env=env or {}, observations=[],
                           sql_results=sql_results or [], mutation_landed=False, label="ok")


def test_record_ref_grounded_from_evidence_then_verify_passes():
    path = "/proc/catalog/STO-2R84BSHQ.json"
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$missing"}]})  # source never binds
    cap = CapturedAnswer(message="STO-2R84BSHQ exists", outcome="OUTCOME_OK", refs=[])
    res = _result(cap, sql_results=[f"sku,record_path\nSTO-2R84BSHQ,{path}"])
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})

    res.captured.refs = ground_refs(intent, res.captured, res, vm,
                                    task_text="does STO-2R84BSHQ exist?", docs_read=[])
    assert path in res.captured.refs
    ok, err = verify(res, intent)
    assert ok, err


def test_doc_ref_grounded_from_docs_read_satisfies_non_ok_requirement():
    doc = "/docs/checkout.md"
    intent = _intent(required_refs={"OUTCOME_NONE_UNSUPPORTED": [
        {"kind": "policy_doc", "path": doc}]})
    cap = CapturedAnswer(message="cannot proceed", outcome="OUTCOME_NONE_UNSUPPORTED",
                         refs=[])
    res = _result(cap)
    vm = MockVMSpy(fixtures={fixture_key("Stat", doc): {"path": doc}})

    # before grounding: verify fails (required doc absent on a non-OK outcome)
    ok_before, _ = verify(res, intent)
    assert not ok_before

    res.captured.refs = ground_refs(intent, res.captured, res, vm,
                                    task_text="checkout", docs_read=[doc])
    assert doc in res.captured.refs
    ok_after, err = verify(res, intent)
    assert ok_after, err


def test_cross_customer_record_not_auto_cited():
    import json
    path = "/proc/baskets/basket_99.json"
    intent = _intent()
    cap = CapturedAnswer(message="basket_99 belongs to someone else",
                         outcome="OUTCOME_OK", refs=[])

    class _Facts:
        identity = {"customer_id": "cust_016"}

    res = _result(cap, env={"_facts": _Facts()})
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", path): {"path": path},
        fixture_key("Read", path): {"content": json.dumps({"customer_id": "cust_777"})},
    })
    out = ground_refs(intent, res.captured, res, vm,
                      task_text="show basket_99", docs_read=[])
    assert path not in out
