from typing import Literal

from pydantic import BaseModel, ConfigDict


class PlanStep(BaseModel):
    type: Literal["sql", "exec", "read", "compute"]
    description: str
    query: str | None = None
    operation: str | None = None
    args: list[str] = []


class SddOutput(BaseModel):
    reasoning: str
    spec: str
    plan: list[PlanStep]
    agents_md_refs: list[str] = []
    error: str | None = None


class TestOutput(BaseModel):
    reasoning: str
    sql_tests: str
    answer_tests: str


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


# Aliases for old names — removed after Task 6 (pipeline.py rewrite) + Task 9 (resolve.py delete)
SqlPlanOutput = SddOutput
TestGenOutput = TestOutput


class ResolveCandidate(BaseModel):
    term: str
    field: str
    discovery_query: str
    confirmed_value: str | None = None


class ResolveOutput(BaseModel):
    reasoning: str
    candidates: list[ResolveCandidate]



