---
review:
  plan_hash: 7bd8c37763f5c1d6
  spec_hash: 7136e5521c553673
  last_run: 2026-06-21
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings: []
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-21-richer-downstream-context-design.md
result_check:
  verdict: OK
  plan_hash: 7bd8c37763f5c1d6
  last_run: 2026-06-21
---

# Richer Downstream Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give downstream phases more grounding context — (A) INVESTIGATE probes seed data-paths into the Brief before stopping (flag-gated, default off), and (B) `_enrich_prim_error` attaches a primitive CONTRACT to lint-reject errors, not just runtime/arity ones.

**Architecture:** Two independent changes coupled only by theme. Part B broadens one regex + adds a fallback scan in `agent/pipeline.py`. Part A adds a deterministic data-path seed (`pipeline._data_path_seed`), a forced read-only probe in the existing `agent/investigate.py` ReAct loop (priority: doc-read > data-probe > router), a `sufficient()` data-clause, and an `investigate_stop` trace record for measuring the (unproven) hypothesis. All Part-A behaviour is inert when `ECOM_INVESTIGATE_DATA_PATHS=0` (default).

**Tech Stack:** Python 3, pytest, `uv` (deps + `.env` autoload), pydantic IR models, `MockVMSpy` test double.

**Spec:** `docs/superpowers/specs/2026-06-21-richer-downstream-context-design.md`

**Conventions:**
- Run tests with `uv run pytest ...` (bare `python` lacks deps — `google.protobuf` import fails).
- Commit after each green task. Prefix: `feat:` / `test:` / `docs:`.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `agent/pipeline.py` | Modify `_enrich_prim_error` (~L99); add `_data_path_seed` helper; wire `data_paths=` at the `investigate(...)` call (~L400) | Part B regex; Part A seed construction + flag gate |
| `agent/investigate.py` | Add `_forced_data_probe`; extend `sufficient`; add `data_paths` param + loop wiring + stop-reason trace emit | Part A read-only probe + stop condition |
| `agent/trace.py` | Add `TraceLogger.log_investigate_stop` + `log_investigate_stop_auto` | Part A measurement record |
| `tests/test_pipeline_interpreted.py` | Add Part B + `_data_path_seed` tests | unit coverage |
| `tests/test_investigate.py` | Add `_forced_data_probe`, `sufficient` data-clause, probe-integration, stop-trace tests | unit + integration coverage |
| `CLAUDE.md`, `agent/CLAUDE.md` | Document `ECOM_INVESTIGATE_DATA_PATHS` | mandatory docs-current |
| `docs/wiki/` | `iwiki-ingest` regenerate affected pages | mandatory docs-current |

---

## Task 1: Part B — CONTRACT on lint-reject errors

**Files:**
- Modify: `agent/pipeline.py:99-109` (`_enrich_prim_error`)
- Test: `tests/test_pipeline_interpreted.py` (near existing `test_enrich_prim_error_*`, ~L358)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline_interpreted.py` after `test_enrich_prim_error_idempotent` (~L377):

```python
def test_enrich_prim_error_lint_compute_form():
    # check_compute_on_raw_discovery_bind emits "... (compute 'X' arg $root)"
    from agent import pipeline
    out = pipeline._enrich_prim_error("plan: bad source (compute 'column' arg $rows)")
    assert "CONTRACT:" in out
    assert "column(rows, col)" in out          # column's contract appended


def test_enrich_prim_error_lint_contract_message():
    # primitive_contract spec messages lead with the quoted primitive
    from agent import pipeline
    out = pipeline._enrich_prim_error(
        "plan: 'column' expects list[dict]; use 'get'+'to_number' for a single row"
    )
    assert "CONTRACT:" in out
    assert "column(rows, col)" in out          # first known primitive wins, not 'get'/'to_number'


def test_enrich_prim_error_quoted_nonprimitive_noop():
    from agent import pipeline
    msg = "verify: missing ref 'foobar'"
    assert pipeline._enrich_prim_error(msg) == msg     # 'foobar' is not a primitive
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_interpreted.py -k enrich_prim_error -v`
Expected: the 3 new tests FAIL (no CONTRACT appended for lint forms); the 3 existing `enrich` tests PASS.

- [ ] **Step 3: Broaden `_enrich_prim_error`**

Replace `agent/pipeline.py:99-109` entirely with:

```python
def _enrich_prim_error(err: str) -> str:
    """Append the failed primitive's contract so the retry sees the spec, not just the
    symptom. Matches the runtime forms ("compute step 'X'", "primitive 'X'") and the lint
    forms ("compute 'X'", "'X' expects ..."). No-op when the message names no known
    primitive (contract() is empty for non-primitives, so a stray quoted word is safe)."""
    import re as _re
    from .primitives import contract
    m = _re.search(r"(?:compute(?: step)?|primitive) '([a-z_]+)'", err)
    prim = m.group(1) if m else None
    if prim is None:
        # lint primitive_contract messages lead with the quoted primitive, e.g.
        # "'column' expects list[dict]; use 'get'..." — first quoted token that is a primitive.
        for tok in _re.findall(r"'([a-z_]+)'", err):
            if contract(tok):
                prim = tok
                break
    if prim:
        c = contract(prim)
        if c and c not in err:
            return f"{err}\nCONTRACT: {c}"
    return err
```

- [ ] **Step 4: Run the full enrich suite to verify green**

Run: `uv run pytest tests/test_pipeline_interpreted.py -k enrich_prim_error -v`
Expected: all 6 tests PASS (3 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "feat(pipeline): attach primitive CONTRACT to lint-reject errors

Broaden _enrich_prim_error to match the lint forms ('compute X', 'X
expects ...') in addition to the runtime forms, so iLEARN sees the
primitive spec when a plan is rejected at lint time, not only at
interpret time."
```

---

## Task 2: Part A — trace record `investigate_stop`

**Files:**
- Modify: `agent/trace.py` (add method after `log_lint_fire` ~L327; add module helper after `log_lint_fire_auto` ~L564)
- Test: covered by Task 4's stop-trace integration test (no standalone test — this is plumbing).

- [ ] **Step 1: Add the `TraceLogger.log_investigate_stop` method**

Insert into `agent/trace.py` immediately after the `log_lint_fire` method (after L327, before `def log_answer`):

```python
    def log_investigate_stop(self, reason: str, data_paths_total: int,
                             data_paths_probed: int) -> None:
        """Why the investigator stopped (sufficient | budget | data_probed) and how many
        seed data-paths it probed. Lets an A/B run compare flag-off vs flag-on
        (ECOM_INVESTIGATE_DATA_PATHS)."""
        self._write({
            "type": "investigate_stop",
            "reason": reason or "",
            "data_paths_total": int(data_paths_total),
            "data_paths_probed": int(data_paths_probed),
        })
```

- [ ] **Step 2: Add the `log_investigate_stop_auto` module helper**

Insert into `agent/trace.py` at end of file, immediately after `log_lint_fire_auto` (after L564):

```python
def log_investigate_stop_auto(reason: str, total: int, probed: int) -> None:
    t = get_trace()
    if t is None:
        return
    try:
        t.log_investigate_stop(reason, total, probed)
    except Exception:
        pass
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `uv run python -c "from agent.trace import log_investigate_stop_auto; print('ok')"`
Expected: prints `ok` (after the usual `[llm] Active backend` banner line).

- [ ] **Step 4: Commit**

```bash
git add agent/trace.py
git commit -m "feat(trace): add investigate_stop record (reason + data-path counts)"
```

---

## Task 3: Part A — `_forced_data_probe` + `sufficient()` data-clause

**Files:**
- Modify: `agent/investigate.py` (add `_forced_data_probe` after `_forced_doc_read` ~L197; extend `sufficient` ~L159-174)
- Test: `tests/test_investigate.py` (after the existing `sufficient` tests, ~L198)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_investigate.py` after `test_sufficient_true_when_only_record_path_refs` (~L198):

```python
from agent.investigate import _forced_data_probe


def test_forced_data_probe_picks_first_unprobed_dir_then_file():
    dp = _forced_data_probe(["/proc/payments", "/docs/p.md"], probed=set())
    assert dp["_seed"] == "/proc/payments"
    assert dp["tool"] == "list"                 # no '.' in basename -> directory -> list
    assert dp["args"] == {"path": "/proc/payments"}
    dp2 = _forced_data_probe(["/docs/p.md"], probed=set())
    assert dp2["tool"] == "read"                # '.' in basename -> file -> read


def test_forced_data_probe_none_when_all_probed_or_empty():
    assert _forced_data_probe(["/a/b"], probed={"/a/b"}) is None
    assert _forced_data_probe([], probed=set()) is None
    assert _forced_data_probe(None, probed=set()) is None


def test_sufficient_false_when_data_path_unprobed():
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
    assert sufficient(intent, env={}, data_paths=["/proc/payments"], probed=set()) is False


def test_sufficient_true_when_all_data_paths_probed():
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
    assert sufficient(intent, env={}, data_paths=["/proc/payments"],
                      probed={"/proc/payments"}) is True


def test_sufficient_data_clause_inert_when_no_data_paths():
    # regression guard: omitting data_paths/probed reproduces the old behaviour
    env = {"policy_doc:/docs/security.md": True, "row.record_path": "/p.json"}
    assert sufficient(_intent_with_refs(), env=env) is True
    assert sufficient(_intent_with_refs(), env={}) is False
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_investigate.py -k "forced_data_probe or data_path or data_clause" -v`
Expected: FAIL — `ImportError`/`AttributeError` for `_forced_data_probe`, and `TypeError` on `sufficient(... data_paths=...)`.

- [ ] **Step 3: Add `_forced_data_probe`**

Insert into `agent/investigate.py` immediately after `_forced_doc_read` (after L197):

```python
def _forced_data_probe(data_paths, probed: set) -> "dict | None":
    """Return a read-only action for the first un-probed seed data-path, or None.
    Probe-tool heuristic: a '.' in the basename ⇒ a file ⇒ `read`; otherwise a directory
    ⇒ `list`. The caller marks the path probed (probe-once) when it dispatches."""
    for p in data_paths or []:
        if p in probed:
            continue
        base = p.rsplit("/", 1)[-1]
        tool = "read" if "." in base else "list"
        return {"tool": tool, "args": {"path": p}, "_seed": p}
    return None
```

- [ ] **Step 4: Extend `sufficient()`**

Replace `agent/investigate.py:159-174` (the whole `def sufficient(...)` body) with:

```python
def sufficient(intent, env: dict, data_paths=None, probed=None) -> bool:
    """True when every investigator-groundable required_ref for the desired outcome is
    grounded in env AND every seed data-path has been probed. Refs whose grounding is
    PLAN's responsibility (e.g. record_path resolved from a $source) are skipped — the
    investigator cannot ground them and must not block on them. data_paths/probed default
    to None ⇒ the data clause is inert (pre-feature behaviour)."""
    outcome = intent.desired_outcome
    refs = (intent.required_refs or {}).get(outcome, [])
    for ref in refs:
        g = ref.grounded(env)
        if g is None:            # PLAN produces this ref (e.g. record_path) — not the investigator's job
            continue
        if not g:
            return False
    if data_paths:
        if any(p not in (probed or set()) for p in data_paths):
            return False
    return True
```

- [ ] **Step 5: Run the tests to verify green**

Run: `uv run pytest tests/test_investigate.py -k "forced_data_probe or data_path or data_clause or sufficient" -v`
Expected: all PASS (new tests + the pre-existing `test_sufficient_*` tests).

- [ ] **Step 6: Commit**

```bash
git add agent/investigate.py tests/test_investigate.py
git commit -m "feat(investigate): _forced_data_probe + sufficient() data-path clause"
```

---

## Task 4: Part A — wire the data-path probe into the investigate loop

**Files:**
- Modify: `agent/investigate.py` (import; `investigate()` signature ~L289; loop body ~L296-360)
- Test: `tests/test_investigate.py` (append integration + trace tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_investigate.py` (end of file):

```python
def test_investigate_probes_seed_data_path_and_records(monkeypatch):
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
    vm = MockVMSpy({fixture_key("List", "/proc/payments"): {"entries": "p_1.json\np_2.json"}})
    # router would end immediately, but the forced data-probe runs FIRST (higher priority).
    monkeypatch.setattr(inv, "router", lambda i, b, atoms, escalate: {"done": True})
    monkeypatch.setattr(inv, "digest",
                        lambda goal, tool, args, observation, escalate: (
                            Note(tool=tool, args=args, lesson="listed dir"), {}))
    brief = inv.investigate(vm, intent, data_paths=["/proc/payments"], max_steps=6)
    assert "/proc/payments" in brief.env.get("data_paths", {})       # recorded
    assert any(c[0] == "List" for c in vm.calls)                     # dir probed via list


def test_investigate_data_paths_inert_when_flag_off(monkeypatch):
    # data_paths=None (flag off) -> no probe, router decides immediately, no data_paths env
    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
    vm = MockVMSpy({})
    monkeypatch.setattr(inv, "router", lambda i, b, atoms, escalate: {"done": True})
    brief = inv.investigate(vm, intent, max_steps=6)
    assert "data_paths" not in brief.env
    assert not any(c[0] == "List" for c in vm.calls)


def test_investigate_emits_stop_trace(tmp_path, monkeypatch):
    import json
    from agent import trace
    logpath = tmp_path / "t.jsonl"
    logger = trace.TraceLogger(path=logpath, task_id="tT")
    trace.set_trace(logger)
    try:
        intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                            outcome_space=["OUTCOME_OK"], answer_shape={}, required_refs={})
        vm = MockVMSpy({fixture_key("List", "/proc/payments"): {"entries": "p_1.json"}})
        monkeypatch.setattr(inv, "router", lambda i, b, atoms, escalate: {"done": True})
        monkeypatch.setattr(inv, "digest",
                            lambda goal, tool, args, observation, escalate: (Note(tool=tool), {}))
        inv.investigate(vm, intent, data_paths=["/proc/payments"], max_steps=6)
    finally:
        logger.close(); trace.set_trace(None)
    recs = [json.loads(l) for l in logpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    stop = [r for r in recs if r.get("type") == "investigate_stop"]
    assert stop, "no investigate_stop record emitted"
    assert stop[-1]["data_paths_total"] == 1
    assert stop[-1]["data_paths_probed"] == 1
    assert stop[-1]["reason"] == "data_probed"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_investigate.py -k "probes_seed or inert_when_flag_off or emits_stop" -v`
Expected: FAIL — `investigate()` rejects the `data_paths=` kwarg (TypeError) / no `data_paths` env key / no `investigate_stop` record.

- [ ] **Step 3: Extend the trace import**

In `agent/investigate.py`, replace L13:

```python
from .trace import set_step_type, current_step_type
```

with:

```python
from .trace import set_step_type, current_step_type, log_investigate_stop_auto
```

- [ ] **Step 4: Add the `data_paths` parameter to `investigate()`**

Replace `agent/investigate.py:289` (the `def investigate(...)` signature line):

```python
def investigate(vm, intent, seed=None, oracle=None, max_steps: int | None = None) -> "Brief":
```

with:

```python
def investigate(vm, intent, seed=None, oracle=None, max_steps: int | None = None,
                data_paths: list[str] | None = None) -> "Brief":
```

- [ ] **Step 5: Initialise the probe state**

In `agent/investigate.py`, replace the line `    seen: set[str] = set()` (~L297) with:

```python
    seen: set[str] = set()
    probed: set[str] = set()
    data_seed = list(data_paths or [])
    stop_reason = "budget"
```

- [ ] **Step 6: Replace the action-selection block (insert data-probe at priority 2)**

Replace this block in `agent/investigate.py` (~L306-315):

```python
                atoms = _retrieve_atoms(oracle, goal)
                forced = _forced_doc_read(brief.env, req_refs)
                if forced is not None and tool_signature(
                        forced["tool"], forced["args"]) not in seen:
                    act = forced  # prioritize grounding the governing doc
                elif _MERGE_STEPS and pending_action is not None:
                    act = pending_action
                    pending_action = None
                else:
                    act = router(intent, brief, atoms, escalate=False)
```

with:

```python
                atoms = _retrieve_atoms(oracle, goal)
                act = None
                probe_seed = None
                forced = _forced_doc_read(brief.env, req_refs)
                if forced is not None and tool_signature(
                        forced["tool"], forced["args"]) not in seen:
                    act = forced  # priority 1: ground the governing doc
                if act is None:
                    while True:   # priority 2: probe seed data-paths (probe-once)
                        dp = _forced_data_probe(data_seed, probed)
                        if dp is None:
                            break
                        probed.add(dp["_seed"])           # mark probed regardless of outcome
                        if tool_signature(dp["tool"], dp["args"]) not in seen:
                            act = {"tool": dp["tool"], "args": dp["args"]}
                            probe_seed = dp["_seed"]
                            break
                        # already fetched under another step → try the next seed
                if act is None and _MERGE_STEPS and pending_action is not None:
                    act = pending_action
                    pending_action = None
                if act is None:                           # priority 3: free router
                    act = router(intent, brief, atoms, escalate=False)
```

- [ ] **Step 7: Tag the router-done break with a stop reason**

Replace (~L316-317):

```python
                if act.get("done"):
                    break
```

with:

```python
                if act.get("done"):
                    stop_reason = "sufficient"
                    break
```

- [ ] **Step 8: Record a probed data-path into env**

Replace this block (~L318-324):

```python
                tool, args = act.get("tool", ""), act.get("args", {}) or {}
                try:
                    observation = run_tool(vm, tool, args)
                except ToolRejected as e:
                    brief.notes.append(Note(goal=goal, tool=tool, args=args,
                                            lesson=f"rejected (mutation): {e}"))
                    continue
```

with:

```python
                tool, args = act.get("tool", ""), act.get("args", {}) or {}
                try:
                    observation = run_tool(vm, tool, args)
                except ToolRejected as e:
                    brief.notes.append(Note(goal=goal, tool=tool, args=args,
                                            lesson=f"rejected (mutation): {e}"))
                    continue
                if probe_seed is not None:                # surface the probed data-path for PLAN
                    brief.env.setdefault("data_paths", {})[probe_seed] = (observation or "")[:200]
```

- [ ] **Step 9: Tag the escalation breaks + sufficiency break, then emit the stop record**

(9a) Replace the escalated-done break (~L329-330):

```python
                    if act2.get("done"):
                        break
```

with:

```python
                    if act2.get("done"):
                        stop_reason = "sufficient"
                        break
```

(9b) Replace the still-stalled stop break (~L339-343):

```python
                    if is_stalled(observation, sig, seen):     # still stalled after escalation → stop
                        note, env_updates = digest(goal, tool, args, observation, escalate=True)
                        brief.notes.append(note); brief.env.update(env_updates)
                        _ground_doc_refs(brief.env, tool, args, req_refs)
                        break
```

with:

```python
                    if is_stalled(observation, sig, seen):     # still stalled after escalation → stop
                        note, env_updates = digest(goal, tool, args, observation, escalate=True)
                        brief.notes.append(note); brief.env.update(env_updates)
                        _ground_doc_refs(brief.env, tool, args, req_refs)
                        stop_reason = "sufficient"
                        break
```

(9c) Replace the sufficiency break (~L353-354):

```python
                if sufficient(intent, brief.env):
                    break
```

with:

```python
                if sufficient(intent, brief.env, data_seed, probed):
                    stop_reason = "data_probed" if data_seed else "sufficient"
                    break
```

(9d) Emit the stop record after the loop. Replace this tail (~L355-360):

```python
            except Exception as e:                             # graceful: never raise out of a step
                brief.notes.append(Note(goal=goal, lesson=f"step error: {e}"))
                continue
    finally:
        set_step_type(_prev_step)
    return brief
```

with:

```python
            except Exception as e:                             # graceful: never raise out of a step
                brief.notes.append(Note(goal=goal, lesson=f"step error: {e}"))
                continue
        log_investigate_stop_auto(stop_reason, len(data_seed), len(probed))
    finally:
        set_step_type(_prev_step)
    return brief
```

- [ ] **Step 10: Run the new + full investigate suite to verify green**

Run: `uv run pytest tests/test_investigate.py tests/test_investigate_doc_grounding.py tests/test_investigate_merge.py -v`
Expected: all PASS — new probe/inert/stop-trace tests green AND every pre-existing investigate test still green (regression guard: flag-off Brief unchanged).

- [ ] **Step 11: Commit**

```bash
git add agent/investigate.py tests/test_investigate.py
git commit -m "feat(investigate): probe seed data-paths before stopping (flag-gated)

Priority doc-read > data-probe > router; probe-once; record probed paths
into brief.env['data_paths']; emit investigate_stop trace. Inert when no
data_paths are supplied (ECOM_INVESTIGATE_DATA_PATHS=0)."
```

---

## Task 5: Part A — pipeline seed construction + call-site wiring

**Files:**
- Modify: `agent/pipeline.py` (add `_data_path_seed` helper; pass `data_paths=` at the `investigate(...)` call ~L400)
- Test: `tests/test_pipeline_interpreted.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline_interpreted.py` (end of file):

```python
def test_data_path_seed_empty_when_flag_off(monkeypatch):
    from agent import pipeline
    monkeypatch.delenv("ECOM_INVESTIGATE_DATA_PATHS", raising=False)
    assert pipeline._data_path_seed("read /proc/payments/p_1.json", "t01") == []


def test_data_path_seed_unions_literals_and_deep_read(monkeypatch, tmp_path):
    from agent import pipeline, learned_store
    monkeypatch.setenv("ECOM_INVESTIGATE_DATA_PATHS", "1")
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    learned_store.append_prephase_deep_read("tZ", ["/proc/ledger", "orders"])
    seed = pipeline._data_path_seed("inspect /proc/payments now", "tZ")
    assert "/proc/payments" in seed      # instruction path-literal
    assert "/proc/ledger" in seed        # learned absolute path
    assert "orders" not in seed          # non-absolute (table name) excluded
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_interpreted.py -k data_path_seed -v`
Expected: FAIL — `AttributeError: module 'agent.pipeline' has no attribute '_data_path_seed'`.

- [ ] **Step 3: Add the `_data_path_seed` helper**

Insert into `agent/pipeline.py` immediately after `_enrich_prim_error` (after its `return err`, ~L110):

```python
def _data_path_seed(instruction: str, task_id: str) -> list[str]:
    """Deterministic data-path seed for INVESTIGATE: absolute-path literals in the
    instruction UNION learned prephase_deep_read absolute paths. Empty (no-op) unless
    ECOM_INVESTIGATE_DATA_PATHS=1. Bounded by ECOM_PREPHASE_PATH_LITERALS — no wandering.
    Imports are function-level: orchestrator imports pipeline, so a module-level import
    here would be a cycle; by call time orchestrator is fully loaded."""
    import os as _os
    if _os.environ.get("ECOM_INVESTIGATE_DATA_PATHS", "0") != "1":
        return []
    from .orchestrator import _extract_path_literals
    from .learned_store import load_prephase_deep_read
    seed = list(_extract_path_literals(instruction))
    for d in load_prephase_deep_read(task_id):
        if d.startswith("/") and d not in seed:
            seed.append(d)
    return seed
```

- [ ] **Step 4: Run the helper tests to verify green**

Run: `uv run pytest tests/test_pipeline_interpreted.py -k data_path_seed -v`
Expected: both PASS.

- [ ] **Step 5: Wire the seed into the `investigate(...)` call**

In `agent/pipeline.py` (~L400), replace:

```python
            brief = investigate(vm, intent, seed=facts, oracle=_oracle)
```

with:

```python
            brief = investigate(vm, intent, seed=facts, oracle=_oracle,
                                data_paths=_data_path_seed(instruction, task_id))
```

- [ ] **Step 6: Verify the wider pipeline suite still passes**

Run: `uv run pytest tests/test_pipeline_interpreted.py tests/test_pipeline_investigate.py -v`
Expected: all PASS (flag defaults off ⇒ `_data_path_seed` returns `[]` ⇒ `investigate` behaviour unchanged).

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "feat(pipeline): seed INVESTIGATE with instruction+learned data-paths (flag-gated)"
```

---

## Task 6: Docs — env var + iwiki refresh (MANDATORY)

**Files:**
- Modify: `CLAUDE.md` (env-var table), `agent/CLAUDE.md` (INVESTIGATE env-var list)
- Regenerate: `docs/wiki/` pages for `agent/investigate.py` and `agent/pipeline.py`

- [ ] **Step 1: Document the flag in the root `CLAUDE.md`**

In `CLAUDE.md`, in the env-var table, add a row immediately after the `ECOM_MODEL_INVESTIGATE` row:

```markdown
| `ECOM_INVESTIGATE_DATA_PATHS` | `1` → INVESTIGATE probes seed data-paths (instruction absolute-path literals ∪ learned `prephase_deep_read` paths) into `brief.env["data_paths"]` before stopping; `sufficient()` then requires every seed probed (or step budget). Default `0` → no seed, no probe, pre-feature behaviour. Emits an `investigate_stop` trace record either way for A/B measurement. |
```

- [ ] **Step 2: Document the flag in `agent/CLAUDE.md`**

In `agent/CLAUDE.md`, in the "Key env vars" bullet list, extend the INVESTIGATE bullet by appending `/ ECOM_INVESTIGATE_DATA_PATHS` to the existing list:

Replace:

```markdown
- `ECOM_INVESTIGATE_ENABLED` / `ECOM_INVESTIGATE_MAX_STEPS` / `ECOM_INVESTIGATE_ORACLE_K` / `ECOM_MODEL_INVESTIGATE` — INVESTIGATE phase controls (see root `../CLAUDE.md`)
```

with:

```markdown
- `ECOM_INVESTIGATE_ENABLED` / `ECOM_INVESTIGATE_MAX_STEPS` / `ECOM_INVESTIGATE_ORACLE_K` / `ECOM_MODEL_INVESTIGATE` / `ECOM_INVESTIGATE_DATA_PATHS` — INVESTIGATE phase controls (see root `../CLAUDE.md`)
```

- [ ] **Step 3: Regenerate the affected wiki pages**

Invoke the `iwiki:iwiki-ingest` skill for the two changed sources:

```
iwiki:iwiki-ingest agent/investigate.py
iwiki:iwiki-ingest agent/pipeline.py
```

- [ ] **Step 4: Lint the docs graph**

Invoke the `iwiki:iwiki-lint` skill.
Expected: no broken `[[refs]]`, no new orphan/stale pages introduced by the change.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md agent/CLAUDE.md docs/wiki
git commit -m "docs: document ECOM_INVESTIGATE_DATA_PATHS + refresh iwiki pages"
```

---

## Task 7: Full verification

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all tests PASS (no regressions). If any pre-existing red appears, confirm it is the known stale fixture `test_t09_replay_matches_known_good` (a known pre-existing red per project memory) and nothing else.

- [ ] **Step 2: Smoke-check the flag end-to-end (manual, optional)**

Run a single task with the flag on and inspect the trace for the new record:

```bash
ECOM_INVESTIGATE_DATA_PATHS=1 make task TASKS='t38'
```

Expected: the run completes; the task's trace JSONL contains an `investigate_stop` record with a `reason` and `data_paths_total`/`data_paths_probed` counts. (No assertion — this is the A/B measurement hook.)

- [ ] **Step 3: Final commit (if Step 2 produced artifacts you want to keep, otherwise skip)**

```bash
git status   # confirm a clean tree or only intended trace artifacts
```

---

## Self-Review

**Spec coverage:**
- A1 Configuration (flag, default 0, inert) → Task 5 (`_data_path_seed` gate) + Task 4 (`data_paths=None` inert path) + Task 6 (docs). ✓
- A2 Seed construction (literals ∪ deep_read /-paths, function-level import) → Task 5 Step 3. ✓
- A3 `investigate()` signature (`data_paths` param) → Task 4 Step 4. ✓
- A4 Forced data-probe (priority doc>data>router, read/list heuristic, probe-once, env record) → Task 3 Step 3 + Task 4 Steps 6,8. ✓
- A5 Stop condition (doc-refs AND all probed, ceiling unchanged) → Task 3 Step 4 + Task 4 Step 9c. ✓
- A6 Trace signal (`investigate_stop` reason+counts) → Task 2 + Task 4 Steps 7,9a,9b,9d. ✓
- B1 CONTRACT on lint messages (`compute(?: step)?` + fallback scan, contract()-gated) → Task 1 Step 3. ✓
- Testing (Part A + B) → Tasks 1,3,4,5 tests. ✓
- Files touched / Non-goals (ceiling not raised; tables not probed; doc-ref mechanism untouched; inert when off) → respected: no `_MAX_STEPS` change; `_forced_data_probe` skips non-`/` via `_data_path_seed` filter; `_forced_doc_read`/`_ground_doc_refs` untouched. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/vague steps — every code step shows full code; every run step shows the command + expected result. ✓

**Type/name consistency:** `_data_path_seed(instruction, task_id)`, `_forced_data_probe(data_paths, probed)` returns `{"tool","args","_seed"}`, `sufficient(intent, env, data_paths=None, probed=None)`, `log_investigate_stop(reason, data_paths_total, data_paths_probed)` / `log_investigate_stop_auto(reason, total, probed)`, env key `brief.env["data_paths"]`, flag `ECOM_INVESTIGATE_DATA_PATHS` — used identically across all tasks. ✓
