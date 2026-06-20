---
review:
  plan_hash: e735e71945afc0f8
  spec_hash: 10b83de36b765939
  last_run: 2026-06-20
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - { id: F-001, phase: consistency,   severity: WARNING, section: "Task 5/§5.5", text: "cache_read/cache_creation populated only by the CC provider; Anthropic/OpenAI paths write only input/output", verdict: wontfix, verdict_at: 2026-06-20 }
    - { id: F-002, phase: verifiability,  severity: WARNING, section: "Task 8",      text: "gate-emit test guards the Task 3 helper rather than red-green driving the pipeline edit; edit covered E2E by Task 19", verdict: accepted, verdict_at: 2026-06-20 }
    - { id: F-003, phase: dependencies,   severity: WARNING, section: "Task 7",      text: "loose line citation for the orchestrator wrap; locate by symbol", verdict: fixed, verdict_at: 2026-06-20 }
    - { id: F-004, phase: consistency,    severity: WARNING, section: "Task 12",     text: "collapses _INTENT_KEYS = _PLAN_KEYS+('policies',) without calling it out; behavior preserved", verdict: fixed, verdict_at: 2026-06-20 }
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-20-agent-observability-tooling-design.md
---

# Agent Observability, Explicit Tool Catalog & HTML Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a v2 JSONL trace schema that records every pipeline step (named phases, captured reasoning, full tool-use detail), an explicit validated tool catalog that grounds PLAN's RPC/arg selection, a self-contained HTML report over the v2 traces, and a general code-backed fix for the t38 frozen-clarification root cause.

**Architecture:** Three separable workstreams (B = logging, C = tool catalog, A = architectural fix) share one backbone — JSONL trace schema v2 in `agent/trace.py`. The schema is backward-compatible: existing fields stay, new fields are added, every consumer tolerates missing new keys. The production logging seams (reasoning capture, VM-call logging) move out of the standalone `scripts/trace_t38.py` into the main agent under an env flag; the script becomes a thin caller. The report (`scripts/agent_report.py`) is a pure parser/renderer over v2 traces.

**Tech Stack:** Python 3.12, pydantic v2, pytest, `uv` for runs. Report uses stdlib only (`html`, `json`, `difflib`, inline SVG). Source protos under `bitgn/`. No new third-party deps.

---

## Spec reference

Source spec: `docs/superpowers/specs/2026-06-20-agent-observability-tooling-design.md` (all design-check findings F-001…F-008 resolved). Section numbers below (§4, §5, …) refer to that spec.

## File Structure

**New files**
- `agent/tools.py` — declarative `TOOL_CATALOG`, `validate_step()`, `build_tool_catalog_block()` (Workstream C).
- `agent/reasoning_capture.py` — provider reasoning seams, thread-local sink, `install()` / `pop_capture()` / `enabled()` (Workstream B).
- `scripts/agent_report.py` — self-contained HTML report over v2 traces (§8).
- Tests: `tests/test_tools.py`, `tests/test_reasoning_capture.py`, `tests/test_trace_v2_schema.py`, `tests/test_agent_report.py`.

**Modified files**
- `agent/trace.py` — backbone: global `seq`, thread-local `step_type`, extended `log_llm_call` / `log_vm_call`, new `log_gate`, auto-emit helpers `log_vm_auto` / `log_gate_auto`.
- `agent/llm.py` — `call_llm_json(phase=…)`, thread cache tokens + reasoning into `log_llm_call`, install reasoning capture.
- `agent/oracle.py`, `agent/oracle_rank.py`, `agent/harness.py` — pass `phase=` (DISTILL / RERANK / HARNESS_DISTILL).
- `agent/vm_adapter.py` — trace-aware dispatch.
- `agent/mock_vm_spy.py` — same auto-emit (so MockVM-driven traces log vm_call).
- `agent/interpreter.py` — remove `_trace_vm`; set `step_type=INTERPRET`; tool validation before dispatch; anti-give-up gate.
- `agent/orchestrator.py` — set `step_type=PREPHASE_GATHER`; read `/docs` deep-read bodies into `policies`.
- `agent/pipeline.py` — emit gate records after lint/interpret/verify.
- `agent/reason.py` — `policies` in PLAN facts block; inject tool-catalog block into PLAN system prompt.
- `agent/ir_models.py` — INTENT `OUTCOME_OK`-in-`outcome_space` guard (D6).
- `data/prompts/plan.md` — remove the ad-hoc RPC table (replaced by the generated catalog block).
- `scripts/trace_t38.py` — slim to a thin caller of the production machinery.

## Conventions used across tasks

- `step_type` taxonomy (§4): `PREPHASE_GATHER · DOC_SELECT · ORACLE_RETRIEVE · INTENT · PLAN · LINT · INTERPRET · VERIFY · ILEARN · ANSWER · DISTILL · TASK_RESULT`.
- Phase → step_type map (`agent/trace.py:_step_type_for_phase`): `INTENT→INTENT`, `PLAN→PLAN`, `ILEARN→ILEARN`, `LEARN→ILEARN`, `DOC_SELECT→DOC_SELECT`, `RERANK→ORACLE_RETRIEVE`, `DISTILL→DISTILL`, `HARNESS_DISTILL→DISTILL`; unknown → `phase.upper()`.
- All logging is best-effort and MUST NEVER raise into a run (existing swallow pattern). Tool-catalog validation is the one exception — it is FUNCTIONAL and raises `InterpretError` (§9).

---

# Phase 0 — Backbone: JSONL trace schema v2

### Task 1: `seq` + thread-local `step_type` in `agent/trace.py`

**Files:**
- Modify: `agent/trace.py`
- Test: `tests/test_trace_v2_schema.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_trace_v2_schema.py`:

```python
import json
from pathlib import Path

from agent import trace
from agent.trace import TraceLogger, current_step_type, set_step_type


def _records(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_seq_is_monotonic_and_global(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_header("task", "m")
    t.log_facts({"docs_inventory": "/d.md", "gather_status": {}})
    t.log_answer(1, "msg", "OUTCOME_OK", ["/d.md"])
    t.close()
    seqs = [r["seq"] for r in _records(p)]
    assert seqs == sorted(seqs)
    assert seqs == list(range(len(seqs)))


def test_step_type_thread_local_default_and_set():
    set_step_type("")
    assert current_step_type() == ""
    set_step_type("INTERPRET")
    assert current_step_type() == "INTERPRET"
    set_step_type("")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_trace_v2_schema.py -v`
Expected: FAIL — `seq` key absent / `current_step_type` import error.

- [ ] **Step 3: Implement seq + step_type thread-local**

In `agent/trace.py`, add thread-local helpers next to `set_cycle`/`current_cycle` (after line 27):

```python
def set_step_type(st: str) -> None:
    """Record the active step_type so VM/gate records emitted by the VM layer
    (which has no phase context) are tagged. PREPHASE_GATHER in the orchestrator,
    INTERPRET in the interpreter."""
    _tl.step_type = st


def current_step_type() -> str:
    return getattr(_tl, "step_type", "")
```

In `TraceLogger.__init__` (after `self._seen_sha = set()`), add:

```python
        self._seq = 0
        self._last_llm_seq: int | None = None
```

In `TraceLogger._write`, stamp `seq` before writing (insert at the top of the method, before `record.setdefault("ts", ...)`):

```python
        record.setdefault("seq", self._seq)
        self._seq += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_trace_v2_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Run the existing trace suite (no regressions)**

Run: `uv run pytest tests/test_trace.py -v`
Expected: PASS — existing records now additionally carry `seq`; no assertion in `test_trace.py` forbids extra keys.

- [ ] **Step 6: Commit**

```bash
git add agent/trace.py tests/test_trace_v2_schema.py
git commit -m "feat(trace): global seq + thread-local step_type (schema v2 backbone)"
```

---

### Task 2: Extend `log_llm_call` (reasoning, prev_llm_seq, cache tokens, step_type)

**Files:**
- Modify: `agent/trace.py`
- Test: `tests/test_trace_v2_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trace_v2_schema.py`:

```python
def test_llm_call_v2_fields(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    sysblk = [{"type": "text", "text": "SYS"}]
    t.log_llm_call("INTENT", 0, sysblk, "u1", "r1", None, 10, 5, 100)
    t.log_llm_call(
        "PLAN", 1, sysblk, "u2", "r2", {"ok": 1}, 20, 8, 200,
        reasoning="because X", raw_response_full="<think>because X</think>r2",
        cache_read=900, cache_creation=1200,
    )
    t.close()
    calls = [r for r in _records(p) if r["type"] == "llm_call"]
    a, b = calls
    assert a["step_type"] == "INTENT" and a["prev_llm_seq"] is None
    assert a["reasoning_available"] is False and a["reasoning"] == ""
    assert b["step_type"] == "PLAN" and b["prev_llm_seq"] == a["seq"]
    assert b["reasoning_available"] is True and b["reasoning"] == "because X"
    assert b["raw_response_full"].endswith("r2")
    assert b["cache_read"] == 900 and b["cache_creation"] == 1200


def test_no_llm_call_phase_is_literal_llm(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_llm_call("RERANK", 0, [{"type": "text", "text": "S"}], "u", "r", None, 1, 1, 1)
    t.close()
    rec = next(r for r in _records(p) if r["type"] == "llm_call")
    assert rec["phase"] != "llm"
    assert rec["step_type"] == "ORACLE_RETRIEVE"  # RERANK maps to ORACLE_RETRIEVE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_trace_v2_schema.py::test_llm_call_v2_fields -v`
Expected: FAIL — `step_type`/`reasoning`/`prev_llm_seq` keys absent.

- [ ] **Step 3: Add the phase→step_type map and extend `log_llm_call`**

In `agent/trace.py`, add the map after the truncation caps (after line 33, `_VM_ARG_KEYS = (...)`):

```python
_PHASE_TO_STEP_TYPE = {
    "INTENT": "INTENT", "PLAN": "PLAN", "ILEARN": "ILEARN", "LEARN": "ILEARN",
    "DOC_SELECT": "DOC_SELECT", "RERANK": "ORACLE_RETRIEVE",
    "DISTILL": "DISTILL", "HARNESS_DISTILL": "DISTILL",
}


def _step_type_for_phase(phase: str) -> str:
    p = (phase or "").upper()
    return _PHASE_TO_STEP_TYPE.get(p, p)
```

Replace the whole `log_llm_call` method (lines 90–115) with:

```python
    def log_llm_call(
        self,
        phase: str,
        cycle: int,
        system: "str | list[dict]",
        user_msg: str,
        raw_response: str,
        parsed_output: "dict | None",
        tokens_in: int,
        tokens_out: int,
        duration_ms: int,
        reasoning: str = "",
        reasoning_available: "bool | None" = None,
        raw_response_full: str = "",
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        sha = self._ensure_header_system(system)
        avail = bool(reasoning) if reasoning_available is None else bool(reasoning_available)
        rec = {
            "type": "llm_call",
            "cycle": cycle,
            "phase": phase,
            "step_type": _step_type_for_phase(phase),
            "prev_llm_seq": self._last_llm_seq,
            "system_sha256": sha,
            "user_msg": user_msg,
            "raw_response": raw_response,
            "raw_response_full": raw_response_full or raw_response,
            "reasoning": reasoning or "",
            "reasoning_available": avail,
            "parsed_output": parsed_output,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
            "duration_ms": duration_ms,
            "success": parsed_output is not None or bool(raw_response),
        }
        self._last_llm_seq = self._seq  # seq this record will receive in _write
        self._write(rec)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_trace_v2_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Run the funnel + trace suites**

Run: `uv run pytest tests/test_trace.py tests/test_trace_llm_funnel.py -v`
Expected: PASS — positional callers unaffected (new params have defaults).

- [ ] **Step 6: Commit**

```bash
git add agent/trace.py tests/test_trace_v2_schema.py
git commit -m "feat(trace): v2 llm_call — step_type, reasoning, prev_llm_seq, cache tokens"
```

---

### Task 3: Extend `log_vm_call`, add `log_gate`, add auto-emit helpers

**Files:**
- Modify: `agent/trace.py`
- Test: `tests/test_trace_v2_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trace_v2_schema.py`:

```python
def test_vm_call_v2_fields(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_vm_call(1, "INTERPRET", "Exec",
                  {"path": "/bin/sql", "args": ["SELECT 1"]},
                  "n\n1\n", mutated=False, validation="ok", duration_ms=12)
    t.log_vm_call(2, "INTERPRET", "Exec",
                  {"path": "/bin/sql", "stdin": "SELECT 1"},
                  "", mutated=False, validation="fail(rpc 'Foo' not in catalog)")
    t.close()
    recs = [r for r in _records(p) if r["type"] == "vm_call"]
    ok, bad = recs
    assert ok["step_type"] == "INTERPRET" and ok["phase"] == "INTERPRET"
    assert ok["validation"] == "ok" and ok["has_data"] is True
    assert ok["bytes"] == len("n\n1\n") and ok["duration_ms"] == 12
    assert bad["has_data"] is False and bad["validation"].startswith("fail(")


def test_gate_record(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    t.log_gate(1, "LINT", True, "")
    t.log_gate(2, "VERIFY", False, "I1: unresolved refs")
    t.close()
    g = [r for r in _records(p) if r["type"] == "gate"]
    assert g[0]["step_type"] == "LINT" and g[0]["passed"] is True
    assert g[1]["step_type"] == "VERIFY" and g[1]["passed"] is False
    assert "unresolved" in g[1]["reason"]


def test_log_vm_auto_reads_thread_local(tmp_path):
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    trace.set_cycle(3)
    trace.set_step_type("PREPHASE_GATHER")
    try:
        trace.log_vm_auto("Read", {"path": "/d.md"}, {"content": "hello"})
    finally:
        trace.set_trace(None)
        trace.set_step_type("")
    rec = next(r for r in _records(p) if r["type"] == "vm_call")
    assert rec["step_type"] == "PREPHASE_GATHER" and rec["cycle"] == 3
    assert rec["rpc"] == "Read" and rec["has_data"] is True


def test_log_vm_auto_noop_without_logger():
    trace.set_trace(None)
    trace.log_vm_auto("Read", {"path": "/x"}, {"content": "y"})  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_trace_v2_schema.py -k "vm_call_v2 or gate_record or vm_auto" -v`
Expected: FAIL — new vm_call keys / `log_gate` / `log_vm_auto` absent.

- [ ] **Step 3: Implement `_result_text`, extend `log_vm_call`, add `log_gate`, add auto-helpers**

In `agent/trace.py`, add a result extractor next to `_head` (after line 40):

```python
def _result_text(result) -> str:
    """Best-effort payload text from an RPC result (proto object or dict)."""
    if isinstance(result, str):
        return result
    stdout = getattr(result, "stdout", None)
    if stdout is None and isinstance(result, dict):
        stdout = result.get("stdout")
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    return str(stdout or content or "")
```

Replace the `log_vm_call` method (lines 225–236) with:

```python
    def log_vm_call(self, cycle: int, step_type: str, rpc: str, args: dict,
                    result, mutated: bool = False, *,
                    validation: str = "ok", duration_ms: int = 0) -> None:
        """One VM RPC: which call (filtered args), validation verdict, and result head.

        `step_type` is also mirrored to `phase` for backward-compatible readers.
        `bytes`/`has_data` are computed from the full result text before capping.
        """
        text = _result_text(result)
        self._write({
            "type": "vm_call",
            "cycle": cycle,
            "step_type": step_type,
            "phase": step_type,
            "rpc": rpc,
            "args": {k: v for k, v in (args or {}).items() if k in _VM_ARG_KEYS},
            "validation": validation,
            "bytes": len(text),
            "has_data": bool(text.strip()),
            "result_head": _head(text, _VM_HEAD_CAP),
            "mutated": bool(mutated),
            "duration_ms": duration_ms,
        })

    def log_gate(self, cycle: int, step_type: str, passed: bool, reason: str) -> None:
        """A deterministic gate verdict (LINT | INTERPRET | VERIFY). Supersedes the
        ad-hoc gate_check record."""
        self._write({
            "type": "gate",
            "cycle": cycle,
            "step_type": step_type,
            "passed": bool(passed),
            "reason": reason or "",
        })
```

At the end of the module (after `render_trace`), add the best-effort auto-emit helpers:

```python
# ---------------------------------------------------------------------------
# Best-effort auto-emit — used by the VM layer and the pipeline. Read the active
# logger + thread-local cycle/step_type. NEVER raise into a run (observability).
# ---------------------------------------------------------------------------

def log_vm_auto(rpc: str, args: dict, result, *, mutated: bool = False,
                validation: str = "ok", duration_ms: int = 0) -> None:
    t = get_trace()
    if t is None:
        return
    try:
        t.log_vm_call(current_cycle(), current_step_type() or "INTERPRET", rpc, args,
                      result, mutated=mutated, validation=validation,
                      duration_ms=duration_ms)
    except Exception:
        pass


def log_gate_auto(step_type: str, passed: bool, reason: str) -> None:
    t = get_trace()
    if t is None:
        return
    try:
        t.log_gate(current_cycle(), step_type, passed, reason)
    except Exception:
        pass
```

- [ ] **Step 4: Update the existing `log_vm_call` test for the renamed 2nd param**

In `tests/test_trace.py`, the test `test_log_vm_call_record_filters_args_and_caps` (lines 216–228) passes `"EXEC"` positionally as the old `phase` arg. It still works (now bound to `step_type`), and `r["phase"]` is still emitted (mirrored). Add two assertions after line 228 to cover the new keys:

```python
    assert r["validation"] == "ok"
    assert r["bytes"] >= 0 and isinstance(r["has_data"], bool)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_trace_v2_schema.py tests/test_trace.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/trace.py tests/test_trace_v2_schema.py tests/test_trace.py
git commit -m "feat(trace): v2 vm_call (validation/bytes/has_data) + gate record + auto-emit"
```

---

# Phase 1 — Workstream B: log every step in the main agent

### Task 4: Name all phases (no `llm_call.phase == "llm"`)

**Files:**
- Modify: `agent/llm.py:691-698` (`call_llm_json`)
- Modify: `agent/oracle_rank.py:20`
- Modify: `agent/oracle.py:171-172`
- Modify: `agent/harness.py:188`
- Test: `tests/test_oracle_rank.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_oracle_rank.py`:

```python
def test_llm_rerank_passes_rerank_phase(monkeypatch):
    import agent.oracle_rank as orank

    captured = {}

    def fake_json(system, user_msg, model, max_tokens=1024, token_out=None, phase="llm"):
        captured["phase"] = phase
        return {"keep": []}

    monkeypatch.setattr(orank, "call_llm_json", fake_json)

    class A:
        id = "a1"
        description = "d"

    orank.llm_rerank("task", [A()], 3)
    assert captured["phase"] == "RERANK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_rank.py::test_llm_rerank_passes_rerank_phase -v`
Expected: FAIL — `call_llm_json` has no `phase` param (TypeError) or phase not forwarded.

- [ ] **Step 3: Add `phase` to `call_llm_json` and forward it**

In `agent/llm.py`, replace `call_llm_json` (lines 691–698) with:

```python
def call_llm_json(system, user_msg, model, max_tokens=1024, token_out=None, phase="llm"):
    """Call the LLM and parse a JSON object from the reply. Returns {} on failure."""
    from .json_extract import _extract_json_from_text
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=max_tokens,
                       token_out=token_out, phase=phase)
    if not raw:
        return {}
    obj = _extract_json_from_text(raw)
    return obj if isinstance(obj, dict) else {}
```

- [ ] **Step 4: Name the three call sites**

In `agent/oracle_rank.py` line 20, change:

```python
    out = call_llm_json(_SYS, user, model)
```
to
```python
    out = call_llm_json(_SYS, user, model, phase="RERANK")
```

In `agent/oracle.py` lines 171–172, change the `distill` call to:

```python
        out = call_llm_json(self._DISTILL_SYS, user,
                            _resolve_model_for_phase("distill", os.environ.get("ECOM_MODEL", "")),
                            phase="DISTILL")
```

In `agent/harness.py` line 188, add `phase="HARNESS_DISTILL"` to the `call_llm_json(...)` call (keep the existing positional args; append the keyword).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_oracle_rank.py tests/test_oracle_distill.py tests/test_harness_distill.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/llm.py agent/oracle_rank.py agent/oracle.py agent/harness.py tests/test_oracle_rank.py
git commit -m "feat(trace): name every LLM phase — RERANK/DISTILL/HARNESS_DISTILL (no phase=llm)"
```

---

### Task 5: Thread cache tokens into the `llm_call` record

**Files:**
- Modify: `agent/llm.py:563-619` (`call_llm_raw`)
- Test: `tests/test_trace_llm_funnel.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trace_llm_funnel.py`:

```python
def test_call_llm_raw_threads_cache_tokens(tmp_path, monkeypatch):
    def fake_single(system, user_msg, model, cfg, **kw):
        tok = kw.get("token_out")
        if tok is not None:
            tok["input"] = 5
            tok["output"] = 3
            tok["cache_read"] = 900
            tok["cache_creation"] = 1200
        return "REPLY"

    monkeypatch.setattr(llm, "_call_raw_single_model", fake_single)
    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    set_trace(t)
    try:
        llm.call_llm_raw([{"type": "text", "text": "S"}], "U", "m", {}, phase="PLAN")
    finally:
        set_trace(None)
        t.close()
    call = next(r for r in _records(p) if r["type"] == "llm_call")
    assert call["cache_read"] == 900 and call["cache_creation"] == 1200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_trace_llm_funnel.py::test_call_llm_raw_threads_cache_tokens -v`
Expected: FAIL — `cache_read`/`cache_creation` are 0 (not threaded).

- [ ] **Step 3: Pass cache tokens to `log_llm_call`**

In `agent/llm.py`, inside `call_llm_raw`, replace the `_tr.log_llm_call(...)` block (lines 605–615) with:

```python
            _tr.log_llm_call(
                phase=phase,
                cycle=current_cycle(),
                system=system,
                user_msg=user_msg,
                raw_response=result or "",
                parsed_output=None,
                tokens_in=_tok.get("input", 0),
                tokens_out=_tok.get("output", 0),
                duration_ms=int((time.monotonic() - _t0) * 1000),
                cache_read=_tok.get("cache_read", 0),
                cache_creation=_tok.get("cache_creation", 0),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_trace_llm_funnel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/llm.py tests/test_trace_llm_funnel.py
git commit -m "feat(trace): thread cache_read/cache_creation into llm_call (caching providers)"
```

---

### Task 6: `agent/reasoning_capture.py` + wire into the funnel

**Files:**
- Create: `agent/reasoning_capture.py`
- Modify: `agent/llm.py` (pop capture in `call_llm_raw`; install at import)
- Test: `tests/test_reasoning_capture.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_reasoning_capture.py`:

```python
import agent.reasoning_capture as rc


def test_pop_capture_empty_without_push():
    rc._sink.items = []  # reset thread-local
    assert rc.pop_capture() == {"reasoning": "", "raw_full": ""}


def test_push_then_pop_prefers_item_with_reasoning():
    rc._sink.items = []
    rc._push("", "raw-a")
    rc._push("the reasoning", "raw-b")
    cap = rc.pop_capture()
    assert cap["reasoning"] == "the reasoning"
    assert cap["raw_full"] == "raw-b"
    # pop resets
    assert rc.pop_capture() == {"reasoning": "", "raw_full": ""}


def test_reasoning_from_openai_resp_handles_think_inline():
    class _Resp:
        def model_dump(self):
            return {"choices": [{"message": {"content": "<think>why</think>answer"}}]}

    reasoning, full = rc._reasoning_from_openai_resp(_Resp())
    assert reasoning == "why" and full == "<think>why</think>answer"


def test_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("ECOM_TRACE_REASONING", raising=False)
    assert rc.enabled() is False
    monkeypatch.setenv("ECOM_TRACE_REASONING", "1")
    assert rc.enabled() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reasoning_capture.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create `agent/reasoning_capture.py`**

Port the seams from `scripts/trace_t38.py` into production. Create `agent/reasoning_capture.py`:

```python
"""Production reasoning-capture seams (B2). Active only when ECOM_TRACE_REASONING=1.

Wraps the OpenAI-compatible clients (Ollama/OpenRouter), the Anthropic client, and
the claude-code spawn so each LLM call tees its chain-of-thought into a thread-local
sink. `call_llm_raw` pops the capture and folds it into the `llm_call` record.

Best-effort: any provider/parse failure leaves `reasoning_available=false`.
"""
from __future__ import annotations

import json
import os
import re
import threading

_sink = threading.local()
_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_installed = False


def enabled() -> bool:
    return os.environ.get("ECOM_TRACE_REASONING") == "1"


def _push(reasoning: str, raw_full: str) -> None:
    items = getattr(_sink, "items", None)
    if items is None:
        items = []
        _sink.items = items
    items.append({"reasoning": reasoning or "", "raw_full": raw_full or ""})


def pop_capture() -> dict:
    """Capture for the just-completed logical LLM call; reset the sink.

    A logical call may issue several spawns/creates (retries/fallback); take the
    last one carrying reasoning, else the last one at all, else empty."""
    items = getattr(_sink, "items", [])
    _sink.items = []
    chosen = None
    for it in items:
        if it["reasoning"]:
            chosen = it
    if chosen is None and items:
        chosen = items[-1]
    return chosen or {"reasoning": "", "raw_full": ""}


def _reasoning_from_openai_resp(resp) -> tuple[str, str]:
    reasoning = full = ""
    try:
        data = resp.model_dump()
    except Exception:
        data = None
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            full = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if not reasoning and full:
                m = _THINK_RE.search(full)
                if m:
                    reasoning = m.group(1).strip()
    return (reasoning or ""), (full or "")


def _wrap_openai_client(client) -> None:
    if client is None:
        return
    comp = client.chat.completions
    orig = comp.create

    def wrapped(*a, **k):
        resp = orig(*a, **k)
        try:
            _push(*_reasoning_from_openai_resp(resp))
        except Exception:
            pass
        return resp

    comp.create = wrapped


def _wrap_anthropic_client(client) -> None:
    if client is None:
        return
    orig = client.messages.create

    def wrapped(*a, **k):
        resp = orig(*a, **k)
        try:
            think = "".join(getattr(b, "thinking", "") or ""
                            for b in resp.content if getattr(b, "type", None) == "thinking")
            text = "\n".join(getattr(b, "text", "") or ""
                             for b in resp.content if getattr(b, "type", None) == "text")
            _push(think, text)
        except Exception:
            pass
        return resp

    client.messages.create = wrapped


def _parse_stream_reasoning(lines: list[str]) -> tuple[str, str]:
    parts: list[str] = []
    text_parts: list[str] = []
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            obj = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "assistant":
            for b in (obj.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "thinking":
                    parts.append(b.get("thinking") or "")
                elif b.get("type") == "redacted_thinking":
                    parts.append("[redacted_thinking]")
                elif b.get("type") == "text":
                    text_parts.append(b.get("text") or "")
        elif obj.get("type") == "thinking":
            parts.append(obj.get("thinking") or obj.get("text") or "")
    return "\n".join(p for p in parts if p), "\n".join(t for t in text_parts if t)


def _install_cc_stream_capture() -> None:
    import agent.cc_client as CC
    orig_spawn = CC._spawn_once

    def _spawn(cmd, cwd, env, timeout_s, stdin_data=None):
        cmd = list(cmd)
        if "--output-format" in cmd:
            i = cmd.index("--output-format")
            if i + 1 < len(cmd):
                cmd[i + 1] = "stream-json"
        else:
            cmd += ["--output-format", "stream-json"]
        if "--verbose" not in cmd:  # required with --print --output-format stream-json
            cmd.append("--verbose")
        lines, exit_code, fail = orig_spawn(cmd, cwd, env, timeout_s, stdin_data=stdin_data)
        try:
            _push(*_parse_stream_reasoning(lines))
        except Exception:
            pass
        return lines, exit_code, fail

    CC._spawn_once = _spawn


def install() -> None:
    """Idempotent: wrap every provider seam. Safe to call when disabled (no-op)."""
    global _installed
    if _installed or not enabled():
        return
    _installed = True
    import agent.llm as L
    try:
        _wrap_openai_client(L.ollama_client)
        _wrap_openai_client(L.openrouter_client)
        _wrap_anthropic_client(L.anthropic_client)
        _install_cc_stream_capture()
    except Exception:
        pass
```

- [ ] **Step 4: Wire capture into `call_llm_raw` and install at import**

In `agent/llm.py`, inside `call_llm_raw`, after the fallback block and before `_tr = get_trace()` (around line 602), add:

```python
    reasoning = raw_full = ""
    try:
        from . import reasoning_capture
        if reasoning_capture.enabled():
            cap = reasoning_capture.pop_capture()
            reasoning, raw_full = cap.get("reasoning", ""), cap.get("raw_full", "")
    except Exception:
        pass
```

Then extend the `_tr.log_llm_call(...)` call (the block edited in Task 5) with two more kwargs:

```python
                reasoning=reasoning,
                raw_response_full=raw_full or (result or ""),
```

At the very end of `agent/llm.py` (after the `embed_texts` / `call_llm_json` definitions), add the install hook:

```python
# Reasoning capture (B2): wrap provider seams when ECOM_TRACE_REASONING=1. Done at
# import end so the clients above already exist; install() is idempotent + best-effort.
try:
    from . import reasoning_capture as _rc
    _rc.install()
except Exception:
    pass
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_reasoning_capture.py tests/test_trace_llm_funnel.py tests/test_llm_module.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/reasoning_capture.py agent/llm.py tests/test_reasoning_capture.py
git commit -m "feat(trace): reasoning capture in prod (ECOM_TRACE_REASONING), folded into llm_call"
```

---

### Task 7: VMAdapter + MockVMSpy trace-aware; remove interpreter `_trace_vm`

**Files:**
- Modify: `agent/vm_adapter.py`
- Modify: `agent/mock_vm_spy.py`
- Modify: `agent/interpreter.py:23-35` (remove `_trace_vm`), `interpret()` sets step_type, drops `_trace_vm` calls
- Modify: `agent/orchestrator.py:676-682` (set PREPHASE_GATHER)
- Test: `tests/test_orchestrator.py` (extend), `tests/test_interpreter.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interpreter.py`:

```python
def test_vmadapter_logs_vm_call_with_step_type(tmp_path):
    import json
    from agent import trace
    from agent.trace import TraceLogger
    from agent.vm_adapter import VMAdapter

    class _FakeClient:
        def read(self, req):
            return {"content": "hello world"}

    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    trace.set_cycle(1)
    trace.set_step_type("INTERPRET")
    try:
        VMAdapter(_FakeClient()).read(path="/d.md")
    finally:
        trace.set_trace(None)
        trace.set_step_type("")
        t.close()
    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    vm = next(r for r in recs if r["type"] == "vm_call")
    assert vm["rpc"] == "Read" and vm["step_type"] == "INTERPRET"
    assert vm["has_data"] is True and vm["duration_ms"] >= 0
```

Note: `VMAdapter.read` builds `ReadRequest(**kwargs)`; pass `path=` which is a valid `ReadRequest` field, so the fake client receives the proto request and returns the dict.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py::test_vmadapter_logs_vm_call_with_step_type -v`
Expected: FAIL — no `vm_call` record (VMAdapter does not log).

- [ ] **Step 3: Make VMAdapter trace-aware**

Replace the body of `class VMAdapter` in `agent/vm_adapter.py` (lines 49–82) with a logging dispatch:

```python
class VMAdapter:
    def __init__(self, client):
        self._c = client

    def _call(self, rpc, fn, req_cls, kwargs, *, mutated=False, req_kwargs=None):
        import time

        from . import trace
        t0 = time.monotonic()
        result = fn(req_cls(**(req_kwargs if req_kwargs is not None else kwargs)))
        trace.log_vm_auto(rpc, kwargs, result, mutated=mutated,
                          duration_ms=int((time.monotonic() - t0) * 1000))
        return result

    def read(self, **kwargs):
        return self._call("Read", self._c.read, ReadRequest, kwargs)

    def list(self, **kwargs):
        return self._call("List", self._c.list, ListRequest, kwargs)

    def tree(self, **kwargs):
        return self._call("Tree", self._c.tree, TreeRequest, kwargs,
                          req_kwargs=_normalise_kind(kwargs))

    def find(self, **kwargs):
        return self._call("Find", self._c.find, FindRequest, kwargs,
                          req_kwargs=_normalise_kind(kwargs))

    def search(self, **kwargs):
        return self._call("Search", self._c.search, SearchRequest, kwargs)

    def exec(self, **kwargs):
        path = str(kwargs.get("path", ""))
        mutated = path.startswith("/bin/") and path != "/bin/sql"
        return self._call("Exec", self._c.exec, ExecRequest, kwargs, mutated=mutated)

    def write(self, **kwargs):
        return self._call("Write", self._c.write, WriteRequest, kwargs, mutated=True)

    def delete(self, **kwargs):
        return self._call("Delete", self._c.delete, DeleteRequest, kwargs, mutated=True)

    def stat(self, **kwargs):
        return self._call("Stat", self._c.stat, StatRequest, kwargs)

    def answer(self, **kwargs):
        return self._c.answer(AnswerRequest(**kwargs))
```

- [ ] **Step 4: Make MockVMSpy trace-aware (so MockVM-driven traces log vm_call)**

In `agent/mock_vm_spy.py`, add a helper after `_lookup` (line 30) and call it from every read/exec-style method. Add:

```python
    def _emit(self, rpc: str, kwargs: dict, result, *, mutated: bool = False) -> None:
        from agent import trace
        trace.log_vm_auto(rpc, kwargs, result, mutated=mutated)
```

Then in each method, capture the looked-up result and emit before returning. For example `read`:

```python
    def read(self, path: str = "", **kwargs: Any) -> Any:
        self._record("Read", path=path, **kwargs)
        result = self._lookup("Read", path)
        self._emit("Read", {"path": path, **kwargs}, result)
        return result
```

Apply the same shape to `list` (`List`), `tree` (`Tree`, key `root`), `find` (`Find`, key `root`), `search` (`Search`, key `root`), `stat` (`Stat`), `exec` (`Exec`, pass `{"path": path, "args": args_list, "stdin": stdin}`, `mutated=path.startswith("/bin/") and path != "/bin/sql"`), `write` (`Write`, `mutated=True`), `delete` (`Delete`, `mutated=True`). Leave `answer` unchanged (the interpreter never calls `vm.answer`; the pipeline logs the answer record separately).

- [ ] **Step 5: Remove `_trace_vm` from the interpreter; set step_type=INTERPRET**

In `agent/interpreter.py`:
1. Delete the `_trace_vm` function (lines 23–35).
2. Remove its import of `current_cycle, get_trace` if now only used by `_trace_answer` — `_trace_answer` still needs `get_trace`/`current_cycle`, so keep the import.
3. In `interpret(...)`, at the top of the function body (after `lint_security_first(plan)`, before building `env`), add:

```python
    from .trace import set_step_type
    set_step_type("INTERPRET")
```

4. Delete the two `_trace_vm("INTERPRET", ...)` calls — the one in the discovery loop (line 302) and the one in the ops loop (line 350). The VM layer now logs these.

- [ ] **Step 6: Set PREPHASE_GATHER in the orchestrator**

In `agent/orchestrator.py`, in `run_agent`, locate the call `facts = gather_prephase_facts(...)` (by symbol, not line number) and wrap it (leave the following `_t = get_trace()` / `_t.log_facts(facts)` block untouched):

```python
    from agent.trace import set_step_type
    set_step_type("PREPHASE_GATHER")
    facts = gather_prephase_facts(vm, task_text, agents_md_text, task_id=task_id)
    set_step_type("")
```

(The `_t = get_trace()` / `_t.log_facts(facts)` block stays as-is, immediately after.)

- [ ] **Step 7: Write the orchestrator pre-phase logging test**

Append to `tests/test_orchestrator.py` a focused test that a pre-phase RPC through VMAdapter is tagged PREPHASE_GATHER (model it on the existing orchestrator test fixtures in that file; if it uses a fake client + `gather_prephase_facts` directly, set the thread-local first):

```python
def test_prephase_vm_calls_tagged(tmp_path):
    import json
    from agent import trace
    from agent.trace import TraceLogger

    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    trace.set_step_type("PREPHASE_GATHER")
    try:
        from agent.vm_adapter import VMAdapter

        class _C:
            def stat(self, req):
                return {"kind": "file"}

        VMAdapter(_C()).stat(path="/docs/x.md")
    finally:
        trace.set_trace(None)
        trace.set_step_type("")
        t.close()
    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert any(r["type"] == "vm_call" and r["step_type"] == "PREPHASE_GATHER" for r in recs)
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_interpreter.py tests/test_orchestrator.py tests/test_mock_vm_spy.py tests/test_corpus_replay.py -v`
Expected: PASS. (Replay tests drive MockVMSpy with no trace attached → `log_vm_auto` no-ops.)

- [ ] **Step 9: Commit**

```bash
git add agent/vm_adapter.py agent/mock_vm_spy.py agent/interpreter.py agent/orchestrator.py tests/test_interpreter.py tests/test_orchestrator.py
git commit -m "feat(trace): VM-layer vm_call logging (pre-phase + interpret); drop interpreter _trace_vm"
```

---

### Task 8: Gate records after lint / interpret / verify

**Files:**
- Modify: `agent/pipeline.py:390-486` (the cycle loop)
- Test: `tests/test_pipeline_v2.py` (extend) — covered end-to-end in Task 19's integration test, plus a focused unit here.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_v2.py`:

```python
def test_log_gate_auto_emits_gate(tmp_path):
    import json
    from agent import trace
    from agent.trace import TraceLogger

    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    trace.set_cycle(2)
    try:
        trace.log_gate_auto("LINT", True, "")
        trace.log_gate_auto("VERIFY", False, "I1: unresolved refs")
    finally:
        trace.set_trace(None)
        t.close()
    gates = [json.loads(l) for l in p.read_text().splitlines()
             if l.strip() and json.loads(l)["type"] == "gate"]
    kinds = {(g["step_type"], g["passed"]) for g in gates}
    assert ("LINT", True) in kinds and ("VERIFY", False) in kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_v2.py::test_log_gate_auto_emits_gate -v`
Expected: PASS only if Task 3 landed `log_gate_auto`; this test guards the helper. If it fails, Task 3 is incomplete.

- [ ] **Step 3: Emit gate records in the pipeline loop**

In `agent/pipeline.py`, add the import at the top change (line 17) to also import the gate helper:

```python
from .trace import log_gate_auto, set_cycle
```

In `run_pipeline`, wrap the lint/interpret/verify outcomes:

After the `try: plan = run_plan(...); plan = repair_sql_stdin(plan); lint(plan)` block — on success (the line after the `except` clauses, right after `empty_streak = 0` at line 423) add:

```python
        log_gate_auto("LINT", True, "")
```

In the `except (PlanError, InterpretError) as e:` block (lint failures route here), after setting `last_error` (line 416), add:

```python
            log_gate_auto("LINT", False, last_error)
```

In the interpret `try`/`except` (lines 432–461): after `result = interpret(...)` succeeds (immediately after line 433, before `last_observed = ...`) add:

```python
        log_gate_auto("INTERPRET", True, "")
```

In the `except InterpretError as e:` block (after line 435 `last_error = ...`) add:

```python
            log_gate_auto("INTERPRET", False, last_error)
```

In the `except Exception as e:` real-VM block (after line 446 `last_error = ...`) add:

```python
            log_gate_auto("INTERPRET", False, last_error)
```

After `ok, verr = verify(result, intent)` (line 464) add:

```python
        log_gate_auto("VERIFY", ok, "" if ok else verr)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_pipeline_v2.py tests/test_pipeline_interpreted.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_v2.py
git commit -m "feat(trace): emit gate records after lint/interpret/verify"
```

---

# Phase 2 — Workstream C: explicit tool catalog + validation

### Task 9: `agent/tools.py` — catalog, validation, prompt block

**Files:**
- Create: `agent/tools.py`
- Test: `tests/test_tools.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_tools.py`:

```python
from agent.tools import TOOL_CATALOG, build_tool_catalog_block, validate_step


def test_known_rpc_valid_args_ok():
    assert validate_step("Read", {"path": "/d.md"}) is None
    assert validate_step("Exec", {"path": "/bin/sql", "stdin": "SELECT 1"}) is None
    assert validate_step("Exec", {"path": "/bin/sql", "args": ["SELECT 1"]}) is None


def test_unknown_rpc_rejected():
    err = validate_step("Foo", {"path": "/x"})
    assert err is not None and "not in catalog" in err and "Foo" in err


def test_bad_arg_key_rejected():
    err = validate_step("Read", {"pathh": "/x"})
    assert err is not None and "pathh" in err and "Read" in err


def test_missing_required_arg_rejected():
    err = validate_step("Read", {})
    assert err is not None and "required" in err.lower() and "path" in err


def test_catalog_block_is_markdown_listing_all_rpcs():
    block = build_tool_catalog_block()
    assert "TOOL CATALOG" in block
    for rpc in TOOL_CATALOG:
        assert rpc in block
    # the r012 /bin/sql lesson must be encoded as a structural note
    assert "stdin" in block and "/bin/sql" in block


def test_exec_catalog_documents_sql_stdin_channel():
    exec_entry = TOOL_CATALOG["Exec"]
    note = (exec_entry.get("note") or "").lower()
    assert "stdin" in note and "/bin/sql" in note
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create `agent/tools.py`**

```python
"""Explicit, validated tool catalog (Workstream C).

PLAN emits stringly-typed `rpc`+`args`. Without a contract the model guesses RPC
names, arg keys, and column names (the r012 stdin-key bug class). This catalog is
the single source of truth: it grounds the PLAN prompt (build_tool_catalog_block)
and structurally validates each dispatch (validate_step). Validation is FUNCTIONAL
— a violation raises InterpretError (-> iLEARN), distinct from swallowed logging.
"""
from __future__ import annotations

# Each entry: purpose, required (set), optional (set), mode (read|mutate),
# when_to_use (str), example (dict), and an optional structural `note`.
TOOL_CATALOG: dict[str, dict] = {
    "Read": {
        "purpose": "Read a file (optionally line-numbered range).",
        "required": {"path"},
        "optional": {"number", "start_line", "end_line"},
        "mode": "read",
        "when_to_use": "Fetch a known file's content (policy doc, /proc record).",
        "example": {"rpc": "Read", "args": {"path": "/docs/security.md"}},
    },
    "List": {
        "purpose": "List a directory's entries.",
        "required": {"path"},
        "optional": set(),
        "mode": "read",
        "when_to_use": "Enumerate a dir before reading specific children.",
        "example": {"rpc": "List", "args": {"path": "/proc"}},
    },
    "Tree": {
        "purpose": "Recursive tree under a root (level=0 unlimited).",
        "required": {"root"},
        "optional": {"level", "kind"},
        "mode": "read",
        "when_to_use": "Discover a subtree's shape; prefer Find/Search when targeted.",
        "example": {"rpc": "Tree", "args": {"root": "/docs", "level": 0}},
    },
    "Find": {
        "purpose": "Path search by name under a root.",
        "required": {"root"},
        "optional": {"name", "kind", "limit"},
        "mode": "read",
        "when_to_use": "Locate a file by name when its dir is unknown.",
        "example": {"rpc": "Find", "args": {"root": "/", "name": "security.md"}},
    },
    "Search": {
        "purpose": "Regex content search; returns path+line+text.",
        "required": {"root", "pattern"},
        "optional": {"limit"},
        "mode": "read",
        "when_to_use": "Find docs/records mentioning an entity token.",
        "example": {"rpc": "Search", "args": {"root": "/docs", "pattern": "refund", "limit": 30}},
    },
    "Exec": {
        "purpose": "Run a runtime tool (e.g. /bin/sql, /bin/id).",
        "required": {"path"},
        "optional": {"args", "stdin"},
        "mode": "read",
        "when_to_use": "Query the catalog DB via /bin/sql; read identity via /bin/id.",
        "example": {"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT 1;"}},
        "note": ("/bin/sql reads the query from the real STDIN channel. Put the SQL in "
                 "`stdin` (a string); do NOT inline it anywhere else. `args` is also "
                 "accepted and is moved to stdin by the pre-lint repair. The runner "
                 "returns its usage banner if the SQL never reaches stdin (the r012 bug)."),
    },
    "Write": {
        "purpose": "Write a file (optional compare-and-swap).",
        "required": {"path", "content"},
        "optional": {"if_match_sha256"},
        "mode": "mutate",
        "when_to_use": "Persist a mutation; belongs in `ops`, never `discovery`.",
        "example": {"rpc": "Write", "args": {"path": "/proc/x.json", "content": "{}"}},
    },
    "Delete": {
        "purpose": "Delete a file or directory.",
        "required": {"path"},
        "optional": set(),
        "mode": "mutate",
        "when_to_use": "Remove a record; belongs in `ops`.",
        "example": {"rpc": "Delete", "args": {"path": "/proc/x.json"}},
    },
    "Stat": {
        "purpose": "Metadata for a path (kind, content_type).",
        "required": {"path"},
        "optional": set(),
        "mode": "read",
        "when_to_use": "Check existence/kind before Read.",
        "example": {"rpc": "Stat", "args": {"path": "/docs"}},
    },
}


def validate_step(rpc: str, args: dict | None) -> str | None:
    """Return None when (rpc, args) is structurally valid, else a precise error.

    Checks: rpc in catalog; every arg key in (required | optional); every required
    key present. `bind`/`guard_label`/`outcome_from_exit` live on the Step/GuardedOp
    envelope, not in `args`, so they are never seen here.
    """
    entry = TOOL_CATALOG.get(rpc)
    if entry is None:
        return f"rpc {rpc!r} not in catalog (valid: {', '.join(sorted(TOOL_CATALOG))})"
    allowed = entry["required"] | entry["optional"]
    keys = set((args or {}).keys())
    extra = keys - allowed
    if extra:
        bad = sorted(extra)[0]
        hint = ""
        if rpc == "Exec" and bad == "stdin":
            hint = ""  # stdin IS allowed; never reached
        return (f"arg {bad!r} not accepted by {rpc} "
                f"(accepts: {', '.join(sorted(allowed)) or 'none'})")
    missing = entry["required"] - keys
    if missing:
        return f"{rpc} missing required arg(s): {', '.join(sorted(missing))}"
    return None


def build_tool_catalog_block() -> str:
    """Markdown block injected into the PLAN prompt — the grounded, code-backed RPC
    surface (replaces the ad-hoc table previously inline in plan.md)."""
    lines = ["## TOOL CATALOG (validated — exact rpc names + arg keys)", ""]
    for rpc, e in TOOL_CATALOG.items():
        req = ", ".join(sorted(e["required"])) or "—"
        opt = ", ".join(sorted(e["optional"])) or "—"
        lines.append(f"### {rpc} ({e['mode']})")
        lines.append(f"- purpose: {e['purpose']}")
        lines.append(f"- required args: {req}")
        lines.append(f"- optional args: {opt}")
        lines.append(f"- when: {e['when_to_use']}")
        if e.get("note"):
            lines.append(f"- NOTE: {e['note']}")
        lines.append(f"- example: {e['example']}")
        lines.append("")
    lines.append("Use ONLY these rpc names and arg keys. An unknown rpc or arg key is "
                 "rejected by the interpreter and returned to you to fix.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tools.py tests/test_tools.py
git commit -m "feat(tools): declarative TOOL_CATALOG + validate_step + prompt block"
```

---

### Task 10: Interpreter validates each dispatch (discovery + ops)

**Files:**
- Modify: `agent/interpreter.py` (`interpret` discovery loop + ops loop)
- Test: `tests/test_interpreter.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interpreter.py`. Model the PlanIR construction on the existing interpreter tests in this file (reuse their helper if present). A minimal standalone:

```python
def _intent_ok():
    from agent.ir_models import AnswerShape, IntentSpec
    return IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                      outcome_space=["OUTCOME_OK"], answer_shape=AnswerShape(),
                      success_criteria={}, required_refs={})


def test_interpret_rejects_unknown_rpc():
    import pytest
    from agent.interpreter import InterpretError, interpret
    from agent.ir_models import (AnswerTemplateIR, DecisionTree, PlanIR, Step)
    from agent.mock_vm_spy import MockVMSpy

    plan = PlanIR(
        discovery=[Step(rpc="Frobnicate", args={"path": "/x"})],
        decision=DecisionTree(branches=[], default_label="d"),
        answer={"d": AnswerTemplateIR(message="m", outcome="OUTCOME_OK", refs=[])},
    )
    with pytest.raises(InterpretError) as ei:
        interpret(plan, _intent_ok(), MockVMSpy({}), None)
    assert "not in catalog" in str(ei.value)


def test_interpret_rejects_bad_arg_key():
    import pytest
    from agent.interpreter import InterpretError, interpret
    from agent.ir_models import (AnswerTemplateIR, DecisionTree, PlanIR, Step)
    from agent.mock_vm_spy import MockVMSpy

    plan = PlanIR(
        discovery=[Step(rpc="Read", args={"pathh": "/x"})],
        decision=DecisionTree(branches=[], default_label="d"),
        answer={"d": AnswerTemplateIR(message="m", outcome="OUTCOME_OK", refs=[])},
    )
    with pytest.raises(InterpretError) as ei:
        interpret(plan, _intent_ok(), MockVMSpy({}), None)
    assert "pathh" in str(ei.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -k "rejects_unknown_rpc or rejects_bad_arg_key" -v`
Expected: FAIL — `interpret` currently calls `getattr(vm, "frobnicate")` → AttributeError (not InterpretError) / bad key passed through.

- [ ] **Step 3: Add validation before each dispatch**

In `agent/interpreter.py`, add the import near the top (after `from .ir_models import ...`):

```python
from .tools import validate_step
```

Add a small helper near `_refuse` (after line 183):

```python
def _validate_dispatch(rpc: str, args: dict, mutation_landed: bool):
    """Structural tool-catalog check before any VM dispatch. On violation, log a
    fail vm_call (observability) and raise InterpretError (functional -> iLEARN)."""
    err = validate_step(rpc, args)
    if err is not None:
        from .trace import log_vm_auto
        log_vm_auto(rpc, args or {}, "", validation=f"fail({err})")
        raise _refuse(f"tool validation: {err}", mutation_landed)
```

In the discovery loop, before `result = getattr(vm, step.rpc.lower())(**kwargs)` (line 298), add:

```python
        _validate_dispatch(step.rpc, step.args, mutation_landed)
```

(Validate the declared `step.args` keys — `kwargs` after `_resolve_args` has the same keys.)

In the ops loop, before `result = getattr(vm, op.rpc.lower())(**kwargs)` (line 343), add:

```python
        _validate_dispatch(op.rpc, op.args, mutation_landed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: PASS. Existing interpreter tests use only catalog RPCs (Exec/Read/Write/Delete/List/Stat/Tree/Search), so they continue to pass.

- [ ] **Step 5: Run the replay corpus (guards against false rejections)**

Run: `uv run pytest tests/test_corpus_replay.py -v`
Expected: PASS, OR the only failure is the pre-existing stale t09 parity fixture (`test_t09_replay_matches_known_good`, documented red). If any OTHER replay newly fails with "tool validation", a known-good plan uses an arg key the catalog omits — widen that RPC's `optional` set in `agent/tools.py` and re-run.

- [ ] **Step 6: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(tools): interpreter validates rpc+arg keys before dispatch (kills guess-the-arg class)"
```

---

### Task 11: Inject the catalog block into PLAN; remove the RPC table from `plan.md`

**Files:**
- Modify: `agent/reason.py:139-160` (`run_plan` system prompt)
- Modify: `data/prompts/plan.md` (remove the "## Available RPCs" table)
- Test: `tests/test_reason_prompts.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reason_prompts.py` (this file builds prompts without a live LLM; mirror its existing monkeypatch pattern that captures the `system` passed to the LLM call):

```python
def test_plan_system_includes_tool_catalog(monkeypatch):
    import agent.reason as reason
    from agent.ir_models import AnswerShape, IntentSpec

    captured = {}

    def fake_raw(system, user, model, cfg, **kw):
        captured["system"] = system
        return '{"discovery": [], "decision": {"branches": [], "default_label": "d"}, ' \
               '"answer": {"d": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}}}'

    monkeypatch.setattr(reason, "_call_llm_raw", fake_raw)
    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape=AnswerShape())
    reason.run_plan(intent, None, [], None)
    sys_text = "\n".join(b["text"] for b in captured["system"])
    assert "TOOL CATALOG" in sys_text
    assert "Frobnicate" not in sys_text  # only catalog rpcs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reason_prompts.py::test_plan_system_includes_tool_catalog -v`
Expected: FAIL — catalog block not injected.

- [ ] **Step 3: Inject the catalog block in `run_plan`**

In `agent/reason.py`, add the import (after line 8, `from .ir_models import ...`):

```python
from .tools import build_tool_catalog_block
```

In `run_plan`, replace the system construction (lines 142–143):

```python
    guide = load_prompt("plan") or "# PHASE: PLAN"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
```
with:
```python
    guide = load_prompt("plan") or "# PHASE: PLAN"
    guide = guide + "\n\n" + build_tool_catalog_block()
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
```

- [ ] **Step 4: Remove the ad-hoc RPC table from `plan.md`**

In `data/prompts/plan.md`, delete the section `## Available RPCs (EcomRuntime)` through the `Outcome` enum paragraph (the markdown table + the enum list immediately following it), since the generated catalog now supplies the RPC surface. Keep the `Outcome` enum line by relocating it into the PlanIR `answer.outcome` rules if not already present — verify the enum values still appear elsewhere in `plan.md` (they do, under "answer" field rules). Leave everything from `## Output format — PlanIR` onward untouched.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_reason_prompts.py tests/test_reason.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/reason.py data/prompts/plan.md tests/test_reason_prompts.py
git commit -m "feat(tools): PLAN prompt grounded by generated tool catalog (drop ad-hoc RPC table)"
```

---

# Phase 3 — Workstream A: architectural fix (code-backed, general)

### Task 12: `policies` reach PLAN (facts block)

**Files:**
- Modify: `agent/reason.py:88-115` (`_PLAN_KEYS`, `_facts_block`)
- Test: `tests/test_reason.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reason.py`:

```python
def test_facts_block_plan_tier_includes_policies():
    from agent.reason import _facts_block

    facts = {
        "schema": "CREATE TABLE x(...)",
        "docs_inventory": "/docs/refunds.md",
        "policies": {"/docs/refunds.md": "Refunds allowed within 30 days."},
        "gather_status": {"policies": "ok"},
    }
    block = _facts_block(facts, tier="plan")
    assert "Refunds allowed within 30 days." in block
    assert "/docs/refunds.md" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reason.py::test_facts_block_plan_tier_includes_policies -v`
Expected: FAIL — `_PLAN_KEYS` excludes `policies`; the plan tier omits the body.

- [ ] **Step 3: Add `policies` to the plan tier and render dicts readably**

In `agent/reason.py`, change `_PLAN_KEYS` (line 88) to include `policies`. Note this also collapses the existing `_INTENT_KEYS = _PLAN_KEYS + ("policies",)` — INTENT keeps `policies` exactly once because it is now inside `_PLAN_KEYS` (no behavioral loss for the INTENT tier):

```python
_PLAN_KEYS = ("agents_md_inventory", "schema", "identity", "docs_inventory", "policies")
_INTENT_KEYS = _PLAN_KEYS   # was: _PLAN_KEYS + ("policies",) — policies now in _PLAN_KEYS
```

Replace the rendering loop in `_facts_block` (lines 99–102):

```python
    for key in keys:
        val = facts.get(key) if isinstance(facts, dict) else None
        if not val:
            continue
        if key == "policies" and isinstance(val, dict):
            for path, body in val.items():
                parts.append(f"## POLICY {path}\n{body}")
        else:
            parts.append(f"## {key}\n{val}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reason.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/reason.py tests/test_reason.py
git commit -m "feat(plan): surface policy-doc content to PLAN (CRITERIA block) — t38 root cause"
```

---

### Task 13: `deep_read` of a `/docs` file reads its body into `policies`

**Files:**
- Modify: `agent/orchestrator.py:639-654` (literal-path listings loop)
- Test: `tests/test_orchestrator.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orchestrator.py`. Use the file's existing fake-VM helper if present; otherwise a minimal stub:

```python
def test_deep_read_docs_file_reads_body_into_policies(monkeypatch, tmp_path):
    import agent.orchestrator as orch

    # deep_read hint resolves to a /docs file literal
    monkeypatch.setattr(orch, "load_prephase_deep_read", lambda tid: ["/docs/policy.md"])

    class _VM:
        def exec(self, **k):
            return {"stdout": ""}

        def list(self, **k):
            return {"entries": []}

        def stat(self, **k):
            return {"kind": "file"} if k.get("path") == "/docs/policy.md" else {"kind": ""}

        def read(self, **k):
            if k.get("path") == "/docs/policy.md":
                return {"content": "DEEP POLICY BODY"}
            return {"content": ""}

        def tree(self, **k):
            return {"root": None}

        def search(self, **k):
            return {"matches": []}

    facts = orch.gather_prephase_facts(_VM(), "do the thing", "", task_id="t38")
    assert facts.policies.get("/docs/policy.md") == "DEEP POLICY BODY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py::test_deep_read_docs_file_reads_body_into_policies -v`
Expected: FAIL — the file currently records `path_listings["/docs/policy.md"] = "file ..."` (existence only); `policies` lacks the body.

- [ ] **Step 3: Read `/docs` deep-read file bodies into `policies`**

In `agent/orchestrator.py`, in the literal-path listings loop (lines 642–653), change the `elif kind == "file":` branch to read `/docs` deep-read bodies into `policies`:

```python
        elif kind == "file":
            # A /docs deep-read literal is a criteria source — read its BODY into
            # policies (not just existence), so PLAN sees the rule. General: scoped
            # to /docs files named by a learned prephase_deep_read hint or instruction.
            if lit.startswith("/docs") and lit in deep_paths and lit not in policies:
                body = _extract_text(vm.read(path=lit), "content")
                if body:
                    policies[lit] = body[:_DOC_CONTENT_CAP]
            path_listings[lit] = f"file {lit}"           # existence; body recorded above
```

Note: `policies` is populated earlier in the function (line 544+) and is in scope here. `_mark("policies", policies)` already ran; re-mark after this loop is unnecessary because a deep-read body only adds. (If `policies` was empty before and only filled here, add `_mark("policies", policies)` after the loop to keep `gather_status` truthful.)

Add the re-mark after the listings loop, before `_mark("path_listings", path_listings)`:

```python
    _mark("policies", policies)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): deep-read /docs body into policies (not just existence) — t38 root cause"
```

---

### Task 14: Anti-give-up gate in the interpreter

**Files:**
- Modify: `agent/interpreter.py` (`interpret`, after outcome is chosen)
- Test: `tests/test_interpreter.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interpreter.py`:

```python
def test_anti_give_up_gate_rejects_clarify_only_when_ok_possible():
    import pytest
    from agent.interpreter import InterpretError, interpret
    from agent.ir_models import (AnswerShape, AnswerTemplateIR, DecisionTree,
                                  IntentSpec, PlanIR)
    from agent.mock_vm_spy import MockVMSpy

    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
                        answer_shape=AnswerShape(), success_criteria={}, required_refs={})
    # clarify-only plan: no discovery, no rowsets, default label -> CLARIFICATION
    plan = PlanIR(
        discovery=[], rowsets=[],
        decision=DecisionTree(branches=[], default_label="clar"),
        answer={"clar": AnswerTemplateIR(message="please clarify",
                                         outcome="OUTCOME_NONE_CLARIFICATION", refs=[])},
    )
    with pytest.raises(InterpretError) as ei:
        interpret(plan, intent, MockVMSpy({}), None)
    assert "grounded discovery" in str(ei.value)


def test_anti_give_up_gate_allows_clarify_when_ok_not_in_space():
    from agent.interpreter import interpret
    from agent.ir_models import (AnswerShape, AnswerTemplateIR, DecisionTree,
                                  IntentSpec, PlanIR)
    from agent.mock_vm_spy import MockVMSpy

    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_NONE_CLARIFICATION",
                        outcome_space=["OUTCOME_NONE_CLARIFICATION"],
                        answer_shape=AnswerShape(), success_criteria={}, required_refs={},
                        constraints=[])
    plan = PlanIR(
        discovery=[], rowsets=[],
        decision=DecisionTree(branches=[], default_label="clar"),
        answer={"clar": AnswerTemplateIR(message="please clarify",
                                         outcome="OUTCOME_NONE_CLARIFICATION", refs=[])},
    )
    res = interpret(plan, intent, MockVMSpy({}), None)
    assert res.captured.outcome == "OUTCOME_NONE_CLARIFICATION"
```

(The second test constructs an OK-less `outcome_space` directly via `IntentSpec(...)`. After Task 15 adds the INTENT guard, this is still valid because the guard exempts a security deny OR it must be constructed with the guard satisfied — see Task 15's note; if Task 15 lands first, give this intent a security constraint. Order: implement Task 14 before Task 15, and in Task 15 update this fixture to add a security constraint.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -k anti_give_up -v`
Expected: FAIL — the clarify-only plan is accepted (no gate).

- [ ] **Step 3: Add the gate after the chosen outcome is known**

In `agent/interpreter.py`, in `interpret`, after `outcome = exit_outcome or tmpl.outcome` (line 364) and before `message = _fill_slots(...)`, add:

```python
    # Anti-give-up gate (A3): if OK is reachable and the plan did no grounding
    # (empty discovery AND rowsets) yet chose to clarify, reject -> iLEARN. General
    # (no task-specific prose): attempt grounded discovery before clarifying.
    if (outcome == "OUTCOME_NONE_CLARIFICATION"
            and "OUTCOME_OK" in (intent.outcome_space or [])
            and not plan.discovery and not plan.rowsets):
        raise _refuse("attempt grounded discovery before clarifying "
                      "(clarify-only plan rejected while OUTCOME_OK is reachable)",
                      mutation_landed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py -k anti_give_up -v`
Expected: PASS.

- [ ] **Step 5: Run the full interpreter + pipeline suites**

Run: `uv run pytest tests/test_interpreter.py tests/test_pipeline_interpreted.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(interpreter): anti-give-up gate — reject clarify-only plan when OK reachable"
```

---

### Task 15: INTENT `OUTCOME_OK`-in-`outcome_space` guard (D6)

**Files:**
- Modify: `agent/ir_models.py` (`IntentSpec` validator)
- Modify: `tests/test_interpreter.py` (fix the Task-14 fixture per its note)
- Test: `tests/test_ir_models.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ir_models.py`:

```python
def test_intent_requires_ok_in_outcome_space():
    import pytest
    from agent.ir_models import AnswerShape, IntentSpec

    with pytest.raises(Exception):
        IntentSpec(objective="o", desired_outcome="OUTCOME_NONE_CLARIFICATION",
                   outcome_space=["OUTCOME_NONE_CLARIFICATION"],
                   answer_shape=AnswerShape())


def test_intent_ok_less_allowed_with_security_deny():
    from agent.ir_models import (AnswerShape, Constraint, IntentSpec, PredExpr)

    intent = IntentSpec(
        objective="o", desired_outcome="OUTCOME_DENIED_SECURITY",
        outcome_space=["OUTCOME_DENIED_SECURITY"],
        answer_shape=AnswerShape(),
        constraints=[Constraint(anchor="a", rule="r", security=True,
                                deny_when=PredExpr(op="nonempty", lhs="$x"))],
    )
    assert "OUTCOME_OK" not in intent.outcome_space  # accepted: security deny present


def test_intent_with_ok_is_fine():
    from agent.ir_models import AnswerShape, IntentSpec

    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
                        answer_shape=AnswerShape())
    assert "OUTCOME_OK" in intent.outcome_space
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ir_models.py -k intent -v`
Expected: FAIL — first test does not raise (no guard).

- [ ] **Step 3: Add the validator to `IntentSpec`**

In `agent/ir_models.py`, add an `after` validator to `IntentSpec` (after the existing `_coerce_success_criteria` before-validator, ~line 99):

```python
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
```

- [ ] **Step 4: Fix the Task-14 second fixture**

In `tests/test_interpreter.py`, the `test_anti_give_up_gate_allows_clarify_when_ok_not_in_space` intent now needs a security constraint to construct (per Task 14's note). Update its `IntentSpec(...)` to add:

```python
        constraints=[Constraint(anchor="a", rule="r", security=True,
                                deny_when=PredExpr(op="nonempty", lhs="$x"))],
```

and add the imports `Constraint, PredExpr` to that test's `from agent.ir_models import ...` line.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_ir_models.py tests/test_interpreter.py -v`
Expected: PASS.

- [ ] **Step 6: Verify no persisted intent.json regression in distill paths**

Run: `uv run pytest tests/test_pipeline_distill.py tests/test_oracle_distill.py -v`
Expected: PASS — `distill_from_grader` / `learn_from_grader` wrap `IntentSpec.model_validate_json` in a try/except, so a legacy OK-less persisted intent degrades to a skipped distill rather than crashing.

- [ ] **Step 7: Commit**

```bash
git add agent/ir_models.py tests/test_ir_models.py tests/test_interpreter.py
git commit -m "feat(intent): require OUTCOME_OK in outcome_space unless security-deny (D6)"
```

---

# Phase 4 — Report: `scripts/agent_report.py`

### Task 16: Report — v2 parser + run-overview rendering

**Files:**
- Create: `scripts/agent_report.py`
- Test: `tests/test_agent_report.py` (create)

- [ ] **Step 1: Invoke the html-report skill for the rendering contract**

Run the `html-report` skill (single self-contained file, both themes via CSS custom properties, no external `src=`/`href=`, halts on unreadable/contradictory source). Follow its structure for `_HEAD`/CSS.

- [ ] **Step 2: Write the failing test (parser + overview)**

Create `tests/test_agent_report.py`:

```python
import json
from pathlib import Path

import scripts.agent_report as R


def _write_trace(p: Path, records: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _v2_records() -> list[dict]:
    return [
        {"type": "meta", "seq": 0, "task_id": "t38", "model": "m"},
        {"type": "header", "seq": 1, "task_id": "t38", "model": "m", "task_text": "do x"},
        {"type": "facts", "seq": 2, "task_id": "t38",
         "docs_inventory": "/docs/p.md", "gather_status": {"policies": "ok"}},
        {"type": "llm_call", "seq": 3, "cycle": 0, "phase": "INTENT",
         "step_type": "INTENT", "user_msg": "PRE-PHASE FACTS:\nA B C\n\nINSTRUCTION:\nx",
         "raw_response": "{}", "reasoning": "thinking hard", "reasoning_available": True,
         "tokens_in": 10, "tokens_out": 5, "cache_read": 100, "cache_creation": 0,
         "duration_ms": 50, "success": True},
        {"type": "llm_call", "seq": 4, "cycle": 1, "phase": "PLAN",
         "step_type": "PLAN", "user_msg": "PRE-PHASE FACTS:\nA B C\n\nINTENT_SPEC:\n{}",
         "raw_response": "{}", "reasoning": "", "reasoning_available": False,
         "tokens_in": 20, "tokens_out": 8, "cache_read": 900, "cache_creation": 1200,
         "duration_ms": 80, "success": True},
        {"type": "vm_call", "seq": 5, "cycle": 1, "step_type": "INTERPRET",
         "rpc": "Exec", "args": {"path": "/bin/sql"}, "validation": "ok",
         "bytes": 4, "has_data": True, "mutated": False, "duration_ms": 12,
         "result_head": "n\n1"},
        {"type": "vm_call", "seq": 6, "cycle": 1, "step_type": "INTERPRET",
         "rpc": "Read", "args": {"path": "/docs/p.md"}, "validation": "fail(arg 'x')",
         "bytes": 0, "has_data": False, "mutated": False, "duration_ms": 1,
         "result_head": ""},
        {"type": "gate", "seq": 7, "cycle": 1, "step_type": "VERIFY",
         "passed": True, "reason": ""},
        {"type": "answer", "seq": 8, "cycle": 1, "message": "1",
         "outcome": "OUTCOME_OK", "refs": ["/docs/p.md"]},
        {"type": "task_result", "seq": 9, "outcome": "OUTCOME_OK", "score": 1.0,
         "cycles_used": 1, "total_tokens_in": 30, "total_tokens_out": 13,
         "elapsed_ms": 130, "score_detail": []},
    ]


def test_parse_task_trace_summary(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    task = R.parse_task_trace(p)
    assert task.task_id == "t38"
    assert task.outcome == "OUTCOME_OK" and task.score == 1.0 and task.cycles == 1
    # tokens incl. cache (read + creation) summed across llm_calls
    assert task.tokens_in == 30
    assert task.cache_read == 1000 and task.cache_creation == 1200
    # tool usage: 2 rpc dispatches, 1 empty, 1 validation failure
    assert task.rpc_counts["Exec"] == 1 and task.rpc_counts["Read"] == 1
    assert task.empty_results == 1 and task.validation_failures == 1


def test_facts_overlap_ratio_between_intent_and_plan(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    task = R.parse_task_trace(p)
    # identical "PRE-PHASE FACTS:\nA B C" block -> ratio 1.0
    assert task.facts_overlap == 1.0


def test_render_overview_no_external_resources(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    html_doc = R.render_report([R.parse_task_trace(p)])
    assert "src=" not in html_doc and "href=" not in html_doc
    assert "t38" in html_doc and "OUTCOME_OK" in html_doc
    # both themes present (light :root + dark override custom props)
    assert "--bg" in html_doc and "prefers-color-scheme: dark" in html_doc
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_report.py -k "summary or overlap or overview" -v`
Expected: FAIL — module does not exist.

- [ ] **Step 4: Create `scripts/agent_report.py` (parser + overview)**

```python
#!/usr/bin/env python3
"""Self-contained HTML report over v2 JSONL traces (logs/<run>/*.jsonl).

One file, both themes (CSS custom properties + prefers-color-scheme), no external
resources. Run-overview grid + per-task drill-down (step timeline, cycle SVG, tool
usage, reasoning panels, prompt-redundancy metric). HALTS on an unreadable source —
never fabricates data.

Usage:
    uv run python scripts/agent_report.py --logs logs/<run_dir> --out docs/reports/agent-report.html
"""
from __future__ import annotations

import argparse
import difflib
import html as _html
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LlmCall:
    seq: int
    cycle: int
    phase: str
    step_type: str
    user_msg: str
    raw_response: str
    reasoning: str
    reasoning_available: bool
    tokens_in: int
    tokens_out: int
    cache_read: int
    cache_creation: int
    duration_ms: int


@dataclass
class VmCall:
    seq: int
    cycle: int
    step_type: str
    rpc: str
    args: dict
    validation: str
    bytes: int
    has_data: bool
    mutated: bool
    duration_ms: int
    result_head: str


@dataclass
class Gate:
    seq: int
    cycle: int
    step_type: str
    passed: bool
    reason: str


@dataclass
class TaskTrace:
    task_id: str
    model: str
    instruction: str
    outcome: str
    score: "float | None"
    cycles: "int | None"
    elapsed_ms: int
    score_detail: list
    llm_calls: list = field(default_factory=list)
    vm_calls: list = field(default_factory=list)
    gates: list = field(default_factory=list)
    answer: "dict | None" = None
    # derived
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    rpc_counts: dict = field(default_factory=dict)
    empty_results: int = 0
    validation_failures: int = 0
    facts_overlap: "float | None" = None


_FACTS_MARKER = "PRE-PHASE FACTS:"
_FACTS_END = ("\n\nINSTRUCTION:", "\n\nINTENT_SPEC:", "\n\nLEARNED_RULES",
              "\n\nOBSERVED_RPC_OUTPUTS", "\n\nPREVIOUS_ERROR")


def _facts_block(user_msg: str) -> str:
    """Extract the shared PRE-PHASE FACTS block from an INTENT/PLAN user_msg."""
    i = user_msg.find(_FACTS_MARKER)
    if i < 0:
        return ""
    rest = user_msg[i:]
    end = len(rest)
    for marker in _FACTS_END:
        j = rest.find(marker)
        if 0 <= j < end:
            end = j
    return rest[:end]


def parse_task_trace(path: Path) -> TaskTrace:
    """Parse one v2 trace file. HALTS (raises) on an unreadable file (§9)."""
    text = Path(path).read_text(encoding="utf-8")
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))  # malformed line -> raises -> halt

    header = next((r for r in records if r.get("type") == "header"), {})
    tr = next((r for r in reversed(records) if r.get("type") == "task_result"), None)
    ans = next((r for r in reversed(records) if r.get("type") == "answer"), None)

    task = TaskTrace(
        task_id=header.get("task_id") or path.stem,
        model=header.get("model", ""),
        instruction=header.get("task_text", ""),
        outcome=(tr or ans or {}).get("outcome", ""),
        score=(tr or {}).get("score"),
        cycles=(tr or {}).get("cycles_used") or (ans or {}).get("cycle"),
        elapsed_ms=(tr or {}).get("elapsed_ms", 0),
        score_detail=list((tr or {}).get("score_detail") or []),
        answer=ans,
    )

    for r in records:
        t = r.get("type")
        if t == "llm_call":
            task.llm_calls.append(LlmCall(
                seq=r.get("seq", 0), cycle=r.get("cycle", 0), phase=r.get("phase", ""),
                step_type=r.get("step_type", ""), user_msg=r.get("user_msg", ""),
                raw_response=r.get("raw_response", ""), reasoning=r.get("reasoning", ""),
                reasoning_available=bool(r.get("reasoning_available")),
                tokens_in=r.get("tokens_in", 0), tokens_out=r.get("tokens_out", 0),
                cache_read=r.get("cache_read", 0), cache_creation=r.get("cache_creation", 0),
                duration_ms=r.get("duration_ms", 0)))
        elif t == "vm_call":
            task.vm_calls.append(VmCall(
                seq=r.get("seq", 0), cycle=r.get("cycle", 0),
                step_type=r.get("step_type", ""), rpc=r.get("rpc", ""),
                args=r.get("args", {}), validation=r.get("validation", "ok"),
                bytes=r.get("bytes", 0), has_data=bool(r.get("has_data")),
                mutated=bool(r.get("mutated")), duration_ms=r.get("duration_ms", 0),
                result_head=r.get("result_head", "")))
        elif t == "gate":
            task.gates.append(Gate(seq=r.get("seq", 0), cycle=r.get("cycle", 0),
                                   step_type=r.get("step_type", ""),
                                   passed=bool(r.get("passed")), reason=r.get("reason", "")))

    # derive token + tool-usage aggregates
    for c in task.llm_calls:
        task.tokens_in += c.tokens_in
        task.tokens_out += c.tokens_out
        task.cache_read += c.cache_read
        task.cache_creation += c.cache_creation
    for v in task.vm_calls:
        task.rpc_counts[v.rpc] = task.rpc_counts.get(v.rpc, 0) + 1
        if not v.has_data:
            task.empty_results += 1
        if not v.validation.startswith("ok"):
            task.validation_failures += 1

    # prompt-redundancy: facts-overlap ratio between INTENT and PLAN user_msg
    intent = next((c for c in task.llm_calls if c.step_type == "INTENT"), None)
    plan = next((c for c in task.llm_calls if c.step_type == "PLAN"), None)
    if intent and plan:
        a, b = _facts_block(intent.user_msg), _facts_block(plan.user_msg)
        if a or b:
            task.facts_overlap = round(difflib.SequenceMatcher(None, a, b).ratio(), 3)

    return task


def discover_traces(logs_dir: Path) -> list[Path]:
    return sorted(Path(logs_dir).glob("t*.jsonl"))


# ── HTML rendering (overview; per-task drill-down added in Task 17) ──────────

_CSS = """:root{--bg:#fff;--fg:#222;--muted:#777;--line:#ccc;--ok:#2e7d32;
--warn:#f9a825;--bad:#c62828;--panel:#fafafa;--accent:#1565c0}
@media (prefers-color-scheme: dark){:root{--bg:#15171a;--fg:#e6e6e6;--muted:#9aa0a6;
--line:#39414a;--ok:#66bb6a;--warn:#ffca28;--bad:#ef5350;--panel:#1e2227;--accent:#64b5f6}}
body{font:13px/1.45 system-ui,sans-serif;margin:24px;background:var(--bg);color:var(--fg)}
h1,h2,h3{border-bottom:1px solid var(--line);padding-bottom:4px}
table{border-collapse:collapse;margin:8px 0}
th,td{border:1px solid var(--line);padding:3px 7px;text-align:center;white-space:nowrap}
th.l,td.l{text-align:left}
th{background:var(--panel)}
details{margin:6px 0;border:1px solid var(--line);border-radius:4px;padding:4px 8px;background:var(--panel)}
summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;word-break:break-word;margin:4px 0}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.muted{color:var(--muted)}
.timeline span{display:inline-block;margin:1px;padding:1px 5px;border-radius:3px;
background:var(--panel);border:1px solid var(--line);font-size:11px}"""

_HEAD = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
         "<title>Agent Report</title><style>" + _CSS + "</style></head><body>"
         "<h1>Agent Observability Report</h1>")
_FOOT = "</body></html>"


def _esc(s) -> str:
    return _html.escape(str(s))


def _overview_table(tasks: list[TaskTrace]) -> str:
    head = ("<tr><th class='l'>task</th><th>outcome</th><th>score</th><th>cycles</th>"
            "<th>tok in/out</th><th>cache r/c</th><th>time</th>"
            "<th>facts overlap</th></tr>")
    rows = []
    for t in tasks:
        cls = "ok" if t.outcome == "OUTCOME_OK" else "warn"
        score = "" if t.score is None else f"{t.score:.2f}"
        overlap = "" if t.facts_overlap is None else f"{t.facts_overlap:.2f}"
        rows.append(
            f"<tr><td class='l'><a href='#{_esc(t.task_id)}'>{_esc(t.task_id)}</a></td>"
            f"<td class='{cls}'>{_esc(t.outcome)}</td><td>{score}</td>"
            f"<td>{_esc(t.cycles or '')}</td>"
            f"<td>{t.tokens_in}/{t.tokens_out}</td>"
            f"<td>{t.cache_read}/{t.cache_creation}</td>"
            f"<td>{t.elapsed_ms}ms</td><td>{overlap}</td></tr>")
    return "<h2>Run Overview</h2><table>" + head + "".join(rows) + "</table>"


def _error_summary(tasks: list[TaskTrace]) -> str:
    agg: dict = {}
    for t in tasks:
        for d in t.score_detail:
            agg[d] = agg.get(d, 0) + 1
    if not agg:
        return "<h3>Error summary</h3><p class='muted'>no grader failures recorded</p>"
    rows = "".join(f"<tr><td class='l'>{_esc(k)}</td><td>{v}</td></tr>"
                   for k, v in sorted(agg.items(), key=lambda kv: -kv[1]))
    return f"<h3>Error summary</h3><table><tr><th class='l'>detail</th><th>n</th></tr>{rows}</table>"


def _tool_summary(tasks: list[TaskTrace]) -> str:
    counts: dict = {}
    empty: dict = {}
    fails: dict = {}
    for t in tasks:
        for v in t.vm_calls:
            counts[v.rpc] = counts.get(v.rpc, 0) + 1
            if not v.has_data:
                empty[v.rpc] = empty.get(v.rpc, 0) + 1
            if not v.validation.startswith("ok"):
                fails[v.rpc] = fails.get(v.rpc, 0) + 1
    rows = "".join(
        f"<tr><td class='l'>{_esc(rpc)}</td><td>{n}</td>"
        f"<td>{empty.get(rpc, 0)}</td><td>{fails.get(rpc, 0)}</td></tr>"
        for rpc, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    if not rows:
        rows = "<tr><td colspan='4' class='muted'>no tool calls</td></tr>"
    return ("<h3>Tool usage</h3><table>"
            "<tr><th class='l'>rpc</th><th>count</th><th>empty</th><th>val-fail</th></tr>"
            + rows + "</table>")


def render_report(tasks: list[TaskTrace]) -> str:
    tasks = sorted(tasks, key=lambda t: t.task_id)
    parts = [_HEAD, _overview_table(tasks), _error_summary(tasks), _tool_summary(tasks)]
    parts += [render_task_section(t) for t in tasks]  # defined in Task 17
    parts.append(_FOOT)
    return "\n".join(parts)


def render_task_section(task: TaskTrace) -> str:  # replaced in Task 17
    return f"<h2 id='{_esc(task.task_id)}'>{_esc(task.task_id)}</h2>"


def main() -> int:
    ap = argparse.ArgumentParser(description="HTML report over v2 JSONL traces.")
    ap.add_argument("--logs", required=True, help="run dir holding t*.jsonl traces")
    ap.add_argument("--out", required=True, help="output HTML path")
    args = ap.parse_args()

    paths = discover_traces(Path(args.logs))
    if not paths:
        print(f"no t*.jsonl traces under {args.logs}", file=sys.stderr)
        return 1
    tasks = [parse_task_trace(p) for p in paths]  # raises -> halt on bad source
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(tasks), encoding="utf-8")
    print(f"wrote {out}  ({len(tasks)} tasks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_report.py -k "summary or overlap or overview" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/agent_report.py tests/test_agent_report.py
git commit -m "feat(report): v2 trace parser + run-overview (grid, errors, tool usage, redundancy)"
```

---

### Task 17: Report — per-task drill-down (timeline, cycle SVG, tool table, reasoning panels)

**Files:**
- Modify: `scripts/agent_report.py` (`render_task_section` + helpers)
- Test: `tests/test_agent_report.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_report.py`:

```python
def test_per_task_section_has_timeline_svg_reasoning(tmp_path):
    p = tmp_path / "t38.jsonl"
    _write_trace(p, _v2_records())
    html_doc = R.render_report([R.parse_task_trace(p)])
    # anchored section
    assert "id='t38'" in html_doc
    # step timeline mentions step types
    assert "INTENT" in html_doc and "PLAN" in html_doc and "INTERPRET" in html_doc
    # cycle diagram rendered as inline SVG (no external image)
    assert "<svg" in html_doc and "verify" in html_doc.lower()
    # reasoning panel for the INTENT call (reasoning_available True)
    assert "thinking hard" in html_doc
    # per-task tool-usage table shows validation failure
    assert "fail(" in html_doc or "val-fail" in html_doc
    # still self-contained
    assert "src=" not in html_doc and "href='http" not in html_doc


def test_cycle_svg_is_inline_and_static():
    svg = R._cycle_svg()
    assert svg.startswith("<svg") and "PLAN" in svg and "iLEARN" in svg
    assert "http" not in svg  # no external refs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_report.py -k "per_task or cycle_svg" -v`
Expected: FAIL — `render_task_section` is the stub; `_cycle_svg` missing.

- [ ] **Step 3: Implement the per-task drill-down**

In `scripts/agent_report.py`, add the helpers and replace the stub `render_task_section`:

```python
_STEP_COLOR = {
    "INTENT": "var(--accent)", "PLAN": "var(--accent)", "INTERPRET": "var(--ok)",
    "VERIFY": "var(--warn)", "ILEARN": "var(--bad)", "DOC_SELECT": "var(--muted)",
    "ORACLE_RETRIEVE": "var(--muted)", "DISTILL": "var(--muted)",
    "PREPHASE_GATHER": "var(--muted)", "ANSWER": "var(--ok)", "LINT": "var(--warn)",
}


def _cycle_svg() -> str:
    """Static inline SVG of the per-cycle loop: PLAN -> lint -> interpret -> verify
    -> answer, with the verify-fail -> iLEARN -> PLAN branch."""
    boxes = [("PLAN", 10), ("lint", 110), ("interpret", 200), ("verify", 320), ("answer", 430)]
    rects = []
    for label, x in boxes:
        rects.append(
            f"<rect x='{x}' y='30' width='85' height='28' rx='4' fill='var(--panel)' "
            f"stroke='var(--line)'/>"
            f"<text x='{x + 42}' y='48' text-anchor='middle' font-size='12' "
            f"fill='var(--fg)'>{label}</text>")
    arrows = (
        "<line x1='95' y1='44' x2='110' y2='44' stroke='var(--fg)'/>"
        "<line x1='195' y1='44' x2='200' y2='44' stroke='var(--fg)'/>"
        "<line x1='285' y1='44' x2='320' y2='44' stroke='var(--fg)'/>"
        "<line x1='405' y1='44' x2='430' y2='44' stroke='var(--fg)'/>"
        # verify-fail branch back to PLAN via iLEARN
        "<path d='M360 58 L360 90 L52 90 L52 58' fill='none' stroke='var(--bad)' "
        "stroke-dasharray='4'/>"
        "<text x='200' y='86' text-anchor='middle' font-size='11' fill='var(--bad)'>"
        "verify fail -> iLEARN -> re-PLAN</text>")
    return (f"<svg width='540' height='100' role='img' aria-label='cycle diagram'>"
            f"{''.join(rects)}{arrows}</svg>")


def _timeline(task: TaskTrace) -> str:
    events = []
    for c in task.llm_calls:
        events.append((c.seq, c.step_type, f"{c.phase} c{c.cycle} {c.duration_ms}ms"))
    for v in task.vm_calls:
        events.append((v.seq, v.step_type, f"{v.rpc} c{v.cycle}"))
    for g in task.gates:
        events.append((g.seq, g.step_type, f"gate {'ok' if g.passed else 'FAIL'}"))
    events.sort(key=lambda e: e[0])
    spans = "".join(
        f"<span style='border-left:4px solid {_STEP_COLOR.get(st, 'var(--line)')}' "
        f"title='{_esc(detail)}'>{_esc(st)}</span>"
        for _, st, detail in events)
    return f"<div class='timeline'>{spans}</div>"


def _task_tool_table(task: TaskTrace) -> str:
    rows = "".join(
        f"<tr><td class='l'>{_esc(v.rpc)}</td>"
        f"<td class='l'>{_esc((v.args or {}).get('path') or (v.args or {}).get('root') or '')}</td>"
        f"<td>{v.bytes}</td><td>{'data' if v.has_data else 'empty'}</td>"
        f"<td class='{'ok' if v.validation.startswith('ok') else 'bad'}'>{_esc(v.validation)}</td></tr>"
        for v in task.vm_calls)
    if not rows:
        rows = "<tr><td colspan='5' class='muted'>no tool calls</td></tr>"
    return ("<table><tr><th class='l'>rpc</th><th class='l'>target</th><th>bytes</th>"
            "<th>hit</th><th>validation</th></tr>" + rows + "</table>")


def _reasoning_panels(task: TaskTrace) -> str:
    out = []
    for c in task.llm_calls:
        avail = "yes" if c.reasoning_available else "no"
        body = c.reasoning if c.reasoning_available else "(no reasoning captured)"
        out.append(
            f"<details><summary>{_esc(c.phase)} · cycle {c.cycle} · "
            f"reasoning={avail} · tok {c.tokens_in}/{c.tokens_out}</summary>"
            f"<pre>{_esc(body)}</pre></details>")
    return "".join(out)


def render_task_section(task: TaskTrace) -> str:
    overlap = "" if task.facts_overlap is None else f" · facts-overlap {task.facts_overlap:.2f}"
    detail = "".join(f"<li>{_esc(d)}</li>" for d in task.score_detail)
    detail_html = f"<ul>{detail}</ul>" if detail else ""
    return (
        f"<h2 id='{_esc(task.task_id)}'>{_esc(task.task_id)} — "
        f"<span class='{'ok' if task.outcome == 'OUTCOME_OK' else 'warn'}'>"
        f"{_esc(task.outcome)}</span>{overlap}</h2>"
        f"<pre class='muted'>{_esc(task.instruction)}</pre>"
        f"<h3>Step timeline</h3>{_timeline(task)}"
        f"<h3>Cycle</h3>{_cycle_svg()}"
        f"<h3>Tool usage</h3>{_task_tool_table(task)}"
        f"<h3>Reasoning</h3>{_reasoning_panels(task)}"
        f"{('<h3>Grader feedback</h3>' + detail_html) if detail_html else ''}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_report.py tests/test_agent_report.py
git commit -m "feat(report): per-task drill-down — timeline, cycle SVG, tool table, reasoning panels"
```

---

# Phase 5 — Integration + thin trace_t38

### Task 18: Slim `scripts/trace_t38.py` to a thin caller

**Files:**
- Modify: `scripts/trace_t38.py`
- Test: `tests/test_trace_main.py` (verify it still imports/parses) + manual run.

- [ ] **Step 1: Confirm the current `trace_t38` smoke test**

Run: `uv run pytest tests/test_trace_main.py -v`
Expected: PASS (baseline before edit).

- [ ] **Step 2: Replace the in-script reasoning seams + ReasoningTrace with the prod machinery**

In `scripts/trace_t38.py`:
1. Set the env flag at the top, before importing `agent.llm`, so the production capture installs itself (next to `os.environ["ECOM_MODEL"] = MODEL`, ~line 73):

```python
os.environ.setdefault("ECOM_TRACE_REASONING", "1")  # prod reasoning capture (B2)
```

2. Delete the script-local seam machinery: `_sink`, `_push`, `_pop`, `_reasoning_from_openai_resp`, `_wrap_openai_client`, `_wrap_anthropic_client`, `_parse_stream_reasoning`, `_install_cc_stream_capture`, and the `# install the seams relevant to this run` block (lines ~124–294). These now live in `agent/reasoning_capture.py`, installed at `agent.llm` import.

3. Delete the `ReasoningTrace` subclass (lines ~300–371). Use the production `TraceLogger` directly; it now stamps `seq`/`prev_llm_seq`/`reasoning`/`raw_response_full`. Keep `log_meta` by adding it as a tiny local helper OR drop the `meta` record (the report tolerates its absence). Simplest: drop `ReasoningTrace`, instantiate `TraceLogger`, and skip `log_meta`.

4. In `main()`, replace `trace = ReasoningTrace(run_dir / f"{TASK}.jsonl", TASK)` with `trace = TraceLogger(run_dir / f"{TASK}.jsonl", TASK)` and remove the `trace.log_meta(MODEL)` line (or keep a one-line `trace._write({"type": "meta", "model": MODEL, "task_id": TASK})`).

5. Keep `render_reasoning_md` (the readable companion) — it reads records by key and tolerates the production schema unchanged.

6. Remove now-unused imports (`re`, `threading` if no longer referenced).

- [ ] **Step 3: Verify it imports and the smoke test passes**

Run: `uv run python -c "import ast,sys; ast.parse(open('scripts/trace_t38.py').read()); print('ok')"`
Expected: `ok`.

Run: `uv run pytest tests/test_trace_main.py -v`
Expected: PASS (adjust the test only if it referenced the removed `ReasoningTrace`/seam symbols; update those references to the production equivalents).

- [ ] **Step 4: Commit**

```bash
git add scripts/trace_t38.py tests/test_trace_main.py
git commit -m "refactor(trace): trace_t38 becomes a thin caller of prod reasoning capture + TraceLogger"
```

---

### Task 19: Integration — full `run_pipeline` over MockVMSpy yields a complete v2 trace

**Files:**
- Test: `tests/test_pipeline_v2.py` (extend) — mock the LLM phases, drive the real `run_pipeline`, assert every `step_type` present and all phases named.

- [ ] **Step 1: Write the integration test**

Append to `tests/test_pipeline_v2.py`:

```python
def test_run_pipeline_emits_full_v2_trace(tmp_path, monkeypatch):
    """A full run_pipeline over MockVMSpy yields a v2 trace exercising INTENT, PLAN,
    LINT, INTERPRET, VERIFY gates, vm_call (logged by MockVMSpy), and ANSWER — every
    llm_call phase named (no 'llm')."""
    import json

    from agent import trace
    from agent.trace import TraceLogger
    import agent.reason as reason
    from agent.ir_models import (AnswerShape, AnswerTemplateIR, DecisionTree,
                                 IntentSpec, PlanIR, Step)
    from agent.mock_vm_spy import MockVMSpy, fixture_key
    import agent.pipeline as pipeline

    intent = IntentSpec(objective="count", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
                        answer_shape=AnswerShape(), success_criteria={}, required_refs={})
    plan = PlanIR(
        discovery=[Step(rpc="Exec", args={"path": "/bin/sql", "stdin": "SELECT 1 AS n"},
                        bind="r")],
        decision=DecisionTree(branches=[], default_label="d"),
        answer={"d": AnswerTemplateIR(message="done", outcome="OUTCOME_OK", refs=[])},
    )
    monkeypatch.setattr(reason, "run_intent", lambda *a, **k: intent)
    monkeypatch.setattr(reason, "run_plan", lambda *a, **k: plan)

    fixtures = {fixture_key("Exec", "/bin/sql", ["SELECT 1 AS n"]): {"stdout": "n\n1\n"}}
    vm = MockVMSpy(fixtures)

    p = tmp_path / "t01.jsonl"
    t = TraceLogger(p, "t01")
    trace.set_trace(t)
    try:
        pipeline.run_pipeline(vm, instruction="count rows", task_id="t01",
                              agents_md_text="", facts=None)
    finally:
        trace.set_trace(None)
        t.close()

    recs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    step_types = {r.get("step_type") for r in recs if "step_type" in r}
    assert {"PLAN", "INTERPRET", "VERIFY", "ANSWER"} <= step_types
    # vm_call logged by MockVMSpy under INTERPRET
    assert any(r["type"] == "vm_call" and r["step_type"] == "INTERPRET" for r in recs)
    # gate records present with reasons
    gates = [r for r in recs if r["type"] == "gate"]
    assert any(g["step_type"] == "LINT" for g in gates)
    assert any(g["step_type"] == "VERIFY" for g in gates)
    # no llm_call left at the literal 'llm' phase (real INTENT/PLAN are monkeypatched
    # out here; any incidental funnel call must still be named)
    assert all(r.get("phase") != "llm" for r in recs if r["type"] == "llm_call")
    # seq strictly monotonic and gap-free
    seqs = [r["seq"] for r in recs]
    assert seqs == list(range(len(seqs)))
```

Note: INTENT/PLAN are monkeypatched, so their `llm_call` records are not emitted in this test (no real LLM). The test asserts the deterministic records (PLAN-driven INTERPRET/VERIFY/ANSWER + gates + vm_call). The INTENT/PLAN llm_call phase naming is covered by the funnel tests (Tasks 2, 5).

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/test_pipeline_v2.py::test_run_pipeline_emits_full_v2_trace -v`
Expected: PASS. If `vm_call` is absent, MockVMSpy logging (Task 7 Step 4) is incomplete. If gates absent, Task 8 is incomplete.

- [ ] **Step 3: Run the whole suite**

Run: `uv run python -m pytest tests/ -v`
Expected: PASS, except the documented pre-existing red `tests/test_corpus_replay.py::test_t09_replay_matches_known_good` (stale parity fixture). Confirm no NEW failures.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_v2.py
git commit -m "test(trace): integration — run_pipeline over MockVMSpy yields a complete v2 trace"
```

---

### Task 20: End-to-end verification — re-run t38 and generate the report

**Files:** none (verification + docs). Requires live benchmark credentials in `.env` (`ECOM_BITGN_API_KEY`, `ECOM_BENCHMARK_*`).

- [ ] **Step 1: Check for a concurrent run first**

Run: `pgrep -af "python.*main.py" || echo "no active run"`
If another session is looping `main.py`, coordinate before consuming benchmark trials (per the concurrent-run-contention guidance).

- [ ] **Step 2: Re-run t38 with the now-thin trace script**

Run: `uv run python scripts/trace_t38.py t38 claude-code/haiku`
Expected: a `logs/trace_t38_<ts>_claude-code-haiku/` dir with `t38.jsonl` (v2 records), `t38.detail.log`, `t38.reasoning.md`. The console prints `with_reasoning=` > 0 if the provider exposed thinking.

- [ ] **Step 3: Generate the HTML report over the run**

Run: `uv run python scripts/agent_report.py --logs logs/trace_t38_<ts>_claude-code-haiku --out docs/reports/t38-v2-report.html`
Expected: `wrote docs/reports/t38-v2-report.html  (1 tasks)`.

- [ ] **Step 4: Confirm the A-fix took effect (manual trace read)**

Open `t38.reasoning.md` / the HTML report and verify:
- the PLAN `user_msg` now contains a `## POLICY /docs/...` block (Task 12/13 — policies reach PLAN);
- the PLAN `user_msg` contains the `## TOOL CATALOG` block (Task 11);
- if the model still emits a clarify-only plan while `OUTCOME_OK` is reachable, an `INTERPRET` gate shows `passed=false` with reason "attempt grounded discovery before clarifying" (Task 14), driving a re-PLAN.

Record the resulting score. A score improvement over the prior 0 confirms the architectural fix; if still 0, the trace + report now expose exactly which lever did not fire (this is the observability payoff — diagnose, then add a LEARN trigger, never task-specific prose).

- [ ] **Step 5: Update the project docs (MANDATORY per CLAUDE.md)**

Run: `iwiki:iwiki-ingest agent/trace.py agent/tools.py agent/reasoning_capture.py scripts/agent_report.py`
Then run `/iwiki-lint` and fix any broken `[[refs]]` or stale pages introduced by these changes (do not touch pre-existing unrelated broken refs — out of scope per §2).

- [ ] **Step 6: Commit the report + doc updates**

```bash
git add docs/reports/t38-v2-report.html docs/wiki/
git commit -m "docs(report): t38 v2 report + wiki ingest for observability tooling"
```

---

## Self-Review

**Spec coverage**
- §4 schema v2 (seq, step_type, llm_call fields, vm_call fields, gate, header/meta) → Tasks 1–3, 5–8.
- §5.1 name all phases → Task 4. §5.2 reasoning capture (DoD: `reasoning_available == true` iff `reasoning` non-empty) → Task 6 (`avail = bool(reasoning)`), asserted in `test_llm_call_v2_fields` + `test_push_then_pop`. §5.3 pre-phase VM logging + remove interpreter `_trace_vm` → Task 7. §5.4 gate records → Task 8. §5.5 token accounting → Task 5.
- §6 tool catalog + validation + prompt block + tool-use logging → Tasks 9–11 (+ fail vm_call in Task 10).
- §7.1 policies→PLAN → Task 12. §7.2 deep_read body → Task 13. §7.3 anti-give-up gate (in interpreter, per F-004) → Task 14. §7.4 INTENT guard (D6) → Task 15.
- §8 report (overview + per-task drill-down, both themes, no external resources, prompt-redundancy via difflib over PRE-PHASE FACTS, F-002) → Tasks 16–17.
- §9 error handling (logging best-effort; validation raises; report halts on bad source) → Task 3 (`log_*_auto` swallow), Task 10 (raises), Task 16 (`parse_task_trace` raises on malformed line).
- §10 testing (catalog, schema v2, report renderer, integration over MockVM, A-fix) → Tasks 9, 1–3, 16–17, 19, 12–15.
- §11 sequencing → Phases 0→5 mirror it. §12 D6 flagged + `ECOM_TRACE_REASONING` default off → Task 15 + Task 6 (`enabled()` checks `== "1"`).

**Placeholder scan:** every code step shows full code; no TBD/"handle edge cases". Test steps include real assertions.

**Type consistency:** `step_type`/`phase` keys, `validate_step` returns `str | None`, `TaskTrace`/`LlmCall`/`VmCall`/`Gate` dataclasses used consistently between Tasks 16 and 17; `render_task_section` defined as a stub in Task 16 and replaced (same signature) in Task 17; `_cycle_svg`/`_timeline`/`_task_tool_table`/`_reasoning_panels` all referenced only after definition. `log_llm_call`/`log_vm_call` new params are keyword-with-defaults, preserving existing positional callers.

**Known carve-outs:** `tests/test_corpus_replay.py::test_t09_replay_matches_known_good` is a documented pre-existing red, not introduced here. The INTENT guard (Task 15) may reject legacy OK-less persisted intents in distill paths — those paths already `try/except`, so they degrade gracefully (verified in Task 15 Step 6).
