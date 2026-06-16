from agent.models import LearnConsolidateOutput, AnswerOutput


def test_learn_consolidate_output_minimal():
    lc = LearnConsolidateOutput(
        rule_content="Never hardcode SKUs from task_text",
        reasoning="prior cycle hardcoded value",
        deactivate_ids=[],
        skip=False,
    )
    assert lc.skip is False
    assert lc.agents_md_anchor is None
    assert lc.deactivate_reason is None


def test_learn_consolidate_skip_path():
    lc = LearnConsolidateOutput(
        rule_content="",
        reasoning="duplicate of r001",
        deactivate_ids=[],
        skip=True,
        skip_reason="r001",
    )
    assert lc.skip is True
    assert lc.skip_reason == "r001"


def test_answer_output_basic():
    a = AnswerOutput(message="3 baskets", outcome="OUTCOME_OK", grounding_refs=["/proc/baskets/b1.json"])
    assert a.outcome == "OUTCOME_OK"


def test_deleted_models_no_longer_importable():
    import agent.models as m
    for name in (
        # legacy DESIGN/CODEGEN/TEST pipeline models (unified-pipeline cleanup)
        "DesignOutput", "CodegenOutput", "TestSpec", "ToolOp",
        "AgentsMdRef", "AnswerTemplate",
        # earlier-removed staged-pipeline models
        "IddOutput", "SddOutput", "PlanOutput", "ExecuteOutput",
        "ConsolidateOutput", "ConsolidationItem", "ResolveCandidate",
        "ResolveOutput", "LearnOutput", "TestOutput",
    ):
        assert not hasattr(m, name), f"{name} must be deleted"
