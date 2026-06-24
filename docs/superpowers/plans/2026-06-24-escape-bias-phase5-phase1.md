---
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-24-escape-bias-elimination-design.md
review:
  plan_hash: e0c468667ada7984
  spec_hash: 5447cff2d00861e3
  last_run: 2026-06-24
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: consistency
      severity: INFO
      section: "### Task 2: Cap per-call retry/tier wall-clock so a degraded endpoint fails fast"
      section_hash: a908e3de18a02e85
      text: >-
        Step 3's locate hint `grep -n "range(3)\|attempt"` will not match a
        literal `range(3)` — the retry loop in agent/llm.py is
        `for attempt in range(max_retries + 1)` with `max_retries: int = 3`
        as the function default (agent/llm.py:359, repeated for the three
        provider transports). The `\|attempt` alternative still locates the
        loops, and the real lever is lowering that default (or wiring
        `_MAX_RETRIES`); the constants-contract test is the actual gate.
        Concrete, not a defect — flagged so the implementer edits the
        `max_retries` default rather than hunting a non-existent literal.
      verdict: fixed
      verdict_at: 2026-06-24
    - id: F-002
      phase: consistency
      severity: INFO
      section: "### Task 3: `agent/resolve.py` — normalization, `relax_sql`, prose-param parsing"
      section_hash: 14b1a396aba7b862
      text: >-
        Task 4's _RelaxVM stub sets `r.exit_code = 0` but Task 5's _FakeVM /
        _VM stubs omit it. This is consistent with the consuming code: the
        resolve.py path parses `.stdout` directly via _parse_csv and never
        reads exit_code, while interpreter._payload (used in Task 4) tolerates
        a missing field. No conflict — recorded only to confirm the stub
        divergence is intentional, not an inconsistency.
      verdict: accepted
      verdict_at: 2026-06-24
---

# Escape-bias Phase 5 + Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop one slow/hung task from freezing the whole benchmark run (so `SubmitRun` always produces scores), then make key-entity resolution a verified deterministic step so the agent stops giving up with `UNSUPPORTED` on entities that exist.

**Architecture:** Two phases from `docs/superpowers/specs/2026-06-24-escape-bias-elimination-design.md`. Phase 5 (reliability) lands first because without it no clean scored run is possible. Phase 1 (resolve-or-prove) is the highest-leverage correctness fix (~14 tasks) and has **two seats**: interpreter auto-relaxation of the resolving SQL PLAN already wrote (primary), plus an INVESTIGATE descriptor-probe (fallback). Phases 2–4 are deferred to later plans.

**Tech Stack:** Python 3, `pytest`, `uv`. Existing agent package (`agent/*.py`), `concurrent.futures` for orchestration, `httpx` for transport (already timeout-bounded). VM SQL is SQLite-dialect over `/bin/sql` (stdin).

## Global Constraints

- No task-specific rules in `data/prompts/*` — all behaviour change is in code mechanisms (project rule, copied verbatim from spec).
- All new env vars are read with a safe default so an unset env reproduces prior behaviour where the spec allows.
- Match existing code style; surgical changes only — every changed line traces to Phase 5 or Phase 1.
- Branch: work on `determinism` (per user decision); commit frequently with the trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Run tests with `uv run pytest`. `.env` is auto-loaded by `uv`; tests must not depend on a live LLM/VM (use fakes).
- **Real DB schema** (verified from a trace; use these exact names): `product_variants(product_sku PK, record_path, product_category_id, product_kind_id, product_family_id, brand, series, model, product_name, price_cents, price_currency, properties)`; `product_families(product_family_id PK, …, brand, series, model, product_family_name, properties)`; `product_variant_properties(product_sku, property_key, property_value_text, property_value_number REAL NULL, PK(product_sku, property_key))`; `stores(store_id PK, record_path, store_name, city, is_open, …)`; `store_inventory(store_id, product_sku, on_hand_quantity, reserved_quantity, available_today_quantity, incoming_quantity, …)`.

---

## File Structure

| File | Responsibility | Phase |
|---|---|---|
| `main.py` (modify `_run_one_pass`) | Per-task wall-clock deadline; never block `SubmitRun` on a hung worker | 5 |
| `agent/llm.py` (modify retry/timeout consts) | Cap total per-call retry/tier wall-clock so a degraded endpoint fails fast | 5 |
| `agent/resolve.py` (create) | Pure helpers: value normalization, SQL literal quoting, `relax_sql` (predicate relaxation: text-normalize + numeric-column fallback), prose-param literal parsing, `resolve_product` | 1 |
| `agent/interpreter.py` (modify discovery loop) | Auto-relax: retry a 0-row read-only `/bin/sql` discovery step once with `relax_sql` | 1 |
| `agent/investigate.py` (modify) | Descriptor-probe fallback: bind resolved candidates into `Brief.env`; `sufficient()` requires key-entity refs resolved | 1 |
| `tests/test_resolve.py` (create) | Unit tests: normalization, `relax_sql`, prose-param parsing, `resolve_product` ladder | 1 |
| `tests/test_run_deadline.py` (create) | Orchestration deadline does not block on a hung task | 5 |
| `tests/test_interpreter_relax.py` (create) | 0-row resolving discovery step is retried relaxed | 1 |
| `tests/test_investigate_resolve.py` (create) | Probe integration + sufficiency | 1 |

---

## Phase 5 — Reliability

### Task 1: Per-task wall-clock deadline in the run loop

**Files:**
- Modify: `main.py` (`_run_one_pass`, ~L245-288; module env block near `PARALLEL_TASKS` ~L108)
- Test: `tests/test_run_deadline.py` (create)

**Interfaces:**
- Consumes: `run.trial_ids`, `_run_single_task(tid, task_filter, train_cycle)`, `client.submit_run(...)` (existing).
- Produces: `ECOM_TASK_TIMEOUT_S` env (float seconds, default `600`); `_collect_with_deadline(pool, futures, deadline_s) -> dict[str, tuple]` returning results of finished futures only.

**Why:** The current `with ThreadPoolExecutor(...) as pool:` runs `for fut in as_completed(futures):` with no timeout. A slow/degraded task (10 cycles × ~180s LLM reads × retries) blocks `as_completed` indefinitely; the `with` exit then blocks again on `shutdown(wait=True)`. `SubmitRun` (in `finally`) is never reached → no scores. Bounding the collection and tearing the pool down non-blockingly fixes this for any hang vector.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_deadline.py
import time
from concurrent.futures import ThreadPoolExecutor


def _collect_with_deadline(pool, futures, deadline_s):
    import main
    return main._collect_with_deadline(pool, futures, deadline_s)


def test_collect_returns_finished_and_does_not_block_on_hung_task():
    def quick(n):
        return ("t%02d" % n, n)

    def hung(n):
        time.sleep(60)        # simulates a stuck task
        return ("t99", n)

    pool = ThreadPoolExecutor(max_workers=4)
    try:
        futures = {pool.submit(quick, i): "t%02d" % i for i in range(3)}
        futures[pool.submit(hung, 99)] = "t99"
        t0 = time.monotonic()
        done = _collect_with_deadline(pool, futures, deadline_s=2.0)
        elapsed = time.monotonic() - t0
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    assert elapsed < 10.0, "collection must not block on the hung task"
    assert len(done) == 3, "all quick tasks collected"
    assert "t99" not in done, "hung task excluded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_deadline.py -v`
Expected: FAIL with `AttributeError: module 'main' has no attribute '_collect_with_deadline'`

- [ ] **Step 3: Add the env var near the other module-level config**

In `main.py`, just after the `PARALLEL_TASKS = ...` line (~L108):

```python
PARALLEL_TASKS = max(1, int(os.getenv("ECOM_PARALLEL_TASKS", "1")))
# FIX: hard per-task wall-clock cap so one slow/hung task never freezes the run.
# A degraded LLM endpoint can make a single task take tens of minutes (10 cycles ×
# ~180s reads × retries); past this many seconds we abandon the task and submit the rest.
TASK_TIMEOUT_S = float(os.getenv("ECOM_TASK_TIMEOUT_S", "600"))
```

- [ ] **Step 4: Add the `_collect_with_deadline` helper**

In `main.py`, above `_run_one_pass`:

```python
def _collect_with_deadline(pool, futures: dict, deadline_s: float) -> dict:
    """Collect results of futures that finish within `deadline_s` (wall clock from now).
    Unfinished futures are abandoned (their worker thread leaks but the process exits at
    run end). Returns {task_id: (task_id, trial_id, elapsed, token_stats, trace, filtered)}.
    """
    import concurrent.futures as _cf
    out: dict = {}
    end = time.monotonic() + deadline_s
    pending = set(futures)
    while pending:
        remaining = end - time.monotonic()
        if remaining <= 0:
            break
        done, pending = _cf.wait(pending, timeout=remaining,
                                 return_when=_cf.FIRST_COMPLETED)
        if not done:                      # timed out with nothing newly finished
            break
        for fut in done:
            try:
                res = fut.result()
            except Exception as exc:
                print(f"{CLI_RED}[{futures[fut]}] Task error: {exc}{CLI_CLR}")
                continue
            out[res[0]] = res             # res[0] is task_id
    if pending:
        print(f"{CLI_RED}[run] {len(pending)} task(s) exceeded "
              f"{deadline_s:.0f}s deadline — abandoned, submitting the rest{CLI_CLR}")
    return out
```

- [ ] **Step 5: Run the deadline test to verify it passes**

Run: `uv run pytest tests/test_run_deadline.py -v`
Expected: PASS

- [ ] **Step 6: Rewire `_run_one_pass` to use the deadline and a non-blocking teardown**

Replace the body of `_run_one_pass` from `pending: dict ...` through the end of the `try`/`finally` with:

```python
    pending: dict[str, tuple] = {}
    pool = ThreadPoolExecutor(max_workers=PARALLEL_TASKS)
    try:
        futures = {
            pool.submit(_run_single_task, tid, task_filter, train_cycle): tid
            for tid in run.trial_ids
        }
        # Whole-pass budget: each parallel lane may spend TASK_TIMEOUT_S per task.
        import math
        lanes = max(1, PARALLEL_TASKS)
        pass_deadline = TASK_TIMEOUT_S * math.ceil(len(futures) / lanes) + 120.0
        collected = _collect_with_deadline(pool, futures, pass_deadline)
        for task_id, res in collected.items():
            _task_id, trial_id, task_elapsed, token_stats, trace, filtered = res
            if filtered:
                continue
            pending[task_id] = (trial_id, task_elapsed, token_stats, trace)
            _ts_now = datetime.datetime.now().strftime("%H:%M:%S")
            _log_stats(
                f"[{_ts_now}] done {task_id:<10} {task_elapsed:>6.1f}s  "
                f"in={token_stats.get('input_tokens', 0):>8,} "
                f"out={token_stats.get('output_tokens', 0):>8,} "
                f"cycles={token_stats.get('cycles_used', 0)}  (score @submit)"
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        print(f"\n{CLI_GREEN}>>>> Submitting run... <<<<{CLI_CLR}")
        result = client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))
        print(f"Run submitted: {run.run_id}")
        scores = _settle_scores(result, pending)
    return scores, result
```

(Remove the now-unused `as_completed` import only if no other function in `main.py` uses it — grep first: `grep -n as_completed main.py`. Keep `ThreadPoolExecutor`.)

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: PASS (no regressions). If `tests/` imports `main` and triggers env requirements, run `tests/test_run_deadline.py` alone first and report any import-time failures.

- [ ] **Step 8: Commit**

```bash
git add main.py tests/test_run_deadline.py
git commit -m "fix(run): per-task wall-clock deadline so a hung task never blocks SubmitRun

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Cap per-call retry/tier wall-clock so a degraded endpoint fails fast

**Files:**
- Modify: `agent/llm.py` (timeout consts ~L53-66; retry/backoff loop — locate with `grep -n "TRANSIENT" agent/llm.py`)
- Test: extend `tests/test_run_deadline.py` with a constants-contract test.

**Interfaces:**
- Consumes: `_HTTP_READ_TIMEOUT_S` (existing, default 180).
- Produces: `ECOM_LLM_MAX_RETRIES` (int, default 2) and a lowered default read timeout — NO control-flow change; the goal is making the *defaults* survivable under Task 1's per-task deadline.

**Why:** Under endpoint degradation each call burns `read_timeout × retries × tiers`. With Task 1's 600s task cap, a single 180s×3 chain already eats half the budget. Bounding retries keeps multiple cycles feasible within the cap.

- [ ] **Step 1: Write the failing test (constants contract)**

```python
# append to tests/test_run_deadline.py
import os


def test_llm_retry_budget_is_bounded():
    import agent.llm as llm
    max_retries = int(os.environ.get("ECOM_LLM_MAX_RETRIES", "2"))
    # worst-case single-call wall clock must leave room for several cycles in TASK_TIMEOUT_S
    assert llm._HTTP_READ_TIMEOUT_S * (max_retries + 1) <= 400.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_run_deadline.py::test_llm_retry_budget_is_bounded -v`
Expected: FAIL (`180 * (N+1) > 400` with the current 180s default and a 3-attempt loop).

- [ ] **Step 3: Lower the default read timeout and bound retries**

In `agent/llm.py`, change the read-timeout default 180 → 120:

```python
    _HTTP_READ_TIMEOUT_S = float(os.environ.get("ECOM_LLM_HTTP_READ_TIMEOUT_S", "120"))
```

Add near the transient-retry constants:

```python
_MAX_RETRIES = int(os.environ.get("ECOM_LLM_MAX_RETRIES", "2"))
```

The per-tier retry loop is `for attempt in range(max_retries + 1)` where `max_retries: int = 3`
is a **function default** (`agent/llm.py:359`, repeated for the three provider transports — there
is NO literal `range(3)`). Change that default `3 → _MAX_RETRIES` (or wire each call site to pass
`_MAX_RETRIES`). Confirm the line with `grep -n "max_retries" agent/llm.py` and show the exact
edit in the diff. The constants-contract test (Step 1) is the gate.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_run_deadline.py::test_llm_retry_budget_is_bounded -v`
Expected: PASS (`120 * 3 = 360 <= 400`).

- [ ] **Step 5: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/llm.py tests/test_run_deadline.py
git commit -m "fix(llm): bound per-call retry/timeout budget (read 120s, 2 retries) to fit the task cap

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Phase 1 — Resolve-or-prove

> **Phase-1 gate:** start only after Phase 5 Task 1 is merged (a scored run is now possible).

### Task 3: `agent/resolve.py` — normalization, `relax_sql`, prose-param parsing

**Files:**
- Create: `agent/resolve.py`
- Test: `tests/test_resolve.py` (create)

**Interfaces:**
- Produces:
  - `normalize_value(s) -> str` — lower, trim, collapse internal whitespace, strip a trailing unit token from `{l, ml, mm, cm, m, kg, g, v, w}`.
  - `sql_quote(s) -> str` — single-quoted SQL literal.
  - `relax_sql(sql) -> str` — rewrite text equality predicates `X = 'lit'` → `LOWER(TRIM(X)) = '<norm lit>'`; for a `property_value_text = '<num> <unit?>'` predicate also OR-in `property_value_number = <num>`. Returns the input unchanged when no equality predicate is present.
  - `literal_from_prose(s) -> str` — pull the quoted literal out of an INTENT prose param value (`"literal 'Sika' from instruction"` → `Sika`); fall back to the trimmed string when no quote is present.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolve.py
from agent.resolve import normalize_value, sql_quote, relax_sql, literal_from_prose


def test_normalize_strips_unit_suffix_and_case():
    assert normalize_value("8 l") == "8"
    assert normalize_value("1000 ml") == "1000"
    assert normalize_value("900 mm") == "900"
    assert normalize_value("  Gray ") == "gray"
    assert normalize_value("Tool   Bag") == "tool bag"
    assert normalize_value("20 V") == "20"
    assert normalize_value("hybrid sealant") == "hybrid sealant"


def test_sql_quote_escapes():
    assert sql_quote("a'b") == "'a''b'"


def test_literal_from_prose():
    assert literal_from_prose("literal 'Sika' from instruction") == "Sika"
    assert literal_from_prose("literal '100 ml' from instruction") == "100 ml"
    assert literal_from_prose("Vienna") == "Vienna"


def test_relax_sql_text_predicate():
    out = relax_sql("SELECT 1 WHERE pv.color_family = 'Gray'")
    assert "lower(trim(pv.color_family))" in out.lower()
    assert "'gray'" in out.lower()


def test_relax_sql_numeric_fallback_on_property_value_text():
    out = relax_sql("SELECT 1 WHERE p0.property_value_text = '8 l'").lower()
    assert "p0.property_value_number = 8" in out
    assert "lower(trim(p0.property_value_text))" in out


def test_relax_sql_noop_without_equality():
    sql = "SELECT count(*) FROM stores"
    assert relax_sql(sql) == sql
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'agent.resolve'`)

- [ ] **Step 3: Implement the module**

```python
# agent/resolve.py
"""Deterministic key-entity resolution helpers: value normalization, SQL literal
quoting, predicate relaxation, prose-param literal extraction, product resolution.

General data hygiene only — NO task-specific values. Relaxation is applied to the
SQL PLAN already wrote so an exact-match miss on an entity that EXISTS (case/unit/
whitespace skew) does not collapse to UNSUPPORTED."""
from __future__ import annotations

import re

_UNIT_SUFFIX = re.compile(r"\s*\b(?:l|ml|mm|cm|m|kg|g|v|w)\b\s*$", re.IGNORECASE)
_WS = re.compile(r"\s+")
# X = 'lit'  where X is a (optionally table-qualified) column reference
_EQ = re.compile(r"([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?)\s*=\s*'((?:[^']|'')*)'")
_LEAD_NUM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")
_PROSE = re.compile(r"'((?:[^']|'')*)'")


def normalize_value(s: str) -> str:
    s = (s or "").strip().lower()
    s = _WS.sub(" ", s)
    s = _UNIT_SUFFIX.sub("", s).strip()
    return s


def sql_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def literal_from_prose(s: str) -> str:
    """Extract the quoted literal from an INTENT prose param value, else the trimmed input."""
    m = _PROSE.search(s or "")
    return (m.group(1) if m else (s or "")).strip()


def _relax_one(col: str, lit: str) -> str:
    norm = normalize_value(lit)
    text_clause = f"LOWER(TRIM({col})) = {sql_quote(norm)}"
    if col.lower().endswith("property_value_text"):
        m = _LEAD_NUM.match(lit)
        if m:
            num_col = col[: -len("property_value_text")] + "property_value_number"
            return f"({text_clause} OR {num_col} = {m.group(1)})"
    return text_clause


def relax_sql(sql: str) -> str:
    """Relax every `X = 'lit'` equality in `sql`: case/whitespace/unit-insensitive text
    match, plus a numeric-column fallback for property_value_text. No equality → unchanged."""
    def repl(m: "re.Match") -> str:
        return _relax_one(m.group(1), m.group(2))
    return _EQ.sub(repl, sql)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/resolve.py tests/test_resolve.py
git commit -m "feat(resolve): normalization, relax_sql (text + numeric fallback), prose-literal parse

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Interpreter auto-relax — retry a 0-row resolving discovery step

**Files:**
- Modify: `agent/interpreter.py` (discovery loop, ~L335-346; add a small helper near `_payload`)
- Test: `tests/test_interpreter_relax.py` (create)

**Interfaces:**
- Consumes: `resolve.relax_sql`; `_payload(result)` (existing, returns stdout text); `vm.exec(path="/bin/sql", stdin=<sql>)`.
- Produces: helper `_rows_in_payload(pay) -> int` (data-row count = non-empty lines minus header); a changed discovery loop that, for a read-only `/bin/sql` step returning 0 data rows, re-runs once with `relax_sql(stdin)` and uses the relaxed result when it has rows.

**Why:** PLAN already writes the correct resolving query against the real schema; only the literal formatting misses (`property_value_text='8 l'` vs queried `'8'`). Relaxing PLAN's own query needs no descriptor re-derivation and is general across entity types.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interpreter_relax.py
from agent.ir_models import PlanIR, IntentSpec, AnswerShape
from agent import interpreter


class _RelaxVM:
    """Exact query (no LOWER) → 0 rows; relaxed query (has LOWER) → 1 row."""
    def __init__(self):
        self.sqls = []

    def exec(self, path=None, stdin=None, **kw):
        self.sqls.append(stdin or "")
        class R:
            pass
        r = R()
        if "lower(" in (stdin or "").lower():
            r.stdout = "product_sku,record_path\nSKU-7,/proc/products/sku-7.json\n"
        else:
            r.stdout = "product_sku,record_path\n"
        r.exit_code = 0
        return r


def _plan(sql):
    return PlanIR.model_validate({
        "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": sql}, "bind": "res"}],
        "rowsets": [], "compute": [], "custom_extract": [],
        "decision": {"branches": [], "default_label": "ok"},
        "ops": [],
        "answer": {"ok": {"message": "done", "outcome": "OUTCOME_OK", "refs": []}},
    })


def _intent():
    return IntentSpec(objective="x", desired_outcome="OUTCOME_OK",
                      outcome_space=["OUTCOME_OK"], answer_shape=AnswerShape(msg_skeleton="x"))


def test_zero_row_resolving_step_is_retried_relaxed():
    vm = _RelaxVM()
    sql = "SELECT product_sku, record_path FROM product_variants pv WHERE pv.brand = 'Sika'"
    res = interpreter.interpret(_plan(sql), _intent(), vm)
    assert any("lower(" in s.lower() for s in vm.sqls), "relaxed retry was issued"
    assert "SKU-7" in interpreter._payload(res.env["res"]), "relaxed result rebound into env"
```

> Before running, verify `PlanIR`/`Step`/`AnswerTemplateIR` field names against `agent/ir_models.py` (the `model_validate` dict must match — adjust keys like `from_`, `bind`, `guard_label`, `default_label` if the models differ).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_interpreter_relax.py -v`
Expected: FAIL (exact query returns 0 rows, no relaxed retry issued → `vm.sqls` has no LOWER query; `res.env["res"]` payload header-only).

- [ ] **Step 3: Add the row-count helper**

In `agent/interpreter.py`, near `_payload`:

```python
def _rows_in_payload(pay: str) -> int:
    """Data-row count for a delimited /bin/sql payload (non-empty lines minus header)."""
    lines = [ln for ln in (pay or "").splitlines() if ln.strip()]
    return max(0, len(lines) - 1)
```

- [ ] **Step 4: Hook auto-relax into the discovery loop**

Replace the discovery loop (currently lines ~335-346) with:

```python
    from .resolve import relax_sql
    for step in plan.discovery:
        kwargs = _resolve_args(step.args, env)
        _validate_dispatch(step.rpc, step.args, mutation_landed)
        result = getattr(vm, step.rpc.lower())(**kwargs)
        # Auto-relax (A-seat): a read-only /bin/sql resolving step that returns 0 data rows
        # is retried once with normalized predicates (case/unit/whitespace + numeric-column
        # fallback). If the relaxed query finds rows, use it; else the empty result stands.
        if step.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            pay0 = _payload(result)
            stdin0 = str(kwargs.get("stdin") or "")
            if not _is_sql_banner(pay0) and _rows_in_payload(pay0) == 0 and stdin0:
                relaxed = relax_sql(stdin0)
                if relaxed != stdin0:
                    r2 = vm.exec(path="/bin/sql", stdin=relaxed)
                    if _rows_in_payload(_payload(r2)) > 0:
                        result = r2
                        kwargs = dict(kwargs, stdin=relaxed)
        if step.bind:
            env[step.bind] = result
        pay = _payload(result)
        observations.append(f"[{step.rpc} {kwargs.get('path', kwargs.get('root', ''))}] {pay[:_OBS_PER_CALL]}")
        if step.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(pay)
            if _is_sql_banner(pay):
                raise _refuse("sql returned usage banner — SQL not delivered via stdin", False)
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_interpreter_relax.py -v`
Expected: PASS

- [ ] **Step 6: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter_relax.py
git commit -m "feat(interpreter): auto-relax 0-row /bin/sql resolving discovery step (text + numeric)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: INVESTIGATE descriptor-probe fallback

**Files:**
- Modify: `agent/resolve.py` (add `resolve_product`), `agent/investigate.py` (add `descriptors_from_intent`, `run_resolution_probe`; call after the ReAct loop)
- Test: `tests/test_resolve.py`, `tests/test_investigate_resolve.py` (create)

**Interfaces:**
- Produces in `resolve.py`:
  `resolve_product(vm, *, columns: dict, properties: dict, limit=5) -> list[dict]` — build a SELECT against `product_variants pv` with `pv.<col> = 'val'` per column and an `EXISTS(... product_variant_properties)` per property; run exact, then `relax_sql` of the same query; first non-empty wins; rows are `{"product_sku","record_path"}`.
- Produces in `investigate.py`:
  `descriptors_from_intent(intent) -> tuple[dict, dict]` — parse prose params into `(columns, properties)` via `literal_from_prose`; map keys containing `brand`→`brand`, `series`→`series`, `model`→`model`, `family`/`line`/`name`→`product_name`; any other key → a property keyed by the param-key (stripped of a `product_`/`_family` affix). Prose-only params (e.g. `{"exists": "<query>"}`) → `({}, {})`.
  `run_resolution_probe(vm, intent, brief) -> None` — resolve and bind `brief.env["resolved_product_sku"/"resolved_product_record_path"]` plus `brief.env[f"resolved:{source}"]` per record_path RefSpec source in `required_refs[desired_outcome]`. Best-effort, never raises.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_resolve.py
from agent.resolve import resolve_product


class _FakeVM:
    def __init__(self): self.calls = []
    def exec(self, path=None, stdin=None, **kw):
        self.calls.append(stdin or "")
        class R: pass
        r = R()
        r.stdout = ("product_sku,record_path\nSKU-1,/proc/products/sku-1.json\n"
                    if "lower(" in (stdin or "").lower()
                    else "product_sku,record_path\n")
        return r


def test_resolve_product_falls_through_to_relaxed():
    vm = _FakeVM()
    rows = resolve_product(vm, columns={"brand": "Milwaukee"}, properties={"volume": "8 l"})
    assert rows == [{"product_sku": "SKU-1", "record_path": "/proc/products/sku-1.json"}]
    assert len(vm.calls) >= 2
```

```python
# tests/test_investigate_resolve.py
from agent.investigate import descriptors_from_intent, run_resolution_probe, Brief
from agent.ir_models import IntentSpec, AnswerShape, RefSpec


def _intent():
    return IntentSpec(
        objective="count units",
        desired_outcome="OUTCOME_OK",
        params={"product_brand": "literal 'Sika' from instruction",
                "volume": "literal '100 ml' from instruction"},
        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
        answer_shape=AnswerShape(msg_skeleton="count: %d"),
        required_refs={"OUTCOME_OK": [RefSpec(kind="record_path", source="$product.record_path")]},
    )


class _VM:
    def exec(self, path=None, stdin=None, **kw):
        class R: stdout = "product_sku,record_path\nSKU-9,/proc/products/sku-9.json\n"
        return R()


def test_descriptors_parse_prose_params():
    cols, props = descriptors_from_intent(_intent())
    assert cols.get("brand") == "Sika"
    assert props.get("volume") == "100 ml"


def test_probe_binds_resolved_record_path():
    brief = Brief()
    run_resolution_probe(_VM(), _intent(), brief)
    assert brief.env.get("resolved_product_record_path") == "/proc/products/sku-9.json"
    assert brief.env.get("resolved:$product.record_path") == "/proc/products/sku-9.json"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_resolve.py tests/test_investigate_resolve.py -v`
Expected: FAIL (`ImportError`: `resolve_product` / `descriptors_from_intent` not defined).

- [ ] **Step 3: Implement `resolve_product` in `agent/resolve.py`**

```python
# add to agent/resolve.py
def _parse_csv(stdout: str) -> list[dict]:
    lines = [ln for ln in (stdout or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    hdr = lines[0].split(",")
    return [dict(zip(hdr, ln.split(","))) for ln in lines[1:]]


def _sql_stdout(vm, sql: str) -> str:
    out = vm.exec(path="/bin/sql", stdin=sql)
    return out.get("stdout", "") if isinstance(out, dict) else getattr(out, "stdout", "")


def _product_select(columns: dict, properties: dict) -> str:
    clauses = [f"pv.{c} = {sql_quote(v)}" for c, v in columns.items()]
    for i, (k, v) in enumerate(properties.items()):
        clauses.append(
            f"EXISTS (SELECT 1 FROM product_variant_properties p{i} "
            f"WHERE p{i}.product_sku = pv.product_sku "
            f"AND p{i}.property_key = {sql_quote(k)} "
            f"AND p{i}.property_value_text = {sql_quote(v)})")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return f"SELECT pv.product_sku, pv.record_path FROM product_variants pv{where} LIMIT 5;"


def resolve_product(vm, *, columns: dict, properties: dict, limit: int = 5) -> list[dict]:
    """Resolve [{product_sku, record_path}] via exact → relax_sql(exact). Empty ⇒ unresolved."""
    if not columns and not properties:
        return []
    exact = _product_select(columns, properties)
    for sql in (exact, relax_sql(exact)):
        rows = _parse_csv(_sql_stdout(vm, sql))
        if rows:
            return [{"product_sku": r.get("product_sku", ""),
                     "record_path": r.get("record_path", "")} for r in rows[:limit]]
    return []
```

- [ ] **Step 4: Implement the probe in `agent/investigate.py`**

Add import near the top: `from . import resolve as _resolve`. Then:

```python
_COL_KEYS = (("brand", "brand"), ("series", "series"), ("model", "model"),
             ("family", "product_name"), ("line", "product_name"), ("name", "product_name"))


def descriptors_from_intent(intent) -> tuple[dict, dict]:
    """Parse INTENT prose params into (columns, properties). Free-form keys map to schema
    columns by substring (brand/series/model/family|line|name); other keys become property
    filters. Prose values reduce to their quoted literal. General — no task values. A param
    with no usable literal (e.g. {'exists': '<long prose query>'}) is skipped."""
    cols: dict = {}
    props: dict = {}
    for key, raw in (intent.params or {}).items():
        if not isinstance(raw, str):
            continue
        lit = _resolve.literal_from_prose(raw)
        # skip prose-only params: no quoted literal AND long free text
        if (lit == raw and "'" not in raw and (" " in raw and len(raw) > 60)):
            continue
        if not lit:
            continue
        lk = key.lower()
        mapped = next((col for sub, col in _COL_KEYS if sub in lk), None)
        if mapped:
            cols[mapped] = lit
        else:
            prop_key = lk.replace("product_", "").replace("_family", "")
            props[prop_key] = lit
    return cols, props


def run_resolution_probe(vm, intent, brief: "Brief") -> None:
    """Best-effort key-entity resolution (descriptor-probe fallback). Binds resolved SKU /
    record_path into brief.env so PLAN builds against a known-resolving entity. Never raises."""
    cols, props = descriptors_from_intent(intent)
    if not cols and not props:
        return
    try:
        rows = _resolve.resolve_product(vm, columns=cols, properties=props)
    except Exception as e:
        brief.notes.append(Note(goal="resolve product", lesson=f"resolve error: {e}"))
        return
    if not rows:
        brief.notes.append(Note(goal="resolve product",
                                lesson="product unresolved after relaxation"))
        return
    r = rows[0]
    brief.env["resolved_product_sku"] = r["product_sku"]
    brief.env["resolved_product_record_path"] = r["record_path"]
    for ref in (intent.required_refs or {}).get(intent.desired_outcome, []):
        if ref.kind == "record_path" and ref.source:
            brief.env[f"resolved:{ref.source}"] = r["record_path"]
    brief.notes.append(Note(goal="resolve product", tool="sql",
                            observation_digest=f"resolved {r['product_sku']}",
                            lesson="key product resolved; build aggregation against it",
                            refs_found=[r["record_path"]]))
```

In `investigate()`, immediately before `log_investigate_stop_auto(stop_reason, 0, 0)`:

```python
        run_resolution_probe(vm, intent, brief)   # B-seat: descriptor-probe fallback
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_resolve.py tests/test_investigate_resolve.py -v`
Expected: PASS

- [ ] **Step 6: Run the suite + commit**

Run: `uv run pytest tests/ -q` → PASS

```bash
git add agent/resolve.py agent/investigate.py tests/test_resolve.py tests/test_investigate_resolve.py
git commit -m "feat(investigate): prose-param descriptor probe binds resolved entity into Brief.env

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `sufficient()` requires the key-entity record_path to be resolved

**Files:**
- Modify: `agent/investigate.py` (`sufficient`, ~L159-172)
- Test: `tests/test_investigate_resolve.py`

**Interfaces:**
- Consumes: `brief.env[f"resolved:{source}"]` from Task 5; `intent.required_refs[desired_outcome]`.
- Produces: changed `sufficient(intent, env)` — a `record_path` RefSpec is grounded only when `env[f"resolved:{ref.source}"]` is set (was: skipped as "PLAN's job").

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_investigate_resolve.py
from agent.investigate import sufficient


def test_sufficient_requires_resolved_record_path():
    intent = _intent()
    assert sufficient(intent, {}) is False
    assert sufficient(intent, {"resolved:$product.record_path": "/proc/p.json"}) is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_investigate_resolve.py::test_sufficient_requires_resolved_record_path -v`
Expected: FAIL (current `sufficient` returns True for `{}` because it skips `record_path` refs).

- [ ] **Step 3: Update `sufficient()`**

Replace its body with:

```python
def sufficient(intent, env: dict) -> bool:
    """True when every required_ref for the desired outcome is grounded. Doc refs use their
    env_key; record_path refs are grounded only when the resolution probe bound
    `resolved:{source}` — the key entity must actually resolve before stopping."""
    outcome = intent.desired_outcome
    refs = (intent.required_refs or {}).get(outcome, [])
    for ref in refs:
        if ref.kind == "record_path" and ref.source:
            if not env.get(f"resolved:{ref.source}"):
                return False
            continue
        g = ref.grounded(env)
        if g is None:
            continue
        if not g:
            return False
    return True
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_investigate_resolve.py -v`
Expected: PASS

- [ ] **Step 5: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: PASS. If an existing investigate test asserted sufficiency on an unresolved record_path, update it to bind `resolved:{source}` (the new contract) and note the change in the commit body.

- [ ] **Step 6: Commit**

```bash
git add agent/investigate.py tests/test_investigate_resolve.py
git commit -m "fix(investigate): sufficiency requires the key-entity record_path to be resolved

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Manual trace verification + scored slice

**Files:** none (verification task)

- [ ] **Step 1: Pick a live B1 product task and run it traced**

Run: `LOG_LEVEL=DEBUG ECOM_TASK_TIMEOUT_S=600 uv run python main.py t20`
Expected: completes (no hang) and emits the `ИТОГО` table.

- [ ] **Step 2: Inspect the newest `logs/*/t20.jsonl`**

Confirm one of the two seats fired:
- interpreter auto-relax: a discovery `Exec /bin/sql` whose first run had 0 rows is followed by a relaxed (`LOWER(`-containing) query that returns rows; OR
- probe: an `investigate` note "key product resolved …".
And the submitted outcome is no longer `OUTCOME_NONE_UNSUPPORTED` with "product not found".

Expected: the product resolves and the answer computes (`OUTCOME_OK`). If still failing, capture the trace and open a follow-up — do NOT add a task-specific rule.

- [ ] **Step 3: Scored slice to confirm no regression**

Run: `ECOM_TASK_TIMEOUT_S=600 uv run python main.py t01,t03,t08,t17,t20,t32,t33`
Expected: finishes end-to-end and prints grader scores; the B1 "not found" give-ups trend toward `OUTCOME_OK`. Record the before/after outcome distribution for the phase write-up.

---

## Self-Review

**Spec coverage:**
- Spec Phase 5 (hard timeout + per-task budget) → Tasks 1–2. ✓ Orchestration per-task deadline (load-bearing) + bounded retry budget. (Embed/harness/CC paths confirmed already httpx/subprocess timeout-bounded; the orchestration backstop catches the compounding-timeout hang.)
- Spec Phase 1 seat (a) interpreter auto-relaxation → Tasks 3 (`relax_sql`) + 4 (discovery hook). ✓
- Spec Phase 1 seat (b) descriptor-probe fallback → Tasks 3 (`literal_from_prose`) + 5 (`descriptors_from_intent`, `resolve_product`, probe). ✓
- Spec Phase 1 "`sufficient()` no longer punts" → Task 6. ✓
- Spec Phase 1 "no give-up on empty for presumed-existing entity" → realized by Task 4's relax-before-it-feeds-a-branch retry + Task 6's stop-gate. ✓ Verified by Task 7.
- Phases 2–4 explicitly deferred. ✓

**Placeholder scan:** No "TBD/TODO/handle edge cases". Two explicit verification notes (confirm `PlanIR` field names in Task 4's test dict; confirm the `range(3)` retry-loop literal in Task 2) are concrete checks with shown fallbacks, not deferred work.

**Type consistency:** `relax_sql(str)->str`, `normalize_value(str)->str`, `literal_from_prose(str)->str`, `resolve_product(...)->list[{"product_sku","record_path"}]` defined in Task 3/5 and consumed identically in Tasks 4–5. `brief.env["resolved:{source}"]` written in Task 5 is the exact key read by `sufficient()` in Task 6. `_collect_with_deadline -> {task_id: res_tuple}` (Task 1) consumed in `_run_one_pass`. `_rows_in_payload(str)->int` defined and used within Task 4.

**Residual risk (flagged, non-blocking):** `descriptors_from_intent`'s key→column heuristic is best-effort; the interpreter auto-relax seat (Task 4) does NOT depend on it and covers the dominant case, so a mis-mapped descriptor degrades to "probe binds nothing" (PLAN's own relaxed query still resolves) rather than a wrong answer.
