---
review:
  spec_hash: 05bd146a260ec6cc
  last_run: 2026-06-18
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "F6 — LEARN/oracle for exact-match brittleness"
      section_hash: 97bc33281c09c4bd
      text: "'LIKE where appropriate' has no explicit criterion for when LIKE vs eq; acceptable as a method-rule but the boundary is implicit."
      verdict: accepted
      verdict_at: 2026-06-18
    - id: F-002
      phase: clarity
      severity: WARNING
      section: "F7 — DOC_SELECT fallback"
      section_hash: 6ad6697160e08217
      text: "'Lightweight / defensive only' lacks a quantified DoD beyond the F7 unit test; bounded by the test so non-blocking."
      verdict: accepted
      verdict_at: 2026-06-18
chain:
  intent: null
---

# Interpreter Robustness — Design Spec

**Date:** 2026-06-18
**Status:** Approved for planning
**Scope:** All seven defects surfaced by the t01 failure diagnosis
(`docs/t01-failure-diagnosis.html`), plus a learnable lint registry (F8) that lets the
harness's check catalogue grow from validated lessons while the enforcement engine stays
deterministic code.

## Problem

Task `t01` ("does Festool SYS 3JJ-9LM tool bag exist in the catalogue?") is winnable —
in run `15:08` the SQL returned the correct row (`STO-12JLHT7D`,
`record_path=/proc/catalog/STO-12JLHT7D.json`, `storage_type=tool bag`). Yet three
consecutive runs all ended in `OUTCOME_NONE_CLARIFICATION`, each via a **different**
failure mode. The pipeline is a chain of fragile links; P(success) is the product of
each link working, so the reliability ceiling is low.

### Observed failure modes (same task, 3 runs)

| Run | Outcome | Grader feedback | Root cause |
|-----|---------|-----------------|------------|
| 14:59 | CLARIFY | answer missing required reference `/proc/catalog/FST-APSRIZJW.json` | `/bin/sql` returned its usage banner (SQL not delivered via stdin) → empty rowset |
| 15:07 | CLARIFY | expected OUTCOME_OK, got OUTCOME_NONE_UNSUPPORTED | SQL returned 0 rows (PLAN variance + exact-match vs re-seeded data) → `not_found` |
| 15:08 | CLARIFY | expected OUTCOME_OK, got OUTCOME_NONE_CLARIFICATION | Interpreter crash `'str' object has no attribute 'get'` on **correct** data |

### Root-cause detail (run 15:08 — the core bug)

PLAN composed primitives with mismatched contracts:

```
{"prim": "first",  "args": ["$row"],                      "into": "first_row"}
{"prim": "column", "args": ["$first_row", "product_name"], "into": "product_name"}
```

- `first($row)` returns a single `dict`.
- `column` (`primitives.py:26`) is a **list** operation: `[r.get(col) for r in rows]`.
- Iterating a `dict` yields its **string keys** → `"product_sku".get(col)` →
  `'str' object has no attribute 'get'`. Crash.
- The correct primitive for one dict is `get` (`primitives.py:47`), not `column`.

The crash escapes `interpret()` as a bare `Exception` (the compute loop at
`interpreter.py:236-238` has no `try`), is caught at `pipeline.py:325` as a `real_vm`
error, fails the `_is_retryable_vm_error` check (the message is not in
`_RETRYABLE_VM_ERROR_PATTERNS`), and dead-ends at clarification after one cycle. An
**interpreter bug is masquerading as a VM error**, and `_ilearn` then writes a
misdirected rule (blaming rowset `format`) that cannot fix code and pollutes the
learned store.

## Goals

1. A correct PLAN over correct data must not crash the interpreter (close #1).
2. A type-incorrect PLAN must produce an actionable, retryable signal — never a
   dead-end `real_vm` error (close #1 + #2).
3. PLAN should be corrected at lint time before wasting a VM round-trip where cheaply
   detectable (#1, #6).
4. `t01` reaches `OUTCOME_OK` with the catalog `record_path` ref on a live run.
5. The set of lint checks is data-driven (a registry), so a new check is a validated
   registry entry — not a code edit — while the act of checking stays code (F8).

## Non-Goals

- No changes to `data/prompts/*.md` (project rule: task-specific knowledge flows through
  LEARN, never prompt patches).
- No redesign of the INTENT→loop→verify pipeline shape.
- No new LLM phases or grammar; primitives are a registry, not new IR grammar.
- No natural-language → executable-code generation. Registry check-specs (F8) are
  **closed-schema structured data** interpreted by a fixed set of code-side `kind`
  handlers. A new *kind* of check is a code change (rare); new *instances* of an existing
  kind are learnable data (common). This preserves the no-codegen invariant the
  deterministic-interpreter redesign was built on.

## Architecture

All changes land in deterministic links + data files. No new LLM calls.

```
orchestrator.py        ──► F7 DOC_SELECT fallback (pre-phase)
pipeline.py            ──► F4 answer-once idempotency; lint() call swap;
                            F8 distill→validate→promote a check-spec candidate
interpreter.py         ──► F1 compute try-wrap + banner detect;
                            F8 lint() = registry dispatcher over check `kind`s
primitives.py          ──► F1 arity/type validation in run_primitive + defensive list-ops
harness.py (new)       ──► F8 load_checks / kind handlers / distill candidate check-spec
harness_validate.py(new)──► F8 validate_check_via_grader (mirror of oracle_validate)
verify.py              ──► F5 regression lock (no code change expected)
data/harness/checks.yaml (new) ──► F8 check-spec registry; F2/F3 seeded as active entries
data/learned/t01.yaml   ──► F6 method-not-value rule
data/oracle/atoms.yaml  ──► F6 normalized-catalog-match atom
```

The lint **engine** (`harness.py` kind handlers + `interpreter.py:lint` dispatcher) is
the trust anchor and is pure code. The lint **catalogue** (`data/harness/checks.yaml`) is
data that grows by validated promotion. Each fix is an isolated unit with a deterministic
`MockVMSpy` unit test.

## Components (8 fixes)

### F1 — Compute crash → typed retryable InterpretError · P0

**Files:** `interpreter.py`, `primitives.py`

- `interpreter.py`: wrap the `compute` loop (236-238) and `custom_extract` loop
  (239-240) in `try/except (TypeError, AttributeError, KeyError, IndexError)` →
  `raise _refuse(f"compute step '{cs.prim}' failed: {e}", mutation_landed)`. Because
  compute runs before any `ops`, `mutation_landed` is `False` here → the pipeline
  retries.
- `primitives.py`: `run_primitive(name, args)` validates the primitive exists and arity
  matches; list-consuming primitives (`column`, `sum_col`, `filter_rows`) raise a clear
  `TypeError("'<prim>' expects list[dict]; use 'get' for a single row")` when handed a
  non-list. The message is the actionable signal for `_ilearn`/PLAN.

**Effect:** run-15:08 crash becomes `InterpretError` at `pipeline.py:318` → `_ilearn` →
`continue` (retry). Next PLAN sees the actionable message and switches to `get`.

### F2 — `primitive_contract` check kind (plan-time, registry-driven) · P0

**Files:** `interpreter.py`, `harness.py`, `pipeline.py`, `data/harness/checks.yaml`

F2 is the first learnable check expressed through the F8 registry, not an inline `if`.

- `harness.py`: a `primitive_contract` kind handler validates each compute step against a
  check-spec — (a) `prim` exists in `PRIMITIVES`; (b) arity matches the primitive's
  parameter count; (c) shape chain — a list-consuming primitive (`column`, `sum_col`,
  `count`, `filter_rows`) must not consume a binding produced by a scalar/dict-producing
  primitive listed in `forbid_source` (e.g. `first`, `get`).
- `data/harness/checks.yaml`: seed an `active` entry `chk_column_on_scalar` (and a
  `chk_primitive_arity` / `chk_primitive_exists`) covering the run-15:08 class.
- `interpreter.py`: `lint_security_first(plan)` → `lint(plan)` dispatches over active
  registry entries by `kind` (the existing security-first check becomes the
  `security_first` kind). Violations raise `InterpretError` before `interpret` runs.
- `pipeline.py:302` calls `lint`; the existing `except (PlanError, InterpretError)` path
  (303-307) routes failures to `_ilearn` + next cycle.

**Effect:** the `first`→`column` mismatch is caught before a VM round-trip via a data
entry; PLAN is corrected one cycle earlier.

### F3 — `sql_stdin` check kind + usage-banner detection (#6) · P1

**Files:** `interpreter.py`, `harness.py`, `data/harness/checks.yaml`

- `harness.py`: a `sql_stdin` kind handler — an `Exec` step with `path == "/bin/sql"`
  must carry a non-empty `stdin`; SQL placed in `args` with empty `stdin` raises
  `InterpretError`. Seed an `active` entry `chk_sql_stdin` in `data/harness/checks.yaml`.
- `interpreter.py` (runtime, not a registry check): after a `/bin/sql` Exec, detect the
  usage banner (payload starts with `# /bin/sql` or contains `Send SQL on stdin`) →
  `raise _refuse("sql returned usage banner — SQL not delivered via stdin", False)`
  (retryable, read-only). This is a runtime guarantee (like F1), not a plan-time check.

**Effect:** run-14:59 man-page path becomes a retryable signal instead of a silent empty
rowset.

### F4 — answer-once idempotency (#4) · P1

**Files:** `pipeline.py`

- Guard `vm.answer` with a single `_answered` flag so the success path (345) and
  `_terminal_clarification` (363) can never both fire. Eliminates the
  `real_vm: answer already provided` error seen in run-14:59 cycle 2.

### F5 — verify-gate regression lock (#3) · P2

**Files:** `tests/` only (verify.py + interpret refuse-invariant already cover this)

- Add a unit test asserting: an OK answer whose required `record_path` ref does not
  resolve never reaches `vm.answer` (the `interpreter.py:277` refuse-invariant fires and
  `verify` I1 at `verify.py:24-31` rejects). Locks current behavior against regressions
  from F1–F4.

### F6 — LEARN/oracle for exact-match brittleness (#5) · P2

**Files:** `data/learned/t01.yaml`, `data/oracle/atoms.yaml`

- `data/learned/t01.yaml`: a method-not-value rule — for catalogue existence queries,
  match brand/model/property normalized (case-insensitive, trimmed, `LIKE` where
  appropriate), apply `first` to the rowset before `column`, and project `record_path`
  into refs. States the method, never the re-seeded values.
- `data/oracle/atoms.yaml`: a general atom on normalized catalogue matching (not
  t01-specific), retrievable by other catalogue tasks.

### F7 — DOC_SELECT fallback (#7) · P2

**Files:** `orchestrator.py`

- In the pre-phase: when the instruction is a product/catalogue query and DOC_SELECT
  returned only irrelevant docs, log the gap and do not break (deterministic fallback,
  no prompt change). Lightweight; t01 has no catalogue doc so this is defensive only.

### F8 — Learnable lint registry (auto-forming harness) · P1

**Files:** `harness.py` (new), `harness_validate.py` (new), `interpreter.py`,
`pipeline.py`, `data/harness/checks.yaml` (new)

The harness's *catalogue of checks* becomes data that grows from validated lessons; the
*enforcement engine* stays deterministic code. This is the kernel-vs-catalogue split:
lessons **propose** checks, the code engine **enforces** them, grader-validation **gates**
promotion.

**Check-spec schema (closed, structural — never natural language):**

```yaml
# data/harness/checks.yaml
- id: chk_column_on_scalar
  kind: primitive_contract     # one of a FIXED, code-backed set of kinds
  prim: column
  arg_index: 0
  expect: list_of_dict
  forbid_source: [first, get]  # binding produced by these = scalar/dict
  severity: error              # error -> InterpretError; warn -> log only
  message: "'column' expects list[dict]; use 'get' for a single row"
  status: active               # candidate | active | inactive
  source_task: t01
```

**Engine (`harness.py` + `interpreter.py:lint`):**
- `load_checks()` reads `data/harness/checks.yaml`; `lint(plan)` dispatches each `active`
  entry to its `kind` handler. Supported kinds (closed set): `security_first` (the H3
  check, migrated), `primitive_contract` (F2), `sql_stdin` (F3), `primitive_exists`,
  `primitive_arity`. A `kind` with no handler is ignored with a logged warning (a new
  kind requires a code change — by design).
- `severity: error` → `InterpretError` (blocks); `severity: warn` → logged, non-blocking.
  `status: candidate` entries are enforced **warn-only** regardless of severity until
  promoted, so an unvalidated check can never dead-end a run.

**Promotion pipeline (mirrors `oracle.distill` / `oracle_validate`):**
- `harness.distill(plan, error)` — gated by env `HARNESS_DISTILL` (default `0`, no cost).
  After a cycle where F1 reclassified a compute crash, it proposes a `candidate`
  check-spec generalised from the failing step (LLM, reason tier).
- `harness_validate.validate_check_via_grader(check, task_id)` — gated by
  `HARNESS_VALIDATE_INLINE` (default `1` when distill is on). Confirms the candidate
  would have flagged the failing plan AND does not flag a known-good plan (no false
  positive), then `harness.promote(check)` flips `candidate` → `active`. On no
  improvement the entry stays `candidate` (warn-only) for an offline promote.

**Trust boundary:** engine code, kind handlers, and the promote gate are never learned —
only check-spec *instances* are. What is learnable is the *discovery* of which check is
needed; the *act* of checking and the validation gate remain deterministic code.

**Env vars (new, mirror the oracle flags):** `HARNESS_DISTILL` (default `0`),
`HARNESS_VALIDATE_INLINE` (default `1`).

**Effect:** F2/F3 ship as seeded `active` entries; future crash classes can be turned
into validated checks without editing `lint`, closing the loop the t01 diagnosis exposed
(an interpreter bug that no existing check caught).

## Data Flow (post-fix, happy path)

```
INTENT → PLAN → lint (registry: active checks by kind — contracts + sql-stdin OK)
       → interpret: discovery(/bin/sql via stdin) → rowset(list[dict])
       → compute(first→get, type-safe) → decision(found)
       → answer: project record_path ref
       → verify(I1/I2 pass) → vm.answer(once) → OUTCOME_OK
       → [HARNESS_DISTILL] distill candidate check → validate via grader → promote
```

Failure recovery: any compute type error or sql-banner now raises `InterpretError`
(read-only, retryable) → `_ilearn` with an actionable message → next PLAN cycle. A
`candidate` check is enforced warn-only, so it can surface a signal without dead-ending.

## Error Handling

- compute/custom_extract exceptions → typed `InterpretError` (retryable, `mutation_landed=False`).
- lint violations (any `error`-severity active check) → `InterpretError` pre-interpret →
  `_ilearn` + next cycle.
- sql usage-banner → retryable `_refuse`.
- double `vm.answer` → impossible (F4 flag).
- The `_RETRYABLE_VM_ERROR_PATTERNS` set is unchanged — F1 moves compute crashes OUT of
  the `real_vm` bucket entirely, so they no longer depend on that set.
- A malformed or unknown-`kind` check-spec is skipped with a logged warning — a bad
  registry entry degrades to no-op, never crashes `lint`.
- A `candidate` check is warn-only — it can never block a run before grader-validation
  promotes it.

## Testing Strategy

- Per-fix deterministic unit tests on `MockVMSpy`:
  - F1: `column($single_dict)` → `InterpretError` (not bare crash); pipeline retries.
  - F2: `first`→`column` chain → lint raises before interpret.
  - F3: `/bin/sql` with empty stdin → lint raises; usage-banner payload → retryable refuse.
  - F4: two `vm.answer` attempts → second is a no-op.
  - F5: OK answer with unresolved required ref → never answered.
  - F6: load `data/learned/t01.yaml` + oracle atom parse cleanly; rule is method-shaped.
  - F7: catalogue query + irrelevant DOC_SELECT → logged, no break.
  - F8: registry round-trip — `load_checks` parses seed `checks.yaml`; `lint` dispatches
    each `kind`; an `error` active check blocks, a `candidate` is warn-only, an
    unknown-`kind` entry is skipped (logged); `validate_check_via_grader` promotes only on
    catches-bad ∧ ¬flags-good.
- `uv run pytest tests/ -v` — no regressions. Known pre-existing reds:
  `test_t09_replay_matches_known_good`, `test_t09_corpus` (stale fixtures, not caused here).
- One live `t01` run at the end: expect `OUTCOME_OK` with ref `/proc/catalog/<SKU>.json`.

## Execution Order

`F1 → F8a → F2 → F3 → F4 → F5 → F6 → F7 → F8b` → final live t01 run.

- **F8a** = registry engine first (`harness.load_checks`, `interpreter.lint` dispatcher,
  migrate the existing security-first check to the `security_first` kind). It is the
  prerequisite for F2/F3, which ship as `kind` handlers + seeded `active` entries.
- **F8b** = the distill→validate→promote pipeline, gated off by default
  (`HARNESS_DISTILL=0`), added last so it cannot affect the core fixes' validation.

Each fix: red test → implement → green. F1 + F8a + F2 unblock the run-15:08 mode
(highest ROI).

## Docs

After implementation, regenerate the affected `docs/wiki/` pages via `iwiki:iwiki-ingest`
for `interpreter.py`, `pipeline.py`, `primitives.py`, `harness.py`, `harness_validate.py`
and run `/iwiki-lint`. Document the new env vars (`HARNESS_DISTILL`,
`HARNESS_VALIDATE_INLINE`) in the root `CLAUDE.md` env table.
