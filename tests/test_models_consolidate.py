from agent.models import ConsolidationItem, ConsolidateOutput


def test_consolidate_output_default_is_skip():
    out = ConsolidateOutput()
    assert out.skip is True
    assert out.consolidations == []
    assert out.skip_reason is None


def test_consolidation_item_fields():
    item = ConsolidationItem(
        deactivate=["r002", "r003"],
        merged_rule="use /bin/ls for directory listing",
        merged_reasoning="r002 and r003 are duplicates",
    )
    assert item.deactivate == ["r002", "r003"]
    assert "r002" in item.merged_reasoning


def test_consolidate_output_with_consolidations():
    out = ConsolidateOutput(
        skip=False,
        skip_reason=None,
        consolidations=[
            ConsolidationItem(
                deactivate=["r002", "r003"],
                merged_rule="merged rule content",
                merged_reasoning="r002 and r003 overlap",
            )
        ],
    )
    assert out.skip is False
    assert len(out.consolidations) == 1
    assert out.consolidations[0].deactivate == ["r002", "r003"]
