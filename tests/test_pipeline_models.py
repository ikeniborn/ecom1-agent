# tests/test_pipeline_models.py
from pydantic import ValidationError
import pytest
from agent.models import (
    SddOutput, PlanStep, LearnOutput, AnswerOutput,
    ResolveCandidate, ResolveOutput,
)


def test_sql_plan_output_valid():
    obj = SddOutput(
        reasoning="products table has type column",
        spec="return count of Lawn Mowers",
        plan=[PlanStep(type="sql", description="count", query="SELECT COUNT(*) FROM products WHERE type='Lawn Mower'")],
    )
    assert obj.reasoning == "products table has type column"
    assert len(obj.plan) == 1


def test_sql_plan_output_requires_reasoning():
    with pytest.raises(ValidationError):
        SddOutput(spec="s", plan=[])


def test_sql_plan_output_requires_queries():
    with pytest.raises(ValidationError):
        SddOutput(reasoning="ok")


def test_learn_output_valid():
    obj = LearnOutput(
        reasoning="column name mismatch",
        conclusion="Use 'model' not 'series' for product line",
        rule_content="Never filter on 'series' column for product line names — use 'model'.",
    )
    assert obj.conclusion.startswith("Use")


def test_answer_output_valid():
    obj = AnswerOutput(
        reasoning="SQL returned 3 rows",
        message="<YES> Product found",
        outcome="OUTCOME_OK",
        grounding_refs=["/proc/catalog/ABC-123.json"],
        completed_steps=["ran SQL", "found product"],
    )
    assert obj.outcome == "OUTCOME_OK"


def test_answer_output_invalid_outcome():
    with pytest.raises(ValidationError):
        AnswerOutput(
            reasoning="x",
            message="x",
            outcome="OUTCOME_UNKNOWN",
            grounding_refs=[],
            completed_steps=[],
        )


def test_sql_plan_output_agents_md_refs_defaults_empty():
    obj = SddOutput(reasoning="r", spec="s", plan=[])
    assert obj.agents_md_refs == []


def test_sql_plan_output_agents_md_refs_set():
    obj = SddOutput(reasoning="r", spec="s", plan=[], agents_md_refs=["brand_aliases"])
    assert obj.agents_md_refs == ["brand_aliases"]


def test_learn_output_agents_md_anchor_defaults_none():
    obj = LearnOutput(reasoning="r", conclusion="c", rule_content="Always use X")
    assert obj.agents_md_anchor is None


def test_learn_output_agents_md_anchor_set():
    obj = LearnOutput(reasoning="r", conclusion="c", rule_content="r", agents_md_anchor="brand_aliases > Heco")
    assert obj.agents_md_anchor == "brand_aliases > Heco"


def test_resolve_candidate_minimal():
    c = ResolveCandidate(
        term="Heco",
        field="brand",
        discovery_query="SELECT DISTINCT brand FROM products WHERE brand ILIKE '%Heco%' LIMIT 10",
    )
    assert c.confirmed_value is None


def test_resolve_candidate_with_value():
    c = ResolveCandidate(
        term="heco", field="brand",
        discovery_query="SELECT DISTINCT brand FROM products WHERE brand ILIKE '%heco%' LIMIT 10",
        confirmed_value="Heco",
    )
    assert c.confirmed_value == "Heco"


def test_resolve_output_validate():
    obj = ResolveOutput(
        reasoning="found brand",
        candidates=[
            ResolveCandidate(
                term="heco", field="brand",
                discovery_query="SELECT DISTINCT brand FROM products WHERE brand ILIKE '%heco%' LIMIT 10",
            )
        ],
    )
    assert len(obj.candidates) == 1


def test_learn_output_new_fields_defaults():
    obj = LearnOutput(
        reasoning="diagnosis",
        conclusion="summary",
        rule_content="Always use sku",
    )
    assert obj.deactivate == []
    assert obj.deactivate_reason is None
    assert obj.skip is False
    assert obj.skip_reason is None


def test_learn_output_skip_flag():
    obj = LearnOutput(
        reasoning="already covered",
        conclusion="rule exists",
        rule_content="",
        skip=True,
        skip_reason="Duplicate of r002",
    )
    assert obj.skip is True
    assert obj.skip_reason == "Duplicate of r002"


def test_learn_output_deactivate_list():
    obj = LearnOutput(
        reasoning="new rule supersedes old",
        conclusion="updated",
        rule_content="Use LIKE not equality",
        deactivate=["r001", "r003"],
        deactivate_reason="Superseded by more specific rule",
    )
    assert obj.deactivate == ["r001", "r003"]
    assert obj.deactivate_reason == "Superseded by more specific rule"


def test_learn_output_no_compacted_ctx():
    import pydantic
    with pytest.raises((pydantic.ValidationError, TypeError)):
        LearnOutput(
            reasoning="r", conclusion="c", rule_content="x",
            compacted_ctx=["rule 1"],
        )
