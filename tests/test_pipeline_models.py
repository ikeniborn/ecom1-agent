from pydantic import ValidationError
import pytest
from agent.models import (
    SddOutput, PlanOutput, ExecuteOutput,
    LearnOutput, AnswerOutput,
    ResolveCandidate, ResolveOutput,
    IddOutput,
)


# ── SddOutput ────────────────────────────────────────────────────────────────

def test_sdd_output_valid():
    obj = SddOutput(
        spec_goal="Count Lawn Mowers",
        success_criteria=["result contains count > 0"],
        plan=["query products by type"],
        actions=["SELECT COUNT(*) FROM products WHERE type='Lawn Mower'"],
    )
    assert obj.spec_goal == "Count Lawn Mowers"
    assert len(obj.actions) == 1
    assert obj.error_code == ""


def test_sdd_output_error_code_default():
    obj = SddOutput(
        spec_goal="g", success_criteria=[], plan=[], actions=[]
    )
    assert obj.error_code == ""


def test_sdd_output_error_code_set():
    obj = SddOutput(
        spec_goal="", success_criteria=[], plan=[], actions=[],
        error_code="DENIED_SECURITY",
    )
    assert obj.error_code == "DENIED_SECURITY"


def test_sdd_output_missing_spec_goal_fails():
    with pytest.raises(ValidationError):
        SddOutput(success_criteria=[], plan=[], actions=[])


# ── PlanOutput ───────────────────────────────────────────────────────────────

def test_plan_output_valid():
    obj = PlanOutput(
        approach="single SQL query",
        steps=["count rows matching type filter"],
        action="SELECT COUNT(*) FROM products WHERE type='Lawn Mower'",
    )
    assert obj.action.startswith("SELECT")
    assert len(obj.steps) == 1


def test_plan_output_missing_action_fails():
    with pytest.raises(ValidationError):
        PlanOutput(approach="a", steps=[])


# ── ExecuteOutput ────────────────────────────────────────────────────────────

def test_execute_output_valid():
    obj = ExecuteOutput(
        results=[{"output": "[{\"count\": 3}]"}],
        action="SELECT COUNT(*) FROM products WHERE type='Lawn Mower'",
    )
    assert len(obj.results) == 1
    assert obj.action.startswith("SELECT")


def test_execute_output_empty_results():
    obj = ExecuteOutput(results=[], action="SELECT 1")
    assert obj.results == []


# ── LearnOutput (unchanged) ──────────────────────────────────────────────────

def test_learn_output_valid():
    obj = LearnOutput(
        reasoning="column name mismatch",
        conclusion="Use 'model' not 'series'",
        rule_content="Never filter on 'series' — use 'model'.",
    )
    assert obj.deactivate == []
    assert obj.skip is False


def test_learn_output_no_extra_fields():
    import pydantic
    with pytest.raises((pydantic.ValidationError, TypeError)):
        LearnOutput(reasoning="r", conclusion="c", rule_content="x", compacted_ctx=[])


# ── AnswerOutput (unchanged) ─────────────────────────────────────────────────

def test_answer_output_valid():
    obj = AnswerOutput(
        reasoning="SQL returned 3 rows",
        message="<YES> Product found",
        outcome="OUTCOME_OK",
        grounding_refs=["/proc/catalog/ABC-123.json"],
        completed_steps=["ran SQL"],
    )
    assert obj.outcome == "OUTCOME_OK"


def test_answer_output_invalid_outcome():
    with pytest.raises(ValidationError):
        AnswerOutput(
            reasoning="x", message="x", outcome="OUTCOME_UNKNOWN",
            grounding_refs=[], completed_steps=[],
        )


# ── Resolve (unchanged) ──────────────────────────────────────────────────────

def test_resolve_candidate_minimal():
    c = ResolveCandidate(
        term="Heco", field="brand",
        discovery_query="SELECT DISTINCT brand FROM products WHERE brand ILIKE '%Heco%' LIMIT 10",
    )
    assert c.confirmed_value is None


def test_idd_output_proceed():
    data = {
        "intent_objective": "Find payment status",
        "reformulated_task": "Return the status of payment pay_001",
        "intent_type": "read",
        "extracted_params": {"payment_id": "pay_001"},
        "success_criteria": ["result contains pay_001 status"],
        "stop_rules": [],
        "health_metrics": [],
        "decision": "proceed",
        "stop_code": "",
        "stop_message": "",
        "stop_refs": [],
        "reasoning": "",
    }
    out = IddOutput.model_validate(data)
    assert out.decision == "proceed"
    assert out.intent_type == "read"
    assert out.extracted_params == {"payment_id": "pay_001"}


def test_idd_output_hard_stop():
    data = {
        "intent_objective": "",
        "reformulated_task": "",
        "intent_type": "read",
        "extracted_params": {},
        "success_criteria": [],
        "stop_rules": [],
        "health_metrics": [],
        "decision": "hard_stop",
        "stop_code": "OUTCOME_DENIED_SECURITY",
        "stop_message": "Social engineering detected.",
        "stop_refs": ["/docs/security.md"],
        "reasoning": "task matched social engineering pattern",
    }
    out = IddOutput.model_validate(data)
    assert out.decision == "hard_stop"
    assert out.stop_code == "OUTCOME_DENIED_SECURITY"
    assert "/docs/security.md" in out.stop_refs


def test_idd_output_defaults():
    """Minimal proceed payload — optional fields default correctly."""
    data = {
        "intent_objective": "Fetch order",
        "reformulated_task": "Return order details for order_007",
        "success_criteria": ["response includes order status"],
        "decision": "proceed",
    }
    out = IddOutput.model_validate(data)
    assert out.intent_type == "read"
    assert out.extracted_params == {}
    assert out.stop_rules == []
    assert out.health_metrics == []
    assert out.stop_code == ""
