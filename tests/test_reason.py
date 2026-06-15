# tests/test_reason.py
import json
from unittest.mock import patch
import pytest

from agent.reason import run_intent, run_plan, IntentError, PlanError, _facts_block
from agent.ir_models import IntentSpec

_FACTS = {"schema": "CREATE TABLE x(...)", "agents_md": "RULES", "policies": {}, "identity": {}}

_INTENT_JSON = json.dumps({
    "objective": "count", "desired_outcome": "int", "params": {"k": "v"},
    "outcome_space": ["OUTCOME_OK"], "constraints": [], "success_criteria": [],
    "answer_shape": {},
})
_PLAN_JSON = json.dumps({
    "discovery": [], "rowsets": [], "compute": [],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})


def test_run_intent_parses():
    with patch("agent.pipeline.call_llm_raw", return_value=_INTENT_JSON):
        spec = run_intent(_FACTS, "count things")
    assert isinstance(spec, IntentSpec) and spec.objective == "count"


def test_run_intent_empty_raises():
    with patch("agent.pipeline.call_llm_raw", return_value=""):
        with pytest.raises(IntentError):
            run_intent(_FACTS, "count things")


def test_run_plan_parses():
    spec = IntentSpec(**json.loads(_INTENT_JSON))
    with patch("agent.pipeline.call_llm_raw", return_value=_PLAN_JSON):
        plan = run_plan(spec, _FACTS, [], None)
    assert plan.decision.default_label == "ok"


def test_run_plan_bad_json_raises():
    spec = IntentSpec(**json.loads(_INTENT_JSON))
    with patch("agent.pipeline.call_llm_raw", return_value="not json"):
        with pytest.raises(PlanError):
            run_plan(spec, _FACTS, [], None)


def test_facts_block_surfaces_gather_status():
    facts = {
        "schema": "CREATE TABLE x(...)",
        "docs_inventory": "/docs/a.md",
        "gather_status": {"docs_inventory": "ok", "policies": "empty"},
    }
    block = _facts_block(facts)
    assert "gather_status" in block
    assert "policies" in block and "empty" in block
