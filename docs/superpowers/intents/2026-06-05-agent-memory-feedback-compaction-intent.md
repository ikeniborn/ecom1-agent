# Intent: agent memory — verdict feedback loop + context compaction

**Date:** 2026-06-05
**Status:** approved

## Objective

Close the feedback loop between platform verdict and learned knowledge, and make
context growth deliberate rather than blindly truncated.

Two coupled problems, one intent:

1. **Verdict feedback loop.** After the agent submits an answer, the platform
   returns `score` + `score_detail` (problem descriptions) via `end_trial` in
   `main.py:_run_single_task` — *outside* the pipeline. On `score < 1.0`,
   `save_last_run` persists only status/outcome/cycles; `score_detail` and the
   submitted answer are discarded. The next run of the same `task_id` repeats the
   same mistake because it never sees the real verdict. Note: the platform does
   **not** return the correct answer — only `score` + `score_detail`.

2. **Context compaction.** The model is effective with context at the start
   (≤30%) and end (≥80%) of the window ("lost in the middle"). Today the pipeline
   bounds growth with blind char-slices (`[:80]`, `[:380]`, `[:16000]` in
   `_build_sdd_user_msg` / `_build_answer_user_msg`) that cut important content
   indiscriminately. Compaction must be deliberate (importance- and
   conclusion-based), not truncation.

Why now: failing tasks have no cross-run improvement path, and blind truncation
silently drops grounding the model needs.

## Desired Outcomes

- On `score < 1.0`, `data/learned/{task_id}.yaml` gains a verdict record:
  `score_detail` + submitted `message` / `outcome` / `refs`.
- Next run of the same task runs `test_runner` as a gate **before** `vm.answer()`;
  asserts derived from the prior `score_detail`. Gate failure → retry/LEARN, not
  submission.
- A previously-failing task's score increases on re-run.
- `prior_results` / `learn_ctx` stay under a configured % of context; on breach,
  deliberate compaction fires — last N steps verbatim, older steps compressed to
  conclusions.
- Blind truncation (`[:80]` / `[:380]` / `[:16000]`) removed — replaced by
  deliberate compaction, not slicing.
- Reasoning never flows into phase context — only final conclusions.
- Threshold % and retained-step count configurable via env vars (sensible
  defaults).

## Health Metrics

- **Speed (critical):** mock-test gate must not multiply task wall-clock.
- **Green tasks (critical):** tasks at `score = 1.0` must not regress from
  compaction or the new gate.
- Tokens per cycle (`tok_in`/`tok_out`): may grow — quality is allowed to cost
  tokens.
- `MAX_STEPS`: may increase if the gate needs more retry cycles.

## Strategic Context

- Interacts with:
  - `main.py:_run_single_task` — sole site of platform verdict (`end_trial`);
    writes `score_detail`.
  - `prompt_assembler.py` — `save_last_run` / `load_last_run` / `_build_sources`
    (verdict injection), `assemble_prompt` (compaction at assembly).
  - `pipeline.py` — `prior_results` / `learn_ctx` growth; gate before
    `vm.answer()`.
  - `test_runner.py` — wired in as the pre-submit gate (reuse existing subprocess
    mechanism).
  - `models.py` — importance label on lesson records; env config surface.
  - `data/learned/{task_id}.yaml` — schema extended with verdict record.
- Priority trade-off: **trust > speed** (cost not a priority).
- Parallelism: `PARALLEL_TASKS` > 1 uses a thread pool, but distinct tasks write
  distinct yaml files — no write contention.

## Constraints

### Steering (behavioral guidance)
- Compaction is deliberate (LLM summarization to conclusions / importance label),
  never `[:N]` slicing.
- Reasoning never enters phase context — only conclusions.
- Config via env (threshold %, retained-step count) with sensible defaults.
- The mock-test gate reuses the existing `test_runner` subprocess mechanism — no
  new execution path.

### Hard (architectural enforcement)
- Verdict record is written under `source: verdict` (or `last_run.failure`),
  **bypassing** `_apply_learn_diff` validation — it is a fact, not a rule
  (rules require ≥20 chars + action prefix).
- Never patch `data/prompts/*.md` to fix a specific task — knowledge flows through
  LEARN/verdict records; phase guides hold only general structural rules.
- Verdict is read only in `main.py` (post-submit) → loop is cross-run, not
  within a single run.
- No changes to proto / harness contract.

## Autonomy Zones
- **Full autonomy** (reversible, low risk): verdict yaml record format, env
  names/defaults, `prior_results` compaction, removal of blind `[:N]` slices.
- **Guarded** (log + threshold): mock-test assert generation from `score_detail`,
  per-step importance label.
- **Proposal-first** (needs approval): public `data/learned/*.yaml` schema change
  (breaks existing files), new phase ordering in pipeline.
- **No autonomy** (human only): edits to `data/prompts/*.md`, proto/harness
  contract changes.

## Stop Rules
- Halt if: the mock-test gate starts failing previously-green tasks
  (`score = 1.0` → `< 1.0`).
- Escalate if: `score_detail` format does not parse into asserts (unknown
  structure).
- Done when: a failing task's score rises on re-run **and** green tasks do not
  regress **and** reasoning is absent from phase context **and** blind truncation
  is removed.
