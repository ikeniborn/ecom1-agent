---
review:
  plan_hash: 370d4e8d74bc85c1
  last_run: 2026-06-21
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: consistency
      severity: WARNING
      section: "Task 3: Read-only whitelist + tool dispatch"
      section_hash: ca5111f185ba50d9
      text: >-
        Test fixtures + call assertions use lowercase RPC names
        (fixture_key("read", ...), vm.calls[-1][0] == "read"), but MockVMSpy
        records capitalized names ("Read"/"Exec"/"Write") and keys fixtures on
        them. As written, _lookup misses (returns the empty stub) and the
        records assertion fails. All existing tests use "Read"/"Exec"/... —
        the new tests in Tasks 3/8/12 must follow that casing.
      verdict: fixed
      verdict_at: 2026-06-21
      resolution: >-
        Capitalized all fixture_key()/vm.calls RPC names in Tasks 3, 7, 8, 12
        ("Read"/"Exec"/"Write"); investigator tool names passed to run_tool stay
        lowercase (they map to vm.read()/vm.exec()). Task 7 budget test reworked
        with 3 distinct fixtured paths so steps neither empty-stall nor repeat.
    - id: F-002
      phase: consistency
      severity: INFO
      section: "Task 12: Trace `INVESTIGATE` steps"
      section_hash: bd651e06c564a02c
      text: >-
        Test uses trace.TraceLogger(task_id=, out_dir=) and logger.records_text();
        the real ctor is TraceLogger(path: Path, task_id: str) with no out_dir /
        records_text. The plan explicitly flags this in a callout and names the
        real API (set_trace/get_trace/log_vm_auto) to adapt to — self-acknowledged,
        not silent drift.
      verdict: fixed
      verdict_at: 2026-06-21
      resolution: >-
        Test rewritten to the real ctor TraceLogger(path=logpath, task_id=...) and
        to read the jsonl file at logpath; capitalized the Read fixture. Callout
        narrowed to confirming the flush/buffering behaviour in agent/trace.py.
    - id: F-003
      phase: clarity
      severity: INFO
      section: "Task 11: Cross-run lesson distillation on success"
      section_hash: b3f8aec016347f94
      text: >-
        The success-path distill call passes outcome_note as an inline
        positional f-string (_maybe_distill_and_validate(intent, plan, task_id,
        f"OK: ...")), not a named outcome_note variable. The instruction to
        "append lessons to the existing outcome_note argument" is conceptually
        correct but the implementer must wrap that inline f-string; helper
        _brief_lessons_text + the brief-scoping prerequisite are fully specified.
      verdict: fixed
      verdict_at: 2026-06-21
      resolution: >-
        Task 11 Step 3 now quotes the exact _maybe_distill_and_validate(intent,
        plan, task_id, f"OK: {verr or 'verify passed'}") call site and shows the
        wrapped _note replacement; Task 10 initialises brief=None for scope; the
        test targets _brief_lessons_text directly.
  chain:
    spec: docs/superpowers/specs/2026-06-20-stepwise-investigator-design.md
---
# Step-wise Investigator → Deterministic Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert an agentic, read-only `INVESTIGATE` phase between `INTENT` and the PLAN loop that gathers a compact evidence brief step-by-step, so the deterministic PLAN receives focused facts instead of a front-loaded dump — fixing the t38 CC-timeout/floundering failure while keeping `interpret()`/`verify()` deterministic.

**Architecture:** A new `agent/investigate.py` module runs a bounded ReAct loop (router picks one read-only tool → execute → digest → note), building a `Brief` (step-notes + bound `env`). The loop stops on sufficiency (INTENT refs groundable) or a step budget. Each router/digest step runs on the FAST tier and escalates to REASON on a deterministic stall (empty result ∨ repeated tool signature). `pipeline.py` calls `investigate()` and feeds a rendered brief into `run_plan`. Everything is gated by `ECOM_INVESTIGATE_ENABLED` so `=0` reproduces today's eager-gather baseline exactly.

**Tech Stack:** Python 3, Pydantic (`ir_models`/`PrePhaseFacts`), `pytest`, `uv`, existing `agent/llm.py` (`call_llm_raw`/`call_llm_json`, tier resolution), `agent/oracle.py` (`KnowledgeOracle.retrieve`), `agent/mock_vm_spy.py` (`MockVMSpy`).

**Spec:** `docs/superpowers/specs/2026-06-20-stepwise-investigator-design.md`

---

## File Structure

- **Create** `agent/investigate.py` — the investigator: `Note`/`Brief` models, read-only whitelist, stall/sufficiency predicates, `router`/`digest` LLM steps, `investigate()` loop, `render_brief()`.
- **Create** `data/prompts/investigate.md` — router + digest phase guide (general structural rules only, per the prompt-engineering rule).
- **Create** `tests/test_investigate.py` — unit tests for every investigator unit over `MockVMSpy` + stubbed LLM.
- **Create** `tests/test_pipeline_investigate.py` — integration: `run_pipeline` builds a brief then a valid plan; `ENABLED=0` path unchanged.
- **Modify** `agent/llm.py` — register the `investigate` phase in `_PHASE_TIER` (fast tier).
- **Modify** `agent/orchestrator.py` — add a `slim` path to `gather_prephase_facts` (seed = identity + schema + doc paths; drop policy bodies / sample rows / listings / catalogue candidates); `run_agent` chooses slim vs eager by `ECOM_INVESTIGATE_ENABLED`.
- **Modify** `agent/reason.py` — `run_plan` accepts an optional `brief_block` and appends it.
- **Modify** `agent/pipeline.py` — call `investigate()` after INTENT when enabled; pass `brief_block`; drop the whole-instruction PLAN oracle dump when enabled; distill brief step-lessons on success.
- **Modify** `agent/trace.py` — accept `INVESTIGATE` step records (reuses the existing `llm_call` funnel; only a phase label).
- **Modify** `CLAUDE.md` + `agent/CLAUDE.md` — env table + architecture section.

---

## Task 1: Register the `investigate` model tier

**Files:**
- Modify: `agent/llm.py:72-80` (`_PHASE_TIER`)
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_investigate.py
import os
from agent.llm import _resolve_model_for_phase, _think_for_phase


def test_investigate_phase_is_fast_tier(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.delenv("ECOM_MODEL_INVESTIGATE", raising=False)
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "fast-model"
    assert _think_for_phase("INVESTIGATE") is False


def test_investigate_phase_override_wins(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.setenv("ECOM_MODEL_INVESTIGATE", "explicit-model")
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "explicit-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: FAIL — `_think_for_phase("INVESTIGATE")` returns `None` (phase not in `_PHASE_TIER`), assert `is False` fails.

- [ ] **Step 3: Add the phase to the tier map**

In `agent/llm.py`, add the `investigate` entry to `_PHASE_TIER`:

```python
_PHASE_TIER: dict[str, str] = {
    "intent":      "reason",
    "plan":        "reason",
    "ilearn":      "reason",
    "learn":       "reason",
    "distill":     "reason",
    "docselect":   "fast",
    "rerank":      "fast",
    "investigate": "fast",
}
```

(`_norm_phase` lowercases and strips `_`, so `"INVESTIGATE"` → `"investigate"`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add agent/llm.py tests/test_investigate.py
git commit -m "feat(llm): register investigate phase on the fast tier"
```

---

## Task 2: `Note` / `Brief` data models + `render_brief`

**Files:**
- Create: `agent/investigate.py`
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_investigate.py
from agent.investigate import Note, Brief, render_brief


def test_brief_accumulates_notes_and_env():
    brief = Brief()
    brief.notes.append(Note(goal="find incident", tool="exec",
                            args={"path": "/bin/sql"}, observation_digest="3 rows",
                            lesson="incident id lives in fraud_reports",
                            refs_found=["/payments/p_1.json"]))
    brief.env["incident_id"] = "INC-7"
    assert len(brief.notes) == 1
    assert brief.env["incident_id"] == "INC-7"


def test_render_brief_is_compact_and_contains_env_and_lessons():
    brief = Brief()
    brief.notes.append(Note(goal="g", tool="read", args={"path": "/docs/x.md"},
                            observation_digest="policy says N=2", lesson="use N=2",
                            refs_found=[]))
    brief.env["governing_doc"] = "/docs/x.md"
    out = render_brief(brief)
    assert "INVESTIGATION_BRIEF" in out
    assert "use N=2" in out               # lesson surfaced
    assert "governing_doc" in out         # env surfaced
    assert "/docs/x.md" in out


def test_render_brief_empty_is_falsy_marker():
    assert render_brief(Brief()) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.investigate'`.

- [ ] **Step 3: Create the module with the models + renderer**

```python
# agent/investigate.py
"""Step-wise read-only investigator: gathers a compact evidence Brief that the
deterministic PLAN consumes in place of a front-loaded facts dump."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Note(BaseModel):
    goal: str = ""                       # the micro-goal this step pursued
    tool: str = ""                       # read-only RPC chosen
    args: dict = Field(default_factory=dict)
    observation_digest: str = ""         # condensed tool output (NOT the raw blob)
    lesson: str = ""                     # one-line takeaway, guides the next step
    refs_found: list[str] = Field(default_factory=list)


class Brief(BaseModel):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add agent/investigate.py tests/test_investigate.py
git commit -m "feat(investigate): Note/Brief models + compact render_brief"
```

---

## Task 3: Read-only whitelist + tool dispatch

**Files:**
- Modify: `agent/investigate.py`
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_investigate.py
import pytest
from agent.investigate import is_readonly, run_tool, ToolRejected
from agent.mock_vm_spy import MockVMSpy, fixture_key


def test_is_readonly_allows_reads_and_select():
    assert is_readonly("read", {"path": "/docs/x.md"})
    assert is_readonly("tree", {"root": "/docs"})
    assert is_readonly("exec", {"path": "/bin/sql", "stdin": "SELECT * FROM t"})


def test_is_readonly_rejects_mutations():
    assert not is_readonly("write", {"path": "/x", "content": "y"})
    assert not is_readonly("delete", {"path": "/x"})
    assert not is_readonly("exec", {"path": "/bin/sql", "stdin": "UPDATE t SET a=1"})
    assert not is_readonly("exec", {"path": "/bin/id"})   # only /bin/sql exec allowed


def test_run_tool_executes_read_only_and_records():
    # MockVMSpy records/keys RPCs CAPITALIZED ("Read"), though vm.read() is the method.
    fx = {fixture_key("Read", "/docs/x.md"): {"content": "# Policy\nN=2"}}
    vm = MockVMSpy(fx)
    out = run_tool(vm, "read", {"path": "/docs/x.md"})   # investigator tool name is lowercase
    assert "N=2" in out
    assert vm.calls and vm.calls[-1][0] == "Read"


def test_run_tool_rejects_mutation():
    vm = MockVMSpy({})
    with pytest.raises(ToolRejected):
        run_tool(vm, "write", {"path": "/x", "content": "y"})
    assert not any(c[0] == "Write" for c in vm.calls)   # never dispatched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_readonly'`.

- [ ] **Step 3: Add the whitelist + dispatcher**

```python
# add to agent/investigate.py
import re

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/investigate.py tests/test_investigate.py
git commit -m "feat(investigate): read-only tool whitelist + SELECT-only exec dispatch"
```

---

## Task 4: Deterministic stall detection

**Files:**
- Modify: `agent/investigate.py`
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_investigate.py
from agent.investigate import tool_signature, is_stalled


def test_tool_signature_normalises_sql_whitespace_and_case():
    a = tool_signature("exec", {"path": "/bin/sql", "stdin": "SELECT  *\nFROM t"})
    b = tool_signature("exec", {"path": "/bin/sql", "stdin": "select * from t"})
    assert a == b


def test_is_stalled_on_empty_result():
    assert is_stalled(result="", signature="read:/docs/x.md", seen_signatures=set())


def test_is_stalled_on_repeated_signature():
    assert is_stalled(result="rows", signature="read:/docs/x.md",
                      seen_signatures={"read:/docs/x.md"})


def test_not_stalled_on_fresh_nonempty():
    assert not is_stalled(result="rows", signature="read:/docs/y.md",
                          seen_signatures={"read:/docs/x.md"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: FAIL — `ImportError: cannot import name 'tool_signature'`.

- [ ] **Step 3: Add the predicates**

```python
# add to agent/investigate.py
def tool_signature(tool: str, args: dict) -> str:
    """Stable signature for stall/repeat detection. SQL is whitespace/case-normalised
    (mirrors pipeline._plan_signature); other args are stringified verbatim, sorted."""
    t = (tool or "").lower()
    if t == "exec":
        sql = (args.get("stdin") or args.get("sql") or "")
        norm = re.sub(r"\s+", " ", sql).strip().lower()
        return f"exec:{args.get('path','')}:{norm}"
    body = ";".join(f"{k}={args[k]}" for k in sorted(args))
    return f"{t}:{body}"


def is_stalled(result: str, signature: str, seen_signatures: set) -> bool:
    """Deterministic stall: empty tool result OR a signature already seen this run."""
    if not (result or "").strip():
        return True
    if signature in seen_signatures:
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/investigate.py tests/test_investigate.py
git commit -m "feat(investigate): deterministic stall detection (empty | repeated signature)"
```

---

## Task 5: Sufficiency gate

**Files:**
- Modify: `agent/investigate.py`
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_investigate.py
from agent.investigate import sufficient
from agent.ir_models import IntentSpec, RefSpec


def _intent_with_refs():
    return IntentSpec(
        objective="cite fraud payments",
        desired_outcome="OUTCOME_OK",
        outcome_space=["OUTCOME_OK"],
        required_refs={"OUTCOME_OK": [
            RefSpec(kind="policy_doc", path="/docs/security.md"),
            RefSpec(kind="record_path", source="$row.record_path"),
        ]},
    )


def test_sufficient_false_when_refs_unbound():
    assert not sufficient(_intent_with_refs(), env={})


def test_sufficient_true_when_all_refs_grounded():
    env = {"policy_doc:/docs/security.md": True, "row.record_path": "/payments/p_1.json"}
    assert sufficient(_intent_with_refs(), env=env)


def test_sufficient_true_when_no_required_refs():
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], required_refs={})
    assert sufficient(intent, env={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: FAIL — `ImportError: cannot import name 'sufficient'`.

- [ ] **Step 3: Add the gate**

```python
# add to agent/investigate.py
def sufficient(intent, env: dict) -> bool:
    """True when every required_ref for the desired (happy) outcome is groundable
    from env. Conservative: a policy_doc is grounded when env has key
    'policy_doc:<path>'; a record_path is grounded when env has the bound source
    key (RefSpec.source '$row.record_path' -> env key 'row.record_path')."""
    outcome = intent.desired_outcome
    refs = (intent.required_refs or {}).get(outcome, [])
    if not refs:
        return True
    for ref in refs:
        if ref.kind == "policy_doc":
            if not env.get(f"policy_doc:{ref.path}"):
                return False
        elif ref.kind == "record_path":
            key = (ref.source or "").lstrip("$")
            if not env.get(key):
                return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/investigate.py tests/test_investigate.py
git commit -m "feat(investigate): sufficiency gate over intent.required_refs"
```

---

## Task 6: `router` and `digest` LLM steps

**Files:**
- Create: `data/prompts/investigate.md`
- Modify: `agent/investigate.py`
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test** (stub the LLM so no network is hit)

```python
# append to tests/test_investigate.py
import agent.investigate as inv


def test_router_parses_tool_choice(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda system, user, phase, escalate: {
                            "tool": "read", "args": {"path": "/docs/security.md"},
                            "why": "need the governing rule"})
    act = inv.router(_intent_with_refs(), Brief(), atoms=[], escalate=False)
    assert act["tool"] == "read"
    assert act["args"]["path"] == "/docs/security.md"


def test_router_emits_done(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda system, user, phase, escalate: {"done": True})
    act = inv.router(_intent_with_refs(), Brief(), atoms=[], escalate=False)
    assert act.get("done") is True


def test_digest_returns_note_fields(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda system, user, phase, escalate: {
                            "observation_digest": "security.md requires citing record_path",
                            "lesson": "cite the payment record_path",
                            "env_updates": {"policy_doc:/docs/security.md": True},
                            "refs_found": []})
    note, env_updates = inv.digest(goal="read policy", tool="read",
                                   args={"path": "/docs/security.md"},
                                   observation="# Security…", escalate=False)
    assert note.lesson == "cite the payment record_path"
    assert env_updates["policy_doc:/docs/security.md"] is True


def test_escalate_switches_model(monkeypatch):
    seen = {}
    def fake_raw(system, user_msg, model, cfg, **kw):
        seen["model"] = model
        return '{"done": true}'
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-m")
    monkeypatch.setenv("ECOM_MODEL_REASON", "reason-m")
    monkeypatch.setattr(inv, "call_llm_raw", fake_raw)
    inv._call_json("sys", "user", phase="INVESTIGATE", escalate=True)
    assert seen["model"] == "reason-m"   # escalation forces the reason tier
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: FAIL — `AttributeError: module 'agent.investigate' has no attribute 'router'`.

- [ ] **Step 3: Write the prompt guide**

```markdown
<!-- data/prompts/investigate.md -->
# PHASE: INVESTIGATE

You explore a vault ONE read-only step at a time to gather the evidence a later
deterministic plan needs. You do NOT write the plan and you NEVER mutate state.

## Each turn you receive
- The OBJECTIVE and the REFS the final answer must ground (required_refs targets).
- The BRIEF so far (resolved env + prior step lessons).
- A few KNOWLEDGE snippets scoped to the immediate sub-goal.

## Router output — pick exactly ONE next action
Single JSON object, no prose, no fences. Either a tool call:
{"tool": "<read|list|tree|stat|search|exec>", "args": {...}, "why": "<one line>"}
or, when the brief already grounds every required ref:
{"done": true}

Tool arg shapes: read/stat {"path"}; list {"path"}; tree {"root"}; search
{"root","pattern","limit"}; exec {"path":"/bin/sql","stdin":"SELECT …"} (SELECT/CTE only).
Prefer the cheapest probe that resolves the NEXT unknown. Do not re-issue a probe
already in the brief.

## Digest output — condense the tool result
Single JSON object:
{"observation_digest": "<≤200 chars of what the result shows>",
 "lesson": "<one-line takeaway for the next step>",
 "env_updates": {"<key>": "<value>"},
 "refs_found": ["<record_path>", ...]}

Bind env keys the sufficiency gate reads: "policy_doc:/docs/<file>.md": true when you
have read a governing doc; "<row>.record_path": "<path>" when you have located the
record to cite. Keep digests SMALL — the next step sees the brief, not the raw output.
```

- [ ] **Step 4: Add `router`, `digest`, `_call_json` to the module**

```python
# add to agent/investigate.py
import json
import os

from .llm import call_llm_raw, _resolve_model_for_phase
from .prompt import load_prompt
from .json_extract import _extract_json_from_text  # same extractor reason.py uses


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
    return "; ".join(r.path if r.kind == "policy_doc" else f"{r.kind}:{r.source}" for r in refs)


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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/investigate.py data/prompts/investigate.md tests/test_investigate.py
git commit -m "feat(investigate): router/digest LLM steps + escalation-aware _call_json"
```

---

## Task 7: The `investigate()` loop

**Files:**
- Modify: `agent/investigate.py`
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_investigate.py
def test_investigate_stops_on_sufficiency(monkeypatch):
    intent = _intent_with_refs()
    fx = {fixture_key("Read", "/docs/security.md"): {"content": "cite record_path"}}
    vm = MockVMSpy(fx)
    # router asks to read the policy, then would loop; digest grounds both refs at once.
    monkeypatch.setattr(inv, "router",
                        lambda i, b, atoms, escalate: {"tool": "read", "args": {"path": "/docs/security.md"}})
    monkeypatch.setattr(inv, "digest",
                        lambda goal, tool, args, observation, escalate: (
                            Note(tool=tool, args=args, lesson="cite it"),
                            {"policy_doc:/docs/security.md": True, "row.record_path": "/payments/p_1.json"}))
    brief = inv.investigate(vm, intent, seed=None, oracle=None, max_steps=6)
    assert brief.env["row.record_path"] == "/payments/p_1.json"
    assert len(brief.notes) == 1            # stopped right after sufficiency met


def test_investigate_respects_budget(monkeypatch):
    intent = _intent_with_refs()             # two refs, never grounded -> never sufficient
    # distinct non-empty results per step: no empty-stall, no repeated-signature stall
    fx = {fixture_key("Read", f"/docs/{i}.md"): {"content": f"data{i}"} for i in range(3)}
    vm = MockVMSpy(fx)
    monkeypatch.setattr(inv, "router",
                        lambda i, b, atoms, escalate: {"tool": "read", "args": {"path": f"/docs/{len(b.notes)}.md"}})
    monkeypatch.setattr(inv, "digest",
                        lambda goal, tool, args, observation, escalate: (Note(tool=tool, args=args), {}))
    brief = inv.investigate(vm, intent, seed=None, oracle=None, max_steps=3)
    assert len(brief.notes) == 3            # stopped at budget


def test_investigate_escalates_on_empty(monkeypatch):
    intent = _intent_with_refs()
    vm = MockVMSpy({})                       # every read returns empty -> stall -> escalate
    calls = []
    monkeypatch.setattr(inv, "router",
                        lambda i, b, atoms, escalate: (calls.append(("router", escalate)) or
                                                       {"tool": "read", "args": {"path": "/docs/x.md"}}))
    monkeypatch.setattr(inv, "digest",
                        lambda goal, tool, args, observation, escalate: (
                            calls.append(("digest", escalate)) or (Note(tool=tool, args=args), {})))
    inv.investigate(vm, intent, seed=None, oracle=None, max_steps=1)
    assert any(c == ("digest", True) for c in calls)   # empty result escalated the digest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: FAIL — `AttributeError: module 'agent.investigate' has no attribute 'investigate'`.

- [ ] **Step 3: Implement the loop**

```python
# add to agent/investigate.py
_MAX_STEPS = int(os.environ.get("ECOM_INVESTIGATE_MAX_STEPS", "6"))
_ORACLE_K = int(os.environ.get("ECOM_INVESTIGATE_ORACLE_K", "2"))


def _retrieve_atoms(oracle, goal: str) -> list:
    if oracle is None or not goal:
        return []
    try:
        return oracle.retrieve(goal, k=_ORACLE_K)
    except Exception:
        return []


def investigate(vm, intent, seed=None, oracle=None, max_steps: int | None = None) -> "Brief":
    """Bounded read-only ReAct loop → Brief. Never raises: any per-step failure is
    recorded as a lesson and the loop continues (caller falls back to seed facts)."""
    brief = Brief()
    seen: set[str] = set()
    steps = max_steps if max_steps is not None else _MAX_STEPS
    for _ in range(steps):
        goal = intent.objective if not brief.notes else (brief.notes[-1].lesson or intent.objective)
        atoms = _retrieve_atoms(oracle, goal)
        act = router(intent, brief, atoms, escalate=False)
        if act.get("done"):
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
                break
        seen.add(sig)
        note, env_updates = digest(goal, tool, args, observation, escalate=escalate)
        brief.notes.append(note)
        brief.env.update(env_updates)
        if sufficient(intent, brief.env):
            break
    return brief
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -v`
Expected: PASS (all investigator unit tests).

- [ ] **Step 5: Commit**

```bash
git add agent/investigate.py tests/test_investigate.py
git commit -m "feat(investigate): bounded ReAct loop with escalation, budget, sufficiency stop"
```

---

## Task 8: Slim seed gather

**Files:**
- Modify: `agent/orchestrator.py:490` (`gather_prephase_facts` — add `slim` param) and `agent/orchestrator.py:686` (`run_agent` — choose slim vs eager)
- Test: `tests/test_pipeline_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_investigate.py
import os
from agent.orchestrator import gather_prephase_facts
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _vm_with_docs_and_schema():
    fx = {
        fixture_key("Exec", "/bin/sql", ["--help"]): {"stdout": "usage"},
        fixture_key("Read", "/docs/security.md"): {"content": "SECRET POLICY BODY"},
    }
    return MockVMSpy(fx)


def test_slim_gather_drops_policy_bodies_and_samples():
    vm = _vm_with_docs_and_schema()
    facts = gather_prephase_facts(vm, "read /docs/security.md", "", task_id="", slim=True)
    assert facts.policies == {}            # no doc BODIES in the seed
    assert facts.sample_rows == ""         # no sample rows
    assert facts.path_listings == {}       # no listings
    assert facts.catalogue_candidates == ""
    # identity + docs_inventory (paths) are still gathered as the navigation map
    assert facts.gather_status.get("identity") in {"ok", "empty", None} or True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_investigate.py -v`
Expected: FAIL — `TypeError: gather_prephase_facts() got an unexpected keyword argument 'slim'`.

- [ ] **Step 3: Add the `slim` short-circuit**

In `agent/orchestrator.py`, change the signature and skip the heavy fields when `slim`:

```python
def gather_prephase_facts(vm, instruction: str, agents_md_text: str,
                          task_id: str = "", slim: bool = False) -> PrePhaseFacts:
```

Right after `schema = _discover_schema(vm)` / `_mark("schema", schema)` (around line 507), gate the sample-row block:

```python
    if slim:
        samples = ""                       # seed: names/DDL only, no row samples
        _mark("sample_rows", "skipped(slim)")
    else:
        tables = _discover_table_names(vm) if schema else []
        sample_set = _relevant_tables(tables, instruction, deep_read=deep_tables)
        samples = _discover_sample_rows(vm, sample_set) if sample_set else ""
        skipped = [t for t in tables if t not in sample_set]
        if skipped:
            print(f"[prephase] sample_rows: {len(skipped)} table(s) not relevant, not sampled: "
                  + ", ".join(skipped[:10]) + (" …" if len(skipped) > 10 else ""))
        _mark("sample_rows", samples)
```

Then guard the policy-bodies block and the catalogue/listing blocks so they are skipped when `slim` (wrap the `policies` population, the entity-token Search enrichment, the path-listing, and the catalogue-candidate sections in `if not slim:`; in slim mode set `policies = {}`, `path_listings = {}`, `catalogue_candidates = ""` and `_mark("policies", "skipped(slim)")`). `docs_inventory` and `identity` stay (the navigation map). The final `PrePhaseFacts(...)` construction is unchanged.

- [ ] **Step 4: Wire `run_agent` to choose slim vs eager**

At `agent/orchestrator.py:686`, gate by the toggle:

```python
    _slim = os.environ.get("ECOM_INVESTIGATE_ENABLED", "1") != "0"
    facts = gather_prephase_facts(vm, task_text, agents_md_text, task_id=task_id, slim=_slim)
```

(`os` is already imported in `orchestrator.py`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_investigate.py -v`
Expected: PASS.

- [ ] **Step 6: Run the existing orchestrator/pipeline suite to confirm the eager path is intact**

Run: `uv run pytest tests/ -k "prephase or orchestrator or pipeline" -v`
Expected: PASS (eager path unchanged when `slim=False`).

- [ ] **Step 7: Commit**

```bash
git add agent/orchestrator.py tests/test_pipeline_investigate.py
git commit -m "feat(orchestrator): slim seed gather (no doc bodies/samples/listings) behind INVESTIGATE toggle"
```

---

## Task 9: `run_plan` accepts a brief block

**Files:**
- Modify: `agent/reason.py:145-167` (`run_plan`)
- Test: `tests/test_pipeline_investigate.py`

- [ ] **Step 1: Write the failing test** (stub the LLM funnel to capture the user prompt)

```python
# append to tests/test_pipeline_investigate.py
import agent.reason as reason
from agent.ir_models import IntentSpec


def test_run_plan_includes_brief_block(monkeypatch):
    seen = {}
    def fake_raw(system, user, model, cfg, **kw):
        seen["user"] = user
        return ('{"discovery": [], "rowsets": [], "compute": [], '
                '"decision": {"branches": [], "default_label": "ok"}, "ops": [], '
                '"answer": {"ok": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}}, '
                '"custom_extract": []}')
    monkeypatch.setattr(reason, "_call_llm_raw", fake_raw)
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK", outcome_space=["OUTCOME_OK"])
    reason.run_plan(intent, facts=None, learn_ctx=[], prev_error=None,
                    oracle_atoms=[], observed=None, brief_block="INVESTIGATION_BRIEF:\n## RESOLVED_ENV\n- incident_id: INC-7")
    assert "INVESTIGATION_BRIEF" in seen["user"]
    assert "INC-7" in seen["user"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_investigate.py::test_run_plan_includes_brief_block -v`
Expected: FAIL — `TypeError: run_plan() got an unexpected keyword argument 'brief_block'`.

- [ ] **Step 3: Add the optional param**

In `agent/reason.py`, extend the `run_plan` signature and append the block:

```python
def run_plan(intent: IntentSpec, facts, learn_ctx: list[dict], prev_error: str | None,
             token_out: dict | None = None, oracle_atoms: list | None = None,
             observed: list[str] | None = None, brief_block: str | None = None) -> PlanIR:
```

Inside, after the `_facts_block` append and before `if learn_ctx:`, add:

```python
    if brief_block:
        parts.append(brief_block)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_investigate.py::test_run_plan_includes_brief_block -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/reason.py tests/test_pipeline_investigate.py
git commit -m "feat(reason): run_plan accepts an optional investigation brief block"
```

---

## Task 10: Wire `investigate()` into the pipeline

**Files:**
- Modify: `agent/pipeline.py:349-398` (oracle retrieve + INTENT→loop seam + `run_plan` call)
- Test: `tests/test_pipeline_investigate.py`

- [ ] **Step 1: Write the failing test** (full integration over MockVMSpy + stubbed LLM)

```python
# append to tests/test_pipeline_investigate.py
import agent.pipeline as pipeline
import agent.investigate as inv
from agent.investigate import Brief, Note


def test_run_pipeline_builds_brief_then_plan(monkeypatch):
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "1")
    intent = IntentSpec(objective="cite fraud payments", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"])
    captured = {}

    monkeypatch.setattr(pipeline, "load_entries", lambda tid: [])
    monkeypatch.setattr("agent.reason.run_intent",
                        lambda facts, instruction, token_out=None, learn_ctx=None: intent)

    def fake_investigate(vm, intent, seed=None, oracle=None, max_steps=None):
        b = Brief(); b.env["row.record_path"] = "/payments/p_1.json"
        b.notes.append(Note(tool="read", lesson="cite p_1"))
        return b
    monkeypatch.setattr(pipeline, "investigate", fake_investigate)

    def fake_run_plan(intent, facts, learn_ctx, prev_error, token_out=None,
                      oracle_atoms=None, observed=None, brief_block=None):
        captured["brief_block"] = brief_block
        from agent.ir_models import PlanIR
        return PlanIR(answer={"ok": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}})
    monkeypatch.setattr("agent.reason.run_plan", fake_run_plan)
    # interpret/verify pass-through so the loop reaches answer-once
    monkeypatch.setattr(pipeline, "_ilearn", lambda *a, **k: None)

    vm = MockVMSpy({})
    pipeline.run_pipeline(vm, instruction="cite fraud payments", task_id="tX",
                          agents_md_text="", facts=None)
    assert captured["brief_block"] and "p_1.json" in captured["brief_block"]


def test_run_pipeline_disabled_skips_investigate(monkeypatch):
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")
    called = {"investigate": False}
    monkeypatch.setattr(pipeline, "investigate",
                        lambda *a, **k: called.__setitem__("investigate", True) or Brief())
    monkeypatch.setattr(pipeline, "load_entries", lambda tid: [])
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_NONE_CLARIFICATION",
                        outcome_space=["OUTCOME_OK"])
    monkeypatch.setattr("agent.reason.run_intent",
                        lambda facts, instruction, token_out=None, learn_ctx=None: intent)
    # force an immediate empty-plan exit so we only assert the investigate gate
    monkeypatch.setattr("agent.reason.run_plan",
                        lambda *a, **k: (_ for _ in ()).throw(__import__("agent.reason", fromlist=["PlanEmptyError"]).PlanEmptyError("empty")))
    pipeline.run_pipeline(MockVMSpy({}), instruction="x", task_id="tY",
                          agents_md_text="", facts=None)
    assert called["investigate"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_investigate.py -k run_pipeline -v`
Expected: FAIL — `pipeline` has no attribute `investigate` (not imported/wired).

- [ ] **Step 3: Wire the seam in `pipeline.py`**

Add the import near the top of `run_pipeline` (with the other local imports at ~line 335):

```python
    from .investigate import investigate, render_brief
```

Replace the whole-instruction oracle retrieve block (lines ~349-354) so it is skipped when investigating, and build the brief after INTENT (after the `if intent is None:` guard, ~line 369):

```python
    _investigate_on = os.environ.get("ECOM_INVESTIGATE_ENABLED", "1") != "0"

    oracle_atoms: list = []
    _oracle = None
    try:
        from .oracle import KnowledgeOracle
        _oracle = KnowledgeOracle()
        if not _investigate_on:
            oracle_atoms = _oracle.retrieve(instruction)   # legacy whole-instruction dump
    except Exception:
        _oracle = None

    # ... INTENT block unchanged ...

    brief = None                                             # kept in scope for Task 11 distill
    brief_block = None
    if _investigate_on:
        try:
            brief = investigate(vm, intent, seed=facts, oracle=_oracle)
            brief_block = render_brief(brief) or None
        except Exception as e:                               # graceful: fall back to seed facts
            print(f"{CLI_YELLOW}[pipeline] investigate failed, using seed facts: {e}{CLI_CLR}")
            brief = None
            brief_block = None
```

Then thread `brief_block` into the `run_plan` call (line ~396):

```python
            plan = run_plan(intent, facts, learn_ctx, last_error,
                            token_out=tk, oracle_atoms=oracle_atoms,
                            observed=last_observed, brief_block=brief_block); _accum(tk)
```

(`os` and `CLI_YELLOW`/`CLI_CLR` are already imported in `pipeline.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_investigate.py -k run_pipeline -v`
Expected: PASS (both: brief threaded when on; investigate skipped when off).

- [ ] **Step 5: Run the full suite — confirm no regression on the deterministic path**

Run: `uv run pytest tests/ -v`
Expected: PASS. Known pre-existing red `test_t09_replay_matches_known_good` (stale parity fixture) may remain red — confirm it is the ONLY failure and unrelated.

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_investigate.py
git commit -m "feat(pipeline): run investigate after INTENT, thread brief into PLAN, gate by toggle"
```

---

## Task 11: Cross-run lesson distillation on success

**Files:**
- Modify: `agent/pipeline.py:196-221` (`_distill_call` / success-path distill) and the success branch
- Test: `tests/test_pipeline_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pipeline_investigate.py
from agent.investigate import Brief, Note


def test_brief_lessons_text_collects_lessons():
    from agent import pipeline as P
    brief = Brief()
    brief.notes.append(Note(tool="read", lesson="cite the governing doc path"))
    brief.notes.append(Note(tool="exec", lesson="incident id lives in fraud_reports"))
    brief.notes.append(Note(tool="list", lesson=""))     # blank lessons skipped
    txt = P._brief_lessons_text(brief)
    assert "cite the governing doc path" in txt
    assert "incident id lives in fraud_reports" in txt


def test_brief_lessons_text_empty_or_none():
    from agent import pipeline as P
    assert P._brief_lessons_text(Brief()) == ""
    assert P._brief_lessons_text(None) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_investigate.py -k brief_lessons_text -v`
Expected: FAIL — `AttributeError: module 'agent.pipeline' has no attribute '_brief_lessons_text'`.

- [ ] **Step 3: Add the helper and pass lessons into the existing distill note**

In `agent/pipeline.py`, add:

```python
def _brief_lessons_text(brief) -> str:
    """One-line-per-step lessons from an investigation brief, for distillation."""
    if brief is None or not getattr(brief, "notes", None):
        return ""
    return "\n".join(f"- {n.lesson}" for n in brief.notes if n.lesson)
```

Task 10 already keeps `brief` in scope (it initialises `brief = None` before the investigate block and assigns the real `Brief` there). On the success path, the existing call site (`agent/pipeline.py`, in the `if ok:` branch right after `_persist_artifacts`) reads:

```python
            _persist_artifacts(task_id, intent, plan)
            _maybe_distill_and_validate(intent, plan, task_id,
                                        f"OK: {verr or 'verify passed'}")
```

Replace it so the investigation lessons enrich the distill note:

```python
            _persist_artifacts(task_id, intent, plan)
            _note = f"OK: {verr or 'verify passed'}"
            _lessons = _brief_lessons_text(brief)
            if _lessons:
                _note = _note + "\nINVESTIGATION_LESSONS:\n" + _lessons
            _maybe_distill_and_validate(intent, plan, task_id, _note)
```

This reuses the existing `oracle.distill → validate_atom_via_grader → promote` machinery inside `_maybe_distill_and_validate` (gated by `ECOM_ORACLE_DISTILL`/`ECOM_ORACLE_VALIDATE_INLINE`); the brief lessons just enrich the distillation source. No new validation path.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_investigate.py::test_brief_lessons_feed_distill -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_investigate.py
git commit -m "feat(pipeline): distill investigation step-lessons on success (reuses validate/promote)"
```

---

## Task 12: Trace `INVESTIGATE` steps

**Files:**
- Modify: `agent/investigate.py` (`_call_json` already routes through `call_llm_raw`, which mirrors into the trace funnel with `phase="INVESTIGATE"`) and `agent/trace.py` (ensure the reasoning renderer recognises the phase label)
- Test: `tests/test_investigate.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_investigate.py
def test_investigate_steps_appear_in_trace(monkeypatch, tmp_path):
    from agent import trace
    logpath = tmp_path / "t.jsonl"
    logger = trace.TraceLogger(path=logpath, task_id="tT")   # real ctor: (path, task_id)
    trace.set_trace(logger)
    try:
        intent = _intent_with_refs()
        vm = MockVMSpy({fixture_key("Read", "/docs/security.md"): {"content": "cite record_path"}})
        monkeypatch.setattr(inv, "router",
                            lambda i, b, atoms, escalate: {"tool": "read", "args": {"path": "/docs/security.md"}})
        monkeypatch.setattr(inv, "digest",
                            lambda goal, tool, args, observation, escalate: (
                                Note(tool=tool, lesson="x"),
                                {"policy_doc:/docs/security.md": True, "row.record_path": "/p.json"}))
        inv.investigate(vm, intent, seed=None, oracle=None, max_steps=2)
    finally:
        trace.set_trace(None)
    # the Read RPC was mirrored into the per-task trace file via MockVMSpy._emit -> log_vm_auto
    body = logpath.read_text(encoding="utf-8") if logpath.exists() else ""
    assert "Read" in body or "INVESTIGATE" in body
```

> Confirm against `agent/trace.py` how `TraceLogger` flushes records to `self.path` (write-through vs buffered). If buffered, call the real flush/close before reading, or assert on the logger's in-memory record list. The assertion target is only: investigator activity is captured in the per-task trace.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate.py -k trace -v`
Expected: FAIL (no trace records, or helper name mismatch to fix against the real API).

- [ ] **Step 3: Make investigator tool calls trace-visible**

`run_tool` dispatches `vm.<rpc>(...)`. The `MockVMSpy` already calls `trace.log_vm_auto(...)` on each RPC via its `_emit`, and `_call_json` → `call_llm_raw` already mirrors LLM turns with `phase="INVESTIGATE"`. If a real-VM adapter path does NOT auto-emit, wrap `run_tool`'s dispatch with an explicit `trace.log_vm_auto(rpc, args, result)` call (guard with `get_trace() is not None`). In `agent/trace.py`, confirm the reasoning-markdown renderer prints any record whose phase is `INVESTIGATE` (the funnel is generic; only add a label mapping if the renderer enumerates known phases).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate.py -k trace -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/investigate.py agent/trace.py tests/test_investigate.py
git commit -m "feat(trace): investigator steps captured under the INVESTIGATE phase"
```

---

## Task 13: Config docs + env table

**Files:**
- Modify: `CLAUDE.md` (env table + architecture flow), `agent/CLAUDE.md` (execution-flow section)

- [ ] **Step 1: Add the new env vars to the root `CLAUDE.md` table**

Add rows for `ECOM_INVESTIGATE_ENABLED` (default 1; `0` → eager gather + investigator off, exact baseline), `ECOM_INVESTIGATE_MAX_STEPS` (6), `ECOM_INVESTIGATE_ORACLE_K` (2), `ECOM_MODEL_INVESTIGATE` (fast-tier override). Note `INVESTIGATE` is a fast-tier phase in the model-tier resolution paragraph.

- [ ] **Step 2: Update the architecture / execution-flow prose**

In both `CLAUDE.md` and `agent/CLAUDE.md`, document the new step order: `INTENT → INVESTIGATE (read-only ReAct → Brief) → LOOP[PLAN(brief) → lint → interpret → verify]`, and that `INVESTIGATE` is skipped (eager gather restored) when `ECOM_INVESTIGATE_ENABLED=0`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md agent/CLAUDE.md
git commit -m "docs: document the INVESTIGATE phase + its env vars"
```

---

## Task 14: iwiki ingest + lint (MANDATORY per project CLAUDE.md)

**Files:**
- Generated: `docs/wiki/*` (via iwiki skill)

- [ ] **Step 1: Ingest the changed/added sources**

Invoke the `iwiki:iwiki-ingest` skill for `agent/investigate.py`, `agent/pipeline.py`, `agent/orchestrator.py`, and `agent/reason.py` to regenerate the affected `docs/wiki/` pages.

- [ ] **Step 2: Lint the wiki**

Invoke `/iwiki-lint`. Expected: no broken `[[refs]]`, no orphan/stale pages introduced by the new module.

- [ ] **Step 3: Commit**

```bash
git add docs/wiki
git commit -m "docs(wiki): ingest INVESTIGATE phase + investigator module"
```

---

## Task 15: Real grader gate — t38 (the decisive verification)

**Files:** none (runtime verification)

- [ ] **Step 1: Baseline (investigator OFF)**

Run: `ECOM_INVESTIGATE_ENABLED=0 make task TASKS='t38'`
Record: t38 score, the `[plan] user prompt chars=` value (enable `ECOM_LOG_LEVEL=DEBUG`), wall-clock, whether a PLAN call times out.

- [ ] **Step 2: Treatment (investigator ON)**

Run: `ECOM_INVESTIGATE_ENABLED=1 ECOM_LOG_LEVEL=DEBUG make task TASKS='t38'`
Record the same metrics.

- [ ] **Step 3: Assert the success criteria from the spec**

- t38 score improves from **0** to **> 0**;
- the `[plan] user prompt chars=` value drops sharply ON vs OFF;
- no 492 s-class CC timeout on PLAN;
- note total LLM call count + token spend ON vs OFF (more small FAST calls expected — confirm net is acceptable).

If t38 does not improve, do NOT patch prompts (project rule) — inspect the brief in the new trace: is the sufficiency gate stopping too early, or is the router missing the fraud-incident source? Adjust `investigate.py` logic or the learned rule, not `data/prompts/`.

- [ ] **Step 4: Spot-check a passing task did not regress**

Run a known-passing task both ways (e.g. `make task TASKS='t01'`); confirm ON does not drop its score.

- [ ] **Step 5: Commit any trace/report artifacts**

```bash
git add logs/ docs/superpowers/reports/ 2>/dev/null || true
git commit -m "test(t38): grader gate for the INVESTIGATE phase (baseline vs treatment)" || true
```

---

## Notes for the Implementer

- **TDD discipline:** every task is red → green → commit. Do not write implementation before its failing test.
- **Determinism is sacred:** `interpret()` and `verify()` are never touched. If a change wants to reach into them, stop — it is out of scope.
- **Read-only is sacred:** the investigator must never mutate. `is_readonly` is the single gate; all mutations stay in the plan's `ops`.
- **Toggle parity:** `ECOM_INVESTIGATE_ENABLED=0` must reproduce today's behaviour exactly (eager gather, no investigator, whole-instruction PLAN oracle dump). Keep that path untouched.
- **No prompt patching for task fixes** (project rule): task-specific knowledge flows through LEARN / oracle, never `data/prompts/`.
- **Pre-existing red:** `test_t09_replay_matches_known_good` is a known stale-fixture failure, not a regression — confirm it is unrelated before and after.
```
