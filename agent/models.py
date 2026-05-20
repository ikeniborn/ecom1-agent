from typing import Literal

from pydantic import BaseModel, ConfigDict


class SddOutput(BaseModel):
    spec_goal: str
    success_criteria: list[str]
    plan: list[str]
    actions: list[str]
    error_code: str = ""


class PlanOutput(BaseModel):
    approach: str
    steps: list[str]
    action: str


class ExecuteOutput(BaseModel):
    results: list[dict]
    action: str


class LearnOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str
    conclusion: str
    rule_content: str
    agents_md_anchor: str | None = None
    deactivate: list[str] = []
    deactivate_reason: str | None = None
    skip: bool = False
    skip_reason: str | None = None


class ConsolidationItem(BaseModel):
    deactivate: list[str]
    merged_rule: str
    merged_reasoning: str


class ConsolidateOutput(BaseModel):
    skip: bool = True
    skip_reason: str | None = None
    consolidations: list[ConsolidationItem] = []


class AnswerOutput(BaseModel):
    reasoning: str
    message: str
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_DENIED_SECURITY",
    ]
    grounding_refs: list[str]
    completed_steps: list[str]


class ResolveCandidate(BaseModel):
    term: str
    field: str
    discovery_query: str
    confirmed_value: str | None = None


class ResolveOutput(BaseModel):
    reasoning: str
    candidates: list[ResolveCandidate]


# Deprecated: TestOutput kept for backward compatibility; removed in Task 6
class TestOutput(BaseModel):
    reasoning: str
    sql_tests: str
    answer_tests: str
