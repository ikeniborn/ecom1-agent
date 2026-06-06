---
review:
  plan_hash: d09fe411255a56ef
  spec_hash: 53502fa773295cee
  last_run: 2026-06-05
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: WARNING
      section: "Task 4: Pass submitted answer through orchestrator.run_agent"
      section_hash: da970410b7a4b2d0
      text: "Task 4 edits agent/orchestrator.py, a file absent from the spec's 'Files Changed' table (spec lists only learned_store/pipeline/main/compact.md/.env.example/CLAUDE.md). Plan documents this as 'Gap discovered beyond spec' and it is necessary to make spec F-001's wiring work end-to-end, but it expands scope beyond the approved spec — confirm acceptance."
      verdict: accepted
      verdict_at: 2026-06-05
      verdict_note: "Accepted as a necessary, documented scope addition: orchestrator.run_agent rebuilds the return dict and would otherwise drop answer_message/answer_refs, breaking the spec's pipeline→main data flow. Removing Task 4 would silently empty every verdict's submitted answer. Kept."
    - id: F-002
      phase: coverage
      severity: INFO
      section: "Task 3: Capture submitted answer in _AnswerGuard and surface into pipeline metrics"
      section_hash: a4e0479f1f2e0982
      text: "Spec §Changes pipeline.py/1 surfaces outcome via token_stats['outcome'] = _captured['outcome']. Plan relies on the pre-existing 'outcome': actual_outcome key instead and only adds answer_message/answer_refs. Semantically equivalent on the success submit path (actual_outcome == submitted OUTCOME_OK), but a literal deviation from the spec snippet — verify equivalence."
      verdict: fixed
      verdict_at: 2026-06-05
      verdict_note: "Plan Task 3 Step 5 now sources outcome from guarded_vm._captured.get('outcome', actual_outcome), matching the spec's _captured-based surfacing while keeping actual_outcome as a safe fallback. Note text updated."
chain:
  intent: docs/superpowers/intents/2026-06-05-agent-memory-feedback-compaction-intent.md
  spec:   docs/superpowers/specs/2026-06-05-agent-memory-feedback-compaction-design.md
---

# Agent Memory — Verdict Feedback Loop + Context Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist grader rejection feedback as a `source: verdict` entry that the next run sees in `learn_ctx`, and bound `learn_ctx` growth via in-memory LLM compaction.

**Architecture:** After SubmitRun, `main.py:_settle_scores` writes a one-per-task verdict record into `data/learned/{tid}.yaml` via a new `write_verdict()`. The record carries the submitted answer (message/outcome/refs) plus the grader's `score_detail`. To populate that record, the submitted answer must flow pipeline → orchestrator → main: `_AnswerGuard` captures it, `run_pipeline` surfaces it into its metrics dict, `run_agent` passes it through. Separately, `run_pipeline` compacts `learn_ctx` in-memory at startup when it exceeds `COMPACTION_THRESHOLD` entries, summarizing older entries via one LLM call against a new `data/prompts/compact.md`. Verdict entries (`content: null`) need special serialization wherever rules are rendered.

**Tech Stack:** Python 3, PyYAML, pytest, pydantic, existing LLM routing (`agent/llm.py`).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `agent/learned_store.py` | Verdict persistence + shared entry formatter | `write_verdict()`, `_next_verdict_id()`, `_format_entry()` |
| `agent/pipeline.py` | Capture submitted answer, surface into metrics, compact `learn_ctx`, drop blind slice | `_AnswerGuard._captured`, metrics keys, `_compact_learn_ctx()`, remove `[:4000]`, use `_format_entry` |
| `agent/codegen_v2.py` | Render verdict entries correctly in CODEGEN prompt | use `_format_entry` |
| `agent/orchestrator.py` | Pass submitted answer through to `main.py` | add `answer_message`/`answer_refs` to return dict |
| `main.py` | Write verdict on `score < 1.0` | `_settle_scores` → `write_verdict(...)` |
| `data/prompts/compact.md` | Compaction system prompt | new file |
| `.env.example` | New env vars | `COMPACTION_THRESHOLD`, `COMPACTION_KEEP_RECENT` |
| `CLAUDE.md` | Env table | document new vars |

**Deviation from spec (noted):** Spec places `_format_entry` in `pipeline.py`. This plan places it in `learned_store.py` instead — both `pipeline.py` and `codegen_v2.py` need it, both already depend on `learned_store` (or can without a cycle: `learned_store` imports only `models`), and putting it in `pipeline` would force `codegen_v2` to import from `pipeline` at module level (currently avoided — `codegen_v2` only reaches `pipeline.call_llm_raw` lazily inside a function). Shared home = `learned_store`.

**Gap discovered beyond spec:** `orchestrator.py:run_agent` rebuilds its return dict from pipeline `metrics` and forwards `outcome` but NOT `answer_message`/`answer_refs`. Spec's wiring (pipeline writes keys, main reads keys) is broken at this middle hop. Task 4 patches it.

---

## Task 1: Verdict persistence in `learned_store.py`

**Files:**
- Modify: `agent/learned_store.py`
- Test: `tests/test_learned_store.py`

- [ ] **Step 1: Write failing tests for `_next_verdict_id` and `write_verdict`**

Append to `tests/test_learned_store.py`:

```python
def test_next_verdict_id_first(tid_dir):
    assert learned_store._next_verdict_id([]) == "v001"


def test_next_verdict_id_skips_rule_ids(tid_dir):
    entries = [
        {"id": "r001", "status": "active"},
        {"id": "v001", "status": "active"},
        {"id": "v002", "status": "inactive"},
    ]
    assert learned_store._next_verdict_id(entries) == "v003"


def test_write_verdict_appends_entry(tid_dir):
    _seed(tid_dir, "t10", entries=[])
    learned_store.write_verdict(
        "t10",
        score=0.5,
        score_detail=["answer missing field customer_id", "wrong total: expected 3, got 1"],
        submitted_message="Found 1 basket.",
        submitted_outcome="OUTCOME_OK",
        submitted_refs=["ref://basket/42"],
    )
    data = yaml.safe_load((tid_dir / "t10.yaml").read_text())
    e = data["entries"][0]
    assert e["id"] == "v001"
    assert e["source"] == "verdict"
    assert e["score"] == 0.5
    assert e["score_detail"] == ["answer missing field customer_id", "wrong total: expected 3, got 1"]
    assert e["submitted_message"] == "Found 1 basket."
    assert e["submitted_outcome"] == "OUTCOME_OK"
    assert e["submitted_refs"] == ["ref://basket/42"]
    assert e["status"] == "active"
    assert e["content"] is None


def test_write_verdict_deactivates_prior_verdict(tid_dir):
    _seed(tid_dir, "t11", entries=[
        {"id": "v001", "source": "verdict", "status": "active", "content": None},
        {"id": "r001", "source": "rule", "status": "active", "content": "always cite the catalog path"},
    ])
    learned_store.write_verdict(
        "t11", score=0.0, score_detail=["nope"],
        submitted_message="m", submitted_outcome="OUTCOME_OK", submitted_refs=[],
    )
    data = yaml.safe_load((tid_dir / "t11.yaml").read_text())
    by_id = {e["id"]: e for e in data["entries"]}
    assert by_id["v001"]["status"] == "inactive"      # prior verdict deactivated
    assert by_id["v002"]["status"] == "active"          # new verdict active
    assert by_id["r001"]["status"] == "active"          # rule untouched


def test_write_verdict_empty_tid_noop(tid_dir):
    learned_store.write_verdict("", score=0.0, score_detail=[], submitted_message="",
                                submitted_outcome="", submitted_refs=[])
    assert not (tid_dir / ".yaml").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_learned_store.py -k "verdict" -v`
Expected: FAIL — `AttributeError: module 'agent.learned_store' has no attribute '_next_verdict_id'`

- [ ] **Step 3: Implement `_next_verdict_id` and `write_verdict`**

In `agent/learned_store.py`, after `_next_entry_id` (ends line 43), add:

```python
def _next_verdict_id(entries: list[dict]) -> str:
    used = {
        int(e["id"][1:])
        for e in entries
        if isinstance(e.get("id"), str) and e["id"].startswith("v") and e["id"][1:].isdigit()
    }
    return f"v{(max(used, default=0) + 1):03d}"
```

After `save_last_run` (ends line 102), add:

```python
def write_verdict(
    tid: str,
    score: float,
    score_detail: list[str],
    submitted_message: str,
    submitted_outcome: str,
    submitted_refs: list[str],
) -> None:
    """Record grader feedback as a `source: verdict` entry in entries[].

    One active verdict per task: writing a new one deactivates all prior
    `source: verdict` entries. `content: null` flags this as a fact, not a
    rule — `apply_learn_diff` validation is bypassed (this writes directly).
    """
    if not tid:
        return
    data = _read(tid)
    entries: list[dict] = list(data.get("entries", []))

    for e in entries:
        if e.get("source") == "verdict" and e.get("status") == "active":
            e["status"] = "inactive"
            e["deactivated_reason"] = "superseded by newer verdict"

    entries.append({
        "id": _next_verdict_id(entries),
        "source": "verdict",
        "score": score,
        "score_detail": list(score_detail or []),
        "submitted_message": submitted_message,
        "submitted_outcome": submitted_outcome,
        "submitted_refs": list(submitted_refs or []),
        "status": "active",
        "created": str(date.today()),
        "content": None,
    })

    data["task_id"] = tid
    data["entries"] = entries
    _write(tid, data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_learned_store.py -k "verdict" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/learned_store.py tests/test_learned_store.py
git commit -m "feat(learned_store): write_verdict records grader feedback as verdict entry"
```

---

## Task 2: Shared `_format_entry` for verdict-aware rendering

**Files:**
- Modify: `agent/learned_store.py`
- Modify: `agent/pipeline.py:106-108` (rules_lines in `_learn_consolidate`)
- Modify: `agent/codegen_v2.py:46-50` (`_fmt` in `run_codegen`)
- Test: `tests/test_learned_store.py`

- [ ] **Step 1: Write failing test for `_format_entry`**

Append to `tests/test_learned_store.py`:

```python
def test_format_entry_rule(tid_dir):
    e = {"id": "r001", "content": "always cite the catalog path"}
    assert learned_store._format_entry(e) == "  - [r001] always cite the catalog path"


def test_format_entry_verdict(tid_dir):
    e = {
        "id": "v001", "source": "verdict", "score": 0.5,
        "score_detail": ["answer missing field customer_id", "wrong total: expected 3, got 1"],
        "content": None,
    }
    assert learned_store._format_entry(e) == (
        "  - [v001] VERDICT score=0.5: "
        "answer missing field customer_id; wrong total: expected 3, got 1"
    )


def test_format_entry_verdict_no_detail(tid_dir):
    e = {"id": "v002", "source": "verdict", "score": 0.0, "score_detail": [], "content": None}
    assert learned_store._format_entry(e) == "  - [v002] VERDICT score=0.0: "
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_learned_store.py -k "format_entry" -v`
Expected: FAIL — `AttributeError: ... has no attribute '_format_entry'`

- [ ] **Step 3: Implement `_format_entry` in `learned_store.py`**

In `agent/learned_store.py`, after `_next_verdict_id` (added in Task 1), add:

```python
def _format_entry(e: dict) -> str:
    """Render one learn_ctx entry for an LLM prompt. Verdict entries have
    content=None and must show their score_detail instead."""
    if e.get("source") == "verdict":
        detail = "; ".join(e.get("score_detail") or [])
        return f"  - [{e.get('id', '?')}] VERDICT score={e.get('score', '?')}: {detail}"
    return f"  - [{e.get('id', '?')}] {e.get('content', '')}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_learned_store.py -k "format_entry" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Use `_format_entry` in `pipeline.py:_learn_consolidate`**

In `agent/pipeline.py`, update the import on line 13:

```python
from .learned_store import apply_learn_diff, load_entries, save_last_run, _format_entry
```

Replace lines 106-108:

```python
    rules_lines = "\n".join(
        f"  - [{e.get('id', '?')}] {e.get('content', '')}" for e in learn_ctx
    ) or "(none)"
```

with:

```python
    rules_lines = "\n".join(_format_entry(e) for e in learn_ctx) or "(none)"
```

- [ ] **Step 6: Use `_format_entry` in `codegen_v2.py:run_codegen`**

In `agent/codegen_v2.py`, add to the imports (after line 8 `from .prompt import load_prompt`):

```python
from .learned_store import _format_entry
```

Replace lines 45-50:

```python
    if learn_ctx:
        def _fmt(e):
            if isinstance(e, dict):
                return f"  - [{e.get('id', '?')}] {e.get('content', '')}"
            return f"  - {e}"
        rule_lines = "\n".join(_fmt(e) for e in learn_ctx)
```

with:

```python
    if learn_ctx:
        def _fmt(e):
            if isinstance(e, dict):
                return _format_entry(e)
            return f"  - {e}"
        rule_lines = "\n".join(_fmt(e) for e in learn_ctx)
```

- [ ] **Step 7: Run the affected suites to verify nothing broke**

Run: `uv run pytest tests/test_learned_store.py tests/test_codegen_v2.py tests/test_pipeline_v2.py -q`
Expected: PASS (all)

- [ ] **Step 8: Commit**

```bash
git add agent/learned_store.py agent/pipeline.py agent/codegen_v2.py tests/test_learned_store.py
git commit -m "feat(learned_store): _format_entry renders verdict entries; wire into CODEGEN+LEARN"
```

---

## Task 3: Capture submitted answer in `_AnswerGuard` and surface into pipeline metrics

**Files:**
- Modify: `agent/pipeline.py` (`_AnswerGuard.__init__`, `_AnswerGuard.answer`, `run_pipeline` success return)
- Test: `tests/test_pipeline_v2.py`

- [ ] **Step 1: Write failing test for guard capture**

Append to `tests/test_pipeline_v2.py`:

```python
def test_answer_guard_captures_submitted_answer():
    design = DesignOutput(**_GOOD_DESIGN)
    vm = MagicMock()
    guard = _AnswerGuard(vm, design)
    guard.answer(message="Found 1 basket.", outcome="OUTCOME_OK", refs=["ref://basket/42"])
    assert guard._captured == {
        "message": "Found 1 basket.",
        "outcome": "OUTCOME_OK",
        "refs": ["ref://basket/42"],
    }


def test_answer_guard_captured_empty_before_answer():
    design = DesignOutput(**_GOOD_DESIGN)
    guard = _AnswerGuard(MagicMock(), design)
    assert guard._captured == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_v2.py -k "captures_submitted_answer or captured_empty" -v`
Expected: FAIL — `AttributeError: '_AnswerGuard' object has no attribute '_captured'`

- [ ] **Step 3: Add `_captured` to `_AnswerGuard.__init__`**

In `agent/pipeline.py`, in `_AnswerGuard.__init__` (lines 242-247), after `self.actual_outcome: str = ""` add:

```python
        self._captured: dict = {}
```

- [ ] **Step 4: Capture on every successful real `vm.answer` call**

`_AnswerGuard.answer` calls `self._vm.answer(...)` at three return points (lines 322, 354 — the non-OK passthrough and the final OK passthrough). Capture immediately before BOTH real calls so the captured dict reflects exactly what was submitted.

In `agent/pipeline.py`, replace line 321-323:

```python
        if outcome != "OUTCOME_OK":
            self._vm.answer(message=message, outcome=outcome, refs=refs_list)
            return
```

with:

```python
        if outcome != "OUTCOME_OK":
            self._captured = {"message": message, "outcome": outcome, "refs": refs_list}
            self._vm.answer(message=message, outcome=outcome, refs=refs_list)
            return
```

Replace line 354 (the final passthrough):

```python
        self._vm.answer(message=message, outcome=outcome, refs=refs_list)
```

with:

```python
        self._captured = {"message": message, "outcome": outcome, "refs": refs_list}
        self._vm.answer(message=message, outcome=outcome, refs=refs_list)
```

- [ ] **Step 5: Surface captured answer into the success metrics dict**

In `agent/pipeline.py`, the success-path return is lines 564-573. The `guarded_vm` local from the loop is still in scope when `answered=True`. Replace lines 566-573:

```python
    save_last_run(task_id, status=status, outcome=actual_outcome, cycles_used=cycle)
    return {
        "cycles_used": cycle,
        "outcome": actual_outcome,
        "status": status,
        "input_tokens": total_in,
        "output_tokens": total_out,
    }
```

with:

```python
    save_last_run(task_id, status=status, outcome=actual_outcome, cycles_used=cycle)
    return {
        "cycles_used": cycle,
        "outcome": guarded_vm._captured.get("outcome", actual_outcome),
        "status": status,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "answer_message": guarded_vm._captured.get("message", ""),
        "answer_refs": guarded_vm._captured.get("refs", []),
    }
```

Note: per spec §"Changes: agent/pipeline.py / 1", all three submitted fields are surfaced from `_captured`. `outcome` is sourced from `guarded_vm._captured.get("outcome", actual_outcome)` (the captured submitted outcome, falling back to `actual_outcome` if capture is absent) — `main.py:_settle_scores` reads it for `submitted_outcome`. `answer_message` + `answer_refs` are the other two.

- [ ] **Step 6: Run guard tests + full pipeline suite**

Run: `uv run pytest tests/test_pipeline_v2.py -q`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_v2.py
git commit -m "feat(pipeline): _AnswerGuard captures submitted answer; surface into metrics"
```

---

## Task 4: Pass submitted answer through `orchestrator.run_agent`

**Files:**
- Modify: `agent/orchestrator.py:111-118`
- Test: `tests/test_orchestrator.py`

**Why:** `run_agent` builds its own return dict from pipeline `metrics` and currently forwards only `outcome` (line 115), dropping `answer_message`/`answer_refs`. Without this hop, `main.py`'s `token_stats.get("answer_message")` is always empty and every verdict records a blank submitted answer.

- [ ] **Step 1: Write failing test for passthrough**

First inspect the existing orchestrator test to match its mocking style:

Run: `uv run pytest tests/test_orchestrator.py -q` and open `tests/test_orchestrator.py` to find how `run_pipeline` is patched.

Append to `tests/test_orchestrator.py` (adapt the patch target / VM mock to match the file's existing helpers — the existing tests already patch `agent.orchestrator.run_pipeline` and the VM client; reuse those fixtures):

```python
def test_run_agent_forwards_answer_message_and_refs(monkeypatch):
    import agent.orchestrator as orch

    monkeypatch.setattr(orch, "EcomRuntimeClientSync", lambda url: MagicMock())
    monkeypatch.setattr(orch, "VMAdapter", lambda raw: MagicMock())
    monkeypatch.setattr(orch, "_read_agents_md", lambda vm: "AGENTS")
    monkeypatch.setattr(orch, "_discover_schema", lambda vm: "")
    monkeypatch.setattr(orch, "run_pipeline", lambda **kw: {
        "cycles_used": 1, "outcome": "OUTCOME_OK", "status": "success",
        "input_tokens": 0, "output_tokens": 0,
        "answer_message": "Found 1 basket.", "answer_refs": ["ref://basket/42"],
    })

    out = orch.run_agent({}, "http://vm", "count baskets", task_id="t10")
    assert out["answer_message"] == "Found 1 basket."
    assert out["answer_refs"] == ["ref://basket/42"]
    assert out["outcome"] == "OUTCOME_OK"
```

Add `from unittest.mock import MagicMock` to the test file's imports if absent.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -k "forwards_answer" -v`
Expected: FAIL — `KeyError: 'answer_message'` (key absent from `run_agent` return)

- [ ] **Step 3: Add the two keys to `run_agent` return**

In `agent/orchestrator.py`, replace lines 111-118:

```python
    return {
        "model_used": os.environ.get("MODEL", ""),
        "task_type": "lookup",
        "cycles_used": metrics.get("cycles_used", 0),
        "outcome": metrics.get("outcome", ""),
        "input_tokens": metrics.get("input_tokens", 0),
        "output_tokens": metrics.get("output_tokens", 0),
```

with:

```python
    return {
        "model_used": os.environ.get("MODEL", ""),
        "task_type": "lookup",
        "cycles_used": metrics.get("cycles_used", 0),
        "outcome": metrics.get("outcome", ""),
        "input_tokens": metrics.get("input_tokens", 0),
        "output_tokens": metrics.get("output_tokens", 0),
        "answer_message": metrics.get("answer_message", ""),
        "answer_refs": metrics.get("answer_refs", []),
```

(Keep the closing `}` and any trailing keys after line 117 intact — read lines 111-120 first to confirm the dict's tail before editing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -k "forwards_answer" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "fix(orchestrator): forward answer_message/answer_refs from pipeline metrics"
```

---

## Task 5: Write verdict in `main.py:_settle_scores`

**Files:**
- Modify: `main.py:101` (import), `main.py:362-368` (`_settle_scores` failure branch)
- Test: `tests/test_settle_scores.py` (new)

- [ ] **Step 1: Write failing test for `_settle_scores` verdict write**

Create `tests/test_settle_scores.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import main
import agent.learned_store as learned_store
from bitgn.harness_pb2 import TRIAL_STATE_DONE


@pytest.fixture
def patch_store(tmp_path, monkeypatch):
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    # main.py imports save_last_run/write_verdict by name — patch where used.
    monkeypatch.setattr(main, "save_last_run", learned_store.save_last_run)
    monkeypatch.setattr(main, "write_verdict", learned_store.write_verdict)
    return tmp_path


def _trial(task_id, score, detail, available=True):
    return SimpleNamespace(
        task_id=task_id,
        score=score,
        score_available=available,
        score_detail=detail,
        state=TRIAL_STATE_DONE,
    )


def test_settle_writes_verdict_on_failure(patch_store, monkeypatch):
    import yaml
    monkeypatch.setattr(main, "_finalize_task_trace", lambda *a, **k: None)
    token_stats = {
        "outcome": "OUTCOME_OK",
        "cycles_used": 2,
        "answer_message": "Found 1 basket.",
        "answer_refs": ["ref://basket/42"],
    }
    pending = {"t10": ("trial-1", 1.5, token_stats, None)}
    submit = SimpleNamespace(trials=[_trial("t10", 0.5, ["wrong total: expected 3, got 1"])])

    main._settle_scores(submit, pending)

    data = yaml.safe_load((patch_store / "t10.yaml").read_text())
    verdicts = [e for e in data["entries"] if e.get("source") == "verdict"]
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["score"] == 0.5
    assert v["score_detail"] == ["wrong total: expected 3, got 1"]
    assert v["submitted_message"] == "Found 1 basket."
    assert v["submitted_outcome"] == "OUTCOME_OK"
    assert v["submitted_refs"] == ["ref://basket/42"]


def test_settle_no_verdict_on_perfect_score(patch_store, monkeypatch):
    monkeypatch.setattr(main, "_finalize_task_trace", lambda *a, **k: None)
    pending = {"t10": ("trial-1", 1.5, {"outcome": "OUTCOME_OK", "cycles_used": 1}, None)}
    submit = SimpleNamespace(trials=[_trial("t10", 1.0, [])])

    main._settle_scores(submit, pending)

    assert not (patch_store / "t10.yaml").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_settle_scores.py -v`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'write_verdict'`

- [ ] **Step 3: Update the import in `main.py`**

In `main.py`, replace line 101:

```python
from agent.learned_store import save_last_run
```

with:

```python
from agent.learned_store import save_last_run, write_verdict
```

- [ ] **Step 4: Write the verdict in the failure branch**

In `main.py:_settle_scores`, replace lines 362-368:

```python
        if t.score_available and score < 1.0:
            save_last_run(
                task_id,
                status="failure",
                outcome=token_stats.get("outcome", "OUTCOME_OK"),
                cycles_used=token_stats.get("cycles_used", 0),
            )
```

with:

```python
        if t.score_available and score < 1.0:
            save_last_run(
                task_id,
                status="failure",
                outcome=token_stats.get("outcome", "OUTCOME_OK"),
                cycles_used=token_stats.get("cycles_used", 0),
            )
            write_verdict(
                task_id,
                score=score,
                score_detail=detail,
                submitted_message=token_stats.get("answer_message", ""),
                submitted_outcome=token_stats.get("outcome", ""),
                submitted_refs=token_stats.get("answer_refs", []),
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_settle_scores.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_settle_scores.py
git commit -m "feat(main): write_verdict on score<1.0 in _settle_scores"
```

---

## Task 6: Compaction prompt `data/prompts/compact.md`

**Files:**
- Create: `data/prompts/compact.md`

- [ ] **Step 1: Create the compaction system prompt**

Create `data/prompts/compact.md`:

```markdown
# PHASE: COMPACT

You compress a list of accumulated learned rules and verdicts into one dense paragraph.

## Input

A list of entries, each a short directive or a grader verdict, prefixed by an id.

## Output

A single plain-text paragraph of the key conclusions. Rules:

- Preserve every action directive ("never X", "always Y", "use Z") in condensed form.
- Preserve concrete grader complaints from VERDICT lines (missing fields, wrong totals).
- Merge duplicates and near-duplicates into one statement.
- No reasoning, no examples, no task-specific narration, no ids.
- Output plain text only — no JSON, no markdown, no code blocks, no list bullets.
```

- [ ] **Step 2: Verify the loader can read it**

Run: `uv run python -c "from agent.prompt import load_prompt; print(bool(load_prompt('compact')))"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add data/prompts/compact.md
git commit -m "feat(prompts): add compaction system prompt"
```

---

## Task 7: `_compact_learn_ctx` in `pipeline.py`

**Files:**
- Modify: `agent/pipeline.py` (new `_compact_learn_ctx`, call in `run_pipeline`)
- Test: `tests/test_pipeline_v2.py`

- [ ] **Step 1: Write failing tests for compaction logic**

Append to `tests/test_pipeline_v2.py`:

```python
def _entries(n):
    return [{"id": f"r{i:03d}", "content": f"always do thing {i}", "status": "active"} for i in range(n)]


def test_compact_below_threshold_returns_unchanged(monkeypatch):
    from agent.pipeline import _compact_learn_ctx
    monkeypatch.setenv("COMPACTION_THRESHOLD", "15")
    ctx = _entries(10)
    assert _compact_learn_ctx(ctx) == ctx


def test_compact_above_threshold_summarizes_older(monkeypatch):
    from agent.pipeline import _compact_learn_ctx
    monkeypatch.setenv("COMPACTION_THRESHOLD", "5")
    monkeypatch.setenv("COMPACTION_KEEP_RECENT", "3")
    ctx = _entries(10)
    with patch("agent.pipeline.call_llm_raw", return_value="condensed summary of older rules"):
        out = _compact_learn_ctx(ctx)
    assert out[0] == {"id": "compacted", "content": "condensed summary of older rules", "source": "compaction"}
    assert out[1:] == ctx[-3:]
    assert len(out) == 4


def test_compact_empty_llm_response_returns_unchanged(monkeypatch):
    from agent.pipeline import _compact_learn_ctx
    monkeypatch.setenv("COMPACTION_THRESHOLD", "5")
    monkeypatch.setenv("COMPACTION_KEEP_RECENT", "3")
    ctx = _entries(10)
    with patch("agent.pipeline.call_llm_raw", return_value=""):
        out = _compact_learn_ctx(ctx)
    assert out == ctx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_v2.py -k "compact" -v`
Expected: FAIL — `ImportError: cannot import name '_compact_learn_ctx'`

- [ ] **Step 3: Implement `_compact_learn_ctx`**

In `agent/pipeline.py`, after `learn_from_grader` (ends line 183) add:

```python
# ---------------------------------------------------------------------------
# Context compaction — bound learn_ctx growth in-memory (YAML untouched)
# ---------------------------------------------------------------------------

def _compact_learn_ctx(
    learn_ctx: list[dict],
    token_out: dict | None = None,
) -> list[dict]:
    """Summarize older learn_ctx entries via one LLM call when the list grows
    past COMPACTION_THRESHOLD. In-memory only — the YAML store is never
    rewritten, so each run compacts fresh from the full stored list. On empty
    or failed LLM response, return the input unchanged (green tasks must not
    regress)."""
    threshold = int(os.environ.get("COMPACTION_THRESHOLD", "15"))
    keep_recent = int(os.environ.get("COMPACTION_KEEP_RECENT", "5"))
    if len(learn_ctx) <= threshold:
        return learn_ctx

    older = learn_ctx[:-keep_recent]
    recent = learn_ctx[-keep_recent:]

    guide = load_prompt("compact") or "# PHASE: COMPACT"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
    user_msg = "\n".join(_format_entry(e) for e in older)

    model = _resolve_model_for_phase("learn", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_LEARN, token_out=token_out)
    summary = (raw or "").strip()
    if not summary:
        print(f"{CLI_YELLOW}[pipeline] compaction: empty response, keeping full ctx{CLI_CLR}")
        return learn_ctx

    print(f"{CLI_BLUE}[pipeline] compacted {len(older)} entries → 1 summary{CLI_CLR}")
    return [{"id": "compacted", "content": summary, "source": "compaction"}] + recent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline_v2.py -k "compact" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Call compaction at the start of `run_pipeline`**

In `agent/pipeline.py`, replace lines 372-373:

```python
    learn_ctx = load_entries(task_id)
    print(f"{CLI_BLUE}[pipeline] task={task_id} active_rules={len(learn_ctx)}{CLI_CLR}")
```

with:

```python
    learn_ctx = load_entries(task_id)
    _tk_compact: dict = {}
    learn_ctx = _compact_learn_ctx(learn_ctx, token_out=_tk_compact)
    print(f"{CLI_BLUE}[pipeline] task={task_id} active_rules={len(learn_ctx)}{CLI_CLR}")
```

Then, so compaction tokens count toward the run total, add an `_accum` call right after `_accum` is defined. The `_accum` helper is defined at lines 378-381; insert immediately after it (after line 381):

```python
    _accum(_tk_compact)
```

- [ ] **Step 6: Run the full pipeline suite to confirm no regression**

Run: `uv run pytest tests/test_pipeline_v2.py -q`
Expected: PASS (all). The happy-path test (`test_happy_path_design_plus_one_codegen`) seeds few/no entries, so compaction returns unchanged without an extra LLM call — its `_seq` mock count is unaffected.

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_v2.py
git commit -m "feat(pipeline): _compact_learn_ctx bounds learn_ctx growth in-memory"
```

---

## Task 8: Remove blind `[:4000]` slice in `_learn_consolidate`

**Files:**
- Modify: `agent/pipeline.py:116`
- Test: `tests/test_pipeline_v2.py`

- [ ] **Step 1: Write a failing test asserting full script reaches the LLM**

Append to `tests/test_pipeline_v2.py`:

```python
def test_learn_consolidate_sends_full_script(tmp_path, monkeypatch):
    import agent.learned_store as ls
    from agent.pipeline import _learn_consolidate
    monkeypatch.setattr(ls, "_LEARNED_DIR", tmp_path)

    design = DesignOutput(**_GOOD_DESIGN)
    long_script = "def run(vm, params):\n" + ("    x = 1  # pad\n" * 600)  # > 4000 chars
    assert len(long_script) > 4000

    captured = {}

    def _fake_llm(system, user_msg, model, opts, **kw):
        captured["user_msg"] = user_msg
        return json.dumps({"skip": True, "skip_reason": "noop", "deactivate_ids": []})

    with patch("agent.pipeline.call_llm_raw", side_effect=_fake_llm):
        _learn_consolidate("t10", [], design, "some error", long_script)

    tail_marker = long_script.strip().splitlines()[-1]
    assert tail_marker in captured["user_msg"]   # last line survived — no truncation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_v2.py -k "sends_full_script" -v`
Expected: FAIL — the tail line is absent because `script_code[:4000]` dropped it.

- [ ] **Step 3: Remove the slice**

In `agent/pipeline.py`, line 116, replace:

```python
        f"SCRIPT_CODE:\n```python\n{script_code[:4000]}\n```\n\n"
```

with:

```python
        f"SCRIPT_CODE:\n```python\n{script_code}\n```\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_v2.py -k "sends_full_script" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_v2.py
git commit -m "fix(pipeline): drop blind [:4000] script truncation in LEARN"
```

---

## Task 9: Document env vars

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md` (env table)

- [ ] **Step 1: Add the two vars to `.env.example`**

Read `.env.example` around line 29 (`FIDELITY_TIMEOUT_S`) and add after it:

```
COMPACTION_THRESHOLD=15              # entry count that triggers learn_ctx compaction
COMPACTION_KEEP_RECENT=5             # recent entries kept verbatim after compaction
```

- [ ] **Step 2: Add rows to the `CLAUDE.md` env table**

In `CLAUDE.md`, in the Environment Variables table (the `| Var | Purpose |` block), add after the `FIDELITY_TIMEOUT_S` row:

```
| `COMPACTION_THRESHOLD` | Entry count in `learn_ctx` that triggers in-memory LLM compaction (default 15) |
| `COMPACTION_KEEP_RECENT` | Recent `learn_ctx` entries kept verbatim after compaction (default 5) |
```

- [ ] **Step 3: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: document COMPACTION_THRESHOLD and COMPACTION_KEEP_RECENT"
```

---

## Task 10: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS (all). No prior tests regressed.

- [ ] **Step 2: Spot-check verdict round-trip is renderable**

Run:
```bash
uv run python -c "
from agent.learned_store import write_verdict, load_entries, _format_entry
import agent.learned_store as ls, tempfile, pathlib
ls._LEARNED_DIR = pathlib.Path(tempfile.mkdtemp())
write_verdict('demo', 0.5, ['missing customer_id'], 'msg', 'OUTCOME_OK', ['ref://x'])
for e in load_entries('demo'):
    print(_format_entry(e))
"
```
Expected output: `  - [v001] VERDICT score=0.5: missing customer_id`

- [ ] **Step 3: Final commit if any docs/graph updates remain**

Per project CLAUDE.md, after a non-trivial change run `graphify` + `update-docs`. Do that now, then:

```bash
git add -A
git commit -m "chore: refresh knowledge graph + docs after memory feedback loop"
```

---

## Self-Review Notes

- **Spec coverage:** verdict schema (Task 1), `_format_entry` branch (Task 2), `_AnswerGuard` capture + token_stats surface (Task 3), `main.py` write_verdict (Task 5), `_compact_learn_ctx` (Task 7), `compact.md` (Task 6), remove `[:4000]` (Task 8), env vars (Task 9). F-001 wiring (outcome into token_stats) — covered: `outcome` already in pipeline return + orchestrator passthrough; Task 4 closes the additional `answer_message`/`answer_refs` hop the spec missed.
- **Kept (not changed):** `_terminal_clarify` `message[:800]` (VM protocol limit, per spec §"Remove blind slice"). `models.py`, `test_runner.py`, `data/prompts/{design,codegen,learn}.md`, proto/harness — untouched.
- **Type consistency:** `write_verdict(tid, score, score_detail, submitted_message, submitted_outcome, submitted_refs)` signature identical across Task 1 def, Task 5 call. `_compact_learn_ctx(learn_ctx, token_out=None)` identical across Task 7 def + call. Verdict dict keys (`source`, `score`, `score_detail`, `submitted_message`, `submitted_outcome`, `submitted_refs`, `content: null`) identical across Task 1 impl, Task 1 tests, Task 5 tests.
```