---
title: Pipeline Unification — collapse legacy DESIGN/CODEGEN into the Plan-IR interpreter
date: 2026-06-16
status: approved
supersedes_runtime_of:
  - 2026-06-07-deterministic-plan-interpreter-design.md
---

# Pipeline Unification

## Problem

`agent/pipeline.py` carries **two parallel pipelines** behind a hard either/or fork
(`run_pipeline:943`):

- **Legacy**: DESIGN → CODEGEN → fidelity/TESTGEN → ANSWER (free-form Python codegen).
- **Interpreter**: INTENT → PLAN → `interpret()` → `verify()` → ANSWER (deterministic
  Plan-IR), gated by `INTERPRETER_ENABLED=1`.

The 2026-06-07 spec intended the interpreter to *replace* CODEGEN. In practice it was
bolted on as a second path, and the knowledge contour was only half-migrated. Evidence
(run `logs/20260615_232738_deepseek-v4-flash-cloud`, interpreter mode):

1. **Oracle distill not wired.** `_run_interpreted` calls `KnowledgeOracle().retrieve()`
   (`pipeline.py:362`) but never `.distill()`. The only `.distill()` call lives in the
   legacy path (`pipeline.py:302`). `interpreter.py` has zero oracle references.
   → `data/oracle/atoms.yaml` never grows in interpreter mode. ("оракул пуст".)
2. **Surface split not bridged.** Interpreter runtime reads/writes learned rules on
   `surface="ir"` (`pipeline.py:351`, `_ilearn:324`). But training-mode
   `learn_from_grader` (`pipeline.py:481-489`) distills grader feedback to the DEFAULT
   `surface="codegen"` — a surface the interpreter never reads. → grader-feedback
   knowledge is lost between training cycles.
3. **Two LEARN seams, two prompts, two model-key conventions.** Interpreter `run_intent`
   / `run_plan` reuse the legacy phase keys `"design"`/`"codegen"`
   (`reason.py:64,95`) → model routing is opaque and mis-labelled.

Separately, the model layer needs per-phase routing: reasoning where the phase reasons,
fast/cheap where the phase is light, no LLM where the phase is deterministic.
(Root-caused in the prior session: `gpt-oss:20b-cloud` returned empty `content` over the
homelab `/v1` OpenAI-compat gateway — harmony channels not surfaced — while `deepseek`
returns `content`+`reasoning_content` correctly. Model choice per phase is load-bearing.)

## Goal

One pipeline (the interpreter), with a complete, single knowledge contour and clean
per-phase model routing. Delete the legacy path and all its dependencies in a single
cutover PR, commits split per step for review.

## Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Migration sequencing | **Single cutover PR**, commits split per step |
| D2 | Model routing | **3 tiers + per-phase override** (`MODEL_REASON`, `MODEL_FAST`, no-LLM, `EMBED_MODEL`, `MODEL_<PHASE>`) |
| D3 | Oracle atom lifecycle | **candidate → grader-validate → active**; `retrieve()` returns active only |
| D4 | Atom validation timing | **Inline in run** (after success), behind `ORACLE_VALIDATE_INLINE` flag |
| D5 | Learned-rule surface | **Collapse to single surface**; `load_entries(tid)` with no filter |
| D6 | TESTGEN/TDD + fidelity | **Delete**; `verify()` is the sole gate |

## Target Architecture

### Single pipeline

`run_pipeline()` loses the fork. Its body becomes the former `_run_interpreted`. The
`INTERPRETER_ENABLED` flag is removed (always on).

```
run_pipeline(vm, instruction, task_id, agents_md_text, facts):
  pre-phase facts (DOC_SELECT + schema + id + listings)        # DOC_SELECT = fast tier
  INTENT (frozen, retry on empty/parse)                         # reason tier
  for cycle in 1..INTERPRETER_MAX_STEPS:
    PLAN (Plan-IR)                                              # reason tier
    lint_security_first(plan)                                   # no LLM
    interpret(plan, intent, vm, facts)                          # no LLM
    ok, verr = verify(result, intent)                          # no LLM
    if ok:
      vm.answer(...)            # exactly once
      _persist_artifacts(intent, plan)
      if ORACLE_DISTILL: distill → (ORACLE_VALIDATE_INLINE? grader-validate → promote)
      return success
    else:
      _ilearn(prev_error + observed)   # reason tier, single surface
  return CLARIFICATION
```

`vm.answer` is called exactly once. The quality gate is `verify()` (deterministic). No
DESIGN, CODEGEN, fidelity, or TESTGEN.

### Model routing (3 tiers + override)

Replace `_PHASE_MODEL_MAP` (`llm.py:70-74`) with phase keys that match the real phases.
`reason.py:64,95` switch from `"design"/"codegen"` to `"intent"/"plan"`.

| Phase | Nature | Tier | env key |
|-------|--------|------|---------|
| DOC_SELECT | light classification | fast | `MODEL_FAST` |
| INTENT | semantic, frozen | reason | `MODEL_REASON` |
| PLAN | structured Plan-IR, self-correcting | reason | `MODEL_REASON` |
| interpret / verify / lint | deterministic | no LLM | — |
| iLEARN | diagnose failure → rule | reason | `MODEL_REASON` |
| distill | generalize atom | reason | `MODEL_REASON` |
| oracle rerank | re-rank candidates | fast | `MODEL_FAST` |
| embeddings | retrieval | embed | `EMBED_MODEL` |

Rules:
- Resolution order per phase: `MODEL_<PHASE>` (e.g. `MODEL_PLAN`) → tier env
  (`MODEL_REASON`/`MODEL_FAST`) → `MODEL`. Empty/unset falls through. Back-compatible:
  with only `MODEL` set, every phase resolves to `MODEL`.
- `reason` tier requests `think=on`; `fast` tier requests `think=off`. Per-model
  `ollama_think` in `models.json` still overrides when set.
- `_PHASE_MODEL_MAP` is read at import; tier env added the same way. Tests that
  `setenv` then call must re-resolve (mirror existing fresh-read pattern where present).

### Knowledge contour

**Surface collapse (D5).** Remove the `surface="ir"` filter at `pipeline.py:351`;
`_run_interpreted` calls `load_entries(task_id)` (no surface). `_ilearn` writes without a
surface filter distinction. `learn_from_grader` reads/writes the same single surface — the
training-mode bug self-heals. Existing `surface=codegen` entries in `data/learned/*.yaml`
become visible to PLAN (accepted risk; they age out as new IR rules accumulate). The
`surface` column may remain in the YAML for back-compat but is no longer a filter key.

**Distill wiring (D2/D3/D4).** After a successful cycle, when `ORACLE_DISTILL=1`:

```python
from .oracle import KnowledgeOracle
oracle = KnowledgeOracle()
atom = oracle.distill(design_intent=<intent text>,
                      error=<last_error or success note>,
                      script_code=plan.model_dump_json(),
                      source_task=task_id)            # writes status="candidate"
if atom and os.environ.get("ORACLE_VALIDATE_INLINE", "1") == "1":
    # grader-oracle re-run on a fresh StartRun (oracle_validate.py)
    if validate_atom_via_grader(atom, task_id):       # score improved?
        oracle.promote(atom.id, validated_by="grader-oracle", validated_at=<run ts>)
```

- **Distill fires on success**, generalizing the plan that worked. `distill()`'s `error`
  parameter is repurposed as a short outcome note (e.g. `"OK: <verify summary>"`); the
  distill prompt already strips all run-specific values, so a success note is fine. (No
  distill on failure — failures feed `_ilearn` into per-task rules, not the general atom
  bank.)
- `retrieve()` returns **active** atoms only (already the case for validated atoms; confirm
  candidate atoms are excluded).
- `ORACLE_VALIDATE_INLINE=0` → distill writes candidate and skips promotion (bulk benchmark
  mode accumulates candidates cheaply for an offline promote later).
- If the grader-oracle harness is unavailable (no live grader), promotion is skipped and the
  atom stays candidate — never raises, never blocks the pipeline.
- **Cost note:** inline validation spends one extra StartRun per distilled atom. This is the
  user-chosen tradeoff; the flag bounds it.

## Legacy Removal Manifest

Ordered so nothing breaks mid-PR. Each numbered group is its own commit.

### Commit 1 — move the shared blocker
`build_oracle_block` (`codegen_v2.py:30-37`) is imported by BOTH `design.py:10` (legacy)
and `reason.py:8` (interpreter). Move it to `agent/oracle.py` (or `oracle_atoms.py`).
Update `reason.py` import. Update `tests/test_codegen_oracle.py` import (or fold into a new
`tests/test_oracle.py`). After this commit the interpreter no longer depends on
`codegen_v2.py`.

### Commit 2 — model routing
- Rewrite `_PHASE_MODEL_MAP` + add tier resolution (`MODEL_REASON`/`MODEL_FAST` + per-phase
  override) in `llm.py`.
- `reason.py:64,95` → `"intent"`, `"plan"`.
- Wire `think` per tier.
- Add `MODEL_DOCSELECT`/DOC_SELECT routing to the fast tier.
- Tests: `tests/test_llm_routing.py` (phase → tier → env resolution).

### Commit 3 — knowledge contour
- Collapse surface: drop `surface="ir"` filter (`pipeline.py:351`); `_ilearn` + grader seam
  share one surface.
- Wire `distill` + candidate→validate→promote into the (renamed) pipeline body.
- Add `ORACLE_VALIDATE_INLINE`; implement `validate_atom_via_grader` on top of
  `oracle_validate.py`.
- Tests: distill writes an atom; promotion gated by flag; `retrieve` returns active only;
  `load_entries(tid)` sees all active rules.

### Commit 4 — unify the entrypoint
- Remove the `INTERPRETER_ENABLED` fork (`pipeline.py:943`); promote `_run_interpreted`
  body into `run_pipeline`.
- Delete the legacy `run_pipeline` body (DESIGN→CODEGEN loop), legacy `_learn_consolidate`
  (surface=codegen), and any now-unreferenced helpers (`_retry_guard_applies`,
  `_is_retryable_vm_error` if interpreter-unused — verify before deleting,
  `_compact_learn_ctx` if legacy-only — verify).
- Remove legacy `learn_from_grader` fallback (`pipeline.py:491-505`); keep only the
  IR-artifact path, fixed to the single surface.
- Stop writing `data/heuristics/{tid}.py` and `{tid}.design.json`.

### Commit 5 — delete legacy modules + models + prompts
- Delete `agent/design.py`, `agent/codegen_v2.py`, `agent/fidelity.py`, `agent/testgen.py`.
- `models.py`: remove `DesignOutput`, `CodegenOutput`, `TestSpec`; keep `AnswerOutput`,
  `LearnConsolidateOutput`, IR types.
- Delete prompts `data/prompts/{design,codegen,test}.md`. Keep `intent`, `plan`, `ilearn`,
  `learn`, `compact`.

### Commit 6 — env, docs, tests cleanup
- Remove env vars: `MAX_STEPS`, `MODEL_CODEGEN`, `MAX_TOKENS_DESIGN`, `MAX_TOKENS_CODEGEN`,
  `MAX_TOKENS_TEST`, `FIDELITY_TIMEOUT_S`, `TDD_ENABLED`, `TDD_MOCK_ENABLED`,
  `TDD_FORCE_SUBMIT_AFTER`, `INTERPRETER_ENABLED`. Add `MODEL_REASON`, `MODEL_FAST`,
  `ORACLE_VALIDATE_INLINE`. Update `.env.example`.
- Update `CLAUDE.md` + `agent/CLAUDE.md` architecture sections (single pipeline, new env
  table, model tiers).
- Delete tests: `test_design.py`, `test_codegen_v2.py`, `test_fidelity.py`,
  `test_testgen.py`. Reconcile `test_codegen_oracle.py` (moved in Commit 1).
- `test_pipeline_v2.py`: cut legacy-path branches; keep interpreter assertions.

### Dead-reference audit (gate before merge)
```
grep -rnE "design\.py|codegen_v2|fidelity|testgen|DesignOutput|CodegenOutput|run_codegen|run_design|generate_fidelity|run_test_gen|INTERPRETER_ENABLED" agent/ main.py
```
Must return zero hits in `agent/` and `main.py` (test deletions covered above).

## Testing & Verification

- **TDD on new code**: distill-wired (atom persisted), surface-collapse (`load_entries`
  visibility), routing (phase → tier → env), inline-validate flag gating.
- **Regression**: full `pytest tests/` green after legacy-test removal.
- **E2E**: run t01/t38/t55 on `deepseek` via the unified path; assert (a) iLEARN writes
  rules, (b) `atoms.yaml` grows when `ORACLE_DISTILL=1`, (c) score recorded. Respect the
  concurrent-run-contention note (pgrep before timed runs; do not kill other sessions' runs).
- **Dead-reference grep** above returns zero.

## Out of Scope

- Per-phase prompt rewrites beyond the `design/codegen` → `intent/plan` key rename.
- Re-tuning `verify()` logic or `INTERPRETER_MAX_STEPS`.
- Offline `promote-atoms` batch target (a future option if inline validation proves too slow).
- Fixing individual task heuristics (t01 yes/no token, t38 SQL parse, t55 last-by-timestamp)
  — tracked separately; this spec is pipeline structure + knowledge contour + routing only.

## Risks

- **Inline atom validation cost** — one StartRun per atom. Bounded by `ORACLE_VALIDATE_INLINE`;
  default off for bulk benchmark runs if it dominates wall-clock.
- **Surface collapse exposes stale codegen rules to PLAN** — accepted; they age out. If they
  measurably mislead PLAN, a one-line deactivate script is the fallback.
- **`build_oracle_block` move** is the only ordering hazard; Commit 1 isolates it.
