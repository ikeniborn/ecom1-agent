---
review:
  spec_hash: dfdc6266343cedfe
  last_run: 2026-06-07
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "Acceptance (from intent)"
      section_hash: 842e28d096a55917
      text: "'materially fewer lines/LOC' (OC7 + Done-when) is a quantitative acceptance criterion with no measurable threshold/DoD."
      verdict: fixed
      verdict_at: 2026-06-07
    - id: F-002
      phase: clarity
      severity: INFO
      section: "Testing strategy (TDD, bottom-up)"
      section_hash: 52ee265bee9d002e
      text: "'a few tasks end-to-end' — integration test count unspecified."
      verdict: fixed
      verdict_at: 2026-06-07
chain:
  intent: docs/superpowers/intents/2026-06-07-deterministic-plan-interpreter-intent.md
---

# Design: Deterministic Plan-IR Interpreter — LLM proposes, agent executes

**Date:** 2026-06-07
**Status:** draft
**Intent:** `docs/superpowers/intents/2026-06-07-deterministic-plan-interpreter-intent.md` (approved)

## Overview

Replace LLM free-form `CODEGEN` (Python `exec()`'d against a re-seeded VM, policed by a
1008-line guard fortress) with a split where the LLM emits **data** and a fixed
**deterministic interpreter** executes it:

- **INTENT** (LLM, 1×, frozen per run) — emits an `IntentSpec` (IDD layer: objective,
  desired outcome, machine-checkable success criteria, applicable constraints), grounded in
  **pre-phase facts** (schema, sample rows, `/docs` policies, `/bin/id`, target record).
- **PLAN** (LLM, iterated under LEARN) — emits a declarative `PlanIR` (SDD layer: discovery,
  rowsets, compute, decision tree, guarded ops, answer templates). The model is free to choose
  HOW; the IR is data, not code.
- **INTERPRET** (deterministic) — executes `PlanIR` with built-in guards.
- **VERIFY** (deterministic, 0 LLM) — checks the captured answer against the `IntentSpec`
  before the single terminal `vm.answer`.

Empirical basis (workflow `classify-heuristics-for-ir`, 2026-06-07, all 51 heuristics):
46/51 fit the core IR cleanly, 3/51 need named compute-primitives, 2/51 (t51, t53) need a
bounded named-parser escape hatch. The IR is small because the corpus is stereotyped
(43/51 share one row parser; the 3 fraud tasks push geo math into SQL window functions; 14
security/checkout/discount tasks collapse to one gate-ladder).

## Acceptance (from intent)

Carried verbatim from the approved intent doc; these gate the work.

**Desired Outcomes**
- OC1. No `exec()`/`compile()` of LLM-authored Python in the answer path; `agent/codegen_v2.py`
  and the LLM-code execution path are removed.
- OC2. The LLM emits two validated data artifacts per task: `IntentSpec` and `PlanIR`. Neither
  contains executable code.
- OC3. A deterministic interpreter executes `PlanIR` with built-in guards and is the sole
  executor of task logic against the real VM.
- OC4. The `IntentSpec` is auto-filled from pre-phase facts (schema + sample rows + `/docs`
  policy inventory + `/bin/id` + target-record probe).
- OC5. Deterministic `VERIFY` against the `IntentSpec` replaces `fidelity`, the intent-test gate,
  and `_AnswerGuard` policing — using the same predicate engine as the IR.
- OC6. Benchmark score on a full run is ≥ the current baseline (~32%).
- OC7. Net complexity drops: `fidelity.py`, the retry-guard machinery, `_AnswerGuard` policing,
  `testgen.py`, `test_runner.py`, and `check_retry_loop` are removed, and the added LOC across the
  new modules (`ir_models`, `predicates`, `primitives`, `interpreter`, `verify`, `reason`) is
  **≤ 60% of the deleted LOC**, measured by `cloc` on the added vs deleted `agent/` files.
- OC8. The escape hatch is a frozen, named-parser registry (`custom_extract`), bounded to ~2
  tasks (t51, t53) — never a general expression/code evaluator.

**Done when**
- A full benchmark run scores ≥ baseline AND
- the `CODEGEN` free-Python path is removed (OC1) AND
- the new-module added LOC ≤ 60% of the deleted LOC by `cloc` (OC7) AND
- HM3 load-bearing guards are covered by passing regression tests AND
- HM1/HM2/HM4–HM6 hold (no green regressions, LEARN/oracle/training intact, cost/tier envelope intact).

**Health Metrics (must not degrade):** HM1 green tasks; HM2 LEARN+oracle; HM3 ref-grounding
refusal + security-gate-first + the two mutation idioms; HM4 token/call envelope (best ≈2,
worst ≈7; VERIFY is 0 LLM); HM5 tier routing; HM6 training mode.

## Architecture

### Module map

| Module | Responsibility | Status |
|--------|----------------|--------|
| `agent/ir_models.py` | Pydantic: `IntentSpec`, `PlanIR` + nodes (`Step`, `RowSet`, `ComputeStep`, `Predicate`/`PredExpr`, `DecisionTree`, `GuardedOp`, `AnswerTemplate`, `CustomExtract`, `MapSpec`) | NEW |
| `agent/predicates.py` | Pure predicate engine `eval(PredExpr, env) -> bool`; 16 ops (`eq ne lt le gt ge nonempty isnull contains_any in_set startswith endswith regex_match` + `and/or/not`) | NEW |
| `agent/primitives.py` | Pure compute-primitive registry (13) + parser registry (escape hatch) | NEW |
| `agent/interpreter.py` | Execute `PlanIR` with built-in guards; capture answer (defer submit) | NEW |
| `agent/verify.py` | Deterministic VERIFY: invariants + `IntentSpec.success_criteria` | NEW |
| `agent/reason.py` | INTENT + PLAN LLM phases (replaces `design.py` + `codegen_v2.py`) | NEW |
| `agent/orchestrator.py` | Pre-phase fact gathering → `PrePhaseFacts` | EXTEND |
| `agent/pipeline.py` | Slim loop: reason → interpret → verify → (LEARN+retry \| answer) | SLIM |
| `agent/vm_adapter.py` | `VMAdapter` kwargs↔protobuf | UNCHANGED |
| `agent/learned_store.py`, `agent/oracle.py` | LEARN + oracle, retargeted to IR authoring | KEEP |
| `agent/codegen_v2.py`, `agent/fidelity.py`, `agent/testgen.py`, `agent/test_runner.py`, `_AnswerGuard`/retry-guard in `pipeline.py`, `check_retry_loop` in `sql_security.py` | LLM-code policing | DELETE (after cutover) |

### Run-time flow

```
PRE-PHASE (deterministic, read-only)  → PrePhaseFacts
  AGENTS.MD · schema+samples · tree /docs + policies · /bin/id · target-record probe
        │
INTENT (LLM 1×, FROZEN per run)        facts + instruction → IntentSpec     [IDD: WHAT/WHY, fact-grounded]
        │
PLAN (LLM, iterated)                   IntentSpec + facts + learn_ctx + oracle → PlanIR   [SDD: free HOW]
        │
INTERPRET (deterministic)             replay discovery · rowsets · compute · decision(security-first)
        │                             · guarded ops · ground refs · refuse-if-unresolved → CapturedAnswer
        ▼
VERIFY (deterministic, 0 LLM)         answer ⊨ invariants + IntentSpec.success_criteria?
   ┌────┴──── pass → vm.answer (terminal, once)
   └─ fail → LEARN (1×) → re-PLAN (≤ MAX_STEPS); exhaust → vm.answer(OUTCOME_NONE_CLARIFICATION)
```

Call budget: best = 2 (INTENT+PLAN), worst ≈ 1 + MAX_STEPS×(PLAN+LEARN) = 7 at MAX_STEPS=3.
Within the current envelope (HM4). VERIFY costs 0 LLM calls.

## Data artifacts

### IntentSpec (IDD layer, frozen after cycle 1)

```
IntentSpec:
  objective:        str                 # one-sentence WHY
  desired_outcome:  str                 # observable answer shape
  params:           dict[str, Any]      # method-level params from instruction (no seed values)
  outcome_space:    list[OUTCOME_*]     # outcomes legitimate for this task
  constraints:      list[Constraint]    # Constraint{anchor, rule, security: bool} — verbatim AGENTS.MD/policy, grounded from pre-phase /docs
  success_criteria: list[PredExpr]      # machine-checkable, SAME predicate language as decision
  answer_shape:     AnswerShape         # {msg_skeleton: str, required_ref_kinds: [static|runtime]}
```

### PlanIR (SDD layer, iterated under LEARN)

```
PlanIR:
  discovery: list[Step]        # Step{rpc, args(literals + $param refs), bind}  — read-only, in order
  rowsets:   list[RowSet]      # RowSet{from:$bind, format:auto_delim|tsv|csv|pipe|json, into, columns?:[ColResolve]}
  compute:   list[ComputeStep] # ComputeStep{prim, args:[ref|literal], into}  — prim ∈ primitive registry
  decision:  DecisionTree      # {branches:[{when:PredExpr, label}], default_label}  — security branch first
  ops:       list[GuardedOp]   # GuardedOp{rpc, args, bind, guard_label? | outcome_from_exit?:{0→OK, keyword_buckets}}
  answer:    dict[label → AnswerTemplate]   # {message(slots {name}), outcome, refs:[$ref|literal]}
  custom_extract?: list[CustomExtract]      # {name(registered parser), input:$bind, into}  — escape hatch
  map_over_param_rows?: MapSpec             # t47 only: {row_ids:[str], per_row: Plan-fragment, collect: rowset}
```

Sub-node detail:
- `Predicate{op, lhs:ref, rhs:ref|literal}`; `PredExpr = Predicate | {and|or|not: [PredExpr]}`.
- `ColResolve` = priority list of name-match predicates (earns t48 multi-tier column detection).
- `ref` = a name resolved from `env`; literals pass through.

### Shared env model

A single namespace `env: dict[str, Any]` maps names → values (scalars, rowsets, RPC results).
Seeded with `params` + `PrePhaseFacts`. `$name` in refs and `{name}` in message slots resolve
from `env`. `custom_extract` writes a rowset into `env`, after which the normal pipeline consumes it.

### Why VERIFY is deterministic (two levers)

1. **One predicate language.** `success_criteria` are `PredExpr` over `env+answer`, evaluated by
   the same `predicates.py` engine as `decision`. No separate test language → `testgen.py`/
   `test_runner.py` are deleted.
2. **Built-in invariants are hard-coded, not LLM-authored** (the LLM cannot forget them).

## Interpreter semantics (`interpreter.py`)

Execution order (deterministic):

1. **seed** — `env ← params + PrePhaseFacts` (identity, target record, policy texts) read-only.
2. **discovery** — each `Step` in order: `env[bind] = vm.<rpc>(**resolve_args(args, env))`; capture
   stdout into `observations` (for LEARN). The discovery list *is* what runs → RPC-multiset
   fidelity is intrinsic; no separate fidelity gate.
3. **rowsets** — parse `env[from]` per `format` (auto-detect `|` / tab / comma; or json/csv) into
   `list[dict]`; apply `ColResolve` priority name-match; `env[into] = rows`.
4. **compute** — `env[into] = primitives[prim](*resolve(args, env))`. `custom_extract` runs here:
   `env[into] = parsers[name](env[input], params)`.
5. **decision** — evaluate `DecisionTree.branches` top-down; first `PredExpr` true → `label`; else
   `default_label`. Build-time lint asserts any branch mapping to `OUTCOME_DENIED_SECURITY`
   precedes non-DENIED branches (security-first).
6. **ops** — for each `GuardedOp`:
   - `guard_label` set → run only if `decision label == guard_label` (**decide-then-guard**, t21/t36).
     Mutation fires only on the chosen branch → security gate already passed.
   - `outcome_from_exit` set → run unconditionally (**mutate-then-classify**, t25/t42); derive
     outcome from `exit_code` (0→OK) + `keyword_buckets` over stdout/stderr; this overrides the
     decision outcome for that path.
7. **answer assembly** — pick `AnswerTemplate` by final label/outcome; resolve `{name}` slots and
   `$ref` from `env`; static refs pass through.
8. **refuse invariant** — if `outcome==OK` and `answer_shape.required_ref_kinds` includes `runtime`
   but no resolved runtime `$ref` is present, OR any `$name` is unresolved → raise `InterpretError`
   (routes to LEARN). Mirrors the deleted `_AnswerGuard`.
9. **return** `CapturedAnswer{message, outcome, refs}` + `observations` + `rowsets`. The interpreter
   does **not** call `vm.answer` — the pipeline submits only after VERIFY passes (defer-submit).

The interpreter tracks whether a mutating op executed this cycle (`mutation_landed`) for
retry-safety.

## VERIFY (`verify.py`, deterministic, 0 LLM)

- **Built-in invariants** (always, regardless of the LLM):
  - `I1` ref-grounding — `OK` requires a runtime ref when `answer_shape` demands it; no unresolved `$`.
  - `I2` `outcome ∈ IntentSpec.outcome_space`.
  - `I3` **security re-check** — independently re-evaluate the security `Constraint` predicates
    (those with `security: true`) from the **frozen, fact-grounded `IntentSpec`** against `env`.
    If they would deny but `outcome != DENIED_SECURITY` → fail. This double-checks the security
    verdict against the spec, *not* the LLM's plan — defense in depth.
  - `I4` exactly one answer.
- **`IntentSpec.success_criteria`** — evaluate each `PredExpr` over `env+answer`; all must hold.
- Returns `(ok: bool, error: str)`. The `error` string feeds LEARN.

## Error → LEARN loop (`pipeline.py`)

| Failure point | Action |
|---------------|--------|
| INTENT parse/empty | retry (as DESIGN does now, `DESIGN_MAX_ATTEMPTS`) |
| PLAN parse/validation | LEARN(error) → re-PLAN next cycle |
| INTERPRET raise (unresolved ref / bad rpc / real-VM exception) | LEARN(error + observations) → re-PLAN if read-only; if `mutation_landed` → terminal |
| VERIFY fail | LEARN(error + observations) → re-PLAN next cycle |
| exhaust `MAX_STEPS` | `vm.answer(OUTCOME_NONE_CLARIFICATION)` |
| pass | `vm.answer(captured)` once |

`IntentSpec` is frozen after cycle 1; only `PlanIR` is re-authored. Mutation safety mirrors today:
a mutating op that already executed makes retry unsafe → terminal. LEARN uses the existing
`learned_store` mechanism; error strings are now IR-level (predicate false / ref unresolved /
criterion X failed) — richer than "fidelity RPC mismatch". `learn_from_grader` (training) persists
and consumes `IntentSpec` + `PlanIR` (replacing `{tid}.design.json`).

## Pre-phase grounding (`orchestrator.py`)

```
PrePhaseFacts:
  agents_md, schema, sample_rows        # existing
  docs_inventory   ← tree /docs (level 2)
  policies: {path: text}                # /docs/security.md always + docs whose name appears in
                                        #   instruction/AGENTS.MD (cap, default 6)
  identity: dict   ← /bin/id parsed
  target_records: {path: text}          # regex-extract basket/payment/return id from instruction
                                        #   → stat + read /proc/{baskets,payments,...} (cap, default 3)
```

Re-seed caveat (S3): facts are valid for THIS run only. The INTENT prompt instructs the model to
use facts to decide WHICH constraints/columns/gates apply (method), never to bake values. PLAN still
performs its own discovery at run time; the target-record probe grounds the intent, it does not
replace discovery. The duplicate read (probe + discovery) is acceptable — both read-only.

## Migration (behind a flag)

- New path lives behind `INTERPRETER_ENABLED` (default `0`). `run_pipeline` branches: enabled →
  reason→interpret→verify; else → current path. Both produce the same metrics dict and a single
  `vm.answer`.
- A/B on the benchmark: full suite both ways, compare scores. Only when interpreter ≥ baseline →
  flip the default, then delete the old path (proposal-first / HUMAN CHECKPOINT per intent).
- The old path stays until the new one is proven → HM1 (no green regression) and the Stop Rule
  (halt if < baseline) are satisfied structurally.

## Testing strategy (TDD, bottom-up)

| Layer | Tests |
|-------|-------|
| `predicates` | each of the 16 operators |
| `primitives` | each of the 13 primitives + the parser registry |
| `interpreter` | golden `PlanIR` → `MockVMSpy` → expected `CapturedAnswer` |
| `verify` | I1–I4 + criteria; **HM3 regressions**: unresolved-`$ref`→REFUSE · static-only→REFUSE · `id≠record`→DENIED (I3 catches an OK plan) · exit-code mapping · guarded-op skipped on non-OK branch |
| **corpus replay** | per task: a frozen `PlanIR` → interpreter → `MockVMSpy`(existing fixtures) → captured answer == known-good answer from `data/heuristics`. Start with the riskiest 6: **t21, t25, t47, t48, t51, t53** |
| integration | 3 named tasks end-to-end against the real VM behind the flag: t09 (lookup), t27 (RBAC/payment decision), t51 (compute + escape hatch) |

Existing `tests/` asserting codegen/fidelity/`_AnswerGuard` behavior are removed/rewritten as those
modules are deleted — expect test churn (called out in the plan).

## Build order

1. `ir_models` + `predicates` + `primitives` — pure, fully unit-tested, no VM.
2. `interpreter` against `MockVMSpy` + corpus replay (riskiest 6 first).
3. `verify` + invariants.
4. `reason.py` (INTENT + PLAN prompts) + `pipeline` wiring behind `INTERPRETER_ENABLED`.
5. Pre-phase extension.
6. A/B benchmark → cutover (delete old path).

## Risks & open questions

- **R1. Predicate/primitive expressiveness drift.** The classify workflow sized 16 predicates +
  13 primitives from the corpus. If a task needs an unlisted op, prefer a new named primitive over
  widening the predicate grammar; never add a general evaluator (H1/H2).
- **R2. INTENT quality depends on pre-phase facts being right.** If the target-record regex misses,
  the INTENT loses grounding for that task — degrade gracefully (facts optional; INTENT still
  produced from schema + AGENTS.MD).
- **R3. Corpus-replay PlanIRs must be authored once.** Hand-author or LLM-author-then-freeze; this
  is the main confidence artifact and the main up-front effort.
- **R4. `map_over_param_rows` (t47) and `custom_extract` (t51/t53)** are the two grammar features
  earned by single/double tasks — keep them isolated so they don't leak into the core.
