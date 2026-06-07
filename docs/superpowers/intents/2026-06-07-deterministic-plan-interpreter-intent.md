# Intent: Deterministic Plan-IR Interpreter — LLM proposes, agent executes

**Date:** 2026-06-07
**Status:** approved

## Objective

The current pipeline has the LLM write free-form Python (`CODEGEN`) that the agent
`exec()`s against a re-seeded VM. To police that arbitrary code, `agent/pipeline.py`
has grown into a 1008-line fortress of runtime guards — `fidelity` (RPC-name multiset),
`check_retry_loop` (identical-SQL detector), `_AnswerGuard` (refs / `$name` / zero-row
policing), `_RETRYABLE_VM_ERROR_PATTERNS`, the intent-test gate — each guard traceable
to a single task regression (t02, t51, t38…). Nondeterminism enters precisely at
`CODEGEN`: the LLM re-derives executable code every cycle, so the guards exist only to
contain it.

Redesign target: **split reasoning from execution**. The LLM becomes pure
reasoning/analysis/proposal — it emits *data*, not code: an `IntentSpec` (the IDD layer:
WHY / desired outcome / success criteria / constraints, **grounded in pre-phase facts**)
and a declarative `PlanIR` (the SDD layer: discovery / rowsets / compute / decision-tree /
guarded-ops / answer-templates). A fixed, hand-written **deterministic interpreter**
executes the `PlanIR` with built-in guards (SQL binding, ordered ops, security-gate-first
decision, conditional mutation, ref-grounding refusal) and **verifies the result against
the IntentSpec** before the single terminal `vm.answer`. No `exec()` of LLM code in the
answer path.

Why now: the agent does not reliably complete the full idd+sdd+plan+test+codegen+learn+
oracle cycle, and the guard fortress is unmaintainable. An empirical sweep of all 51
benchmark heuristics (workflow `classify-heuristics-for-ir`, 2026-06-07) found the corpus
is *stereotyped*: 46/51 fit a small core IR cleanly, 3/51 need named compute-primitives,
only 2/51 (t51, t53) need a bounded escape hatch. The IR is small because the heuristics
are stereotyped, not because capability is amputated.

> IDD owns WHY / WHAT / Outcomes / Constraints (the `IntentSpec`). The Plan/SDD layer owns
> HOW (the `PlanIR`) and is *free* — the model picks whichever RPCs/predicates/primitives
> best satisfy the intent. The agent's freedom is at **plan-authoring time**; its
> determinism is at **run time**. The model decides WHICH plan; the interpreter creates
> nothing — it executes the chosen plan under guards.

## Lineage (supersedes parts of prior intents)

Builds on `2026-05-28-pipeline-redesign-intent.md` (DESIGN + CODEGEN two-phase). That doc
collapsed IDD+SDD+PLAN into one `DESIGN` for speed (H10) and made CODEGEN translate the
plan to Python (H11), gated by a mock test (H18/H19). This redesign **supersedes**:

- **H11 superseded** — CODEGEN no longer translates the plan to a Python module; the plan
  *is* the executable artifact, run by the interpreter.
- **H18/H19 superseded** — the mock-test gate and the lint/fidelity loop are replaced by
  deterministic `VERIFY` against the `IntentSpec`.
- **Retained:** H4/S4 (no task-specific knowledge in `data/prompts/*`; task knowledge flows
  only via LEARN), H8 (`vm.answer` is the only terminal RPC), H15 (intent/plan reasoning is
  frozen-per-run; LEARN feeds the next run's authoring), the knowledge-oracle.

## Desired Outcomes

- **OC1.** No `exec()`/`compile()` of LLM-authored Python in the answer path. `agent/codegen_v2.py`
  and the `_run_script_on_vm`-of-LLM-code path are removed.
- **OC2.** The LLM emits two validated data artifacts per task: `IntentSpec` and `PlanIR`
  (Pydantic models). Neither contains executable code.
- **OC3.** A deterministic interpreter executes `PlanIR` with built-in guards and is the
  *sole* executor of task logic against the real VM.
- **OC4.** The `IntentSpec` (IDD layer) is auto-filled from pre-phase facts — discovered DB
  schema + sample rows + `/docs` policy inventory + `/bin/id` + target-record probe — so
  `success_criteria` and `constraints` are grounded in observed reality, not guessed.
- **OC5.** Deterministic `VERIFY` against the `IntentSpec` replaces `fidelity`, the intent-test
  gate, and `_AnswerGuard` policing — using the same predicate engine as the IR.
- **OC6.** Benchmark score on a full run is **≥ the current baseline (~32%)**.
- **OC7.** Net complexity drops: the interpreter + IR models are materially fewer lines than
  the replaced code; `fidelity.py`, the `check_retry_loop` retry-guard machinery, and the
  `_AnswerGuard` policing in `pipeline.py` are removed.
- **OC8.** The escape hatch is a frozen, named-parser registry (`custom_extract`), bounded to
  the ~2 tasks that need it (t51, t53) — never a general expression/code evaluator.

## Health Metrics

- **HM1.** Score on currently-green tasks does not regress (the green baseline is sacred).
- **HM2.** LEARN + knowledge-oracle remain functional, retargeted to author `IntentSpec`/`PlanIR`
  (not Python); `data/learned/{tid}.yaml` and `data/oracle/atoms.yaml` keep working.
- **HM3.** Load-bearing semantics are preserved, covered by regression tests:
  (a) ref-grounding refusal — `OUTCOME_OK` with an unresolved `$name` or only static refs is
  rejected; (b) security-gate-first — `DENIED_SECURITY` is evaluated before any business gate
  or mutation; (c) the two mutation idioms — decide-then-guard and mutate-then-classify-from-exit.
- **HM4.** Per-task token cost / LLM-call count does not grow beyond the current envelope
  (best ≈2, worst ≈7); `VERIFY` is deterministic (0 LLM calls).
- **HM5.** LLM tier routing (`anthropic/`, `openrouter/`, `ollama/`, `claude-code`) and
  fallback are untouched.
- **HM6.** Training mode (`learn_from_grader`, `{tid}.design.json` persistence, multi-cycle)
  continues to work against the new artifacts.

## Strategic Context

- **Interacts with:**
  - `agent/vm_adapter.py` (`VMAdapter`, kwargs↔protobuf) — **unchanged**; the interpreter
    calls `vm.*` exactly as scripts do today.
  - `agent/orchestrator.py` pre-phase (schema discovery + AGENTS.MD augmentation) — **extended**
    to gather the policy/identity/target-record facts that feed the IDD layer.
  - LEARN (`agent/learned_store.py`, `pipeline.learn_from_grader`) + oracle (`agent/oracle.py`).
  - `main.py` harness + training loop.
- **Priority trade-off:** **trust > speed > cost.** Correctness/determinism first; wall-clock
  second; token spend last (but must not grow per HM4).

## Constraints

### Steering (behavioral guidance)

- **S1.** The model is free at the SDD/IR layer to choose HOW (which RPCs, predicates,
  primitives compose the plan), optimizing for correctness and quality.
- **S2.** The `IntentSpec` is grounded in pre-phase facts, not hallucinated.
- **S3.** Because data is re-seeded every `StartRun`, the intent and plan ground the **method**
  (which columns/policy/gate apply), never the **values** — no value is baked into the artifacts.
- **S4.** Push computation into SQL where the corpus already does (e.g. the fraud tasks'
  impossible-travel math lives in SQL window functions); the interpreter does not reimplement
  geometry or aggregation the DB can do.
- **S5.** Phase guides in `data/prompts/*` stay general; per-task knowledge flows only through
  LEARN → `data/learned/{tid}.yaml` (inherits H4/S4 from the prior intent).

### Hard (architectural enforcement)

- **H1.** No `exec()`/`compile()`/`eval()` of LLM-authored Python (or any LLM-authored code) in
  the answer path. The interpreter is the only executor.
- **H2.** The escape hatch is a frozen registry of pre-registered pure parsers
  `(text, params) -> list[dict]`, dispatched by name. No general expression evaluator, no
  arbitrary AST. Adding a parser is a new registry entry, not new grammar.
- **H3.** The decision tree evaluates the security gate first; `DENIED_SECURITY` precedes any
  business gate or mutating op.
- **H4.** Ref-grounding refusal is preserved: the interpreter refuses to emit `OUTCOME_OK` when a
  required runtime ref (`$name`) is unresolved or when refs carry only static template entries.
- **H5.** Pre-phase discovery is read-only. No mutating RPC runs before the interpreter's guarded `ops`.
- **H6.** `vm.answer` is the only terminal RPC and is called exactly once per task.
- **H7.** Forbidden to patch `data/prompts/*` to fix a specific task (inherits H4 from prior intent).

## Autonomy Zones

- **Full autonomy** (reversible, low risk):
  - Create `agent/interpreter.py`, the IR/IntentSpec Pydantic models, the predicate engine,
    the primitive library, the parser registry.
  - Extend `agent/orchestrator.py` pre-phase gathering.
  - Remove `agent/codegen_v2.py`, `agent/fidelity.py`, and the `_AnswerGuard`/retry-guard
    machinery in `agent/pipeline.py` once the new path is green.
  - Edit `data/prompts/*` for the new intent/plan output contracts; update `tests/*`.
- **Guarded** (log + confidence threshold):
  - Land the interpreter behind a flag (parallel path) and A/B it against the current pipeline
    on the benchmark before deleting the old path.
- **Proposal-first** (needs approval — HUMAN CHECKPOINT):
  - Any change to `data/learned/{tid}.yaml` or `data/oracle/atoms.yaml` schema.
  - Editing `models.json`.
  - Deleting the old `CODEGEN` path (the irreversible cutover).
- **No autonomy** (human only):
  - `agent/llm.py` tier routing / fallback.
  - `bitgn/` generated stubs, `proto/` sources.

## Stop Rules

- **Halt if:** any currently-green task regresses (HM1) — do not mask by patching the interpreter
  around a specific task; fix the IR/intent or the LEARN rule.
- **Halt if:** a full-benchmark validation run scores **below the current baseline** — return to
  design, do not ship.
- **Escalate if:** a task class is found that needs general control flow beyond the named-parser
  escape hatch — that would reopen H1/H2 and is a design decision, not an implementation one.
- **Done when:**
  - A full benchmark run scores **≥ baseline** AND
  - the `CODEGEN` free-Python path is removed (OC1) AND
  - the interpreter + IR are materially fewer LOC than the replaced fortress (OC7) AND
  - HM3 load-bearing guards are covered by passing regression tests AND
  - HM1/HM2/HM4–HM6 hold (no green regressions, LEARN/oracle/training intact, cost/tier envelope intact).
