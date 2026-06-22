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


import agent.pipeline as pipeline
import agent.investigate as inv
from agent.investigate import Brief, Note


def test_run_pipeline_builds_brief_then_plan(monkeypatch):
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "1")
    intent = IntentSpec(objective="cite fraud payments", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={})
    captured = {}

    monkeypatch.setattr(pipeline, "load_entries", lambda tid: [])
    monkeypatch.setattr("agent.reason.run_intent",
                        lambda facts, instruction, token_out=None, learn_ctx=None: intent)

    def fake_investigate(vm, intent, seed=None, oracle=None, max_steps=None, data_paths=None):
        b = Brief(); b.env["row.record_path"] = "/payments/p_1.json"
        b.notes.append(Note(tool="read", lesson="cite p_1"))
        return b
    monkeypatch.setattr(pipeline, "investigate", fake_investigate)

    def fake_run_plan(intent, facts, learn_ctx, prev_error, token_out=None,
                      oracle_atoms=None, observed=None, brief_block=None):
        captured["brief_block"] = brief_block
        from agent.ir_models import PlanIR
        return PlanIR(decision={"branches": [], "default_label": "ok"},
                      answer={"ok": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}})
    monkeypatch.setattr("agent.reason.run_plan", fake_run_plan)
    monkeypatch.setattr(pipeline, "_ilearn", lambda *a, **k: None)

    vm = MockVMSpy({})
    pipeline.run_pipeline(vm, instruction="cite fraud payments", task_id="tX",
                          agents_md_text="", facts=None)
    assert captured["brief_block"] and "p_1.json" in captured["brief_block"]


def test_run_pipeline_disabled_skips_investigate(monkeypatch):
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")
    called = {"investigate": False}
    monkeypatch.setattr(pipeline, "investigate",
                        lambda *a, **k: called.__setitem__("investigate", True) or Brief())
    monkeypatch.setattr(pipeline, "load_entries", lambda tid: [])
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_NONE_CLARIFICATION",
                        outcome_space=["OUTCOME_OK"], answer_shape={})
    monkeypatch.setattr("agent.reason.run_intent",
                        lambda facts, instruction, token_out=None, learn_ctx=None: intent)
    monkeypatch.setattr("agent.reason.run_plan",
                        lambda *a, **k: (_ for _ in ()).throw(__import__("agent.reason", fromlist=["PlanEmptyError"]).PlanEmptyError("empty")))
    pipeline.run_pipeline(MockVMSpy({}), instruction="x", task_id="tY",
                          agents_md_text="", facts=None)
    assert called["investigate"] is False
