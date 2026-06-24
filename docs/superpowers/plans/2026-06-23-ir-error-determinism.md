---
chain:
  intent: docs/superpowers/intents/2026-06-23-ir-error-determinism-intent.md
  spec:   docs/superpowers/specs/2026-06-23-ir-error-determinism-design.md
review:
  plan_hash: fc6acc7d56251240
  spec_hash: 0acea807872811e2
  last_run: 2026-06-23
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
      section: "Task 3: B — deterministic terminal outcome from outcome_space"
      section_hash: be39f7c47c4d4852
      text: >-
        Spec §B (lines 143-147) requires a "mid-loop unrecoverable step error with cycle
        budget left" branch: when outcome_space declares NO negative, do NOT answer an
        out-of-space outcome — route to _ilearn and retry until the budget exhausts
        ("refuse→iLEARN if no valid negative"). The plan's Task 3 only swaps the
        loop-exhaust/break terminal with `negative_outcome_by_precedence(...) or
        "OUTCOME_NONE_CLARIFICATION"`. The fallback-to-literal still emits the hardcoded
        OUTCOME_NONE_CLARIFICATION for a task whose space declares no negative — exactly the
        out-of-space answer the spec mid-loop clause says must not be emitted. The branch is
        neither implemented nor tested by the plan.
      verdict: fixed
      verdict_at: 2026-06-23
      resolution: >-
        Spec §B softened (now "Break decisions are unchanged; B touches only the terminal
        outcome"; the defensive OUTCOME_NONE_CLARIFICATION floor is declared the honest
        terminal when a space lists no negative — an INTENT under-specification, not a
        pipeline choice). Plan Task 3 Step 3 now states "Per the softened spec §B, NO break
        decision changes — B only swaps the terminal outcome; every existing hard break
        still breaks, and _ilearn still fires before each." Spec↔plan aligned.
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "Task 3: B — deterministic terminal outcome from outcome_space"
      section_hash: be39f7c47c4d4852
      text: >-
        Spec Testing (lines 169-172) lists two B integration assertions that the plan's
        Task 3 Step 1 does not cover: (a) "a terminal break with outcome_space lacking
        CLARIFICATION yields a valid in-space negative", and (b) "an unrecoverable error
        with no negative in space drives iLEARN (not an out-of-space answer)". Task 3's
        tests exercise only the pure helper `negative_outcome_by_precedence` in isolation;
        neither integration path through the pipeline terminal is asserted.
      verdict: fixed
      verdict_at: 2026-06-23
      resolution: >-
        Plan Task 3 Step 1 now adds the run_pipeline integration test
        test_terminal_emits_in_space_negative_on_exhaust, asserting the terminal emits the
        in-space negative OUTCOME_NONE_UNSUPPORTED on loop exhaust for a space with
        UNSUPPORTED but no CLARIFICATION — matching the (now single) spec B-integration
        assertion (spec Testing lines 177-180). Plumbing verified against real source:
        run_pipeline signature, call_llm_raw + _ilearn patch targets, learned_store._LEARNED_DIR
        monkeypatch all exist and mirror tests/test_pipeline_decide.py. Step 4 expected
        updated to 5 tests.
    - id: F-003
      phase: coverage
      severity: INFO
      section: "Task 5: Update architecture docs"
      section_hash: 76fb88823a8bf510
      text: >-
        Task 5 (update agent/CLAUDE.md + root CLAUDE.md) has no anchor in the spec — the
        spec declares no doc-update requirement. It traces instead to the project's
        mandatory "Keep Docs Current" CLAUDE.md instruction, so it is a legitimate plan step
        rather than scope creep. Noted for traceability only.
      verdict: wontfix
      verdict_at: 2026-06-23
      resolution: >-
        By design — Task 5 has no spec anchor because the spec declares no doc-update
        requirement; it traces to the project "Keep Docs Current" CLAUDE.md rule. Legitimate,
        documented; INFO/traceability only.
    - id: F-004
      phase: verifiability
      severity: INFO
      section: "Task 5: Update architecture docs"
      section_hash: 76fb88823a8bf510
      text: >-
        Task 5 Steps 1-2 are doc edits with no explicit verification command (no grep/inspect
        DoD). The required content is described concretely, so it is inspectable, but unlike
        every other step there is no Run:/Expected: anchor. Acceptable for doc steps; advisory.
      verdict: wontfix
      verdict_at: 2026-06-23
      resolution: >-
        By design — prose/doc-edit steps appropriately carry no Run:/Expected: command; the
        described content is inspectable. Advisory only.
    - id: F-005
      phase: consistency
      severity: INFO
      section: "Task 3: B — deterministic terminal outcome from outcome_space"
      section_hash: be39f7c47c4d4852
      text: >-
        Internal line-range off-by-one: Task 3 Step 3 prose says "replace the
        loop-exhaust/break terminal at pipeline.py:492-495", while the Task 3 Files header
        and the spec cite pipeline.py:492-494 (the real `return` block spans 492-494). One
        citation reads :495. Advisory.
      verdict: fixed
      verdict_at: 2026-06-23
      resolution: >-
        Typo corrected — Task 3 Step 3 now reads pipeline.py:492-494, consistent with the
        Files header and the spec.
---

# IR error→outcome determinism (A+B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a malformed IR or an unresolved required reference become a precise iLEARN signal or a valid in-space outcome — never a silent wrong answer.

**Architecture:** Three surgical extensions to the deterministic exoskeleton (model proposes, code disposes): A1 a pre-interpret structural lint in `interpreter.py`; A2 a one-line un-discard of the already-computed unresolved-ref set in `verify.py`; B a precedence helper + terminal-outcome swap in `pipeline.py`. No new IR. No prompt changes. `verify()` stays the sole deterministic pre-answer gate.

**Tech Stack:** Python 3.12, Pydantic v2 IR models (`agent/ir_models.py`), pytest, `uv` runner. Branch `dev/ir-error-determinism` (base + PR target `determinism`).

## Global Constraints

- No task-specific knowledge in `data/prompts/*.md` — task knowledge flows only through LEARN. These are code-side determinism fixes, not prompt patches.
- B adds NO new IR surface — derive from existing `intent.outcome_space`; no new `IntentSpec`/`PlanIR` field.
- Surgical changes only: every changed line traces to A1, A2, or B.
- `vm.answer` is called exactly once per task; `verify()` remains the sole deterministic pre-answer quality gate (no LLM-graded check added).
- A1/A2/B intentionally raise / hard-fail — that IS the iLEARN signal (the inverse of grounding/decide/format-gate, which never raise).
- B's negative-outcome precedence mirrors `decide.unsupported_or_clarify`: `OUTCOME_NONE_UNSUPPORTED` outranks `OUTCOME_NONE_CLARIFICATION`.
- Each commit message ends with the trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: A1 — absolute-path lint gate

**Files:**
- Modify: `agent/interpreter.py` (add `lint_paths_absolute`; call it in `interpret()` after `lint_security_first`, interpreter.py:334)
- Test: `tests/test_interpreter.py`

**Interfaces:**
- Produces: `lint_paths_absolute(plan: PlanIR) -> None` — raises `InterpretError` on a literal relative `path`/`root`; returns `None` otherwise.
- Consumes: `PlanIR` / `Step` (`agent/ir_models.py`), `InterpretError` (already defined in `agent/interpreter.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_interpreter.py`:

```python
def test_lint_paths_absolute_rejects_relative_list_path():
    import pytest
    from agent.interpreter import InterpretError, lint_paths_absolute
    from agent.ir_models import PlanIR, Step
    plan = PlanIR(discovery=[Step(rpc="List", args={"path": "."})],
                  decision={"branches": [], "default_label": "d"},
                  answer={"d": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}})
    with pytest.raises(InterpretError) as ei:
        lint_paths_absolute(plan)
    assert "absolute" in str(ei.value) and "List" in str(ei.value)


def test_lint_paths_absolute_rejects_relative_find_root():
    import pytest
    from agent.interpreter import InterpretError, lint_paths_absolute
    from agent.ir_models import PlanIR, Step
    plan = PlanIR(discovery=[Step(rpc="Find", args={"root": "docs", "name": "*.md"})],
                  decision={"branches": [], "default_label": "d"},
                  answer={"d": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}})
    with pytest.raises(InterpretError) as ei:
        lint_paths_absolute(plan)
    assert "root" in str(ei.value)


def test_lint_paths_absolute_allows_absolute_and_dollar_ref():
    from agent.interpreter import lint_paths_absolute
    from agent.ir_models import PlanIR, Step
    plan = PlanIR(
        discovery=[Step(rpc="Read", args={"path": "/proc/catalog/A.json"}),
                   Step(rpc="Stat", args={"path": "$bound_path"})],
        decision={"branches": [], "default_label": "d"},
        answer={"d": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}})
    assert lint_paths_absolute(plan) is None   # no raise: absolute literal + $ref skipped


def test_interpret_rejects_relative_path_before_vm():
    import pytest
    from agent.interpreter import InterpretError, interpret
    from agent.ir_models import PlanIR, Step
    from agent.mock_vm_spy import MockVMSpy
    plan = PlanIR(discovery=[Step(rpc="List", args={"path": "."})],
                  decision={"branches": [], "default_label": "d"},
                  answer={"d": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}})
    with pytest.raises(InterpretError) as ei:
        interpret(plan, _INTENT, MockVMSpy({}), None)
    assert "absolute" in str(ei.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_interpreter.py -k "paths_absolute or relative_path_before_vm" -v`
Expected: FAIL — `ImportError: cannot import name 'lint_paths_absolute'`.

- [ ] **Step 3: Implement `lint_paths_absolute` and wire it into `interpret`**

In `agent/interpreter.py`, add this helper next to `lint_security_first` (after the `lint_security_first` function, before `repair_sql_stdin`):

```python
_PATH_ARG_KEYS = ("path", "root")


def lint_paths_absolute(plan: PlanIR) -> None:
    """A1: a literal relative `path`/`root` in any step is a malformed plan — raise so the
    pipeline routes to iLEARN with a precise message instead of dead-ending at the VM's
    'must be absolute' error. Only literal args are checked; a $ref is resolved from env
    at runtime and is not lintable here. Mirrors repair_sql_stdin's step iteration."""
    for st in list(plan.discovery) + list(plan.ops):
        for key in _PATH_ARG_KEYS:
            v = st.args.get(key)
            if isinstance(v, str) and v and not v.startswith("$") and not v.startswith("/"):
                raise InterpretError(
                    f"step '{st.rpc}' arg '{key}': path must be absolute "
                    f"(got {v!r}); use an absolute path under /proc, /docs, /bin, ..."
                )
```

Then in `interpret()` (interpreter.py:334), add the call immediately after the existing `lint_security_first(plan)` line:

```python
def interpret(plan: PlanIR, intent: IntentSpec, vm, facts=None) -> InterpretResult:
    lint_security_first(plan)
    lint_paths_absolute(plan)
    from .trace import set_step_type
    ...
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_interpreter.py -k "paths_absolute or relative_path_before_vm" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(interpreter): A1 absolute-path lint gate (relative path -> iLEARN)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: A2 — unresolved required record_path hard-fail in verify

**Files:**
- Modify: `agent/verify.py:39-43`
- Test: `tests/test_verify.py` (add 3 tests; update 1 existing)

**Interfaces:**
- Consumes: `_project_required_refs(intent, outcome, env) -> tuple[list[str], list[str]]` (already imported in `verify.py`). The 2nd element is the unresolved-source list, currently discarded.
- Produces: no new symbol — `verify()` now returns `(False, reason)` when the 2nd element is non-empty.

- [ ] **Step 1: Write the failing tests + update the bug-encoding test**

Append to `tests/test_verify.py`:

```python
def test_i1_unresolved_required_record_path_fails_on_ok():
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$basket.record_path"}]})
    # env has no `basket` -> $basket.record_path resolves to None (unresolved source)
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]))
    ok, err = verify(res, intent)
    assert not ok and "resolve-before-cite" in err


def test_i1_unresolved_required_record_path_fails_on_deny():
    intent = _intent(required_refs={"OUTCOME_DENIED_SECURITY": [
        {"kind": "record_path", "source": "$basket.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]))
    ok, err = verify(res, intent)
    assert not ok and "$basket.record_path" in err


def test_i1_resolved_required_record_path_passes():
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$basket.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK",
                                 refs=["/proc/baskets/basket_019.json"]),
                  env={"basket": {"record_path": "/proc/baskets/basket_019.json"}})
    ok, err = verify(res, intent)
    assert ok, err
```

Update the existing `test_i1_ok_with_all_required_refs_passes` (it currently passes with an UNRESOLVED record_path — the exact bug A2 fixes). Bind the source in `env` so the record_path genuinely resolves:

```python
def test_i1_ok_with_all_required_refs_passes():
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "policy_doc", "path": "/docs/counting.md"},
        {"kind": "record_path", "source": "$row.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK",
                                 refs=["/docs/counting.md", "/proc/catalog/A.json"]),
                  env={"row": {"record_path": "/proc/catalog/A.json"}})
    ok, err = verify(res, intent)
    assert ok, err
```

- [ ] **Step 2: Run the tests to verify the new ones fail (and the updated one is correct)**

Run: `uv run pytest tests/test_verify.py -k "required_record_path or all_required_refs" -v`
Expected: the two `*_fails_*` tests FAIL (verify currently returns `ok=True` — the unresolved source is silently dropped); `test_i1_resolved_required_record_path_passes` and the updated `test_i1_ok_with_all_required_refs_passes` PASS.

- [ ] **Step 3: Stop discarding the unresolved-source set**

In `agent/verify.py`, replace the I1 block at lines 39-43:

```python
    required_vals, _missing_src = _project_required_refs(intent, ans.outcome, env)
    absent = [v for v in required_vals if v not in ans.refs]
    if absent:
        return False, (f"I1: required ref(s) {absent!r} absent from "
                       f"{ans.outcome} answer")
```

with:

```python
    required_vals, missing_src = _project_required_refs(intent, ans.outcome, env)
    if missing_src:
        return False, (f"I1: required ref source(s) {missing_src!r} did not resolve on "
                       f"{ans.outcome} answer (resolve-before-cite)")
    absent = [v for v in required_vals if v not in ans.refs]
    if absent:
        return False, (f"I1: required ref(s) {absent!r} absent from "
                       f"{ans.outcome} answer")
```

- [ ] **Step 4: Run the targeted tests, then the full verify suite**

Run: `uv run pytest tests/test_verify.py -v`
Expected: PASS (all, including the new 3 and the updated 1).

- [ ] **Step 5: Commit**

```bash
git add agent/verify.py tests/test_verify.py
git commit -m "feat(verify): A2 hard-fail on unresolved required record_path (all outcomes)

Stops verify I1 from silently dropping a declared required record_path whose
\$source did not bind; it now fails -> iLEARN (resolve-before-cite). Updates the
test that encoded the old vacuous-pass behaviour.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: B — deterministic terminal outcome from outcome_space

**Files:**
- Modify: `agent/pipeline.py` (add `negative_outcome_by_precedence`; swap the loop-exhaust/break terminal at pipeline.py:492-494)
- Test: `tests/test_pipeline_outcome.py` (new — unit tests for the helper + one `run_pipeline` integration test that the terminal actually uses it)

**Interfaces:**
- Produces: `negative_outcome_by_precedence(outcome_space) -> str | None` — first present of `["OUTCOME_NONE_UNSUPPORTED", "OUTCOME_NONE_CLARIFICATION"]`, else `None`.
- Consumes: `intent.outcome_space` (already in scope at the terminal — `intent` is guaranteed non-None past the INTENT-None guard at pipeline.py:319); `run_pipeline` + `Mock/MagicMock` LLM patching for the integration test (mirrors `tests/test_pipeline_decide.py`).

- [ ] **Step 1: Write the failing tests (helper unit tests + terminal integration test)**

Create `tests/test_pipeline_outcome.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from agent.pipeline import negative_outcome_by_precedence, run_pipeline


def test_precedence_prefers_unsupported():
    assert negative_outcome_by_precedence(
        ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION", "OUTCOME_NONE_UNSUPPORTED"]
    ) == "OUTCOME_NONE_UNSUPPORTED"


def test_precedence_clarification_when_only_it():
    assert negative_outcome_by_precedence(
        ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"]) == "OUTCOME_NONE_CLARIFICATION"


def test_precedence_none_when_no_negative():
    assert negative_outcome_by_precedence(
        ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"]) is None


def test_precedence_handles_empty_and_none():
    assert negative_outcome_by_precedence([]) is None
    assert negative_outcome_by_precedence(None) is None


@pytest.fixture
def _isolate(monkeypatch, tmp_path):
    # Mirror tests/test_pipeline_decide.py: skip the ReAct + oracle phases, isolate the
    # learned-rule store and the heuristics dir into tmp.
    from agent import learned_store
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")
    monkeypatch.setenv("ECOM_ORACLE_ENABLED", "0")
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


def test_terminal_emits_in_space_negative_on_exhaust(_isolate):
    # Loop exhausts via the identical-plan short-circuit. outcome_space lists UNSUPPORTED
    # but NOT CLARIFICATION -> the terminal must answer the in-space negative
    # OUTCOME_NONE_UNSUPPORTED (B), not the hardcoded CLARIFICATION.
    intent = json.dumps({
        "objective": "x", "desired_outcome": "OUTCOME_OK", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
        "constraints": [], "success_criteria": {}, "answer_shape": {},
        "required_refs": {"OUTCOME_OK": [{"kind": "policy_doc", "path": "/docs/never.md"}]},
    })
    # Plan authors OK with empty refs -> verify I1 fails (required /docs/never.md absent).
    plan = json.dumps({
        "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 5 AS cnt"]}, "bind": "raw"}],
        "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
        "decision": {"branches": [], "default_label": "ok"}, "ops": [],
        "answer": {"ok": {"message": "{row0.cnt} in stock", "outcome": "OUTCOME_OK", "refs": []}},
        "custom_extract": [],
    })

    def _seq(*items):
        it = iter(items)
        return lambda *a, **kw: next(it)

    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    # _ilearn patched to a no-op so it never consumes an LLM response from the sequence.
    # Sequence: intent, then the SAME plan twice — cycle 1 fails verify (missing required
    # ref), cycle 2 is identical -> short-circuit break -> single terminal answer.
    with patch("agent.pipeline._ilearn"), \
         patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, plan, plan)):
        m = run_pipeline(vm, instruction="q", task_id="t_term_neg",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_NONE_UNSUPPORTED"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pipeline_outcome.py -v`
Expected: FAIL — `ImportError: cannot import name 'negative_outcome_by_precedence'`.

- [ ] **Step 3: Implement the helper and swap the terminal outcome**

In `agent/pipeline.py`, add the helper near the other module-level helpers (e.g. right after `_is_retryable_vm_error`, ~line 95):

```python
def negative_outcome_by_precedence(outcome_space) -> "str | None":
    """B: pick a valid negative terminal outcome from the task's declared space, in the
    precedence decide.unsupported_or_clarify uses (UNSUPPORTED outranks CLARIFICATION).
    None when the space declares neither -> the caller keeps its defensive literal."""
    for o in ("OUTCOME_NONE_UNSUPPORTED", "OUTCOME_NONE_CLARIFICATION"):
        if o in (outcome_space or []):
            return o
    return None
```

Then replace the loop-exhaust/break terminal at pipeline.py:492-494:

```python
    save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", cycle)
    answer_once(last_error or "interpreter cycles exhausted", "OUTCOME_NONE_CLARIFICATION", [])
    return {"cycles_used": cycle, "outcome": "OUTCOME_NONE_CLARIFICATION",
            "status": "failure", "input_tokens": total_in, "output_tokens": total_out}
```

with:

```python
    term = negative_outcome_by_precedence(intent.outcome_space) or "OUTCOME_NONE_CLARIFICATION"
    save_last_run(task_id, "failure", term, cycle)
    answer_once(last_error or "interpreter cycles exhausted", term, [])
    return {"cycles_used": cycle, "outcome": term,
            "status": "failure", "input_tokens": total_in, "output_tokens": total_out}
```

Leave the INTENT-None hard-stop at pipeline.py:320-322 unchanged (it fires before `intent` exists — exempt from B). Per the softened spec §B, NO break decision changes — B only swaps the terminal outcome; every existing hard break (mutation landed / anti-loop guards / non-retryable VM error / empty-plan streak) still breaks, and `_ilearn` still fires before each.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pipeline_outcome.py -v`
Expected: PASS (5 tests — 4 helper unit tests + the terminal integration test).

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_outcome.py
git commit -m "feat(pipeline): B deterministic terminal outcome from outcome_space

Loop-exhaust/break terminal now selects a valid in-space negative outcome by
precedence (UNSUPPORTED > CLARIFICATION), falling back to the literal only when
the space declares neither. INTENT hard-stop stays exempt.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Regression + real benchmark validation

**Files:** none (verification only).

**Interfaces:** consumes Tasks 1-3.

- [ ] **Step 1: Run the full unit suite**

Run: `uv run pytest tests/ -q`
Expected: all green EXCEPT the known stale `test_t09_replay_matches_known_good` red (pre-existing, documented in project memory — NOT a regression). Confirm the 159 determinism tests (`test_format_gate` / `test_decide` / `test_grounding` / `test_pipeline_decide` / `test_pipeline_grounding` / `test_investigate_doc_grounding`) are green. If any OTHER test is red → STOP (Stop Rule: regression not understood).

- [ ] **Step 2: Run the real benchmark on the four tasks**

Run: `uv run python main.py t01 t10 t38 t50`
Capture the final ИТОГОВАЯ СТАТИСТИКА table from the run's `logs/<ts>/main.log`.

- [ ] **Step 3: Check against the intent's "Done when"**

Compare to the pre-change baseline (t01 0.00 / t10 1.00 / t38 0.00 / t50 0.00 = 25%):
- t01: outcome is no longer a cycle-1 terminal NONE on a relative-path crash (A1) — score shift OR a precise evidenced explanation that the remaining gap is upstream (e.g. fuzzy-match SQL still wrong).
- t50: no answer submitted with `/proc/baskets/...basket...json` missing — score shift OR evidenced upstream explanation (e.g. discovery still binds the wrong basket).
- t10: still 1.00 (no regression).
- t38: unchanged is acceptable (impossible-leg cap, per memory).

Record the verdict (observable shift vs evidenced-upstream) in the PR description. Note: the benchmark re-seeds per `StartRun`, so the exact failing record id may differ from `basket_019`.

---

### Task 5: Update architecture docs

**Files:**
- Modify: `agent/CLAUDE.md` (the per-task execution flow: lint, verify I1, terminal outcome)
- Modify: `CLAUDE.md` (root architecture section, the matching flow bullets)

**Interfaces:** none.

- [ ] **Step 1: Update `agent/CLAUDE.md`**

In the per-task execution flow, add to the **lint** bullet that `interpret()` now also runs `lint_paths_absolute(plan)` (A1: literal relative `path`/`root` → `InterpretError` → iLEARN). In the **verify** bullet, note I1 now hard-fails when a declared required `record_path` source did not resolve (A2: resolve-before-cite, all outcomes). In the loop-exhaust description, note the terminal outcome is selected from `intent.outcome_space` by precedence (B), INTENT hard-stop exempt.

- [ ] **Step 2: Mirror the same three notes in the root `CLAUDE.md` Architecture section**

Keep the wording aligned with `agent/CLAUDE.md` (the root file's flow bullets for lint / verify / loop-exhaust).

- [ ] **Step 3: (iwiki) regenerate affected wiki pages if the engine works**

Run: `Skill(iwiki:iwiki-ingest)` on `agent/interpreter.py`, `agent/verify.py`, `agent/pipeline.py`. If the iwiki engine is non-functional in this isolated env (per project memory), SKIP and rely on the CLAUDE.md updates above. Do not block.

- [ ] **Step 4: Commit**

```bash
git add agent/CLAUDE.md CLAUDE.md docs/wiki/ 2>/dev/null
git commit -m "docs: A1/A2/B IR error-determinism flow (lint + verify I1 + terminal outcome)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## HUMAN CHECKPOINT (from intent Autonomy Zones)

After Task 5, **halt before opening the PR into `determinism`** — the intent doc marks PR creation as no-autonomy / human-only. Present the benchmark verdict (Task 4) for human review first.
