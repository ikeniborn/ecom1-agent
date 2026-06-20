---
review:
  spec_hash: 924ef4e46d99ffb5
  last_run: 2026-06-20
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: Model roles — dynamic escalation
      section_hash: 97b69ab11d90e868
      text: >-
        "low self-confidence" stall signal has no defined threshold or mechanism
        (how a step self-reports confidence, what counts as "low"). Mitigated —
        spec marks it a soft/secondary signal behind the deterministic empty/repeat
        signals — but still a requirement-ish criterion without an explicit DoD.
      verdict: fixed
      verdict_at: 2026-06-20
      resolution: >-
        v1 stall detection is now fully deterministic (empty result ∨ repeated tool
        signature); model-reported confidence escalation moved to Out of Scope (v1)
        pending an objective threshold.
  chain:
    intent: null
---
# Step-wise Investigator → Deterministic Plan (Hybrid Pipeline) — Design

**Date:** 2026-06-20
**Status:** Design (approved sections 1–3, pending spec review)
**Trigger:** Architectural analysis of `logs/trace_t38_20260620_223853_claude-code-haiku` (t38, score 0)

## Problem

The current pipeline is **plan-then-execute with full context front-loading**. Per task:

1. `gather_prephase_facts` eagerly reads **everything** up front: full schema (~186 lines for
   t38), all 11 doc paths, the **full bodies** of 4+ policy docs, identity, sample rows, dir
   listings.
2. `INTENT` (1 LLM call) then `PLAN` (1 LLM call) must digest that entire dump and emit the
   **complete** Plan-IR in a single shot.

Observed failure in the t38 trace:

- `seq 19 · cycle 1 · PLAN · 492108ms · tok 0/0 · reasoning=no` — the PLAN call **timed out at
  492 s** (Claude Code CLI) against the huge prompt, then retried.
- `seq 20 · cycle 2 · PLAN` produced a plan; final **score 0**.
- The PLAN chain-of-thought shows the model **floundering** inside the dump: "I can't find a
  fraud_incidents table… I'm making assumptions… should I clarify or discover?" — guessing at
  schema it cannot fully absorb instead of probing step by step.
- `iLEARN` distills **one lesson per failed cycle** from the whole failure — coarse
  "all-good / all-bad", not per-step.
- The oracle injects **K=4 atoms keyed on the whole instruction** into PLAN at once, not
  scoped to the immediate sub-goal.

**Root thesis (confirmed by the trace):** the agent should work **sequentially** — probe a
small piece, analyse it, decide the next tool, accumulate understanding — instead of receiving
one massive blob and being asked to find the answer inside it.

## Direction (decided)

**Hybrid.** Make only the **discovery** phase agentic; keep execution deterministic.

A read-only, step-wise **investigator** loop (reason → pick one tool → observe → note) gathers a
compact **evidence brief**, then **one deterministic PLAN** consumes the brief and is executed by
the unchanged Plan-IR interpreter and gated by the unchanged deterministic `verify()`.

This preserves the project's identity — deterministic execution, deterministic quality gate,
mutations only in the plan — while curing the front-load problem.

Decisions taken during brainstorming:

| Fork | Decision |
|------|----------|
| Radicality | Hybrid: agentic investigator → 1 deterministic plan + `verify()` |
| Step lessons | **Both**: in-run working memory (brief) + cross-run distill → validate → promote to oracle |
| Model roles | **Dynamic escalation**: each step starts FAST; stalls escalate to REASON |
| Stop condition | **Sufficiency OR budget**: stop when `intent.required_refs`/`success_criteria` are groundable, or at a step ceiling |

## Architecture

New phase `INVESTIGATE` slots between `INTENT` and the PLAN loop in
`pipeline.py:run_pipeline`. `interpret()` / `verify()` are untouched.

```
seed   = slim_gather(vm)                  # identity + schema NAMES + doc PATHS (no LLM, no bodies)
intent = run_intent(seed, instruction)    # REASON, frozen — unchanged
brief  = investigate(vm, intent, seed):   # NEW — read-only ReAct
    for step in 1..INVESTIGATE_MAX_STEPS:
        atoms = oracle.retrieve(step_goal, k=INVESTIGATE_ORACLE_K)   # scoped to the micro-goal
        act   = router(FAST → escalate REASON, intent, brief, atoms) # one tool, or {done:true}
        if act.done: break
        obs   = vm.<tool>(act.args)                                  # read-only whitelist
        note  = digest(FAST → escalate, obs)                         # observation + lesson + env bindings
        brief.append(note)
        if sufficient(intent.required_refs, brief.env): break        # sufficiency stop
        if budget_hit: break                                         # ceiling stop
loop cycle 1..N:                          # EXECUTION — unchanged
    plan = run_plan(intent, brief, ...)   # facts <- compact brief (not the eager dump)
    lint → interpret → verify
    pass → answer once + distill step-lessons → validate → promote
    fail → iLEARN(brief + observed) → next cycle
```

**Why this fixes t38:** PLAN no longer receives the dump (full schema + 4 policy bodies + sample
rows + listings at once). It receives a compact brief of **already-resolved** facts (the resolved
incident id, the governing doc path, the candidate `record_path`s). The PLAN prompt shrinks
sharply → the 492 s CC timeout disappears and the model stops floundering.

## Components

| Component | Responsibility | Location |
|-----------|----------------|----------|
| `slim_gather` | Trim `gather_prephase_facts` to a cheap, no-LLM **seed**: identity + table/column **names** + doc **paths**. No policy bodies, no sample rows, no listings — those become on-demand investigator tools. | `agent/orchestrator.py` (edit) |
| `investigate(vm, intent, seed) -> Brief` | Read-only ReAct loop; builds the `Brief` (ordered step-notes + an `env` of bound facts). | `agent/investigate.py` (new) |
| router / digest | FAST `think=off`: pick exactly one tool (or signal `done`) / condense raw tool output into a small `note` (observation digest + lesson + env bindings). Escalate to REASON `think=on` on stall. | `investigate.py` |
| read-only whitelist | `sql` (SELECT only), `read`, `tree`, `stat`, `list`, `search`. A mutation attempt is rejected by lint → recorded as a lesson, step retried — never a crash. | `investigate.py` |
| step-scoped oracle | `oracle.retrieve(step_goal, k=INVESTIGATE_ORACLE_K)` keyed on the **current micro-goal**, not the whole instruction. Replaces the single whole-instruction K=4 dump into PLAN. | reuses `agent/oracle.py` |
| sufficiency gate | After each step: are `intent.required_refs[happy]` + `success_criteria` groundable from `brief.env`? Deterministic where possible (is the `record_path` bound? is the governing doc read?). Yes → stop. | `investigate.py` |
| cross-run lessons | On success: distill the best step-lessons into **candidate** oracle atoms → `validate_atom_via_grader` → `promote` on improvement. General/validated only — never task-specific prose. | reuses `agent/oracle_validate.py` |
| tier label | New phase `INVESTIGATE` (fast-tier default) in `llm.py:_resolve_model_for_phase`. | `agent/llm.py` |

### Brief shape

```
Brief = {
  notes: [ {goal, tool, args, observation_digest, lesson, refs_found}, ... ],
  env:   { <bound fact name>: <value> },   # e.g. resolved incident_id, governing doc path, candidate record_paths
}
```

`env` is what the sufficiency gate inspects and what PLAN consumes in place of the eager facts
block. `notes` carry the in-run lessons that guide the next step and seed cross-run distillation.

### Model roles — dynamic escalation

- router/digest steps default to FAST (`ECOM_MODEL_FAST` / `ECOM_MODEL_INVESTIGATE`, `think=off`).
- A step **stalls** when (v1, fully deterministic — no model self-report): the tool result is
  empty (zero rows / empty body / tool error) **∨** the tool signature `(tool, normalised args)`
  exactly repeats a signature already present in `brief.notes`. Both signals are computed by the
  loop, not reported by the model, so the stall predicate is testable. A model-reported
  "confidence" escalation signal is **out of scope for v1** (deferred to the future-extensions
  list) precisely because it has no objective threshold.
- On stall, the same step is re-run once on REASON (`ECOM_MODEL_REASON`, `think=on`); a second
  consecutive stall on the same signature ends the loop (hands the best-effort brief to PLAN).
- `INTENT`, the final `PLAN`, and cross-run distill stay on REASON (unchanged).

### v1 simplification

The `Brief` is built **once** before the PLAN loop and **frozen** for the run (mirrors how
`INTENT` is frozen). PLAN failures are handled by the existing `iLEARN` loop using
`brief + observed`. Re-investigation triggered by `verify()` feedback is a **future extension**,
out of scope for v1.

## Data Flow (per task)

1. `slim_gather(vm)` → seed (no LLM).
2. `run_intent(seed, instruction)` → `IntentSpec` (REASON, frozen) — unchanged.
3. `investigate(vm, intent, seed)` → `Brief` (the new loop above).
4. PLAN loop `1..N` — `run_plan(intent, brief, …)` → lint → interpret → verify, unchanged except
   `facts` is now the compact `Brief` instead of the eager dump.
5. On success: `answer` once, persist artifacts, distill best step-lessons → validate → promote.
6. On failure: `iLEARN(brief + observed)` → next cycle. Loop exhaust / no-progress →
   `OUTCOME_NONE_CLARIFICATION` (unchanged).

## Error Handling

- Tool error / empty result → counts as a stall → escalate REASON; persistent → record lesson,
  continue until budget.
- No usable brief produced → PLAN runs on the slim seed → graceful degradation to roughly
  current behaviour; **never worse than today**.
- Investigator attempts a mutation → lint rejects → lesson, step retried (not a crash).
- Budget exhausted without sufficiency → hand the best-effort brief to PLAN (PLAN may still
  succeed or fall to CLARIFICATION, as today).
- Unhandled exception inside `investigate` → caught; fall back to slim-seed facts into PLAN.

## Configuration (new env vars)

| Var | Default | Purpose |
|-----|---------|---------|
| `ECOM_INVESTIGATE_ENABLED` | `1` | Master toggle. `0` → use the **old eager `gather_prephase_facts`** and skip the investigator (exact current baseline for clean A/B). |
| `ECOM_INVESTIGATE_MAX_STEPS` | `6` | Hard ceiling on investigator steps. |
| `ECOM_INVESTIGATE_ORACLE_K` | `2` | Atoms retrieved per step (step-scoped). |
| `ECOM_MODEL_INVESTIGATE` | — | Per-phase model override → fast tier → `ECOM_MODEL`. |

The legacy `gather_prephase_facts` is **retained** behind the toggle so `ENABLED=0` reproduces
today's behaviour exactly, enabling a clean A/B comparison.

## Testing / Success Criteria

**Unit** (`investigate.py` over `MockVMSpy`):
- read-only whitelist enforced (mutation → lesson, not execution);
- brief is built from a scripted tool sequence;
- sufficiency stop fires when refs become groundable;
- budget stop fires at `INVESTIGATE_MAX_STEPS`;
- escalation triggers on empty result and on repeated tool signature.

**Integration:**
- `run_pipeline` over the mock VM yields a brief, then a valid plan;
- existing `interpret` / `verify` / interpreter tests stay green (those paths are untouched).

**Real gate (the decisive one) — re-run t38 against the live grader:**
- t38 score improves from **0** to **> 0**;
- the `[plan] user prompt chars=` log drops sharply vs the baseline;
- no 492 s CC timeout on PLAN;
- token accounting recorded: more (small, FAST) calls vs today's 1–2 — net cost noted, not
  assumed.

**Trace:** investigator steps appear in `reasoning.md` / `jsonl` (extend `trace.py` with
`INVESTIGATE` phase records — fits the existing observability workstream).

## Tradeoffs

- **More LLM calls** (many small FAST) vs today's 1–2. Mitigated by: FAST/`think=off`, tiny
  per-step prompts, step-scoped oracle, hard budget.
- **New module + new phase label + 4 env vars.** Contained; does not touch `interpret`/`verify`.
- **Risk: under-investigation** → weak brief → PLAN guesses. Mitigated by the sufficiency gate
  tied to `intent.required_refs`, plus graceful fallback that is never worse than the baseline.

## Out of Scope (v1)

- Re-investigation triggered by `verify()` failure feedback (brief stays frozen for the run).
- Model-reported "confidence" as an escalation signal — v1 stall detection is fully
  deterministic (empty result ∨ repeated tool signature); a confidence-based signal is deferred
  until it has an objective threshold.
- Making the deterministic interpreter or `verify()` agentic — they stay deterministic.
- Mutations inside the investigator — investigator is strictly read-only; all mutations remain
  in the plan's `ops`.

## Docs Obligation (per CLAUDE.md)

After implementation: `iwiki-ingest` the changed sources and the new `investigate.py`; run
`/iwiki-lint`; update `agent/CLAUDE.md`, the root `CLAUDE.md` architecture section, and the env
var table.
