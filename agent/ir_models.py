"""Pydantic models for the deterministic Plan-IR interpreter.

PredExpr is the single predicate language shared by `decision`,
`success_criteria`, and security `deny_when`. A string starting with `$`
is a ref into `env`; anything else is a literal.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

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
