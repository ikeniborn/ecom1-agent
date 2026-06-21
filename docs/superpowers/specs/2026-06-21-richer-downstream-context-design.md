---
review:
  spec_hash: 7136e5521c553673
  last_run: 2026-06-21
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings: []
chain:
  intent: null
---

# Richer Downstream Context — Design

**Date:** 2026-06-21
**Status:** Approved (design); pending implementation plan
**Scope:** Two independent improvements, coupled only by theme ("give downstream phases more context").

- **Part A** — INVESTIGATE surfaces key data-paths into the Brief before stopping (flag-gated, default off).
- **Part B** — `_enrich_prim_error` attaches a primitive CONTRACT to lint-reject messages, not just runtime/arity errors.

---

## Background

### Part A — the Lever-3 trade-off

The step-wise INVESTIGATE phase (`agent/investigate.py`) stops as soon as `sufficient(intent, env)`
returns true — i.e. every investigator-groundable `required_ref` for the desired outcome is grounded
(`investigate.py:159`, gate at `:353`). Those refs are **doc-grounding** refs (governing doc, policy
paths), not data-source paths.

Hypothesis (unproven): the early stop (~3 steps) can cut off side-discovery of key **data-paths** (e.g.
`/proc/payments`) that the older, free-wandering ~11-step loop happened to surface. PLAN then plans
against data sources it has never seen probed. Benchmark re-seeding (data randomised every StartRun)
muddies a clean before/after comparison, so the payoff is genuinely uncertain — the design must be
measurable and reversible.

The slim seed (`orchestrator.gather_prephase_facts(..., slim=True)`) deliberately ships only
identity + schema NAMES + doc PATHS; `path_listings` and `target_records` are skipped and fetched
on-demand by the investigator. So the investigator *can already* reach data-paths — it just stops
before doing so once doc-refs are grounded.

### Part B — the L2 CONTRACT gap

`pipeline._enrich_prim_error` (`pipeline.py:99`) appends a primitive's contract to an error so the
retry sees the spec, not just the symptom. Its regex is:

```python
m = _re.search(r"(?:compute step|primitive) '([a-z_]+)'", err)
```

It matches:
- `compute step 'X'` — interpret runtime failure (`interpreter.py:323`)
- `primitive 'X'` — `check_primitive_exists` / `check_primitive_arity` (`harness.py:88,110`)

It does **not** match the lint-reject formats:
- `... (compute 'X' arg $root)` — `check_compute_on_raw_discovery_bind` (`harness.py:152`)
- `'X' expects list[dict]; use 'get'...` — `primitive_contract` spec messages (`checks.yaml`)

So CONTRACT never attaches when a plan is rejected at **lint** time, only at interpret/runtime time.
Cheap to fix.

---

## Part A — INVESTIGATE data-path surfacing

### Configuration

New env flag `ECOM_INVESTIGATE_DATA_PATHS` (default `0`). When `0`, INVESTIGATE behaves **exactly** as
today — no seed computed, no forced probe, `sufficient()` unchanged. This is the regression guard and
the A/B baseline.

### Seed construction (deterministic, no wandering)

Computed in `pipeline.run_pipeline` (which has both `instruction` and `task_id`), right before the
`investigate(...)` call (`pipeline.py:400`):

```python
data_seed = []
if os.environ.get("ECOM_INVESTIGATE_DATA_PATHS", "0") == "1":
    from .orchestrator import _extract_path_literals      # function-level: orchestrator already
    from .learned_store import load_prephase_deep_read    # imported by the caller -> no import cycle
    data_seed = _dedup(
        _extract_path_literals(instruction)
        + [d for d in load_prephase_deep_read(task_id) if d.startswith("/")]
    )
brief = investigate(vm, intent, seed=facts, oracle=_oracle, data_paths=data_seed)
```

Source = instruction path-literals (reuses `orchestrator._extract_path_literals`, capped by
`ECOM_PREPHASE_PATH_LITERALS`) ∪ learned `prephase_deep_read` path entries. Bounded by that cap plus
the step budget; no free exploration is introduced.

> **Import-cycle note:** `orchestrator` imports `pipeline` (it is the caller of `run_pipeline`). A
> module-level `from .orchestrator import _extract_path_literals` in `pipeline.py` would create a
> cycle at import time. The function-level import inside `run_pipeline` is safe because, by the time
> `run_pipeline` runs, `orchestrator` is fully initialised and present in `sys.modules`.

### `investigate()` signature

Add `data_paths: list[str] | None = None`. The existing `seed` parameter stays reserved/unused. When
`data_paths` is falsy, all new behaviour is inert (mirrors flag-off).

### Forced data-probe (mirrors `_forced_doc_read`)

A new `_forced_data_probe(env, data_paths, probed)` returns a read-action for the first **un-probed**
seed path, or `None`. Per-step action priority becomes:

1. `_forced_doc_read` (ground the governing doc) — unchanged, highest priority
2. `_forced_data_probe` (probe a seed data-path) — **new**
3. free router (`router(...)`) — unchanged

**Probe-tool heuristic (deterministic):** a `.` in the path basename ⇒ likely a file ⇒ `read`;
otherwise ⇒ likely a directory ⇒ `list`. (e.g. `/proc/payments` → `list`, `/docs/policy.md` → `read`.)

**Probe-once:** a seed is marked probed after exactly one attempt, regardless of result. A nonexistent
path or a tool error records a step lesson and still counts as probed — it never re-burns budget. The
probed set is tracked alongside `seen` in the loop.

**Recording:** after a probe, the digested observation is stored at
`brief.env["data_paths"][path] = <digest>`. `render_brief` already iterates `brief.env`, so PLAN sees
a `data_paths: {...}` line under `RESOLVED_ENV` with no change to the renderer.

### Stop condition

`sufficient(...)` gains optional `data_paths` / `probed` arguments:

```
stop when:  (all investigator-groundable doc-refs grounded)
            AND (data_paths empty OR every data_path in `probed`)
        OR  step budget exhausted (unchanged ceiling = ECOM_INVESTIGATE_MAX_STEPS, default 6)
```

The step ceiling is **not** raised. Forcing data-probes inside the existing 6-step budget is exactly
what closes the early (~3-step) stop the hypothesis targets. Empty seed ⇒ the data clause is vacuously
true ⇒ identical to today.

### Trace signal (measurement)

On loop exit, emit a trace event `investigate_stop` with
`{reason: "sufficient" | "budget" | "data_probed", data_paths_total, data_paths_probed}` via the
existing trace seam (mirrors `log_lint_fire_auto`). `data_probed` denotes the case where the data-path
clause was the last gate to clear. This makes the hypothesis measurable: run a baseline (flag off) and
a flag-on pass, compare stop reasons, data-path counts, and task scores.

---

## Part B — CONTRACT on lint messages

Broaden `_enrich_prim_error` (`pipeline.py:99`) in two steps:

```python
def _enrich_prim_error(err: str) -> str:
    import re as _re
    from .primitives import contract
    # structured forms: "compute step 'X'", "compute 'X'", "primitive 'X'"
    m = _re.search(r"(?:compute(?: step)?|primitive) '([a-z_]+)'", err)
    prim = m.group(1) if m else None
    if prim is None:
        # primitive_contract spec messages lead with the quoted primitive, e.g.
        # "'column' expects list[dict]; use 'get'..." — take the first quoted token
        # that names a known primitive (contract() is empty for non-primitives).
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

1. `compute step` → `compute(?: step)?` — also matches `compute 'X'` from
   `check_compute_on_raw_discovery_bind`.
2. Fallback scan of all quoted `'([a-z_]+)'` tokens, taking the first whose `contract()` is non-empty
   — matches `primitive_contract` spec messages that lead with the primitive in quotes.

Safety: `contract()` returns `""` for an unknown primitive, so a quoted token that is not a primitive
(e.g. `'get'` appearing later in a message) never produces a spurious CONTRACT. The existing
behaviour for `compute step 'X'` / `primitive 'X'` is preserved (matched by the structured regex
first).

---

## Testing

### Part B (unit, `_enrich_prim_error`)
- `compute 'column' arg $rows` → CONTRACT for `column` appended once.
- `'column' expects list[dict]; use 'get'+'to_number'` → CONTRACT for `column` (not `get`/`to_number`).
- `compute step 'sum_col' failed: ...` → CONTRACT for `sum_col` (existing behaviour preserved).
- `primitive 'count' takes 1 arg(s)` → CONTRACT for `count` (existing behaviour preserved).
- A message quoting a non-primitive only (e.g. `'foo'`) → unchanged, no CONTRACT line.
- A message already containing its CONTRACT → not doubled (`c not in err` guard).

### Part A (unit + integration)
- `_forced_data_probe`: returns first un-probed seed; `None` when all probed; honours the
  `read`/`list` extension heuristic.
- Probe-once: a seed that errors/returns empty is marked probed and not re-issued.
- `sufficient(...)` with a non-empty `data_paths` and an un-probed member → `False`; all probed →
  falls back to the doc-ref result.
- **Regression guard:** with `ECOM_INVESTIGATE_DATA_PATHS=0` (or `data_paths=None`), `investigate`
  produces an identical Brief to the pre-change code on a fixed scenario.
- Integration: with the flag on and a seed path that exists, `brief.env["data_paths"][path]` is
  populated and `render_brief` includes it.

---

## Files touched

| File | Change |
|------|--------|
| `agent/pipeline.py` | data-seed construction at the investigate call; broaden `_enrich_prim_error` |
| `agent/investigate.py` | `data_paths` param; `_forced_data_probe`; `sufficient()` data clause; `investigate_stop` trace event |
| `CLAUDE.md` (root) + `agent/CLAUDE.md` | document `ECOM_INVESTIGATE_DATA_PATHS` and the data-path stop behaviour |
| `tests/` | unit tests for Part A and Part B |

Prompts (`data/prompts/*.md`) are **not** touched — Part A is a deterministic code gate, Part B is a
regex broadening. No task-specific knowledge enters prompts (per the project's prompt-engineering
rules).

## Non-goals

- Raising `ECOM_INVESTIGATE_MAX_STEPS`.
- Table (non-`/`) data-path probing — only absolute-path seeds are probed in v1; learned
  `prephase_deep_read` table entries remain a PLAN-side concern.
- Changing the doc-ref grounding mechanism (`_forced_doc_read` / `_ground_doc_refs`).
- Any change when `ECOM_INVESTIGATE_DATA_PATHS=0`.
