# agent/investigate.py
"""Step-wise read-only investigator: gathers a compact evidence Brief that the
deterministic PLAN consumes in place of a front-loaded facts dump."""
from __future__ import annotations

import re

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


_READ_RPCS = {"read", "list", "tree", "stat", "search"}
_SELECT_RE = re.compile(r"^\s*(?:with\b.*?\bselect\b|select\b)", re.IGNORECASE | re.DOTALL)


class ToolRejected(Exception):
    """Raised when the investigator picks a tool that would mutate state."""


def is_readonly(tool: str, args: dict) -> bool:
    t = (tool or "").lower()
    if t in _READ_RPCS:
        return True
    if t == "exec":                                  # only /bin/sql, SELECT/CTE only
        if (args.get("path") or "") != "/bin/sql":
            return False
        sql = args.get("stdin") or args.get("sql") or ""
        return bool(_SELECT_RE.match(sql))
    return False


def run_tool(vm, tool: str, args: dict) -> str:
    """Dispatch a read-only RPC. Mutations raise ToolRejected (never dispatched)."""
    if not is_readonly(tool, args):
        raise ToolRejected(f"{tool} {args} is not read-only")
    t = tool.lower()
    if t == "read":
        return _text(vm.read(path=args.get("path", "")), "content")
    if t == "list":
        return _text(vm.list(path=args.get("path", "")), "entries")
    if t == "tree":
        return _text(vm.tree(root=args.get("root", args.get("path", ""))), "nodes")
    if t == "stat":
        return _text(vm.stat(path=args.get("path", "")), "content")
    if t == "search":
        return _text(vm.search(root=args.get("root", "/docs"),
                               pattern=args.get("pattern", ""),
                               limit=int(args.get("limit", 30))), "matches")
    # exec /bin/sql
    res = vm.exec(path="/bin/sql", args=args.get("args", []),
                  stdin=args.get("stdin") or args.get("sql") or "")
    return _text(res, "stdout")


def _text(res, key: str) -> str:
    """Best-effort extract a string from a proto/dict/str RPC result."""
    if res is None:
        return ""
    if isinstance(res, str):
        return res
    if isinstance(res, dict):
        val = res.get(key, "")
        return val if isinstance(val, str) else str(val) if val else ""
    val = getattr(res, key, "")
    return val if isinstance(val, str) else (str(val) if val else "")
