from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    prephase_deep_read: list[str] = []   # table names / literal paths to read eagerly next run (IR)


class AnswerOutput(BaseModel):
    message: str
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_DENIED_SECURITY",
    ]
    grounding_refs: list[str] = []
