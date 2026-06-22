from agent.grounding import extract_entity_tokens


def test_extracts_sku_dash_id_token():
    toks = extract_entity_tokens("Does STO-2R84BSHQ exist in the catalog?", "")
    assert "STO-2R84BSHQ" in toks


def test_extracts_short_sku_token():
    toks = extract_entity_tokens("check SKU-FK availability", "")
    assert "SKU-FK" in toks


def test_extracts_prefixed_entity_id():
    toks = extract_entity_tokens("refund basket_12 for cust_016", "")
    assert "basket_12" in toks
    assert "cust_016" in toks


def test_scans_both_task_text_and_message():
    toks = extract_entity_tokens("task mentions STO-2R84BSHQ", "answer cites SKU-FK")
    assert "STO-2R84BSHQ" in toks and "SKU-FK" in toks


def test_dedupes_and_preserves_order():
    toks = extract_entity_tokens("SKU-FK then SKU-FK again", "SKU-FK")
    assert toks.count("SKU-FK") == 1


def test_does_not_extract_non_allowlisted_prefix_words():
    # 'record_path' / 'product_sku' are schema words, not entity ids — must NOT match.
    toks = extract_entity_tokens("select record_path, product_sku from product_variants", "")
    assert toks == []


def test_allowlisted_prefix_sql_columns_are_extracted_known_limitation():
    # Allowlisted-prefix SQL columns DO match (e.g. 'order_id'); this is acceptable because
    # downstream stat-validation drops any token that does not resolve to a real /proc path.
    toks = extract_entity_tokens("SELECT order_id FROM orders WHERE return_reason IS NULL", "")
    assert "order_id" in toks and "return_reason" in toks
from agent.grounding import resolve_record_path, _proc_paths_in
from agent.mock_vm_spy import MockVMSpy, fixture_key
from agent.interpreter import InterpretResult, CapturedAnswer


def _result(env=None, sql_results=None, message=""):
    return InterpretResult(
        captured=CapturedAnswer(message=message, outcome="OUTCOME_OK", refs=[]),
        env=env or {}, observations=[], sql_results=sql_results or [],
        mutation_landed=False, label="ok")


def test_resolve_via_find_then_stat():
    path = "/proc/catalog/STO-2R84BSHQ.json"
    vm = MockVMSpy(fixtures={
        fixture_key("Find", "/proc"): {"paths": [path]},
        fixture_key("Stat", path): {"path": path},
    })
    assert resolve_record_path(vm, "STO-2R84BSHQ", evidence_paths=[]) == path


def test_resolve_drops_token_with_no_stat_match():
    # find returns nothing, no evidence -> token does not resolve to a real path.
    vm = MockVMSpy(fixtures={})
    assert resolve_record_path(vm, "STO-NOPE", evidence_paths=[]) is None


def test_resolve_evidence_fastpath_when_stat_ok():
    path = "/proc/catalog/SKU-FK.json"
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})
    # path already present in evidence (SQL returned it) -> no find needed.
    assert resolve_record_path(vm, "SKU-FK", evidence_paths=[path]) == path


def test_resolve_evidence_path_dropped_when_stat_fails():
    path = "/proc/catalog/SKU-STALE.json"
    vm = MockVMSpy(fixtures={})   # no Stat fixture -> stub has no "path" -> not ok
    assert resolve_record_path(vm, "SKU-STALE", evidence_paths=[path]) is None


def test_proc_paths_scans_sql_results_and_env_and_message():
    res = _result(
        env={"rows": [{"record_path": "/proc/catalog/SKU-A.json"}]},
        sql_results=["product_sku,record_path\nSKU-B,/proc/catalog/SKU-B.json"],
        message="see /proc/catalog/SKU-C.json")
    found = _proc_paths_in(res, res.captured)
    assert set(found) == {
        "/proc/catalog/SKU-A.json",
        "/proc/catalog/SKU-B.json",
        "/proc/catalog/SKU-C.json",
    }


def test_resolve_via_sql_fallback_when_find_empty():
    # evidence + find both empty -> generic SQL fallback selects record_path from a
    # schema table by LIKE-token, then stat-validates.
    path = "/proc/catalog/STO-2R84BSHQ.json"
    sql = "SELECT record_path FROM catalog WHERE record_path LIKE '%STO-2R84BSHQ%' LIMIT 5"
    vm = MockVMSpy(fixtures={
        fixture_key("Exec", "/bin/sql", [sql]): {"stdout": f"record_path\n{path}"},
        fixture_key("Stat", path): {"path": path},
    })
    assert resolve_record_path(vm, "STO-2R84BSHQ", evidence_paths=[],
                               schema_tables=["catalog"]) == path


def test_resolve_sql_fallback_skips_unsafe_token():
    # a token with a space is not SQL-safe -> fallback is skipped (no injection), None.
    vm = MockVMSpy(fixtures={})
    assert resolve_record_path(vm, "bad token", evidence_paths=[],
                               schema_tables=["catalog"]) is None
import json as _json
from agent.grounding import ownership_safe
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _vm_with_record(path, record):
    return MockVMSpy(fixtures={fixture_key("Read", path): {"content": _json.dumps(record)}})


def test_public_record_is_safe_for_customer():
    path = "/proc/catalog/SKU-FK.json"
    vm = _vm_with_record(path, {"sku": "SKU-FK"})   # no customer_id -> public
    assert ownership_safe(vm, path, {"customer_id": "cust_016"}) is True


def test_owned_record_is_safe():
    path = "/proc/baskets/basket_12.json"
    vm = _vm_with_record(path, {"customer_id": "cust_016"})
    assert ownership_safe(vm, path, {"customer_id": "cust_016"}) is True


def test_cross_customer_record_is_unsafe():
    path = "/proc/baskets/basket_99.json"
    vm = _vm_with_record(path, {"customer_id": "cust_777"})
    assert ownership_safe(vm, path, {"customer_id": "cust_016"}) is False


def test_non_customer_caller_never_blocked():
    # employee/admin identity (no customer_id) -> no cross-customer leak possible.
    path = "/proc/baskets/basket_99.json"
    vm = _vm_with_record(path, {"customer_id": "cust_777"})
    assert ownership_safe(vm, path, {"user": "emp_3"}) is True


def test_unreadable_record_dropped_for_customer():
    # customer caller, record cannot be read -> err toward dropping (conservative).
    vm = MockVMSpy(fixtures={})   # Read stub -> empty content -> unparseable
    assert ownership_safe(vm, "/proc/baskets/basket_x.json", {"customer_id": "cust_016"}) is False

from agent.grounding import canonical_doc_refs
from agent.mock_vm_spy import MockVMSpy, fixture_key


def test_keeps_existing_doc_path_as_is():
    path = "/docs/payments/3ds.md"
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})
    assert canonical_doc_refs([path], vm) == [path]


def test_case_corrects_via_find_basename():
    real = "/docs/Checkout.md"
    asked = "/docs/checkout.md"
    vm = MockVMSpy(fixtures={
        # asked path does not stat; find by basename returns the real-cased path.
        fixture_key("Find", "/docs"): {"paths": [real]},
    })
    assert canonical_doc_refs([asked], vm) == [real]


def test_drops_unresolvable_doc():
    vm = MockVMSpy(fixtures={})   # neither stat nor find resolves
    assert canonical_doc_refs(["/docs/ghost.md"], vm) == []


def test_dedupes_doc_refs():
    path = "/docs/security.md"
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})
    assert canonical_doc_refs([path, path], vm) == [path]


class _Ans:
    def __init__(self, message):
        self.message = message


def test_relies_on_filter_keeps_only_signalled_doc():
    a, b = "/docs/checkout.md", "/docs/returns.md"
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", a): {"path": a},
        fixture_key("Stat", b): {"path": b},
    })
    # 'checkout' stem appears in the message -> only that doc is relied on.
    out = canonical_doc_refs([a, b], vm, intent=None, answer=_Ans("the checkout policy blocks this"))
    assert out == [a]


def test_relies_on_keeps_all_when_no_signal():
    a, b = "/docs/checkout.md", "/docs/returns.md"
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", a): {"path": a},
        fixture_key("Stat", b): {"path": b},
    })
    # no doc stem in the message and no declared policy_doc -> recall-preserving: keep all.
    out = canonical_doc_refs([a, b], vm, intent=None, answer=_Ans("request cannot proceed"))
    assert out == [a, b]


def test_relies_on_policy_doc_signal_from_intent():
    from agent.ir_models import IntentSpec
    a, b = "/docs/checkout.md", "/docs/returns.md"
    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_NONE_UNSUPPORTED",
                        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
                        constraints=[], success_criteria={}, answer_shape={},
                        required_refs={"OUTCOME_NONE_UNSUPPORTED": [
                            {"kind": "policy_doc", "path": a}]})
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", a): {"path": a},
        fixture_key("Stat", b): {"path": b},
    })
    out = canonical_doc_refs([a, b], vm, intent=intent, answer=_Ans("denied"))
    assert out == [a]
