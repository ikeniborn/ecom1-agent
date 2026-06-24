---
review:
  spec_hash: de8fd57ee094020d
  last_run: 2026-06-24
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: INFO
      section: "## Problem / ## Root cause / Verification"
      section_hash: null
      text: >-
        The injected PLAN block is named three ways — "oracle block",
        "VALIDATED KNOWLEDGE — APPLY block", and "knowledge block". One entity,
        inconsistent term. Non-blocking; pick one for the implementation notes.
      verdict: open
      verdict_at: null
chain:
  intent: null
---

# Oracle → PLAN injection regression fix

**Date:** 2026-06-24
**Branch:** `determinism`
**Scope:** `agent/pipeline.py` (single guard removal). No prompt-file edits, no `embeddings.json` change.

## Problem

The knowledge oracle's validated atoms never reach the PLAN prompt when
`ECOM_INVESTIGATE_ENABLED=1` (the default). The oracle effectively does not apply during
runs — the "VALIDATED KNOWLEDGE — APPLY" block is silently absent from every PLAN call.

The user's initial hypothesis ("`embeddings.json` is not updated, stays one line") is a red
herring. `embeddings.json` is written by `KnowledgeOracle._save_vec_cache` as compact
single-line JSON (`json.dumps` without `indent`) regardless of entry count, and is in sync
with `atoms.yaml` (currently 3 active atoms ↔ 3 cached vectors). The single-line appearance
in `git diff` (atoms.yaml `+100` lines vs embeddings.json `+1` line) caused the misread. The
real defect is the retrieval-to-PLAN wiring.

## Root cause

Incomplete refactor when the INVESTIGATE phase became default:

- `pipeline.py` (~L312–317): `oracle_atoms` is initialised to `[]` and populated **only**
  inside `if not _investigate_on:` (the legacy whole-instruction dump). With INVESTIGATE on,
  it stays `[]`.
- `pipeline.py` (~L388): `run_plan(..., oracle_atoms=oracle_atoms)` therefore receives `[]`.
- `reason.py` (L152): `build_oracle_block(oracle_atoms)` on an empty list returns `""` — the
  knowledge block is omitted from the PLAN prompt.
- `investigate.py` (L317, L327): atoms ARE retrieved per step, but only passed to
  `router(...)` via `_atoms_block` as a next-action hint. They are **not** persisted into the
  returned `Brief` (`notes` + `env`), so they never propagate to PLAN.

Net: the old oracle→PLAN channel was removed under INVESTIGATE; the intended step-scoped
replacement channel was never wired into PLAN. This regressed the proven behaviour behind the
memory note "Knowledge oracle proven t51 0→1.0" (proven before INVESTIGATE existed).

## Chosen approach (A): restore the proven retrieval for PLAN

Remove the `if not _investigate_on:` guard so `oracle.retrieve(instruction)` runs in both
modes and always feeds `oracle_atoms` into PLAN. INVESTIGATE keeps its independent per-step
retrievals (`oracle=_oracle`) unchanged.

### Change

`agent/pipeline.py`, the oracle-init block (~L312–319):

```python
oracle_atoms: list = []
_oracle = None
try:
    _oracle = _new_oracle()
    oracle_atoms = _oracle.retrieve(instruction)   # inject into PLAN in both modes
except Exception:
    _oracle = None
```

(The only edit is dropping the `if not _investigate_on:` condition that previously wrapped the
`retrieve` call. The `_investigate_on` flag is still read elsewhere for the INVESTIGATE branch
and the legacy-fallback comment; remove only the now-dead conditional around retrieve.)

### Why this is safe

- Position is preserved (before INTENT). `instruction` is already available; no new
  dependency.
- `retrieve()` already honours `ECOM_ORACLE_ENABLED=0` (returns `[]`), falls back to
  `_tag_fallback`/`[]` on embed failure, and is additionally wrapped in `try/except` here.
- `_oracle` is still handed to `investigate(..., oracle=_oracle)`; `retrieve` does not consume
  or mutate it.

### Cost

One extra `retrieve()` per task when INVESTIGATE is on: one query embed + cosine over the
active atoms (+ one fast-tier LLM re-rank unless `ECOM_ORACLE_RANK_ENABLED=0`). Acceptable;
re-rank is independently gateable.

### Rejected alternative (B)

Accumulate the investigator's step-scoped atoms (dedup by id) into a new `Brief` field and
thread them into `run_plan`. Closer to the "intended" architecture and reuses retrievals
already happening, but changes retrieval semantics (step-goal-scoped vs whole-task), is
UNPROVEN (per memory note on INVESTIGATE data-paths), and adds `Brief` plumbing. Rejected in
favour of restoring the proven channel with minimal risk.

## Out of scope

- `embeddings.json` format/sync — verified correct, untouched.
- `data/prompts/*` — project rule forbids patching prompts to fix task behaviour.
- The orphan-vector accumulation in the vec cache (pruned candidates leave vectors) — pre-
  existing, not a correctness issue, not addressed here.

## Verification

1. **Unit/integration test** (new): with `ECOM_INVESTIGATE_ENABLED=1` and an oracle whose
   `retrieve` returns a matching atom, spy on `run_plan` and assert it receives a non-empty
   `oracle_atoms`. Pre-fix this list is empty; post-fix it contains the atom. Add the inverse
   assertion path or reuse an existing pipeline test fixture for wiring.
2. **Trace check** (manual/real): run t51 (or any oracle-relevant task) with INVESTIGATE on
   and confirm the "VALIDATED KNOWLEDGE — APPLY" block appears in the PLAN prompt in the
   JSONL trace.

## Success criteria

- With INVESTIGATE on (default), a task with a matching active atom produces a PLAN prompt
  containing the rendered oracle block.
- No regression to INVESTIGATE's own per-step retrieval behaviour.
- New test passes; existing pipeline/oracle tests stay green.
