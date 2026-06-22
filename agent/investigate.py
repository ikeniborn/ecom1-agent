"""Step-wise read-only investigator: gathers a compact evidence Brief that the
deterministic PLAN consumes in place of a front-loaded facts dump."""
from __future__ import annotations

import os
import re

from pydantic import BaseModel, ConfigDict, Field

from .llm import call_llm_raw, _resolve_model_for_phase
from .prompt import load_prompt
from .json_extract import _extract_json_from_text
from .trace import set_step_type, current_step_type, log_investigate_stop_auto


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

# Mutating keywords that must never appear in an investigator SQL probe — even
# wrapped in a CTE (e.g. `WITH x AS (DELETE ... RETURNING) SELECT`).
_SQL_MUTATION_RE = re.compile(
    r"\b(?:insert|update|delete|drop|alter|truncate|create|replace|merge|grant|revoke|attach|copy)\b",
    re.IGNORECASE,
)


def _is_readonly_sql(sql: str) -> bool:
    """A SQL probe is read-only iff it starts with SELECT/CTE, is a single
    statement (one optional trailing ';'), and contains no mutating keyword
    (the keyword scan catches CTE-wrapped DML the leading-SELECT check misses)."""
    if not _SELECT_RE.match(sql or ""):
        return False
    body = re.sub(r"'[^']*'", "", sql)          # drop string literals before scanning
    if ";" in body.rstrip().rstrip(";"):        # reject multi-statement (allow one trailing ';')
        return False
    if _SQL_MUTATION_RE.search(body):           # reject embedded DML/DDL
        return False
    return True


class ToolRejected(Exception):
    """Raised when the investigator picks a tool that would mutate state."""


def is_readonly(tool: str, args: dict) -> bool:
    t = (tool or "").lower()
    if t in _READ_RPCS:
        return True
    if t == "exec":
        path = (args.get("path") or "").lower()
        if path == "/bin/id":                        # read-only identity probe (no mutation)
            return True
        if path != "/bin/sql":                       # only /bin/sql otherwise, SELECT/CTE only
            return False
        return _is_readonly_sql(args.get("stdin") or args.get("sql") or "")
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
        try:
            limit = int(args.get("limit", 30))
        except (TypeError, ValueError):
            limit = 30
        return _text(vm.search(root=args.get("root", "/docs"),
                               pattern=args.get("pattern", ""),
                               limit=limit), "matches")
    # exec: /bin/sql (SELECT/CTE) or /bin/id (read-only identity probe)
    exec_path = "/bin/id" if (args.get("path") or "").lower() == "/bin/id" else "/bin/sql"
    res = vm.exec(path=exec_path, args=args.get("args", []),
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


def tool_signature(tool: str, args: dict) -> str:
    """Stable signature for stall/repeat detection. SQL is whitespace/case-normalised
    in the same spirit as pipeline._plan_signature; the investigator always sends SQL
    via stdin, so positional /bin/sql args are not part of the signature. Other tools'
    args are stringified verbatim, sorted by key."""
    args = args or {}
    t = (tool or "").lower()
    if t == "exec":
        sql = (args.get("stdin") or args.get("sql") or "")
        norm = re.sub(r"\s+", " ", sql).strip().lower()
        return f"exec:{args.get('path','')}:{norm}"
    body = ";".join(f"{k}={args[k]}" for k in sorted(args))
    return f"{t}:{body}"


def is_stalled(result: str, signature: str, seen_signatures: set[str]) -> bool:
    """Deterministic stall: empty tool result OR a signature already seen this run."""
    if not (result or "").strip():
        return True
    if signature in seen_signatures:
        return True
    return False


def sufficient(intent, env: dict) -> bool:
    """True when every investigator-groundable required_ref for the desired outcome is
    grounded in env. Refs whose grounding is PLAN's responsibility (e.g. record_path
    resolved from a $source) are skipped — the investigator cannot ground them and must
    not block on them."""
    outcome = intent.desired_outcome
    refs = (intent.required_refs or {}).get(outcome, [])
    for ref in refs:
        g = ref.grounded(env)
        if g is None:            # PLAN produces this ref (e.g. record_path) — not the investigator's job
            continue
        if not g:
            return False
    return True


def _ground_doc_refs(env: dict, tool: str, args: dict, refs: list) -> None:
    """Deterministically ground a required ref when the path it reads from was just
    read — independent of the digest LLM emitting the env key. Grounding state lives
    on RefSpec (env_key/read_target). Mutates env."""
    if (tool or "").lower() != "read":
        return
    path = args.get("path", "")
    for r in refs:
        # read_target() and env_key() are both non-None exactly for groundable kinds
        if r.read_target() == path and r.env_key():
            env[r.env_key()] = True


def _forced_doc_read(env: dict, refs: list) -> "dict | None":
    """If any investigator-groundable ref (one with a read_target) is still ungrounded,
    return a forced read action for its target path (prioritized over free routing);
    else None."""
    for r in refs:
        if r.read_target() and r.grounded(env) is False:
            return {"tool": "read", "args": {"path": r.read_target()}}
    return None


def _call_json(system: str, user: str, phase: str, escalate: bool) -> dict:
    """One LLM round-trip returning a parsed JSON object. FAST tier by default;
    escalate=True forces the REASON tier (think=on) for a stalled step."""
    default = os.environ.get("ECOM_MODEL", "")
    model = (_resolve_model_for_phase("reason", default) if escalate
             else _resolve_model_for_phase(phase, default))
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    raw = call_llm_raw(sys_blocks, user, model, {}, max_tokens=1024,
                       think=True if escalate else False, phase=phase)
    obj = _extract_json_from_text(raw or "")
    return obj if isinstance(obj, dict) else {}


def _atoms_block(atoms: list) -> str:
    if not atoms:
        return ""
    lines = ["KNOWLEDGE (scoped to this step):"]
    for a in atoms:
        content = getattr(a, "content", None) or (a.get("content") if isinstance(a, dict) else str(a))
        lines.append(f"- {content}")
    return "\n".join(lines)


def _refs_targets(intent) -> str:
    refs = (intent.required_refs or {}).get(intent.desired_outcome, [])
    return "; ".join(r.read_target() or f"{r.kind}:{r.source}" for r in refs)


def router(intent, brief: "Brief", atoms: list, escalate: bool) -> dict:
    guide = load_prompt("investigate") or "# PHASE: INVESTIGATE"
    user = "\n\n".join(p for p in [
        f"OBJECTIVE:\n{intent.objective}",
        f"REQUIRED_REFS:\n{_refs_targets(intent)}",
        render_brief(brief),
        _atoms_block(atoms),
        "Choose the next read-only action (or {\"done\": true}).",
    ] if p)
    return _call_json(guide, user, phase="INVESTIGATE", escalate=escalate)


def digest(goal: str, tool: str, args: dict, observation: str, escalate: bool):
    guide = load_prompt("investigate") or "# PHASE: INVESTIGATE"
    user = (f"GOAL:\n{goal}\n\nTOOL: {tool} {args}\n\n"
            f"RAW_RESULT (condense this):\n{observation[:4000]}\n\n"
            "Return the digest JSON.")
    obj = _call_json(guide, user, phase="INVESTIGATE", escalate=escalate)
    note = Note(goal=goal, tool=tool, args=args,
                observation_digest=str(obj.get("observation_digest", ""))[:200],
                lesson=str(obj.get("lesson", "")),
                refs_found=list(obj.get("refs_found", []) or []))
    env_updates = obj.get("env_updates", {}) if isinstance(obj.get("env_updates"), dict) else {}
    return note, env_updates


def digest_and_route(goal: str, tool: str, args: dict, observation: str,
                     escalate: bool):
    """Condense the observation AND choose the next action in one LLM call.
    Returns (Note, env_updates, next_action|None). next_action mirrors router()
    output: {"tool","args"} or None when the investigator is done."""
    guide = load_prompt("investigate") or "# PHASE: INVESTIGATE"
    user = (f"GOAL:\n{goal}\n\nTOOL: {tool} {args}\n\n"
            f"RAW_RESULT (condense this):\n{observation[:4000]}\n\n"
            "Return JSON: observation_digest, lesson, refs_found, env_updates, "
            "and next_action ({\"tool\":...,\"args\":...} or null when done).")
    obj = _call_json(guide, user, phase="INVESTIGATE", escalate=escalate)
    note = Note(goal=goal, tool=tool, args=args,
                observation_digest=str(obj.get("observation_digest", ""))[:200],
                lesson=str(obj.get("lesson", "")),
                refs_found=list(obj.get("refs_found", []) or []))
    env_updates = obj.get("env_updates", {}) if isinstance(obj.get("env_updates"), dict) else {}
    na = obj.get("next_action")
    next_action = na if isinstance(na, dict) and na.get("tool") else None
    return note, env_updates, next_action


_MAX_STEPS = int(os.environ.get("ECOM_INVESTIGATE_MAX_STEPS", "6"))
_ORACLE_K = int(os.environ.get("ECOM_INVESTIGATE_ORACLE_K", "2"))
_MERGE_STEPS = os.environ.get("ECOM_INVESTIGATE_MERGE_STEPS", "0") == "1"


def _retrieve_atoms(oracle, goal: str) -> list:
    if oracle is None or not goal:
        return []
    try:
        return oracle.retrieve(goal, k=_ORACLE_K)
    except Exception:
        return []


def investigate(vm, intent, seed=None, oracle=None, max_steps: int | None = None) -> "Brief":
    """Bounded read-only ReAct loop → Brief. Never raises: a rejected mutation or any
    per-step error is recorded as a lesson and the loop continues; the caller falls back
    to seed facts only if the whole brief is unusable. `seed` is accepted for caller
    compatibility (Task 10 passes the slim pre-phase facts) but is reserved/unused in v1
    — the slim facts still reach PLAN via run_plan's `facts` argument."""
    brief = Brief()
    req_refs = (intent.required_refs or {}).get(intent.desired_outcome, [])
    seen: set[str] = set()
    stop_reason = "budget"
    pending_action = None
    steps = max_steps if max_steps is not None else _MAX_STEPS
    _prev_step = current_step_type()
    set_step_type("INVESTIGATE")
    try:
        for _ in range(steps):
            goal = intent.objective if not brief.notes else (brief.notes[-1].lesson or intent.objective)
            try:
                atoms = _retrieve_atoms(oracle, goal)
                act = None
                forced = _forced_doc_read(brief.env, req_refs)
                if forced is not None and tool_signature(
                        forced["tool"], forced["args"]) not in seen:
                    act = forced  # priority 1: ground the governing doc
                if act is None and _MERGE_STEPS and pending_action is not None:
                    act = pending_action
                    pending_action = None
                if act is None:                           # priority 3: free router
                    act = router(intent, brief, atoms, escalate=False)
                if act.get("done"):
                    stop_reason = "sufficient"
                    break
                tool, args = act.get("tool", ""), act.get("args", {}) or {}
                try:
                    observation = run_tool(vm, tool, args)
                except ToolRejected as e:
                    brief.notes.append(Note(goal=goal, tool=tool, args=args,
                                            lesson=f"rejected (mutation): {e}"))
                    continue
                sig = tool_signature(tool, args)
                escalate = is_stalled(observation, sig, seen)
                if escalate:                                   # one re-run on the reason tier
                    act2 = router(intent, brief, atoms, escalate=True)
                    if act2.get("done"):
                        stop_reason = "sufficient"
                        break
                    tool, args = act2.get("tool", tool), act2.get("args", args) or args
                    try:
                        observation = run_tool(vm, tool, args)
                    except ToolRejected as e:
                        brief.notes.append(Note(goal=goal, tool=tool, args=args,
                                                lesson=f"rejected (mutation): {e}"))
                        continue
                    sig = tool_signature(tool, args)
                    if is_stalled(observation, sig, seen):     # still stalled after escalation → stop
                        note, env_updates = digest(goal, tool, args, observation, escalate=True)
                        brief.notes.append(note); brief.env.update(env_updates)
                        _ground_doc_refs(brief.env, tool, args, req_refs)
                        stop_reason = "budget"   # stalled even after escalation — gave up, not satisfied
                        break
                seen.add(sig)
                if _MERGE_STEPS:
                    note, env_updates, pending_action = digest_and_route(
                        goal, tool, args, observation, escalate=escalate)
                else:
                    note, env_updates = digest(goal, tool, args, observation, escalate=escalate)
                brief.notes.append(note)
                brief.env.update(env_updates)
                _ground_doc_refs(brief.env, tool, args, req_refs)
                if sufficient(intent, brief.env):
                    stop_reason = "sufficient"
                    break
            except Exception as e:                             # graceful: never raise out of a step
                brief.notes.append(Note(goal=goal, lesson=f"step error: {e}"))
                continue
        log_investigate_stop_auto(stop_reason, 0, 0)
    finally:
        set_step_type(_prev_step)
    return brief
