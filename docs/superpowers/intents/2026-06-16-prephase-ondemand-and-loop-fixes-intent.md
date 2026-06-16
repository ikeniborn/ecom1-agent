---
review:
  intent_hash: 009ea159598692f5
  last_run: 2026-06-16
  phases:
    structure:    { status: passed }
    completeness: { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
    alignment:    { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: Desired Outcomes
      section_hash: ff8a05909b47f92f
      text: "Outcome 'AGENTS.MD is parsed into a tool/catalog inventory (revives the dead agents_md_parser)' leaks implementation (HOW) into a desired outcome; restate as an observable capability."
      verdict: fixed
      verdict_at: 2026-06-16
    - id: F-002
      phase: clarity
      severity: WARNING
      section: Health Metrics
      section_hash: c4cfe8f19891da55
      text: "Vague terms 'keep it reasonable' / 'needlessly' in the LLM-budget note lack a measurable criterion."
      verdict: fixed
      verdict_at: 2026-06-16
---
# Intent: Prephase on-demand fetching + loop/oracle fixes

**Date:** 2026-06-16
**Status:** approved

## Objective

The deterministic Plan-IR pipeline loops to `OUTCOME_NONE_CLARIFICATION` on
solvable tasks. Proven on `t01` ("do you carry product X?") across two runs
(`logs/20260616_151702_*`, `logs/20260616_154540_*`): both scored 0.00 although
the grader expected `OUTCOME_OK` (the product exists).

Three compounding root causes, found in the logs + code:

1. **Prephase is simultaneously over- and under-fetching.**
   `reason.py:_facts_block` injects *every* fact (agents_md + schema +
   sample_rows + docs_inventory + **6.2 KB security policy** + identity +
   target_records + listings) into INTENT and into **every** PLAN cycle →
   PLAN prompt = **27–29 K chars re-sent each cycle** → context drift. For a
   simple lookup the security policy is irrelevant noise. Meanwhile the data
   PLAN actually needs — `sample_rows` of the target tables — was **empty**,
   because `orchestrator.py:_relevant_tables` lexically matches table names
   (`product_variants`) against instruction text that never says "product".
   So PLAN wrote blind exact-match SQL (`series='Heco Zinc Plated'`,
   `diameter='8 mm'`) that returned **0 rows** against differently-formatted
   stored data.

2. **The oracle is inert.** `data/oracle/atoms.yaml` is empty (0 lines).
   `ORACLE_ENABLED=1` but there is nothing to retrieve — no atom entered PLAN
   in any cycle. Worse, distill→validate→promote fires **only on a successful
   cycle**, and failing tasks never succeed → the bank can never fill itself
   (chicken-and-egg). This is the "how is new knowledge verified" gap: the
   verification loop never runs.

3. **Cycles are wasted on IR-syntax and an asymmetric verify gate.** In the
   4-cycle run, cycle 1 died on `extra_forbidden` (invalid IR), cycle 3 on
   `unknown predicate op 'neq'`, cycle 4 short-circuited on a repeated plan.
   Only cycle 2 reached interpret — and verify rejected its valid negative
   branch because `success_criteria` demanded `nonempty product_sku`, so a
   legitimate "not carried" answer can never pass. `iLEARN` produced nothing
   usable (`parsed=None`) on every failing cycle.

Why now: `t01` is 0% on two consecutive runs, the benchmark baseline is stuck
(~32%), and the 27–29 K-char per-cycle prompt is a direct context-drift driver.

The redesign: parse AGENTS.MD into a **tool/catalog inventory**, shrink prephase
to a thin inventory (tool list + catalog paths + schema names/DDL), and let PLAN
pull the actual data **portionally via IR `discovery` steps** — reusing the
existing interpreter mechanism. Fix the three loop bugs as part of the same work.

## Desired Outcomes

- `t01` returns `OUTCOME_OK` on a real `make task TASKS='t01'` run (product found
  via format-robust lookup), verified by running the code — not by tests.
- PLAN addresses the correct tools and catalog paths up front, derived from
  AGENTS.MD, without the full document being injected into every cycle.
- Prephase no longer dumps all facts up front; the PLAN prompt for `t01` is
  measurably smaller than the 27–29 K baseline. Real data (sample rows, docs,
  records) is fetched portionally via PLAN `discovery` steps.
- The oracle bank is non-empty and injects ≥1 relevant atom on a matching task.
  (Seeding/verification mechanism — see Open Question.)
- A valid `OUTCOME_NONE_UNSUPPORTED` answer can pass verify when that is the
  correct outcome (verify accepts the negative branch, not only the positive).
- IR-syntax errors no longer silently burn cycles to exhaustion.

## Health Metrics

- **No regression on the other 53 benchmark tasks** — tasks at score 1.0 stay
  1.0; baseline (~32%) does not drop because of the thin prephase.
- **Pipeline determinism preserved** — `verify()` stays the sole deterministic
  gate, `vm.answer` is called exactly once per task, no LLM answer-grading.
- **Re-seed safety** — rules/atoms remain *methods*, not hardcoded values
  (benchmark re-randomizes data every StartRun).
- (LLM-call budget may shift with on-demand fetching — explicitly **not** a hard
  gate per the user. Tracked, not gated: report `t01`'s LLM-call count before
  and after the change so any shift is visible.)

## Strategic Context

- Interacts with: `orchestrator.py:gather_prephase_facts` / `_relevant_tables`,
  `reason.py:_facts_block`, the interpreter's `discovery` steps,
  `agents_md_parser.py` (currently dead), `oracle.py` / `oracle_validate.py`,
  `verify.py`.
- Priority trade-off: **trust** (correctness on solvable tasks) over speed.

## Constraints

### Steering (behavioral guidance)
- Reuse the existing IR `discovery` mechanism for portioned fetch — minimum new
  code; no new pipeline phase.
- Surgical changes; match existing style; touch only what the redesign requires.
- Prephase keeps only cheap, broadly-useful facts (tool inventory, catalog
  paths, schema names + DDL, identity); heavy/task-specific data moves to PLAN.

### Hard (architectural enforcement)
- **No functional tests** (global rule). Verify by running real code
  (`make task TASKS='t01'`) and observing output.
- **Never patch `data/prompts/`** to fix a task failure — task knowledge flows
  through LEARN / the oracle, not the system prompts.
- `verify()` stays deterministic; no LLM-graded answer check.
- `vm.answer` called exactly once per task.
- No re-seed-fragile hardcoded values in rules or atoms.

## Autonomy Zones

- **Full autonomy (reversible, low risk):** diagnosis (done); internal refactor
  of prephase fact-gathering; reviving the AGENTS.MD parser.
- **Guarded (log + threshold):** oracle seeding mechanism — log what is seeded
  and why.
- **Proposal-first (needs approval) — HUMAN CHECKPOINT:** all code changes.
  Flow is brainstorm → plan → checkpoint before any edit (per user).
- **No autonomy (human only):** editing `data/prompts/` for task-specific fixes;
  deleting heuristics of currently-passing tasks.

> These zones OVERRIDE continuous-execution defaults. Code work pauses at the
> plan checkpoint.

## Stop Rules

- **Halt if:** a prephase change regresses any currently-passing task.
- **Escalate if:** resolving the oracle chicken-and-egg requires live grader
  round-trips at a cost that wasn't agreed — bring options to brainstorm.
- **Done when:** `t01` returns `OUTCOME_OK` on a real `make task TASKS='t01'`
  run, AND a spot-check of ≥2 previously-passing tasks still passes, AND the
  PLAN prompt size for `t01` is measurably smaller than the 27–29 K baseline.

## Open Question (deferred to brainstorm)

How the oracle verifies/seeds new knowledge given the chicken-and-egg:
- (a) seed `atoms.yaml` offline from existing `data/learned` / hand-written
  methods before a run; distill augments, or
- (b) distill a candidate atom even from a *failed* cycle and use the grader as
  validator (`validate_atom_via_grader`) to break the deadlock without offline
  seeding.

Decide the mechanism in `superpowers:brainstorming` (HOW), not here.
