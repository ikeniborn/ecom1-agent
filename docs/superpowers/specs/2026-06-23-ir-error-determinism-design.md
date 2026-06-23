---
chain:
  intent: docs/superpowers/intents/2026-06-23-ir-error-determinism-intent.md
review:
  spec_hash: 4c0ed7bb505ae420
  last_run: 2026-06-23
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
    alignment:    { status: passed }   # advisory — вне CRITICAL-gate
  findings:
    - id: F-001
      phase: consistency
      severity: INFO
      section: "B — deterministic error/terminal outcome from `outcome_space` (`agent/pipeline.py`)"
      section_hash: c6bc47a0e6727d31
      text: >-
        §B opening sentence lists both pipeline.py:321 (INTENT hard-stop) and
        pipeline.py:493 (loop-exhaust/break) among the terminal sites the hardcoded
        OUTCOME_NONE_CLARIFICATION hole affects, but the same section later carves
        out :321 ("fires before INTENT is available → keep its literal; B applies
        only where intent exists"). Internally consistent (the exemption is explicit
        and well-reasoned), but the lead sentence could flag the :321 exemption
        up-front so a reader does not expect B to touch :321. Advisory only.
      verdict: fixed
      verdict_at: 2026-06-23
---

# IR error→outcome determinism (A+B) — design

**Status:** Draft for review
**Date:** 2026-06-23
**Branch:** `dev/ir-error-determinism` (base + PR target: `determinism`)
**Depends on:** Phases 1–3 (grounding / decide / format-gate) shipped on `determinism`.

## Goal

Close three holes where a weak-model plan turns a recoverable problem into a silent wrong
answer, by extending the deterministic exoskeleton (model proposes, code disposes):

- **A1** — a malformed *literal* relative `path`/`root` in a step is caught pre-interpret
  and raised as a precise iLEARN signal, instead of dead-ending to a terminal outcome.
- **A2** — an answer whose DECLARED required `record_path` did not bind fails `verify`
  (hard-fail, all outcomes), instead of the ref silently dropping and I1 passing vacuously.
- **B** — a terminal / give-up answer's outcome is selected deterministically from the
  task's `outcome_space` by precedence, instead of a hardcoded outcome that may be
  out-of-space.

The quality gate stays `verify()` (deterministic, no LLM). No new IR surface. No
`data/prompts/*.md` change. `vm.answer` still called exactly once per task.

## Acceptance (from intent)

Carried verbatim from
`docs/superpowers/intents/2026-06-23-ir-error-determinism-intent.md`.

**Desired Outcomes:**
- t01 no longer terminates at cycle 1 on a malformed relative path — a step carrying a
  relative literal `path`/`root` gets a further cycle and can reach a grounded answer
  instead of a terminal give-up.
- No answer reaches `vm.answer` while a DECLARED required `record_path` is unbound — for any
  outcome (including a denial), an answer that should cite a record it never resolved is no
  longer submitted (t50 no longer answers with the basket record missing).
- Every terminal / give-up answer carries an outcome that is in the task's `outcome_space`
  — never an outcome the task does not declare.

**Done when:** all 159 determinism unit tests + full `pytest tests/` green; a real benchmark
run shows t01 and t50 no longer fail via the diagnosed mechanisms (relative-path terminal /
silent record-ref drop) — an observable outcome shift, or a precise evidenced explanation
why a remaining gap is upstream — AND t10 + the other tasks show no new failures.

## Design

### A1 — absolute-path lint gate (`agent/interpreter.py`)

New deterministic structural check `lint_paths_absolute(plan: PlanIR) -> None`, mirroring
the existing `lint_security_first` shape. Called from `interpret()` immediately after
`lint_security_first(plan)` (interpreter.py:334), so it runs before any VM dispatch.

- Iterate `plan.discovery + plan.ops`. For each `Step`, inspect its path-bearing args:
  `path` (Read/List/Stat/Tree/Exec) and `root` (Find).
- A value is a **violation** iff it is a non-empty `str`, does NOT start with `"$"` (a
  `$ref` is resolved from `env` at runtime — not lintable here), and does NOT start with
  `"/"`.
- On any violation: `raise InterpretError("step '<rpc>' arg '<key>': path must be absolute "
  "(got '<value>'); use an absolute path under /proc, /docs, /bin, ...")`. The pipeline maps
  `InterpretError` → `_ilearn` → next cycle (interpreter→pipeline path already exists).
- Exec `path` is the binary (`/bin/...`) and is already absolute in practice; the same gate
  covers it harmlessly.

**Boundary (documented limitation):** only *literal* path args are linted. A relative path
arriving via a bound `env` value (`$ref`) is not visible at lint time; that edge is out of
scope (it would need the retryable-error path, deliberately not changed here).

**Alternative considered:** a registry check (`kind: path_absolute` in
`data/harness/checks.yaml`, fired by `lint()` at pipeline.py:382). Rejected for this change
in favour of the ~15-line hardcoded helper: smaller surface, co-located with the existing
structural lint, no new handler machinery. (Revisit if more structural path checks accrue.)

### A2 — unresolved required record_path → hard-fail (`agent/verify.py`)

`verify()` I1 already computes the unresolved set but discards it:
`required_vals, _missing_src = _project_required_refs(intent, ans.outcome, env)` (verify.py:39)
— only `required_vals ⊆ ans.refs` is checked. A `record_path` whose `$source` resolves to
`None`/`""` lands in `_missing_src` (dropped) → I1 passes vacuously.

Fix: stop discarding it.
```python
required_vals, missing_src = _project_required_refs(intent, ans.outcome, env)
if missing_src:
    return False, (f"I1: required ref source(s) {missing_src!r} did not resolve on "
                   f"{ans.outcome} answer (resolve-before-cite)")
absent = [v for v in required_vals if v not in ans.refs]
if absent:
    return False, (...)   # unchanged
```
- Applies to **all** outcomes (OK, DENIED_*, NONE_*). Unifies the OK-only refuse invariant
  already in the interpreter (interpreter.py:428) at the authoritative post-decide gate
  (`verify` runs on the final decided outcome, after `decide_outcome`).
- `missing_src` carries both unresolved `record_path` sources (the t50 case) and any
  malformed `policy_doc` with no `path`; both are legitimate hard-fails.
- **Non-regression:** an outcome that declares NO required ref, or only resolvable
  `policy_doc` refs, yields `missing_src == []` → behaviour unchanged.

### B — deterministic error/terminal outcome from `outcome_space` (`agent/pipeline.py`)

`verify` I2 already rejects an outcome ∉ `outcome_space`. The remaining hole: the
pipeline's loop-exhaust/break path hardcodes `OUTCOME_NONE_CLARIFICATION` (pipeline.py:493),
which may be out-of-space for the task. (The INTENT hard-stop at pipeline.py:321 fires before
`intent` exists and is **exempt** from B — detailed below.)

- New helper (pipeline-local) `negative_outcome_by_precedence(outcome_space) -> str | None`:
  first present of `["OUTCOME_NONE_UNSUPPORTED", "OUTCOME_NONE_CLARIFICATION"]`, else `None`.
  Precedence mirrors `decide.unsupported_or_clarify` (UNSUPPORTED outranks CLARIFICATION) so
  decide ↔ pipeline never diverge.
- Terminal/break sites use `negative_outcome_by_precedence(intent.outcome_space) or
  "OUTCOME_NONE_CLARIFICATION"` — falling back to the current literal only when the space
  declares neither negative (defensive; preserves today's behaviour for such tasks).
  (The INTENT hard-stop at pipeline.py:321 fires before INTENT is available → keep its
  literal `OUTCOME_NONE_CLARIFICATION`; B applies only where `intent` exists.)
- **Mid-loop unrecoverable step error with cycle budget left:** if `outcome_space` contains
  a valid negative, the terminal answer uses it (per above). If it contains NO negative at
  all, do not answer an out-of-space outcome — route to `_ilearn` and retry (give the model
  a chance to widen the space / handle the error) until the budget exhausts. This is the
  intent's "refuse→iLEARN if no valid negative".

## Error handling

- A1/A2/B intentionally raise / hard-fail — that is the iLEARN signal, not a regression.
  This is the deliberate inverse of the best-effort pass-through used by grounding /
  decide / format-gate (which never raise): those reshape a correct-enough answer; these
  reject a wrong one.
- The anti-infinite-loop guard is unchanged: `_plan_signature` short-circuit still breaks an
  identical-plan retry; A1/A2/B feed it precise `prev_error` text so the next PLAN differs.
- No new exception types; A1 reuses `InterpretError`, A2 returns the standard
  `verify` `(False, reason)`, B selects a string outcome.

## Testing

- `tests/test_interpreter.py` (A1): a relative `path` on Read/List/Stat/Tree and a relative
  `root` on Find each raise `InterpretError`; an absolute path passes; a `$ref` arg is NOT
  linted (passes); a `lint_security_first`-passing plan with a bad path still raises.
- `tests/test_verify.py` (A2): a declared required `record_path` whose `$source` is unbound
  fails I1 on OUTCOME_OK, OUTCOME_DENIED_SECURITY, and OUTCOME_NONE_UNSUPPORTED; a resolved
  record_path passes; an outcome with no declared required ref passes; a resolvable
  `policy_doc`-only outcome passes.
- `tests/test_pipeline_*.py` (B): `negative_outcome_by_precedence` returns UNSUPPORTED when
  both present, CLARIFICATION when only it is present, `None` when neither; a terminal break
  with `outcome_space` lacking CLARIFICATION yields a valid in-space negative; an
  unrecoverable error with no negative in space drives iLEARN (not an out-of-space answer).
- Regression: full `pytest tests/ -q` green (the 159 determinism tests included).
- Real validation: benchmark run on `t01 t10 t38 t50`; assert t01/t50 outcome shift (or a
  precise evidenced upstream explanation), t38 unchanged (impossible-leg), t10 no regression.

## Success criteria

- A1: no plan with a literal relative path reaches a VM dispatch; it produces an
  `InterpretError` → iLEARN with a path-naming message.
- A2: `verify` returns `False` whenever the selected outcome's declared required
  `record_path` did not resolve; no such answer reaches `vm.answer`.
- B: every terminal/give-up outcome the pipeline emits is ∈ `intent.outcome_space`
  (or the defensive literal only when the space declares no negative).
- All Health Metrics from the intent hold: 159 determinism tests green, full `pytest`
  green, happy-path LLM budget unchanged, no benchmark regression.
