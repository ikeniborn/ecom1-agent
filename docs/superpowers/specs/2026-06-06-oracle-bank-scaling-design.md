# Design: knowledge-oracle bank scaling

**Date:** 2026-06-06
**Status:** approved
**Intent:** `docs/superpowers/intents/2026-06-06-oracle-bank-scaling-intent.md`

## Problem

At 6 atoms with `ORACLE_TOPN=10`, the cosine stage returns every active atom (bank < top-N),
so embeddings filter nothing — only the LLM re-rank selects. Every task re-embeds all atoms +
the query (no persisted cache). `nomic-embed-text` is called without its required task prefixes.
The bank cannot grow without hand-editing `atoms.yaml`. Knowledge reaches only CODEGEN, never
DESIGN. Net: the vector machinery is dead weight that still costs ~7 embed calls/task.

## Goals

Make vector retrieval genuinely functional by scaling the bank, while guaranteeing no
already-green task regresses. Priority trade-off: **trust** — atom quality over bank size.

## Non-goals

- No edits to `data/prompts/` to fix task failures (project rule — knowledge flows via atoms/LEARN).
- No deletion of existing validated atoms (human-only zone).
- Not chasing a specific score number; the bar is "≥ baseline 32.32%, green held".

---

## Section A — Embedding cache, nomic prefixes, retrieval tuning

**Autonomy: full (reversible, test-covered).**

### A1. Persistent embed cache
- Today `oracle.py:_embed_atom` caches in `self._vec_cache` (in-memory, dies with the instance;
  `KnowledgeOracle()` is constructed per task in `pipeline.py:457`).
- New: persist vectors to `data/oracle/embeddings.json` as `{content_hash: [floats]}`.
  Vectors do NOT go into `atoms.yaml` (768-dim arrays bloat the yaml); `embedding_hash` in the
  yaml stays as the cache key / invalidation marker.
- `KnowledgeOracle.__init__` loads the cache file once. Miss → embed → append + write back.
- Effect: each atom embedded once across all history, not once per task.

### A2. nomic task prefixes
- `llm.embed_texts(texts, model, base_url=None)` gains a `prefix: str | None` argument.
- Atoms embedded with `search_document: {content}`; query embedded with `search_query: {task_text}`.
- Applied only for `nomic-*` model ids; other models receive raw text (no prefix).

### A3. top-N and cosine floor
- `ORACLE_TOPN` stays env-controlled; intent is to keep it below bank size so cosine filters
  once the bank grows. Default unchanged for now (10); tune after growth.
- New env `ORACLE_FLOOR` (cosine minimum, default 0.5): an atom scoring below the floor is not
  injected even if it lands in top-n. Discards are logged.

### A4. DESIGN-phase injection
- Today `build_oracle_block` feeds atoms only into CODEGEN.
- New: pass `oracle_atoms` into `run_design` and render the same block in the DESIGN prompt.
  `retrieve(instruction)` already runs before the loop in `pipeline.py`; reuse its result.
- **Hard constraint guard:** the DESIGN signature `(instruction, agents_md_text)` is protected
  by F-001 regression tests (`tests/test_design.py`). The new `oracle_atoms` parameter must not
  re-introduce `learn_ctx` into DESIGN — DESIGN stays frozen-for-the-run; oracle knowledge is
  read-only context, not per-cycle state.

---

## Section B — distill → candidate → promote with green-suite gate

**Autonomy: guarded (auto-distill) + full (promote, gated by regression check).**

### B1. Distill
- `oracle.py:distill` writes the atom as `status: candidate` (already does). `ORACLE_DISTILL=1`
  enables auto-distill after LEARN (logs, stays inactive).
- Candidates live in `atoms.yaml` but `_active()` excludes them from `retrieve`, so the
  production bank is never polluted by unvalidated atoms.

### B2. Green-suite manifest
- New `data/oracle/green_suite.yaml`: an explicit, curated list of `task_id` + reference score
  (seeded from current green tasks, e.g. t01, t51 = 1.0, plus the rest).
- Explicit list, not auto-derived from `data/learned/`, for trust control — gate membership is a
  one-time human decision.

### B3. Promote gate — separate offline pass
New CLI entry (`make promote` / a flag on `main.py`). Per `candidate` atom:
1. Temporarily activate the atom (candidate→active, in-memory).
2. Run `_run_one_pass` over the task set = **source-task ∪ green-suite** (reuses the existing
   StartRun → trials → SubmitRun machinery from training mode).
3. Compare each task's score to its reference:
   - source-task improved (was < 1.0, now higher) **AND** every green-suite task held its
     reference (new score ≥ reference score) → **promote** (persist candidate→active).
   - any green-suite task dropped → **halt**: atom stays `candidate`, log + escalate.
4. Iterate over all candidates.

### B4. Why a separate pass, not inside a trial
- Score is visible only post-SubmitRun; inside a trial there is no score to gate on.
- Keeps the per-task LLM call budget (1/2/7) untouched — promote is an offline operation, not
  run on every production task.

### Data flow
```
LEARN rule → distill → candidate (atoms.yaml, inactive)
                          ↓ (make promote, offline)
        run(source ∪ green-suite) with atom active
                          ↓
   green held + source improved? ── yes → active (promote)
                          └─ no → stays candidate + escalate
```

---

## Section C — Error handling and testing

### C1. Error handling (fail-safe preserved)
- Corrupt/missing `embeddings.json` → log + rebuild from scratch, never crash.
- Ollama embed down → existing `retrieve` catch → `_tag_fallback`; prefixes must not break it.
- Promote pass fails (harness/grader unavailable) → atom stays candidate, zero bank change.
  Promote happens only on a fully successful run of the task set.
- DESIGN injection: empty `oracle_atoms` or exception → DESIGN behaves as before; oracle never
  crashes DESIGN.
- Missing `green_suite.yaml` → promote gate halts with a clear message; never a silent promote.

### C2. Testing
- `tests/test_oracle_embed.py` (exists) — extend: nomic prefixes applied; non-nomic gets raw text.
- `tests/test_oracle_retrieve.py` (exists) — cosine floor discards sub-threshold; top-N < bank filters.
- `tests/test_oracle_cache.py` (new) — atom embedded once; persist + reload from `embeddings.json`;
  corrupt file → graceful rebuild.
- `tests/test_oracle_promote.py` (new) — green held → promote; green dropped → stays candidate;
  source not improved → no promote. Harness mocked (no real 3h run).
- `tests/test_design.py` (exists, F-001 guard) — add: `oracle_atoms` parameter does not break the
  `(instruction, agents_md_text)` signature; `learn_ctx` still forbidden in DESIGN.
- `tests/test_codegen_oracle.py` (exists) — unchanged, regression anchor.

### C3. Verification (intent Done-criteria)
- All unit tests green.
- E2E: one real distilled atom passes `make promote` over source ∪ green-suite; green held; atom
  becomes active.
- Full run: score ≥ baseline 32.32% (no regression).

---

## Files touched

| File | Change |
|------|--------|
| `agent/oracle.py` | persistent cache load/save; cosine floor; candidate exclusion already present |
| `agent/llm.py` | `embed_texts` gains `prefix`; nomic prefix logic |
| `agent/codegen_v2.py` | `build_oracle_block` reused for DESIGN (no functional change here) |
| `agent/design.py` | accept + render `oracle_atoms` (guard F-001 signature) |
| `agent/pipeline.py` | pass `oracle_atoms` to `run_design`; auto-distill wiring (ORACLE_DISTILL) |
| `main.py` | `make promote` entry: promote-gate pass over source ∪ green-suite |
| `data/oracle/embeddings.json` | new — persisted vector cache |
| `data/oracle/green_suite.yaml` | new — curated green-task manifest |
| `Makefile` | `promote` target |
| `tests/test_oracle_{cache,promote}.py` | new |
| `tests/test_oracle_{embed,retrieve}.py`, `tests/test_design.py` | extended |
