import pytest
from agent.models import (
    DesignOutput, ToolOp, AgentsMdRef, AnswerTemplate,
    CodegenOutput, LearnConsolidateOutput, AnswerOutput,
)


def _design_kwargs(**over):
    base = dict(
        intent="count baskets by store",
        params={"store_id": "$agent_store_id"},
        success_criteria=["rows non-empty", "cnt >= 0"],
        discovery=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": [".schema baskets"]}, bind="schema")],
        ops=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, bind="rows")],
        agents_md_constraints=[AgentsMdRef(anchor="#baskets > store_scope", rule="filter store_id=$agent_store_id")],
        answer_template=AnswerTemplate(message="{rows[0].cnt} baskets", outcome="OUTCOME_OK", refs=[]),
        outcome_override=None,
    )
    base.update(over)
    return base


def test_design_output_full_shape():
    d = DesignOutput(**_design_kwargs())
    assert d.intent == "count baskets by store"
    assert d.success_criteria == ["rows non-empty", "cnt >= 0"]
    assert d.ops[0].bind == "rows"
    assert d.agents_md_constraints[0].anchor == "#baskets > store_scope"
    assert d.outcome_override is None


def test_design_output_success_criteria_required():
    """F-002: success_criteria is a required field per H10."""
    kw = _design_kwargs()
    del kw["success_criteria"]
    with pytest.raises(Exception):
        DesignOutput(**kw)


def test_design_output_outcome_override_allowed():
    d = DesignOutput(**_design_kwargs(outcome_override="OUTCOME_DENIED_SECURITY"))
    assert d.outcome_override == "OUTCOME_DENIED_SECURITY"


def test_tool_op_bind_optional():
    op = ToolOp(rpc="Read", args={"path": "/AGENTS.MD"})
    assert op.bind is None


def test_codegen_output_minimal():
    cg = CodegenOutput(script_code="def run(vm, params): pass\n")
    assert "def run" in cg.script_code


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
    for name in ("IddOutput", "SddOutput", "PlanOutput", "ExecuteOutput",
                 "ConsolidateOutput", "ConsolidationItem", "ResolveCandidate",
                 "ResolveOutput", "LearnOutput", "TestOutput"):
        assert not hasattr(m, name), f"{name} must be deleted"
