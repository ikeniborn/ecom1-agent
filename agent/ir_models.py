"""Pydantic models for the deterministic Plan-IR interpreter.

PredExpr is the single predicate language shared by `decision`,
`success_criteria`, and security `deny_when`. A string starting with `$`
is a ref into `env`; anything else is a literal.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

LEAF_OPS = {
    "eq", "ne", "lt", "le", "gt", "ge",
    "nonempty", "isnull",
    "contains_any", "in_set", "startswith", "endswith", "regex_match",
}
BOOL_OPS = {"and", "or", "not"}


class PredExpr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    lhs: Any = None
    rhs: Any = None
    args: list["PredExpr"] = []

    @model_validator(mode="after")
    def _check_shape(self) -> "PredExpr":
        if self.op in BOOL_OPS:
            if not self.args:
                raise ValueError(f"bool op {self.op!r} requires non-empty args")
            if self.op == "not" and len(self.args) != 1:
                raise ValueError("'not' takes exactly one arg")
        elif self.op in LEAF_OPS:
            if self.lhs is None:
                raise ValueError(f"leaf op {self.op!r} requires lhs")
        else:
            raise ValueError(f"unknown predicate op {self.op!r}")
        return self


PredExpr.model_rebuild()


# --- IntentSpec (IDD layer) -----------------------------------------------

class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchor: str
    rule: str
    security: bool = False
    deny_when: PredExpr | None = None        # security deny predicate (verify I3 / decide.security_deny)
    requires_protected_action: bool = False  # blast-radius gate: this deny fires only when a protected action is in play
    protected_action: bool = False           # marks this constraint as guarding a protected action (checkout/refund/discount/...)
    unsupported_when: PredExpr | None = None  # terminal-state holds -> OUTCOME_NONE_UNSUPPORTED (decide)
    clarify_when: PredExpr | None = None      # genuine ambiguity holds -> OUTCOME_NONE_CLARIFICATION (decide)
    refs: list["RefSpec"] = []               # anchored refs cited when this constraint decides the outcome


class AnswerShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    msg_skeleton: str = ""


class RefSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str                  # "policy_doc" | "record_path"
    path: str | None = None    # literal /docs/...md, known at INTENT (from discovery)
    source: str | None = None  # $ref binding, resolved at runtime (record_path)

    @model_validator(mode="after")
    def _check(self) -> "RefSpec":
        if self.kind == "policy_doc":
            if not self.path or self.source:
                raise ValueError("policy_doc RefSpec requires `path` and no `source`")
        elif self.kind == "record_path":
            if not self.source or self.path:
                raise ValueError("record_path RefSpec requires `source` and no `path`")
        else:
            raise ValueError(f"unknown RefSpec kind {self.kind!r}")
        return self

    def env_key(self) -> "str | None":
        """The env key under which a read-only investigator records this ref as grounded,
        or None when the ref is PLAN-produced (resolved from a $source at plan time)."""
        if self.kind == "policy_doc":
            return f"policy_doc:{self.path}"
        return None                      # record_path (& future $source kinds) -> PLAN's job

    def grounded(self, env: dict) -> "bool | None":
        """True/False if this ref is investigator-groundable (its env_key state); None when
        it is not the investigator's responsibility (PLAN produces it)."""
        k = self.env_key()
        return None if k is None else bool(env.get(k))

    def read_target(self) -> "str | None":
        """The path a read-only investigator should read to ground this ref, else None."""
        return self.path if self.kind == "policy_doc" else None


Constraint.model_rebuild()   # resolve the forward ref `refs: list["RefSpec"]`


class IntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str
    desired_outcome: str
    params: dict[str, Any] = {}
    outcome_space: list[str]
    constraints: list[Constraint] = []
    success_criteria: dict[str, list[PredExpr]] = {}   # keyed by outcome
    answer_shape: AnswerShape
    required_refs: dict[str, list[RefSpec]] = {}   # keyed by outcome

    @model_validator(mode="before")
    @classmethod
    def _coerce_success_criteria(cls, data):
        # Migration: a bare list (legacy shape / persisted intent.json) means
        # criteria for the positive outcome.
        if isinstance(data, dict) and isinstance(data.get("success_criteria"), list):
            data["success_criteria"] = {"OUTCOME_OK": data["success_criteria"]}
        return data

    @model_validator(mode="after")
    def _require_ok_outcome(self) -> "IntentSpec":
        # D6: OUTCOME_OK must be reachable unless a security deny is declared. Closes
        # the frozen-clarification leg where INTENT pre-commits an OK-less space and
        # no in-loop iLEARN can recover (INTENT is frozen for the run).
        has_security_deny = any(
            c.security and c.deny_when is not None for c in self.constraints
        )
        if "OUTCOME_OK" not in self.outcome_space and not has_security_deny:
            raise ValueError(
                "outcome_space must include OUTCOME_OK unless a security constraint "
                "with deny_when is present"
            )
        return self


# --- PlanIR (SDD layer) ----------------------------------------------------

class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpc: str
    args: dict[str, Any] = {}
    bind: str | None = None


class ColResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    into: str
    candidates: list[str]


class RowSet(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    format: str = "auto_delim"
    into: str
    columns: list[ColResolve] = []


class ComputeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prim: str
    args: list[Any] = []
    into: str


class Branch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: PredExpr
    label: str


class DecisionTree(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branches: list[Branch] = []
    default_label: str


class KeywordBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[str]
    outcome: str


class OutcomeFromExit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok_outcome: str = "OUTCOME_OK"
    keyword_buckets: list[KeywordBucket] = []
    default_outcome: str = "OUTCOME_NONE_UNSUPPORTED"


class GuardedOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpc: str
    args: dict[str, Any] = {}
    bind: str | None = None
    guard_label: str | None = None
    outcome_from_exit: OutcomeFromExit | None = None


class AnswerTemplateIR(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    outcome: str
    refs: list[Any] = []


class CustomExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    input: str
    into: str


class PlanIR(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discovery: list[Step] = []
    rowsets: list[RowSet] = []
    compute: list[ComputeStep] = []
    decision: DecisionTree
    ops: list[GuardedOp] = []
    answer: dict[str, AnswerTemplateIR]
    custom_extract: list[CustomExtract] = []
