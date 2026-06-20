# agent/investigate.py
"""Step-wise read-only investigator: gathers a compact evidence Brief that the
deterministic PLAN consumes in place of a front-loaded facts dump."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = ""                       # the micro-goal this step pursued
    tool: str = ""                       # read-only RPC chosen
    args: dict = Field(default_factory=dict)
    observation_digest: str = ""         # condensed tool output (NOT the raw blob)
    lesson: str = ""                     # one-line takeaway, guides the next step
    refs_found: list[str] = Field(default_factory=list)


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: list[Note] = Field(default_factory=list)
    env: dict = Field(default_factory=dict)   # bound facts: incident_id, governing_doc, candidate paths…


def render_brief(brief: "Brief") -> str:
    """Compact text block for the PLAN prompt. Empty brief → '' (falsy marker)."""
    if not brief.notes and not brief.env:
        return ""
    lines = ["INVESTIGATION_BRIEF:"]
    if brief.env:
        lines.append("## RESOLVED_ENV")
        for k, v in brief.env.items():
            lines.append(f"- {k}: {v}")
    if brief.notes:
        lines.append("## STEP_LESSONS")
        for i, n in enumerate(brief.notes, 1):
            ref = f" refs={n.refs_found}" if n.refs_found else ""
            lines.append(f"{i}. [{n.tool}] {n.observation_digest} -> {n.lesson}{ref}")
    return "\n".join(lines)
