import os
from agent.orchestrator import gather_prephase_facts
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _vm_with_docs_and_schema():
    fx = {
        fixture_key("Exec", "/bin/sql", ["--help"]): {"stdout": "usage"},
        fixture_key("Read", "/docs/security.md"): {"content": "SECRET POLICY BODY"},
    }
    return MockVMSpy(fx)


def test_slim_gather_drops_policy_bodies_and_samples():
    vm = _vm_with_docs_and_schema()
    facts = gather_prephase_facts(vm, "read /docs/security.md", "", task_id="", slim=True)
    assert facts.policies == {}            # no doc BODIES in the seed
    assert facts.sample_rows == ""         # no sample rows
    assert facts.path_listings == {}       # no listings
    assert facts.catalogue_candidates == ""
    # identity + docs_inventory (paths) are still gathered as the navigation map
    assert facts.gather_status.get("identity") != "skipped(slim)"
    # the dropped seed fields are explicitly marked skipped in the status (observability)
    for _k in ("policies", "catalogue_candidates", "target_records", "path_listings"):
        assert facts.gather_status.get(_k) == "skipped(slim)"


import agent.reason as reason
from agent.ir_models import IntentSpec


def test_run_plan_includes_brief_block(monkeypatch):
    seen = {}
    def fake_raw(system, user, model, cfg, **kw):
        seen["user"] = user
        return ('{"discovery": [], "rowsets": [], "compute": [], '
                '"decision": {"branches": [], "default_label": "ok"}, "ops": [], '
                '"answer": {"ok": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}}, '
                '"custom_extract": []}')
    monkeypatch.setattr(reason, "_call_llm_raw", fake_raw)
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={})
    reason.run_plan(intent, facts=None, learn_ctx=[], prev_error=None,
                    oracle_atoms=[], observed=None,
                    brief_block="INVESTIGATION_BRIEF:\n## RESOLVED_ENV\n- incident_id: INC-7")
    assert "INVESTIGATION_BRIEF" in seen["user"]
    assert "INC-7" in seen["user"]
