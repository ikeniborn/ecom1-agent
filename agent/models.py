from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ToolOp(BaseModel):
    rpc: str                           # Read|List|Tree|Find|Search|Exec|Write|Delete|Stat|Answer
    args: dict[str, Any]
    bind: str | None = None            # variable name for result chaining


class AgentsMdRef(BaseModel):
    anchor: str                        # "#section > entry"
    rule: str                          # verbatim rule text


class AnswerTemplate(BaseModel):
    message: str                       # e.g. "{rows[0].cnt} baskets"
    outcome: str = "OUTCOME_OK"
    refs: list[str] = []


class DesignOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    params: dict[str, Any]
    success_criteria: list[str]        # F-002 / H10
    discovery: list[ToolOp] = []
    ops: list[ToolOp]
    agents_md_constraints: list[AgentsMdRef] = []
    answer_template: AnswerTemplate
    outcome_override: Literal[
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_NONE_CLARIFICATION",
    ] | None = None


class CodegenOutput(BaseModel):
    script_code: str                   # standalone module exporting `run(vm, params)`


class LearnConsolidateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Null rule_content allowed when skip=True or when only deactivating prior rules.
    rule_content: str | None = None
    agents_md_anchor: str | None = None
    reasoning: str
    deactivate_ids: list[str] = []
    deactivate_reason: str | None = None
    skip: bool = False
    skip_reason: str | None = None


class AnswerOutput(BaseModel):
    message: str
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_DENIED_SECURITY",
    ]
    grounding_refs: list[str] = []


class TestSpec(BaseModel):
    """TEST-GEN output: intent-driven acceptance tests run by agent.test_runner.

    `sql_tests` defines `test_sql(results)`, `answer_tests` defines
    `test_answer(sql_results, answer)`. Both are Python source strings executed
    in an isolated subprocess against captured runtime data (no LLM at run time).
    """
    reasoning: str = ""
    sql_tests: str
    answer_tests: str
