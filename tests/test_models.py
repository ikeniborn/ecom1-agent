from agent.models import LearnOutput
import pytest


def test_learn_output_minimal():
    out = LearnOutput(
        reasoning="r", conclusion="c", rule_content="use sku not id"
    )
    assert out.rule_content == "use sku not id"
    assert out.agents_md_anchor is None
    assert out.skip is False


def test_learn_output_with_skip():
    out = LearnOutput(
        reasoning="r", conclusion="c", rule_content="",
        skip=True, skip_reason="no new info",
    )
    assert out.skip is True
    assert out.skip_reason == "no new info"


def test_learn_output_with_deactivate():
    out = LearnOutput(
        reasoning="r", conclusion="c", rule_content="new rule",
        deactivate=["old-rule-1"], deactivate_reason="superseded",
    )
    assert out.deactivate == ["old-rule-1"]
    assert out.deactivate_reason == "superseded"
