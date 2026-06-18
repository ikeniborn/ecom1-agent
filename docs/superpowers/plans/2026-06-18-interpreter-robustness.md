---
review:
  plan_hash: df202d63b85a6feb
  spec_hash: 05bd146a260ec6cc
  last_run: 2026-06-18
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
      section: "Task F3: deterministic SQL->stdin repair + sql_stdin check (error) + runtime banner detect"
      section_hash: fbc37fd36565d032
      text: >-
        RESOLVED. Originally: plan seeded chk_sql_stdin as severity: warn, so lint() never
        raised (spec Testing Strategy implies "lint raises"). Fix (user-chosen root-cause):
        Task F3 now adds a deterministic pre-lint repair (interpreter.repair_sql_stdin) that
        rewrites every Exec /bin/sql step args->stdin before lint; chk_sql_stdin is seeded
        severity: error (spec-literal) and never fires on a real plan; the SQL-in-args corpus
        is preserved (repair transparent to PLAN, MockVMSpy fixture-key falls back to [stdin]);
        _plan_signature reads stdin so the no-progress guard still distinguishes queries; the
        runtime banner-detect remains a backstop. No deviation.
      verdict: fixed
      verdict_at: 2026-06-18
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "Task F8b: distill -> validate -> promote pipeline (gated off by default)"
      section_hash: b94842c6f707355c
      text: >-
        RESOLVED. Originally: plan wired only the gated distill call inline and documented
        HARNESS_VALIDATE_INLINE as "reserved for offline promotion" (spec says "default 1 when
        distill is on", inline validate->promote). Fix: Task F8b now wires the full inline
        path — _maybe_harness_distill validates the distilled candidate against (failing plan,
        last persisted known-good plan from data/heuristics/{tid}.plan.json) and promotes
        candidate->active on catches-bad AND not-flags-good; HARNESS_VALIDATE_INLINE=0 falls
        back to a warn-only candidate. Whole path gated by HARNESS_DISTILL=1 (default 0), so it
        cannot affect the core fixes. Matches spec F8. No deviation.
      verdict: fixed
      verdict_at: 2026-06-18
    - id: F-003
      phase: consistency
      severity: WARNING
      section: "Task F2: primitive_contract / primitive_exists / primitive_arity check kinds"
      section_hash: 84443eb9aa357cca
      text: >-
        F2 Step 3 defines `_LIST_CONSUMING = {"column", "sum_col", "count", "filter_rows"}` in
        harness.py but no handler references it — check_primitive_contract keys off
        spec.get("prim") / forbid_source, and the per-prim seeds in checks.yaml drive the
        checks. Dead constant; contradicts the project Simplicity-First / no-dead-code rule.
        Quality only — does not affect coverage or correctness.
      verdict: fixed
      verdict_at: 2026-06-18
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-18-interpreter-robustness-design.md
---

# Interpreter Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a correct PLAN over correct data never crash the interpreter, turn every type-incorrect PLAN into an actionable retryable signal, and grow the lint catalogue from validated lessons — so `t01` reliably reaches `OUTCOME_OK`.

**Architecture:** All changes land in deterministic links (`interpreter.py`, `primitives.py`, `pipeline.py`, `orchestrator.py`) plus two new pure-data files. A new `harness.py` holds a closed set of code-backed lint check-`kind` handlers; `interpreter.lint(plan)` dispatches active check-specs from `data/harness/checks.yaml`. No new LLM calls on the hot path; no `data/prompts/*.md` edits.

**Tech Stack:** Python 3, Pydantic v2 (`ir_models.py`), PyYAML, pytest. Deterministic interpreter over `MockVMSpy` for all unit tests.

---

## Design Decisions & Deviations From Spec

Read this before implementing — two points adjust the spec to honor the project's **no-regression** rule.

1. **F3 closes the `sql_stdin` brittleness at the root, keeping `chk_sql_stdin` spec-literal `error`.** `/bin/sql` is nondeterministic over `args` (diagnosis #6: the man-page appears "when SQL not delivered via stdin"); `stdin` is the reliable channel. A deterministic **pre-lint repair** (`interpreter.repair_sql_stdin`) rewrites every `Exec /bin/sql` step `args→stdin` before `lint`, so `chk_sql_stdin` (seeded `error`, as the spec's Testing Strategy implies "lint raises") never fires on a real plan, and the existing SQL-in-args corpus is preserved (the repair is transparent to PLAN; the MockVMSpy fixture-key falls back to `[stdin]`). `_plan_signature` is taught to read stdin so the no-progress guard still distinguishes queries. The runtime banner-detect stays as a backstop. No deviation.

2. **F8b wires the full inline distill→validate→promote per spec, gated off by default.** The "no false positive" reference is the **last persisted known-good plan** (`data/heuristics/{tid}.plan.json`, written only on a success path), so inline validation is feasible whenever the task has passed at least once; before that, `good_plan=None` and the candidate promotes on catches-bad alone. The whole path is gated by `HARNESS_DISTILL=1` (default `0`), so it cannot affect the core fixes' validation. `HARNESS_VALIDATE_INLINE=0` falls back to a warn-only candidate for an offline promote. This matches spec F8 ("HARNESS_VALIDATE_INLINE default 1 when distill is on").

3. **`interpret()` keeps its internal `lint_security_first(plan)` call** (line 210) as pure defense-in-depth. The new registry `lint(plan)` is called by the **pipeline** (replacing its `lint_security_first` call at `pipeline.py:302`). `harness.check_security_first` delegates to `lint_security_first` so there is one source of truth for the H3 check.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `agent/primitives.py` | modify | F1: list-op type guards + `run_primitive` existence guard |
| `agent/interpreter.py` | modify | F1: compute/custom_extract try-wrap; F3: `repair_sql_stdin` + runtime sql-banner detect; F8a: `lint(plan)` registry dispatcher |
| `agent/harness.py` | **create** | F8a/F2/F3: check-`kind` handlers, `load_checks`/`save_checks`; F8b: `distill`/`promote` |
| `agent/harness_validate.py` | **create** | F8b: `validate_check_via_grader` (catches-bad ∧ ¬flags-good) |
| `agent/pipeline.py` | modify | F2/F8a: swap `lint_security_first`→`lint`; F3: `repair_sql_stdin` before lint + `_plan_signature` stdin; F4: answer-once guard; F8b: gated distill→validate→promote hook |
| `agent/mock_vm_spy.py` | modify | F3: `exec` fixture-key fallback to `[stdin]` (repaired-call lookups) |
| `agent/orchestrator.py` | modify | F7: DOC_SELECT catalogue-gap log |
| `data/harness/checks.yaml` | **create** | F8a/F2/F3: seeded check-spec registry |
| `data/learned/t01.yaml` | modify | F6: method-not-value rule; deactivate misdirected `r003` |
| `data/oracle/atoms.yaml` | modify | F6: normalized-catalogue-match atom |
| `tests/test_primitives.py` | modify | F1 unit tests |
| `tests/test_interpreter.py` | modify | F1 + F3 runtime unit tests |
| `tests/test_harness.py` | **create** | F8a/F2/F3 registry + handler tests |
| `tests/test_harness_distill.py` | **create** | F8b distill/validate/promote tests |
| `tests/test_pipeline_interpreted.py` | modify | F4 + F5 lock tests |
| `tests/test_orchestrator.py` | modify | F7 gap-log test |
| `tests/test_learned_t01_method_rule.py` | **create** | F6 data-shape tests |
| `CLAUDE.md` (root) | modify | document `HARNESS_DISTILL`, `HARNESS_VALIDATE_INLINE` |

**Execution order (spec §Execution Order):** F1 → F8a → F2 → F3 → F4 → F5 → F6 → F7 → F8b → docs → live t01 run.

---

## Task F1: Compute crash → typed retryable InterpretError

**Files:**
- Modify: `agent/primitives.py:22-37`, `agent/primitives.py:57-58`
- Modify: `agent/interpreter.py:234-240`
- Test: `tests/test_primitives.py`, `tests/test_interpreter.py`

- [ ] **Step 1: Write the failing primitives tests**

Append to `tests/test_primitives.py`:

```python
def test_list_ops_reject_scalar_with_actionable_message():
    # F1: a list-consuming primitive handed a non-list (e.g. the output of `first`)
    # raises a clear TypeError naming the fix, not a cryptic AttributeError.
    import pytest
    with pytest.raises(TypeError, match=r"'column' expects list\[dict\]; use 'get'"):
        run_primitive("column", ["product_sku", "name"])
    with pytest.raises(TypeError, match=r"'sum_col' expects list\[dict\]"):
        run_primitive("sum_col", [{"a": 1}, "a"])
    with pytest.raises(TypeError, match=r"'filter_rows' expects list\[dict\]"):
        from agent.ir_models import PredExpr
        run_primitive("filter_rows", ["scalar", PredExpr(op="nonempty", lhs="$x")])


def test_list_ops_allow_none_as_empty():
    # None (empty rowset) stays valid -> [] / 0.0, preserving current semantics.
    assert run_primitive("column", [None, "c"]) == []
    assert run_primitive("sum_col", [None, "c"]) == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_primitives.py::test_list_ops_reject_scalar_with_actionable_message tests/test_primitives.py::test_list_ops_allow_none_as_empty -v`
Expected: FAIL — current `_column("product_sku", ...)` raises `AttributeError: 'str' object has no attribute 'get'`, not the matched `TypeError`.

- [ ] **Step 3: Add the list-op guard in `primitives.py`**

Replace `agent/primitives.py:22-37` (the `_sum_col` / `_column` / `_div` / `_filter_rows` block) with:

```python
def _require_rows(prim: str, rows: Any) -> list:
    """List-consuming primitives accept list[dict] (None -> empty). A scalar/dict
    (e.g. the output of `first`/`get`) is a contract error: raise a clear, actionable
    TypeError so F1's compute-wrap turns it into a retryable signal instead of a crash."""
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise TypeError(f"'{prim}' expects list[dict]; use 'get' for a single row")
    return rows


def _sum_col(rows: list[dict], col: str) -> float:
    return float(sum(_to_number(r.get(col)) for r in _require_rows("sum_col", rows)))


def _column(rows: list[dict], col: str) -> list:
    return [r.get(col) for r in _require_rows("column", rows)]


def _div(a: Any, b: Any) -> float:
    bn = _to_number(b)
    return _to_number(a) / bn if bn else 0.0


def _filter_rows(rows: list[dict], pred) -> list[dict]:
    return [r for r in _require_rows("filter_rows", rows) if evaluate(pred, dict(r))]
```

Replace `agent/primitives.py:57-58` (`run_primitive`) with:

```python
def run_primitive(name: str, args: list) -> Any:
    if name not in PRIMITIVES:
        raise KeyError(f"unknown primitive {name!r}")
    return PRIMITIVES[name](*args)
```

- [ ] **Step 4: Run the primitives tests to verify they pass**

Run: `uv run pytest tests/test_primitives.py -v`
Expected: PASS (including `test_registry_has_13_primitives`, `test_unknown_primitive_raises`, `test_rowset_primitives`).

- [ ] **Step 5: Write the failing interpreter test (run-15:08 reproduction)**

Append to `tests/test_interpreter.py`:

```python
def test_compute_listop_on_scalar_raises_interpret_error():
    # F1: reproduces run-15:08 — first() yields one dict, column() is a list-op.
    # The mismatch must surface as a retryable InterpretError (mutation_landed False),
    # not a bare AttributeError the pipeline misclassifies as a real-VM error.
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]): {"stdout": "product_sku\nSTO-1"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        compute=[
            {"prim": "first", "args": ["$rows"], "into": "first_row"},
            {"prim": "column", "args": ["$first_row", "product_sku"], "into": "names"},
        ],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    with pytest.raises(InterpretError) as ei:
        interpret(plan, _INTENT, vm)
    assert ei.value.mutation_landed is False
    assert "column" in str(ei.value)
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_interpreter.py::test_compute_listop_on_scalar_raises_interpret_error -v`
Expected: FAIL — interpret currently lets the bare `TypeError`/`AttributeError` escape (the `pytest.raises(InterpretError)` is not satisfied).

- [ ] **Step 7: Wrap the compute + custom_extract loops in `interpreter.py`**

Replace `agent/interpreter.py:234-240` with:

```python
    # 4. compute + custom_extract — a type-incorrect step (e.g. a list-op on a single
    #    dict) becomes a retryable InterpretError, never a bare crash the pipeline would
    #    misclassify as a real-VM error (F1). compute runs before any op, so
    #    mutation_landed is still False here -> the pipeline safely retries.
    from .primitives import run_parser, run_primitive
    for cs in plan.compute:
        try:
            cargs = [resolve(a, env) for a in cs.args]
            env[cs.into] = run_primitive(cs.prim, cargs)
        except (TypeError, AttributeError, KeyError, IndexError) as e:
            raise _refuse(f"compute step '{cs.prim}' failed: {e}", mutation_landed)
    for ce in plan.custom_extract:
        try:
            env[ce.into] = run_parser(ce.name, _payload(env.get(ce.input)), intent.params or {})
        except (TypeError, AttributeError, KeyError, IndexError) as e:
            raise _refuse(f"custom_extract '{ce.name}' failed: {e}", mutation_landed)
```

- [ ] **Step 8: Run the interpreter + primitives suites to verify green**

Run: `uv run pytest tests/test_interpreter.py tests/test_primitives.py -v`
Expected: PASS (all, including the new F1 tests).

- [ ] **Step 9: Commit**

```bash
git add agent/primitives.py agent/interpreter.py tests/test_primitives.py tests/test_interpreter.py
git commit -m "fix(interpreter): F1 — typed retryable InterpretError on compute contract failures

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F8a: Lint registry engine + security_first migration

**Files:**
- Create: `agent/harness.py`
- Create: `data/harness/checks.yaml`
- Modify: `agent/interpreter.py` (add `lint`)
- Modify: `agent/pipeline.py:254,302`
- Test: `tests/test_harness.py`

- [ ] **Step 1: Write the failing registry tests**

Create `tests/test_harness.py`:

```python
import pytest
from agent.ir_models import PlanIR
from agent import harness
from agent.interpreter import lint, InterpretError


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def _denied_after_business():
    return _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"},
                               {"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"}],
                  "default_label": "ok"},
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []},
                "deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )


def test_load_checks_missing_file_returns_empty(tmp_path):
    assert harness.load_checks(tmp_path / "nope.yaml") == []


def test_seeded_checks_parse_and_include_security_first():
    specs = harness.load_checks()                 # default repo path
    assert any(s.get("kind") == "security_first" for s in specs)


def test_check_security_first_handler_flags_bad_order():
    spec = {"id": "chk_security_first", "kind": "security_first"}
    assert harness.check_security_first(_denied_after_business(), spec)   # non-empty -> violation
    assert harness.check_security_first(_plan(), spec) == []              # clean -> no violation


def test_lint_blocks_on_active_error_violation(monkeypatch):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "security_first",
                                          "severity": "error", "status": "active"}])
    with pytest.raises(InterpretError):
        lint(_denied_after_business())
    lint(_plan())                                  # clean plan -> no raise


def test_lint_skips_unknown_kind(monkeypatch, capsys):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "no_such_kind",
                                          "severity": "error", "status": "active"}])
    lint(_plan())                                  # no raise
    assert "unknown check kind" in capsys.readouterr().out


def test_lint_candidate_is_warn_only(monkeypatch, capsys):
    monkeypatch.setattr(harness, "load_checks",
                        lambda *a, **k: [{"id": "c", "kind": "security_first",
                                          "severity": "error", "status": "candidate"}])
    lint(_denied_after_business())                 # candidate never blocks
    assert "warn" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_harness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.harness'` (and `cannot import name 'lint'`).

- [ ] **Step 3: Create `agent/harness.py` (engine + security_first handler)**

```python
"""Learnable lint registry: a CLOSED set of code-backed check `kind` handlers over a
data-driven catalogue (data/harness/checks.yaml).

The engine (handlers + the interpreter.lint dispatcher) is deterministic code and the
trust anchor; the catalogue is data that grows by validated promotion (F8). Handlers
are PURE: each takes (plan, check_spec) and returns a list of violation messages — they
never raise and never call vm.answer. interpreter.lint decides block-vs-warn from the
spec's status/severity. A new *kind* is a code change (rare); new *instances* of an
existing kind are learnable data (common).
"""
from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from .primitives import PRIMITIVES

_DEFAULT_CHECKS = Path(__file__).resolve().parent.parent / "data" / "harness" / "checks.yaml"


def load_checks(path=None) -> list[dict]:
    """Read the check-spec catalogue. Missing/corrupt file -> [] (lint degrades to a
    no-op, never crashes)."""
    p = Path(path or _DEFAULT_CHECKS)
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict)]


def save_checks(checks: list[dict], path=None) -> None:
    p = Path(path or _DEFAULT_CHECKS)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(checks, sort_keys=False, allow_unicode=True, width=100),
                 encoding="utf-8")


# --- kind handlers: (plan, spec) -> list[str] (pure; never raise) ----------

def check_security_first(plan, spec) -> list[str]:
    """H3 migrated: delegate to the interpreter's pure security-first check (single
    source of truth) and convert its raise into a violation list."""
    from .interpreter import lint_security_first, InterpretError
    try:
        lint_security_first(plan)
        return []
    except InterpretError as e:
        return [str(e)]


_HANDLERS = {
    "security_first": check_security_first,
}


def handler_for(kind):
    """Return the pure handler for a check `kind`, or None. An unknown kind is skipped
    with a logged warning by the dispatcher — adding a kind is a deliberate code change."""
    return _HANDLERS.get(kind)
```

- [ ] **Step 4: Add the `lint` dispatcher to `interpreter.py`**

Insert after `lint_security_first` (i.e. after `agent/interpreter.py:206`, before `def interpret`):

```python
def lint(plan: PlanIR) -> None:
    """Registry-driven plan-time lint (F8). Dispatches each non-inactive check-spec in
    data/harness/checks.yaml to its `kind` handler. An ACTIVE error-severity violation
    raises InterpretError (blocks); a `candidate` entry, or a `warn`-severity one, logs
    only. Unknown kinds / malformed specs / handler errors degrade to a logged no-op."""
    from . import harness
    for spec in harness.load_checks():
        if not isinstance(spec, dict) or spec.get("status") == "inactive":
            continue
        handler = harness.handler_for(spec.get("kind"))
        if handler is None:
            print(f"[lint] unknown check kind {spec.get('kind')!r} (id={spec.get('id')}) — skipped")
            continue
        try:
            violations = handler(plan, spec)
        except Exception as e:                       # a bad handler/spec is never fatal
            print(f"[lint] check {spec.get('id')!r} errored: {e} — skipped")
            continue
        if not violations:
            continue
        blocking = (spec.get("status", "active") == "active"
                    and spec.get("severity", "error") == "error")
        if blocking:
            raise InterpretError("; ".join(violations))
        print(f"[lint] warn ({spec.get('id')}): {violations[0]}")
```

- [ ] **Step 5: Create the seed `data/harness/checks.yaml`**

```yaml
- id: chk_security_first
  kind: security_first
  severity: error
  status: active
  message: "security-first ordering (H3): a DENIED_SECURITY branch follows a non-DENIED branch"
  source_task: ""
```

- [ ] **Step 6: Swap the pipeline lint call**

In `agent/pipeline.py:254` replace:

```python
    from .interpreter import InterpretError, interpret, lint_security_first
```

with:

```python
    from .interpreter import InterpretError, interpret, lint
```

In `agent/pipeline.py:302` replace:

```python
            lint_security_first(plan)
```

with:

```python
            lint(plan)
```

- [ ] **Step 7: Run harness + pipeline + interpreter suites**

Run: `uv run pytest tests/test_harness.py tests/test_pipeline_interpreted.py tests/test_interpreter.py -v`
Expected: PASS. (The pipeline happy-path plan has correct security ordering, so `lint` passes; `interpret` still runs its internal `lint_security_first`.)

- [ ] **Step 8: Commit**

```bash
git add agent/harness.py agent/interpreter.py agent/pipeline.py data/harness/checks.yaml tests/test_harness.py
git commit -m "feat(lint): F8a — registry lint engine; migrate security-first to a check kind

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F2: `primitive_contract` / `primitive_exists` / `primitive_arity` check kinds

**Files:**
- Modify: `agent/harness.py` (add 3 handlers, extend `_HANDLERS`)
- Modify: `data/harness/checks.yaml` (seed active entries)
- Test: `tests/test_harness.py`

- [ ] **Step 1: Write the failing handler tests**

Append to `tests/test_harness.py`:

```python
def _contract_plan(prim, *args):
    # first() produces a dict-binding `r0`; the named list-op then consumes it.
    return _plan(compute=[{"prim": "first", "args": ["$rows"], "into": "r0"},
                          {"prim": prim, "args": list(args), "into": "out"}])


def test_primitive_contract_flags_listop_on_scalar_source():
    spec = {"id": "chk_column_on_scalar", "kind": "primitive_contract",
            "prim": "column", "arg_index": 0, "forbid_source": ["first", "get"],
            "message": "'column' expects list[dict]; use 'get' for a single row"}
    assert harness.check_primitive_contract(_contract_plan("column", "$r0", "name"), spec)
    # Consuming a rowset binding (not first/get output) is fine.
    good = _plan(compute=[{"prim": "column", "args": ["$rows", "name"], "into": "out"}])
    assert harness.check_primitive_contract(good, spec) == []


def test_primitive_exists_flags_unknown_prim():
    spec = {"id": "chk_primitive_exists", "kind": "primitive_exists"}
    bad = _plan(compute=[{"prim": "frobnicate", "args": ["$rows"], "into": "out"}])
    assert harness.check_primitive_exists(bad, spec)
    assert harness.check_primitive_exists(_plan(), spec) == []


def test_primitive_arity_flags_wrong_arg_count():
    spec = {"id": "chk_primitive_arity", "kind": "primitive_arity"}
    # `get` takes 2 args (obj, key); supplying 1 is an arity violation.
    bad = _plan(compute=[{"prim": "get", "args": ["$r0"], "into": "out"}])
    assert harness.check_primitive_arity(bad, spec)
    ok = _plan(compute=[{"prim": "get", "args": ["$r0", "k"], "into": "out"}])
    assert harness.check_primitive_arity(ok, spec) == []


def test_seeded_checks_include_primitive_contract_active():
    specs = {s.get("id"): s for s in harness.load_checks()}
    assert specs["chk_column_on_scalar"]["status"] == "active"
    assert specs["chk_column_on_scalar"]["severity"] == "error"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_harness.py -k "primitive or seeded_checks_include" -v`
Expected: FAIL — `AttributeError: module 'agent.harness' has no attribute 'check_primitive_contract'` and missing seed entry.

- [ ] **Step 3: Add the three handlers to `harness.py`**

Insert after `check_security_first` (before `_HANDLERS`):

```python
def _ref_root(arg):
    """'$first_row.field' -> 'first_row'; '$rows' -> 'rows'; non-ref -> None."""
    if isinstance(arg, str) and arg.startswith("$"):
        return arg[1:].split(".", 1)[0]
    return None


def check_primitive_contract(plan, spec) -> list[str]:
    """A list-consuming primitive must not consume a binding produced by a scalar/dict
    producer (forbid_source). Catches the run-15:08 first->column mismatch at plan time."""
    prim = spec.get("prim")
    arg_index = int(spec.get("arg_index", 0))
    forbid = set(spec.get("forbid_source") or [])
    msg = spec.get("message") or f"'{prim}' contract violation"
    produced_by = {cs.into: cs.prim for cs in plan.compute}
    out: list[str] = []
    for cs in plan.compute:
        if cs.prim != prim or arg_index >= len(cs.args):
            continue
        root = _ref_root(cs.args[arg_index])
        if root is not None and produced_by.get(root) in forbid:
            out.append(msg)
    return out


def check_primitive_exists(plan, spec) -> list[str]:
    out: list[str] = []
    for cs in plan.compute:
        if cs.prim not in PRIMITIVES:
            out.append(f"unknown primitive {cs.prim!r} (compute -> {cs.into})")
    return out


def _positional_arity(prim: str):
    fn = PRIMITIVES.get(prim)
    if fn is None:
        return None
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return None
    return sum(1 for p in params
               if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
               and p.default is p.empty)


def check_primitive_arity(plan, spec) -> list[str]:
    out: list[str] = []
    for cs in plan.compute:
        n = _positional_arity(cs.prim)
        if n is not None and len(cs.args) != n:
            out.append(f"primitive {cs.prim!r} takes {n} arg(s), plan supplies {len(cs.args)}")
    return out
```

Replace the `_HANDLERS` dict with:

```python
_HANDLERS = {
    "security_first": check_security_first,
    "primitive_contract": check_primitive_contract,
    "primitive_exists": check_primitive_exists,
    "primitive_arity": check_primitive_arity,
}
```

- [ ] **Step 4: Seed the F2 check-specs in `data/harness/checks.yaml`**

Append (after `chk_security_first`):

```yaml
- id: chk_column_on_scalar
  kind: primitive_contract
  prim: column
  arg_index: 0
  expect: list_of_dict
  forbid_source: [first, get]
  severity: error
  status: active
  message: "'column' expects list[dict]; use 'get' for a single row"
  source_task: t01
- id: chk_sumcol_on_scalar
  kind: primitive_contract
  prim: sum_col
  arg_index: 0
  forbid_source: [first, get]
  severity: error
  status: active
  message: "'sum_col' expects list[dict]; use 'get'+'to_number' for a single row"
  source_task: t01
- id: chk_filter_on_scalar
  kind: primitive_contract
  prim: filter_rows
  arg_index: 0
  forbid_source: [first, get]
  severity: error
  status: active
  message: "'filter_rows' expects list[dict]; got a scalar/dict source"
  source_task: t01
- id: chk_count_on_scalar
  kind: primitive_contract
  prim: count
  arg_index: 0
  forbid_source: [first, get]
  severity: error
  status: active
  message: "'count' over a single record is meaningless; count a rowset"
  source_task: t01
- id: chk_primitive_exists
  kind: primitive_exists
  severity: error
  status: active
  message: "unknown primitive in a compute step"
  source_task: t01
- id: chk_primitive_arity
  kind: primitive_arity
  severity: error
  status: active
  message: "primitive arity mismatch"
  source_task: t01
```

- [ ] **Step 5: Run harness + pipeline + interpreter suites**

Run: `uv run pytest tests/test_harness.py tests/test_pipeline_interpreted.py tests/test_interpreter.py -v`
Expected: PASS. (The pipeline `_PLAN` uses `first($rows)` — 1 arg, known prim, no list-op on a scalar — so all F2 checks pass.)

- [ ] **Step 6: Commit**

```bash
git add agent/harness.py data/harness/checks.yaml tests/test_harness.py
git commit -m "feat(lint): F2 — primitive contract/exists/arity check kinds, seeded active

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F3: deterministic SQL→stdin repair + `sql_stdin` check (error) + runtime banner detect

**Root-cause fix.** `/bin/sql`'s args delivery is nondeterministic (diagnosis #6: the man-page appears "when SQL not delivered via stdin"). So a deterministic **pre-lint repair** rewrites every `Exec /bin/sql` step to deliver its SQL on `stdin` (the reliable channel) before `lint` runs. With every plan repaired to stdin, `chk_sql_stdin` is seeded **`severity: error`** (spec-literal) yet never fires on a real plan, and the corpus is preserved because the repair is transparent to PLAN. The runtime banner-detect remains as a backstop.

**Files:**
- Modify: `agent/interpreter.py` (add `repair_sql_stdin`; add `_is_sql_banner` + runtime banner detect)
- Modify: `agent/harness.py` (add `check_sql_stdin`, extend `_HANDLERS`)
- Modify: `agent/pipeline.py` (call `repair_sql_stdin` before `lint`; teach `_plan_signature` to include stdin SQL)
- Modify: `agent/mock_vm_spy.py` (fixture-key fallback to `[stdin]` so args-keyed fixtures still match a repaired call)
- Modify: `data/harness/checks.yaml` (seed `chk_sql_stdin` as `error`)
- Test: `tests/test_harness.py`, `tests/test_interpreter.py`, `tests/test_pipeline_interpreted.py`, `tests/test_mock_vm_spy.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness.py` (add `repair_sql_stdin` to the existing `from agent.interpreter import ...` line, or import inline as shown):

```python
def test_sql_stdin_handler_flags_args_with_empty_stdin():
    spec = {"id": "chk_sql_stdin", "kind": "sql_stdin", "message": "deliver SQL via stdin"}
    bad = _plan(discovery=[{"rpc": "Exec",
                            "args": {"path": "/bin/sql", "args": ["SELECT 1"]}, "bind": "r"}])
    assert harness.check_sql_stdin(bad, spec)
    good = _plan(discovery=[{"rpc": "Exec",
                             "args": {"path": "/bin/sql", "args": [], "stdin": "SELECT 1"},
                             "bind": "r"}])
    assert harness.check_sql_stdin(good, spec) == []


def test_seeded_sql_stdin_is_error():
    spec = {s["id"]: s for s in harness.load_checks()}["chk_sql_stdin"]
    assert spec["severity"] == "error" and spec["status"] == "active"


def test_repair_moves_sql_args_to_stdin_then_lint_passes():
    from agent.interpreter import repair_sql_stdin, lint
    plan = _plan(discovery=[{"rpc": "Exec",
                             "args": {"path": "/bin/sql", "args": ["SELECT 1"]}, "bind": "r"}])
    repaired = repair_sql_stdin(plan)
    st = repaired.discovery[0]
    assert st.args["stdin"] == "SELECT 1" and st.args["args"] == []
    spec = {"id": "chk_sql_stdin", "kind": "sql_stdin", "message": "m"}
    assert harness.check_sql_stdin(repaired, spec) == []   # repaired plan no longer violates
    lint(repaired)                                          # error-severity check no longer blocks
```

Append to `tests/test_interpreter.py`:

```python
def test_sql_usage_banner_raises_retryable_refuse():
    # F3 runtime backstop: /bin/sql returned its man-page instead of data. Detect it and
    # raise a retryable refuse (mutation_landed False) so the pipeline retries.
    banner = "# /bin/sql\nUsage: send SQL on stdin. Send SQL on stdin to query."
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]): {"stdout": banner}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]},
                             "bind": "raw"}])
    with pytest.raises(InterpretError) as ei:
        interpret(plan, _INTENT, vm)
    assert ei.value.mutation_landed is False
    assert "banner" in str(ei.value)
```

Append to `tests/test_mock_vm_spy.py`:

```python
def test_exec_stdin_fixture_key_fallback():
    # A repaired /bin/sql call delivers SQL via stdin with empty args; the fixture recorded
    # under the SQL string (args key) must still resolve.
    fx = {fixture_key("Exec", "/bin/sql", ["SELECT 1"]): {"stdout": "ok"}}
    vm = MockVMSpy(fixtures=fx)
    assert vm.exec(path="/bin/sql", args=[], stdin="SELECT 1") == {"stdout": "ok"}
```

Append to `tests/test_pipeline_interpreted.py`:

```python
def test_plan_signature_includes_stdin_sql():
    # After repair the SQL lives in stdin; the no-progress signature must still distinguish
    # two different queries (else distinct re-plans look identical and false-break).
    from agent.pipeline import _plan_signature
    from agent.ir_models import PlanIR
    base = json.loads(_PLAN)
    a = dict(base); a["discovery"] = [{"rpc": "Exec",
        "args": {"path": "/bin/sql", "args": [], "stdin": "SELECT 1"}}]
    b = dict(base); b["discovery"] = [{"rpc": "Exec",
        "args": {"path": "/bin/sql", "args": [], "stdin": "SELECT 2"}}]
    assert _plan_signature(PlanIR(**a)) != _plan_signature(PlanIR(**b))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_harness.py -k "sql_stdin or repair" tests/test_interpreter.py::test_sql_usage_banner_raises_retryable_refuse tests/test_mock_vm_spy.py::test_exec_stdin_fixture_key_fallback tests/test_pipeline_interpreted.py::test_plan_signature_includes_stdin_sql -v`
Expected: FAIL — no `check_sql_stdin` / `repair_sql_stdin`, no seed entry, banner not detected, stdin not in signature, fixture fallback absent.

- [ ] **Step 3: Add `check_sql_stdin` to `harness.py`**

Insert after `check_primitive_arity` (before `_HANDLERS`):

```python
def check_sql_stdin(plan, spec) -> list[str]:
    """A /bin/sql Exec must deliver SQL on stdin (args delivery is nondeterministic — the
    tool intermittently returns its usage banner). Seeded severity: error; the pre-lint
    repair (interpreter.repair_sql_stdin) normalises args->stdin before lint, so this only
    fires on a plan that still carries SQL in args with empty stdin after repair."""
    msg = spec.get("message") or "deliver SQL via /bin/sql stdin (args is nondeterministic)"
    out: list[str] = []
    for st in list(plan.discovery) + list(plan.ops):
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            stdin = str(st.args.get("stdin") or "").strip()
            if not stdin and st.args.get("args"):
                out.append(msg)
    return out
```

Replace `_HANDLERS` with:

```python
_HANDLERS = {
    "security_first": check_security_first,
    "primitive_contract": check_primitive_contract,
    "primitive_exists": check_primitive_exists,
    "primitive_arity": check_primitive_arity,
    "sql_stdin": check_sql_stdin,
}
```

- [ ] **Step 4: Add `repair_sql_stdin` + the runtime banner detector to `interpreter.py`**

Add the deterministic repair just after the `lint` dispatcher (added in Task F8a):

```python
def repair_sql_stdin(plan: PlanIR) -> PlanIR:
    """Deterministic pre-lint repair (F3): deliver /bin/sql SQL on stdin (the reliable
    channel) instead of args (nondeterministic — intermittently yields the usage banner).
    For each Exec /bin/sql step carrying SQL in args with empty stdin, move the SQL into
    stdin and clear args. Idempotent; mutates the plan's step args in place and returns it."""
    for st in list(plan.discovery) + list(plan.ops):
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            sql_args = st.args.get("args") or []
            stdin = str(st.args.get("stdin") or "").strip()
            if sql_args and not stdin:
                st.args["stdin"] = "\n".join(str(a) for a in sql_args)
                st.args["args"] = []
    return plan
```

Insert this helper after `_payload` (after `agent/interpreter.py:99`):

```python
def _is_sql_banner(payload: str) -> bool:
    """True when /bin/sql returned its usage banner instead of data — a runtime backstop
    to the pre-lint repair. Detect it so the pipeline retries instead of parsing an empty
    rowset."""
    head = (payload or "").lstrip()
    return head.startswith("# /bin/sql") or "Send SQL on stdin" in head
```

In the discovery loop, replace `agent/interpreter.py:227-228`:

```python
        if step.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(pay)
```

with:

```python
        if step.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(pay)
            if _is_sql_banner(pay):
                raise _refuse("sql returned usage banner — SQL not delivered via stdin", False)
```

In the ops loop, replace `agent/interpreter.py:263-264`:

```python
        if op.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(_payload(result))
```

with:

```python
        if op.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            pay = _payload(result)
            sql_results.append(pay)
            if _is_sql_banner(pay):
                raise _refuse("sql returned usage banner — SQL not delivered via stdin",
                              mutation_landed)
```

- [ ] **Step 5: Wire the repair before `lint` and teach `_plan_signature` about stdin in `pipeline.py`**

Extend the F8a import (`agent/pipeline.py:254`) to also import the repair:

```python
    from .interpreter import InterpretError, interpret, lint, repair_sql_stdin
```

Where Task F8a left `lint(plan)` (`agent/pipeline.py:302`), repair first:

```python
            plan = repair_sql_stdin(plan)
            lint(plan)
```

In `_plan_signature` (`agent/pipeline.py:40-42`), replace:

```python
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            normed = tuple(sorted(_norm_sql(a) for a in st.args.get("args", []) or []))
            parts.append((st.rpc, normed))
```

with:

```python
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            sql_bits = list(st.args.get("args", []) or [])
            if st.args.get("stdin"):
                sql_bits.append(st.args.get("stdin"))
            normed = tuple(sorted(_norm_sql(a) for a in sql_bits))
            parts.append((st.rpc, normed))
```

- [ ] **Step 6: Add the fixture-key fallback to `mock_vm_spy.py`**

Replace `agent/mock_vm_spy.py:56-59` (the `exec` method) with:

```python
    def exec(self, path: str = "", args: list[str] | None = None, stdin: str = "", **kwargs: Any) -> Any:
        args_list = list(args or [])
        self._record("Exec", path=path, args=args_list, stdin=stdin, **kwargs)
        # Fixture-key fallback: a repaired /bin/sql call delivers SQL on stdin with empty
        # args; key the lookup on [stdin] so fixtures recorded under the SQL string match.
        lookup_args = args_list or ([stdin] if stdin else None)
        return self._lookup("Exec", path, lookup_args)
```

- [ ] **Step 7: Seed `chk_sql_stdin` (error) in `data/harness/checks.yaml`**

Append:

```yaml
- id: chk_sql_stdin
  kind: sql_stdin
  severity: error         # spec-literal; never fires after the pre-lint args->stdin repair
  status: active
  message: "deliver SQL via /bin/sql stdin, not args (args delivery is nondeterministic)"
  source_task: t01
```

- [ ] **Step 8: Run harness + interpreter + pipeline + mock-vm suites**

Run: `uv run pytest tests/test_harness.py tests/test_interpreter.py tests/test_pipeline_interpreted.py tests/test_mock_vm_spy.py -v`
Expected: PASS. The MagicMock-driven pipeline happy-path is transparent to the repair (constant `return_value`); the MockVMSpy fixture fallback keeps args-keyed fixtures matching repaired calls.

- [ ] **Step 9: Commit**

```bash
git add agent/harness.py agent/interpreter.py agent/pipeline.py agent/mock_vm_spy.py data/harness/checks.yaml tests/test_harness.py tests/test_interpreter.py tests/test_pipeline_interpreted.py tests/test_mock_vm_spy.py
git commit -m "fix(interpreter): F3 — deterministic SQL->stdin pre-lint repair + error-severity sql_stdin check + runtime banner backstop

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F4: answer-once idempotency

**Files:**
- Modify: `agent/pipeline.py` (add `_make_answer_once`; route 3 answer sites; remove `_terminal_clarification`)
- Test: `tests/test_pipeline_interpreted.py`

- [ ] **Step 1: Write the failing answer-once test**

Append to `tests/test_pipeline_interpreted.py`:

```python
def test_answer_once_suppresses_second_answer():
    # F4: the first guarded answer lands vm.answer; any later answer is a no-op, so the
    # success path and a terminal can never both submit ("answer already provided").
    from agent.pipeline import _make_answer_once
    vm = MagicMock()
    ans = _make_answer_once(vm)
    assert ans("first", "OUTCOME_OK", ["/a"]) is True
    assert ans("second", "OUTCOME_NONE_CLARIFICATION", []) is False
    vm.answer.assert_called_once()
    _, kw = vm.answer.call_args
    assert kw["outcome"] == "OUTCOME_OK" and kw["message"] == "first"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pipeline_interpreted.py::test_answer_once_suppresses_second_answer -v`
Expected: FAIL — `ImportError: cannot import name '_make_answer_once'`.

- [ ] **Step 3: Add `_make_answer_once` and route all answer sites in `pipeline.py`**

Add this module-level function just above `def run_pipeline` (before `agent/pipeline.py:247`):

```python
def _make_answer_once(vm):
    """Return a guarded answer fn (F4): the first call lands vm.answer; later calls are
    suppressed no-ops. Guarantees the success path and any terminal can never both submit
    — eliminates the 'answer already provided' dead-end. Returns True if it submitted."""
    state = {"answered": False}

    def _answer(message: str, outcome: str, refs: list) -> bool:
        if state["answered"]:
            print(f"{CLI_YELLOW}[pipeline] duplicate answer suppressed{CLI_CLR}")
            return False
        state["answered"] = True
        vm.answer(message=message[:800], outcome=outcome, refs=list(refs or []))
        return True

    return _answer
```

In `run_pipeline`, immediately after the `learn_ctx`/`total_in`/`total_out` setup (after `agent/pipeline.py:261`), add:

```python
    answer_once = _make_answer_once(vm)
```

Replace the INTENT-failure terminal at `agent/pipeline.py:285`:

```python
        _terminal_clarification(vm, "INTENT failed")
```

with:

```python
        answer_once("INTENT failed", "OUTCOME_NONE_CLARIFICATION", [])
```

Replace the success-path submit at `agent/pipeline.py:344-345`:

```python
            refs = _ground_security_refs(ans.outcome, list(ans.refs))
            vm.answer(message=ans.message[:800], outcome=ans.outcome, refs=refs)
```

with:

```python
            refs = _ground_security_refs(ans.outcome, list(ans.refs))
            answer_once(ans.message, ans.outcome, refs)
```

Replace the loop-exhaust terminal at `agent/pipeline.py:362-363`:

```python
    save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", cycle)
    _terminal_clarification(vm, last_error or "interpreter cycles exhausted")
```

with:

```python
    save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", cycle)
    answer_once(last_error or "interpreter cycles exhausted", "OUTCOME_NONE_CLARIFICATION", [])
```

Remove the now-unused `_terminal_clarification` function (`agent/pipeline.py:410-411`):

```python
def _terminal_clarification(vm, message: str) -> None:
    vm.answer(message=message[:800], outcome="OUTCOME_NONE_CLARIFICATION", refs=[])
```

- [ ] **Step 4: Run the pipeline suite to verify green**

Run: `uv run pytest tests/test_pipeline_interpreted.py -v`
Expected: PASS — including the existing `vm.answer.assert_called_once()` assertions in the happy-path and exhaust tests (now routed through `answer_once`).

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "fix(pipeline): F4 — answer-once idempotency guard; drop _terminal_clarification

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F5: verify-gate regression lock

**Files:**
- Test only: `tests/test_pipeline_interpreted.py`

- [ ] **Step 1: Write the lock test**

Append to `tests/test_pipeline_interpreted.py`:

```python
def test_ok_with_unresolved_required_ref_never_submits_ok(monkeypatch):
    # F5 lock: an OUTCOME_OK whose required record_path ref cannot resolve must refuse
    # inside interpret (mutation_landed False) and route to CLARIFICATION — never submit a
    # broken OK. Locks F1-F4 against regressions.
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 2)
    intent = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [], "answer_shape": {},
        "required_refs": {"OUTCOME_OK": [{"kind": "record_path", "source": "$missing"}]},
    })
    learn = json.dumps({"rule_content": "Always bind the record_path ref for OK answers",
                        "reasoning": "x", "deactivate_ids": [], "skip": False})
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    seq = [intent, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="x", task_id="t_f5", agents_md_text="A")
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    vm.answer.assert_called_once()
    assert vm.answer.call_args.kwargs["outcome"] != "OUTCOME_OK"
```

- [ ] **Step 2: Run it to verify it passes immediately (locks current behavior)**

Run: `uv run pytest tests/test_pipeline_interpreted.py::test_ok_with_unresolved_required_ref_never_submits_ok -v`
Expected: PASS — F1–F4 already make this hold; the test pins it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_interpreted.py
git commit -m "test(pipeline): F5 — lock that an unresolved required ref never submits OK

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F6: LEARN/oracle method-not-value rule for catalogue matching

**Files:**
- Modify: `data/learned/t01.yaml` (deactivate `r003`; add `r004` method rule)
- Modify: `data/oracle/atoms.yaml` (add normalized-catalogue-match atom)
- Test: `tests/test_learned_t01_method_rule.py`

- [ ] **Step 1: Write the failing data-shape tests**

Create `tests/test_learned_t01_method_rule.py`:

```python
from pathlib import Path
from agent.learned_store import load_entries
from agent.oracle_atoms import load_atoms


def test_t01_active_rule_is_method_not_value():
    entries = load_entries("t01")
    text = " ".join((e.get("content") or "") for e in entries).lower()
    assert "normal" in text                 # normalized matching method
    assert "first" in text and "get" in text  # first->get discipline (not column on a row)
    # no baked re-seeded values from the diagnosis
    assert "sto-12jlht7d" not in text and "fst-apsrizjw" not in text


def test_t01_misdirected_format_rule_deactivated():
    # r003 blamed rowset `format` for the F1 interpreter bug — it must be inactive.
    active_ids = {e.get("id") for e in load_entries("t01")}
    assert "r003" not in active_ids


def test_oracle_has_normalized_catalogue_atom():
    atoms = load_atoms(Path("data/oracle/atoms.yaml"))
    assert any("normal" in a.content.lower()
               and "catalog" in (" ".join(a.domain) + " " + a.content).lower()
               for a in atoms)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_learned_t01_method_rule.py -v`
Expected: FAIL — `r003` is active, no method rule mentions first/get, no matching oracle atom.

- [ ] **Step 3: Edit `data/learned/t01.yaml`**

Deactivate `r003` with two precise, uniquely-anchored edits (the file has several `status: active` lines, so do NOT match `status: active` alone).

Edit A — set `r003`'s `deactivated_reason` (anchored on the unique `id: r003`). Change:

```yaml
  deactivated_reason: null
  id: r003
```

to:

```yaml
  deactivated_reason: misdirected — blamed rowset format for an interpreter primitive-contract
    bug now fixed by F1/F2; superseded by r004
  id: r003
```

Edit B — flip `r003`'s status (anchored on the unique tail of `r003`'s `reasoning`, which ends with "format choice.'"). Change:

```yaml
  not support it; thus the rule focuses on format choice.'
  status: active
```

to:

```yaml
  not support it; thus the rule focuses on format choice.'
  status: inactive
```

Add a new entry to the `entries:` list (after `r003`):

```yaml
- agents_md_anchor: null
  content: When answering a catalogue existence query, resolve the product by matching
    brand/model/property normalized (case-insensitive, trimmed; use LIKE for a partial
    model token), apply 'first' to reduce the rowset to one record, read that record's
    fields with 'get' (never 'column' on a single record), and project its record_path
    into the OUTCOME_OK refs.
  created: '2026-06-18'
  deactivated_reason: null
  id: r004
  reasoning: Method-not-value rule (F6). States the matching/extraction method so it
    survives per-StartRun re-seeding; pairs with F1/F2 (typed primitive contracts) and
    the interpreter ref-projection. Replaces r003 which misattributed the crash to format.
  status: active
  surface: ir
```

- [ ] **Step 4: Add the oracle atom to `data/oracle/atoms.yaml`**

Append a new list item at the end of the file:

```yaml
- id: normalized-catalogue-existence-match
  description: General method for catalogue existence queries — normalized attribute
    matching plus single-record extraction discipline.
  domain:
  - product-catalogue
  - sql
  - method
  content: "To decide whether a catalogue product exists, match its identifying
    attributes (brand, model/series, variant properties) NORMALIZED: case-insensitive
    and whitespace-trimmed, using LIKE for partial model tokens rather than strict
    equality, since exact-match against re-seeded data is brittle. Reduce the result
    rowset with `first` to a single record, then read fields with `get` (a single
    record is a dict, not a list — never apply a list operation like `column` to it),
    and surface that record's record_path as the grounding reference."
  source: investigation
  validated_by: manual
  validated_at: '2026-06-18'
  status: active
  embedding_hash: ''
  source_task: t01
  polarity: method
```

- [ ] **Step 5: Run the data-shape tests + parse checks**

Run: `uv run pytest tests/test_learned_t01_method_rule.py tests/test_oracle_atoms.py -v`
Expected: PASS — rules/atoms parse, `r003` inactive, `r004` method-shaped, atom present.

- [ ] **Step 6: Commit**

```bash
git add data/learned/t01.yaml data/oracle/atoms.yaml tests/test_learned_t01_method_rule.py
git commit -m "feat(learn): F6 — method-not-value catalogue rule; deactivate misdirected r003

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F7: DOC_SELECT catalogue-gap log

**Files:**
- Modify: `agent/orchestrator.py` (add `_is_catalogue_query`; log gap after the fallback block)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing gap-log test**

Append to `tests/test_orchestrator.py`:

```python
def test_catalogue_query_logs_doc_select_gap(capsys):
    # F7: a catalogue query whose entity tokens hit no /docs file logs a gap and does NOT
    # break (gather completes). Defensive only — many catalogue tasks have no doc.
    from agent.orchestrator import gather_prephase_facts
    from agent.mock_vm_spy import MockVMSpy
    vm = MockVMSpy(fixtures={})        # all RPCs return the empty stub -> no doc hits
    facts = gather_prephase_facts(vm, 'Does the "Festool SYS bag" exist in the catalogue?',
                                  agents_md_text="", task_id="t01")
    out = capsys.readouterr().out
    assert "DOC_SELECT gap" in out
    assert isinstance(facts.docs_inventory, str)   # completed without raising
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator.py::test_catalogue_query_logs_doc_select_gap -v`
Expected: FAIL — no "DOC_SELECT gap" log emitted.

- [ ] **Step 3: Add the catalogue-gap log to `orchestrator.py`**

Add the helper just above `gather_prephase_facts` (before `agent/orchestrator.py:395`):

```python
_CATALOGUE_HINTS = ("catalog", "catalogue", "product", "sku", "tool bag")


def _is_catalogue_query(instruction: str) -> bool:
    t = (instruction or "").lower()
    return any(h in t for h in _CATALOGUE_HINTS)
```

In `gather_prephase_facts`, immediately after the LLM DOC-SELECT fallback block (after `agent/orchestrator.py:498`, i.e. after the `if picked and policies: status["policies"] = "ok"` line and before the `target_records` comment), add:

```python
    # F7: catalogue query but entity-token Search found no /docs match — log the gap
    # (defensive; no break, no prompt change). Many catalogue tasks have no doc.
    if _is_catalogue_query(instruction) and not search_hit:
        print(f"[prephase] DOC_SELECT gap: catalogue query, no /docs matched entity tokens "
              f"(tokens={tokens[:5]})")
```

- [ ] **Step 4: Run the orchestrator suite to verify green**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): F7 — log DOC_SELECT gap on catalogue queries (defensive)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task F8b: distill → validate → promote pipeline (gated off by default)

**Files:**
- Modify: `agent/harness.py` (add `distill`, `promote`)
- Create: `agent/harness_validate.py`
- Modify: `agent/pipeline.py` (gated `_maybe_harness_distill` hook in the InterpretError branch)
- Modify: `CLAUDE.md` (root, env table)
- Test: `tests/test_harness_distill.py`

- [ ] **Step 1: Write the failing distill/validate/promote tests**

Create `tests/test_harness_distill.py`:

```python
from unittest.mock import patch
from agent import harness, harness_validate
from agent.ir_models import PlanIR


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def test_distill_appends_candidate_of_known_kind(tmp_path, monkeypatch):
    checks = tmp_path / "checks.yaml"; checks.write_text("[]")
    monkeypatch.setattr(harness, "_DEFAULT_CHECKS", checks)
    fake = {"id": "chk_new", "kind": "primitive_contract", "prim": "column",
            "arg_index": 0, "forbid_source": ["first"], "severity": "error",
            "message": "x"}
    plan = _plan(compute=[{"prim": "first", "args": ["$rows"], "into": "r0"}])
    with patch("agent.harness.call_llm_json", return_value=fake):
        spec = harness.distill(plan, "compute step 'column' failed", source_task="t01")
    assert spec["status"] == "candidate" and spec["source_task"] == "t01"
    assert any(c["id"] == "chk_new" and c["status"] == "candidate"
               for c in harness.load_checks(checks))


def test_distill_rejects_unknown_kind(tmp_path, monkeypatch):
    checks = tmp_path / "checks.yaml"; checks.write_text("[]")
    monkeypatch.setattr(harness, "_DEFAULT_CHECKS", checks)
    with patch("agent.harness.call_llm_json", return_value={"id": "x", "kind": "made_up"}):
        assert harness.distill(_plan(), "err") is None


def test_promote_flips_candidate_to_active(tmp_path):
    checks = tmp_path / "checks.yaml"
    harness.save_checks([{"id": "c", "kind": "sql_stdin", "status": "candidate",
                          "severity": "warn"}], checks)
    assert harness.promote("c", path=checks) is True
    assert harness.load_checks(checks)[0]["status"] == "active"


def test_validate_requires_catches_bad_and_not_good():
    check = {"id": "chk_column_on_scalar", "kind": "primitive_contract", "prim": "column",
             "arg_index": 0, "forbid_source": ["first", "get"], "message": "m"}
    bad = _plan(compute=[{"prim": "first", "args": ["$rows"], "into": "r0"},
                         {"prim": "column", "args": ["$r0", "name"], "into": "out"}])
    good = _plan(compute=[{"prim": "column", "args": ["$rows", "name"], "into": "out"}])
    assert harness_validate.validate_check_via_grader(check, bad, good) is True
    assert harness_validate.validate_check_via_grader(check, bad, bad) is False   # flags good too
    assert harness_validate.validate_check_via_grader(check, good, good) is False  # never flags bad


def test_inline_validate_promotes_candidate_when_catches_bad_not_good(tmp_path, monkeypatch):
    # F8b inline path: HARNESS_DISTILL=1 + HARNESS_VALIDATE_INLINE=1 -> distilled candidate
    # is validated against (failing plan, last known-good plan) and promoted to active.
    import json
    from agent import pipeline
    from agent.ir_models import PlanIR
    checks = tmp_path / "checks.yaml"; checks.write_text("[]")
    monkeypatch.setattr(harness, "_DEFAULT_CHECKS", checks)
    monkeypatch.setenv("HARNESS_DISTILL", "1")
    monkeypatch.setenv("HARNESS_VALIDATE_INLINE", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)
    good = {"discovery": [], "rowsets": [],
            "compute": [{"prim": "column", "args": ["$rows", "name"], "into": "out"}],
            "decision": {"branches": [], "default_label": "ok"}, "ops": [],
            "answer": {"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
            "custom_extract": []}
    (tmp_path / "data" / "heuristics" / "tX.plan.json").write_text(json.dumps(good))
    failing = PlanIR(**{**good, "compute": [
        {"prim": "first", "args": ["$rows"], "into": "r0"},
        {"prim": "column", "args": ["$r0", "name"], "into": "out"}]})
    cand = {"id": "chk_auto", "kind": "primitive_contract", "prim": "column",
            "arg_index": 0, "forbid_source": ["first", "get"], "severity": "error",
            "message": "auto"}
    with patch("agent.harness.call_llm_json", return_value=cand):
        pipeline._maybe_harness_distill(failing, "compute step 'column' failed", "tX")
    promoted = {c["id"]: c for c in harness.load_checks(checks)}
    assert promoted["chk_auto"]["status"] == "active"   # validated -> promoted
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_harness_distill.py -v`
Expected: FAIL — `harness.distill`/`harness.promote` and `agent.harness_validate` do not exist.

- [ ] **Step 3: Add `distill` + `promote` to `harness.py`**

At the top of `agent/harness.py`, add `import os` to the imports and add `from .llm import call_llm_json` (place the `from .llm import call_llm_json` import with the other `from .` imports). Then append at the end of the file:

```python
# --- F8b: distill -> validate -> promote (gated off by default) -------------

_DISTILL_SYS = (
    "Distill ONE reusable plan-time CHECK-SPEC from an interpreter contract failure. "
    "Return JSON for a single check of an EXISTING kind "
    "(primitive_contract|sql_stdin|primitive_exists|primitive_arity): "
    "{id, kind, prim?, arg_index?, forbid_source?, severity:'error', message}. "
    "Only the closed structural fields — never natural-language logic."
)


def distill(plan, error, source_task=""):
    """Propose a `candidate` check-spec generalised from a failing step. LLM, reason
    tier; never raises. Returns the appended spec dict, or None (unknown kind, dup id,
    or no usable response). Caller gates on HARNESS_DISTILL."""
    from .llm import _resolve_model_for_phase
    user = f"PLAN:\n{plan.model_dump_json()[:4000]}\n\nERROR:\n{error}\n\nReturn the check JSON."
    try:
        out = call_llm_json(_DISTILL_SYS, user,
                            _resolve_model_for_phase("distill", os.environ.get("MODEL", "")))
    except Exception:
        return None
    if not isinstance(out, dict) or out.get("kind") not in _HANDLERS:
        return None
    checks = load_checks()
    if any(c.get("id") == out.get("id") for c in checks):
        return None
    spec = {**out, "status": "candidate", "source_task": source_task}
    checks.append(spec)
    save_checks(checks)
    return spec


def promote(check_id, path=None) -> bool:
    """Flip a candidate check-spec to active. Returns True if found."""
    checks = load_checks(path)
    found = False
    for c in checks:
        if c.get("id") == check_id:
            c["status"] = "active"
            found = True
    if found:
        save_checks(checks, path)
    return found
```

- [ ] **Step 4: Create `agent/harness_validate.py`**

```python
"""Validation gate for a candidate check-spec (mirror of oracle_validate).

A candidate is promotable only when it FLAGS the failing plan it was distilled from AND
does NOT flag a known-good plan (no false positive). Pure structural evaluation via the
kind handler — named *_via_grader for parallelism with oracle_validate; no live grader
round-trip is required for a structural check.
"""
from __future__ import annotations

from . import harness


def validate_check_via_grader(check: dict, failing_plan, good_plan) -> bool:
    """True iff the check flags `failing_plan` and does not flag `good_plan`."""
    handler = harness.handler_for(check.get("kind"))
    if handler is None:
        return False
    try:
        flags_bad = bool(handler(failing_plan, check))
        flags_good = bool(handler(good_plan, check)) if good_plan is not None else False
    except Exception:
        return False
    return flags_bad and not flags_good
```

- [ ] **Step 5: Add the gated distill hook to `pipeline.py`**

Add this helper just above `def run_pipeline` (near `_make_answer_once`):

```python
def _load_good_plan(task_id):
    """Last persisted successful PlanIR for this task (known-good), or None. Persisted
    only on a success path (_persist_artifacts), so it exists once the task has passed
    at least once — the false-positive reference for inline check validation."""
    pp = Path("data/heuristics") / f"{task_id}.plan.json"
    if not pp.exists():
        return None
    try:
        from .ir_models import PlanIR
        return PlanIR.model_validate_json(pp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _maybe_harness_distill(plan, error, task_id) -> None:
    """F8b (gated HARNESS_DISTILL=1, default 0): after an F1-class compute contract
    failure, propose a `candidate` check-spec. When HARNESS_VALIDATE_INLINE=1 (default),
    validate it — the candidate MUST flag this failing plan AND must NOT flag the last
    known-good plan — and promote (candidate -> active) on success; otherwise it stays a
    warn-only candidate for an offline promote. Never raises (cannot dead-end a run)."""
    if os.environ.get("HARNESS_DISTILL", "0") != "1":
        return
    if "compute step" not in error and "custom_extract" not in error:
        return
    try:
        from . import harness
        candidate = harness.distill(plan, error, source_task=task_id)
        if not candidate or os.environ.get("HARNESS_VALIDATE_INLINE", "1") != "1":
            return
        from .harness_validate import validate_check_via_grader
        if validate_check_via_grader(candidate, plan, _load_good_plan(task_id)):
            harness.promote(candidate["id"])
            print(f"{CLI_GREEN}[pipeline] check {candidate['id']} promoted (validated){CLI_CLR}")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] harness distill skipped: {e}{CLI_CLR}")
```

In `run_pipeline`, in the `except InterpretError as e:` branch, after the `_ilearn(...)` call (after `agent/pipeline.py:321`) and before the `if getattr(e, "mutation_landed", False):` check, add:

```python
            _maybe_harness_distill(plan, last_error, task_id)
```

- [ ] **Step 6: Document the env vars in root `CLAUDE.md`**

In the env-var table in `CLAUDE.md` (root), add two rows after the `ORACLE_VALIDATE_INLINE` row:

```markdown
| `HARNESS_DISTILL` | `1` → after an F1-class compute contract failure, distill a `candidate` lint check-spec into `data/harness/checks.yaml` (LLM, reason tier). Default `0` (no cost). Candidates are enforced **warn-only** by `lint` until promoted. |
| `HARNESS_VALIDATE_INLINE` | `1` (default) → when `HARNESS_DISTILL=1`, a freshly distilled candidate check is validated inline (`harness_validate.validate_check_via_grader`: must flag the failing plan ∧ must NOT flag the last known-good plan) and promoted (`candidate`→`active`) on success. `0` → leave it a warn-only candidate for an offline promote. Only meaningful when `HARNESS_DISTILL=1`. |
```

- [ ] **Step 7: Run the new + full agent test suites**

Run: `uv run pytest tests/test_harness_distill.py tests/test_harness.py tests/test_pipeline_interpreted.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add agent/harness.py agent/harness_validate.py agent/pipeline.py CLAUDE.md tests/test_harness_distill.py
git commit -m "feat(lint): F8b — gated distill->validate->promote for learnable lint checks

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task Docs: regenerate wiki + verify whole suite

**Files:**
- `docs/wiki/*` (via iwiki skill), full test suite

- [ ] **Step 1: Run the full test suite**

Run: `uv run python -m pytest tests/ -v`
Expected: PASS except the two known pre-existing reds — `test_t09_replay_matches_known_good` and `test_t09_corpus` (stale fixtures, unrelated to this work). Confirm no *new* failures.

- [ ] **Step 2: Regenerate affected wiki pages**

Invoke the iwiki skill (not raw CLI) for each changed/new module:

```
iwiki:iwiki-ingest agent/interpreter.py
iwiki:iwiki-ingest agent/pipeline.py
iwiki:iwiki-ingest agent/primitives.py
iwiki:iwiki-ingest agent/harness.py
iwiki:iwiki-ingest agent/harness_validate.py
iwiki:iwiki-ingest agent/orchestrator.py
```

- [ ] **Step 3: Lint the docs graph**

Invoke `/iwiki-lint`. Expected: no broken `[[refs]]`, no orphan/stale pages.

- [ ] **Step 4: Commit docs**

```bash
git add docs/wiki
git commit -m "docs(wiki): regenerate pages for interpreter robustness (F1-F8)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task Live: end-to-end t01 verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm no other run is contending**

Run: `pgrep -af "python.*main.py" || echo "no main.py running"`
Expected: no competing `main.py t01` loop (per the concurrent-run-contention note). If one is running, wait or coordinate before the timed run.

- [ ] **Step 2: Run t01 against the live grader**

Run: `RUN_BENCHMARK=1 uv run pytest tests/test_benchmark_t01.py -v`
(or, equivalently, `RUN_BENCHMARK=1 make task TASKS='t01'` and inspect the trace.)
Expected: `data/learned/t01.yaml` `last_run.status == "success"`, `outcome == "OUTCOME_OK"`, with a catalog `record_path` ref (`/proc/catalog/<SKU>.json`) on the submitted answer.

- [ ] **Step 3: If t01 still fails — diagnose, do not patch prompts**

If the outcome is not `OUTCOME_OK`, read the cycle trace (`data/heuristics/t01.plan.json` + the run JSONL). The fix belongs in a LEARN rule (`data/learned/t01.yaml`) or a new/seeded check-spec (`data/harness/checks.yaml`) — never in `data/prompts/*.md` (project rule). Re-run until green.

---

## Self-Review

**Spec coverage:** F1 (Task F1), F2 (Task F2), F3 (Task F3), F4 (Task F4), F5 (Task F5), F6 (Task F6), F7 (Task F7), F8a (Task F8a), F8b (Task F8b) — all eight defects + the learnable registry are covered, plus docs + a live t01 verification. Execution order matches spec §Execution Order.

**Deviations:** none. F3 keeps `chk_sql_stdin` spec-literal `error` via the deterministic pre-lint `repair_sql_stdin` (root-cause fix, corpus preserved); F8b wires the full inline distill→validate→promote per spec, gated off by default. Both Design Decisions document the *how*, not a deviation.

**Type consistency:** handler signature is uniformly `(plan, spec) -> list[str]`; `_HANDLERS` keys (`security_first`, `primitive_contract`, `primitive_exists`, `primitive_arity`, `sql_stdin`) match the seeded `kind` values and the `handler_for` lookups; `lint(plan)` (interpreter) and `load_checks`/`save_checks`/`handler_for`/`distill`/`promote` (harness) names are consistent across tasks and tests; `_make_answer_once(vm) -> _answer(message, outcome, refs) -> bool` is used identically at all three call sites.

**No placeholders:** every code step shows the full code; every run step gives the exact command and expected result.
