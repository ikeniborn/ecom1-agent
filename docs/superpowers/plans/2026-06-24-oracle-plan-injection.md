---
review:
  plan_hash: 40271f6328a47a9b
  spec_hash: de8fd57ee094020d
  last_run: 2026-06-24
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: verifiability
      severity: WARNING
      section: "### Task 1 / Step 5"
      section_hash: null
      text: >-
        Removing the guard makes run_pipeline call _oracle.retrieve(instruction)
        in BOTH modes. The existing test test_run_pipeline_builds_brief_then_plan
        does NOT monkeypatch _new_oracle, so post-fix it triggers a real retrieve()
        → an Ollama embed attempt. The failure is swallowed by the try/except
        (oracle_atoms=[], _oracle=None) so the test stays green, but a hidden
        network I/O is introduced into a unit test. Non-blocking; if it slows or
        flakes, add monkeypatch.setattr(pipeline,"_new_oracle",...) to that test.
      verdict: open
      verdict_at: null
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-24-oracle-plan-injection-design.md
result_check:
  verdict: OK
  plan_hash: 40271f6328a47a9b
  last_run: 2026-06-24
  note: >-
    All plan steps DONE (Step1 test + Step3 guard removal in diff; Step2/4/5 runs,
    Step6 commit e5748c8). MISSING=0, PARTIAL=0. EXCESS [WARNING]: data/heuristics/t01.*
    and data/learned/t01.yaml were swept into e5748c8 by a shared index (concurrent
    main.py run) — degenerate "count rows" churn, NOT part of this plan. Recommend
    amending e5748c8 to drop the three t01 files when the concurrent run is idle.
    Spec R1/R3/R4/R6 + SC3 covered; intent doc absent (chain.intent=null).
---

# Oracle → PLAN injection regression fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the knowledge oracle's validated atoms reach the PLAN prompt when `ECOM_INVESTIGATE_ENABLED=1` (the default), by removing the guard that only populated `oracle_atoms` in the legacy INVESTIGATE-off path.

**Architecture:** Single-guard removal in `agent/pipeline.run_pipeline`. `oracle.retrieve(instruction)` now runs in both modes and feeds `oracle_atoms` into `run_plan`, which renders the "VALIDATED KNOWLEDGE — APPLY" block via `build_oracle_block`. INVESTIGATE's independent per-step retrieval is untouched.

**Tech Stack:** Python 3.12, pytest, `uv`. Test doubles: `MockVMSpy`, `monkeypatch`.

## Global Constraints

- Do NOT edit `data/prompts/*` — project rule: task behaviour flows through LEARN/oracle, never prompt patches.
- Do NOT touch `data/oracle/embeddings.json` or its format — verified correct, out of scope.
- Surgical change: only the dead `if not _investigate_on:` conditional around the `retrieve` call. The `_investigate_on` variable stays (still used later at the INVESTIGATE branch).
- Run tests with `uv run pytest` (uv auto-loads `.env`).

---

### Task 1: Inject oracle atoms into PLAN under INVESTIGATE on

**Files:**
- Modify: `agent/pipeline.py:312-318` (the oracle-init block in `run_pipeline`)
- Test: `tests/test_pipeline_investigate.py` (append one test)

**Interfaces:**
- Consumes: `pipeline._new_oracle() -> KnowledgeOracle` (existing); `oracle.retrieve(instruction) -> list[Atom]` (existing); `pipeline.investigate(...)` and `agent.reason.run_plan(intent, facts, learn_ctx, prev_error, *, token_out, oracle_atoms, observed, brief_block)` (existing signatures).
- Produces: no new public symbols. Behaviour change only — `run_plan` receives a non-empty `oracle_atoms` when atoms match, regardless of `ECOM_INVESTIGATE_ENABLED`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_investigate.py`:

```python
def test_run_pipeline_injects_oracle_atoms_into_plan(monkeypatch):
    """Regression: with INVESTIGATE on (default), the oracle's validated atoms
    must still reach run_plan via oracle_atoms (the guard previously dropped them)."""
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "1")
    captured = {}

    class _FakeOracle:
        def retrieve(self, task_text, *a, **k):
            return ["ATOM-SENTINEL"]   # non-empty stand-in for a matched atom

    monkeypatch.setattr(pipeline, "_new_oracle", lambda: _FakeOracle())
    monkeypatch.setattr(pipeline, "investigate",
                        lambda *a, **k: Brief())          # keep loop trivial
    monkeypatch.setattr(pipeline, "load_entries", lambda tid: [])
    monkeypatch.setattr(pipeline, "_ilearn", lambda *a, **k: None)

    intent = IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], answer_shape={})
    monkeypatch.setattr("agent.reason.run_intent",
                        lambda facts, instruction, token_out=None, learn_ctx=None: intent)

    def fake_run_plan(intent, facts, learn_ctx, prev_error, token_out=None,
                      oracle_atoms=None, observed=None, brief_block=None):
        captured["oracle_atoms"] = oracle_atoms
        from agent.ir_models import PlanIR
        return PlanIR(decision={"branches": [], "default_label": "ok"},
                      answer={"ok": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}})
    monkeypatch.setattr("agent.reason.run_plan", fake_run_plan)

    pipeline.run_pipeline(MockVMSpy({}), instruction="cite fraud payments",
                          task_id="tZ", agents_md_text="", facts=None)
    assert captured["oracle_atoms"] == ["ATOM-SENTINEL"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_investigate.py::test_run_pipeline_injects_oracle_atoms_into_plan -v`
Expected: FAIL — `assert [] == ['ATOM-SENTINEL']` (guard leaves `oracle_atoms` empty under INVESTIGATE on).

- [ ] **Step 3: Remove the guard (minimal implementation)**

In `agent/pipeline.py`, the oracle-init block, replace:

```python
    _investigate_on = os.environ.get("ECOM_INVESTIGATE_ENABLED", "1") != "0"
    oracle_atoms: list = []
    _oracle = None
    try:
        _oracle = _new_oracle()
        if not _investigate_on:
            oracle_atoms = _oracle.retrieve(instruction)   # legacy whole-instruction dump
    except Exception:
        _oracle = None
```

with:

```python
    _investigate_on = os.environ.get("ECOM_INVESTIGATE_ENABLED", "1") != "0"
    oracle_atoms: list = []
    _oracle = None
    try:
        _oracle = _new_oracle()
        oracle_atoms = _oracle.retrieve(instruction)   # inject validated atoms into PLAN (both modes)
    except Exception:
        _oracle = None
```

(Only the `if not _investigate_on:` line is dropped and its body de-indented. `_investigate_on` stays — it still gates the INVESTIGATE branch further down.)

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/test_pipeline_investigate.py::test_run_pipeline_injects_oracle_atoms_into_plan -v`
Expected: PASS.

- [ ] **Step 5: Run the full investigate/oracle/pipeline test set (no regression)**

Run: `uv run pytest tests/test_pipeline_investigate.py tests/test_pipeline_v2.py tests/test_oracle_retrieve.py -v`
Expected: all PASS. In particular `test_run_pipeline_disabled_skips_investigate` and `test_run_pipeline_builds_brief_then_plan` stay green (the change does not alter the INVESTIGATE-off path's observable behaviour, and adds the eager retrieve to the on-path).

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_investigate.py
git commit -m "fix(pipeline): inject oracle atoms into PLAN when INVESTIGATE on

oracle_atoms was only populated under \`if not _investigate_on\`, so with
INVESTIGATE on (default) PLAN received []. Drop the guard: retrieve in both
modes so build_oracle_block renders the validated-knowledge block.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification (whole-plan, after Task 1)

1. **Automated (done in Task 1):** new test asserts non-empty `oracle_atoms` to `run_plan` under INVESTIGATE on; SC2/SC3 covered by the existing-suite run in Step 5.
2. **Manual trace (SC1, optional but recommended):** run an oracle-relevant task (e.g. t51) with INVESTIGATE on and `ECOM_LOG_LEVEL=DEBUG`, then confirm the "VALIDATED KNOWLEDGE — APPLY" block is present in the PLAN prompt in the JSONL trace:
   ```bash
   make task TASKS='t51'
   # then grep the run's trace for the rendered block
   grep -l "VALIDATED KNOWLEDGE" logs/*/t51*.jsonl
   ```
   Expected: at least one PLAN entry contains the block (pre-fix: none under INVESTIGATE on).

## Spec → Task coverage

- R1, R3, R4, R6 (root cause + fix) → Task 1, Steps 3–4.
- R5 (investigate channel unchanged) → Task 1, Step 5 (regression guard).
- R7 (safety: `retrieve` honours disables / embed failure, `_oracle` not consumed) → preserved by keeping the `try/except` and passing `_oracle` to `investigate` unchanged.
- R8 (cost) → inherent in the eager retrieve; no code beyond Step 3.
- R2, R9, R10 (red herring / rejected B / out of scope) → no task by design.
- SC1 → Verification step 2. SC2, SC3 → Task 1, Step 5.
