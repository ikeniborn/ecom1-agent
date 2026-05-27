from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class IddOutput(BaseModel):
    # Layer 1: Intent
    intent_objective: str
    reformulated_task: str
    intent_type: Literal["read", "write", "security_check", "compute"] = "read"
    extracted_params: dict = {}

    # Layer 1: Expectation contract
    success_criteria: list[str]
    stop_rules: list[str] = []
    health_metrics: list[str] = []

    # Gate
    decision: Literal["proceed", "hard_stop"]
    stop_code: Literal[
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_NONE_CLARIFICATION",
        "",
    ] = ""
    stop_message: str = ""
    stop_refs: list[str] = []
    reasoning: str = ""
    scope_estimate: dict = {}
    # e.g. {"files_to_read": 180, "estimated_cycles": 8}
    # Pipeline uses this to compute adaptive batch cap per cycle.


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_action(cls, data: dict) -> dict:
        # LLM sometimes returns action as list when multiple candidates given
        if isinstance(data.get("action"), list):
            data["action"] = data["action"][0] if data["action"] else ""
        return data


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


class CodegenOutput(BaseModel):
    script_path: str
    script_code: str
    test_code: str


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
