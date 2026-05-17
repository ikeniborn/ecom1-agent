from agent.models import LearnOutput
import pytest


def test_learn_output_compacted_ctx_optional():
    out = LearnOutput(
        reasoning="r", conclusion="c", rule_content="use sku not id"
    )
    assert out.compacted_ctx is None


def test_learn_output_compacted_ctx_populated():
    out = LearnOutput(
        reasoning="r", conclusion="c", rule_content="use sku not id",
        compacted_ctx=["use sku not id", "always GROUP BY when aggregating"]
    )
    assert out.compacted_ctx == ["use sku not id", "always GROUP BY when aggregating"]


def test_learn_output_compacted_ctx_empty_list():
    out = LearnOutput(
        reasoning="r", conclusion="c", rule_content="use sku not id",
        compacted_ctx=[]
    )
    assert out.compacted_ctx == []
