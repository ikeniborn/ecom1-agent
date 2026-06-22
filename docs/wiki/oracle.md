# Oracle

The knowledge oracle is a bank of validated, reusable coding-knowledge atoms with two-stage semantic retrieval. Atoms are injected into the PLAN prompt, distilled from working plans, and promoted to `active` only after grader validation. See [[architecture]], [[pipeline]].

## Atom Model

An atom is a reusable, run-agnostic piece of coding knowledge. The `Atom` dataclass (`agent/oracle_atoms.py:11`) carries `id`, `description`, `domain` tags, `content` (the general method/fact), provenance (`source`, `validated_by`, `validated_at`), `status` (`active` | `candidate`), and `polarity` (`method` | `anti_pattern`, default `method`).

`polarity` records whether an atom is a method to apply or a failure cause to avoid. It defaults to `method`, so pre-existing atoms load unchanged; `load_atoms` reads it via `d.get("polarity") or "method"` and `save_atoms` persists it automatically through `asdict`.

`source_task` records the task an atom was distilled from — the promote gate uses it. `embedding_hash` is a SHA-256 of `content` (`content_hash`, `agent/oracle_atoms.py:26`) and keys the persisted vector cache. `load_atoms`/`save_atoms` handle YAML round-tripping; `extra` is dropped on save.

## Atom Store

Validated and candidate atoms live in `data/oracle/atoms.yaml`, the default store path (`agent/oracle.py:13`). It ships seeded with generic, re-seed-safe `method` atoms (probe-then-refine lookup, normalize free-text filter, read-governing-doc-before-filter), all `validated_by: manual`, `status: active`. Vectors are cached alongside it in `data/oracle/embeddings.json`. See [[data-files]].

`KnowledgeOracle.__init__` (`agent/oracle.py:27`) loads atoms via `load_atoms`, resolves the embed model from `ECOM_MODEL_EMBED` (default `nomic-embed-text`), and loads the persisted per-content vector cache. The cache is keyed by `content_hash`; a corrupt or missing file silently rebuilds (`_load_vec_cache`, `agent/oracle.py:35`). Saves are best-effort and never raise.

## Two-Stage Retrieval

`retrieve()` (`agent/oracle.py:90`) is the entry point: stage-1 cosine top-N over embeddings narrows the active bank, then stage-2 LLM re-rank selects the final atoms. `ECOM_ORACLE_ENABLED=0` short-circuits to an empty list.

Flow: `k = ORACLE_K` (default 4), `topn = ORACLE_TOPN` (default 10). `_cosine_topn` produces candidates; if embedding fails entirely, it falls back to `_tag_fallback` (lexical overlap of `domain`/`description` against the query). With no candidates, returns `[]`. When `rank_fn is None` or `ECOM_ORACLE_RANK_ENABLED=0`, it returns the cosine top-k directly; otherwise it re-ranks. Any re-rank exception degrades gracefully to `cands[:k]`.

## Stage-1: Cosine Top-N

`_cosine_topn` (`agent/oracle.py:63`) embeds the query (`prefix="search_query"`) and every active atom (`prefix="search_document"`, cached by content hash), scores them with cosine similarity, and keeps the top-N.

`ECOM_ORACLE_FLOOR` (default 0.5) is a hard cutoff: any candidate scoring below the floor is discarded (logged at `ECOM_LOG_LEVEL=DEBUG`). Only `status == "active"` atoms are considered (`_active`, `agent/oracle.py:51`) — plus any atom whose id appears in `ECOM_ORACLE_FORCE_ACTIVE`, a comma-separated transient seam that makes one freshly-distilled `candidate` retrievable during efficacy validation without mutating its persisted status (see [[oracle#Efficacy Validation via Full Run]]). `_cosine` (`agent/oracle.py:17`) returns 0.0 for empty/zero-norm vectors.

## Stage-2: LLM Re-rank

`llm_rerank` (`agent/oracle_rank.py:15`) asks an LLM which cosine candidates are relevant to the task. It renders an `id: description` catalog, requests `{"keep": [ids]}` (most relevant first, at most `k`), and maps the returned ids back to atoms — preserving the model's order and silently dropping unknown ids.

The re-rank model is `ECOM_MODEL_RANK` → `ECOM_MODEL` (`agent/oracle_rank.py:19`). This is a fast-tier phase (see [[llm]]). It is wired in as the `"default"` `rank_fn` and is bypassed when `ECOM_ORACLE_RANK_ENABLED=0`.

## Atom Injection into PLAN

Retrieved atoms are rendered into the PLAN prompt by `build_oracle_block` (`agent/oracle_atoms.py:59`), split by `polarity`: `method` atoms under `## VALIDATED KNOWLEDGE — APPLY (verified methods)` and `anti_pattern` atoms under `## ANTI-PATTERNS — AVOID (known failure causes)`, one bullet per atom as `(domain tags) content`. An empty list yields an empty string.

In the single Plan-IR pipeline, atoms flow into PLAN as the `oracle_atoms` input (`reason.run_plan`). There is no separate CODEGEN phase — this block is the injection point. See [[pipeline]].

## Distill

`distill()` (`agent/oracle.py:167`) generalizes a working run into an atom. It feeds the design intent, error, and script (truncated to 4000 chars) to an LLM with a system prompt that strips all run-specific values (ids, paths, skus, amounts) and returns `{id, description, domain, content}` JSON.

A non-dict response or one with empty `content` yields `None`. Otherwise it builds an `Atom` with `source="distilled"`, `embedding_hash=content_hash(content)`, the originating `source_task`, and the caller-supplied `status` and `polarity` (default `candidate`/`method`), then appends and persists it via `add_candidate` (`agent/oracle.py:121`). The distill phase resolves through the reason tier (`_resolve_model_for_phase("distill", …)`). The live callers are `pipeline.distill_from_grader` (end-of-run, `status="active"`), the offline teach bridge (`scripts/harness_to_oracle.py`), and the offline `promote.py` gate — there is no in-pipeline success-path distill (the `ECOM_ORACLE_DISTILL` path was removed in Phase 0).

## End-of-run self-fill (distill_from_grader)

`distill_from_grader(task_id, score, score_detail)` (`agent/pipeline.py`) self-fills the bank from the grader score returned by SubmitRun — not a live grader round-trip. A pass (`score >= 1.0`) distills a `method` atom; a fail distills an `anti_pattern` atom whose content steers PLAN away next run. Both are written with `status="active"` directly. It is gated only by `ECOM_ORACLE_ENABLED`, reads the persisted `IntentSpec`+`PlanIR` ([[data-files]]), no-ops when artifacts are absent, and never raises. `main.py` calls it for every task (pass and fail). See [[pipeline#End-of-run self-fill]].

## Inline Validation via Grader

`validate_atom_via_grader` (`agent/oracle_validate.py:55`) re-runs a plan on a fresh `StartRun` and reports whether the real grader score meets `min_score` (default 1.0). It is best-effort — any failure (no live grader, replay error) returns `False`, leaving the atom a candidate, and never raises.

It builds an answer via `interpret(plan, intent, vm, facts=None)` and runs it through `grade_candidate` (`agent/oracle_validate.py:27`), which serializes harness trials: start the target trial, answer it, then `end_trial` immediately to lock DONE-with-answer before later trials start. `parse_score` extracts the score from the matching trial. Known limitation: plans whose predicates read `$_facts.*` degrade on the fresh facts-less VM and may under-promote (conservative by design). This function is retained for the offline `promote.py` gate; the in-pipeline `ECOM_ORACLE_VALIDATE_INLINE` success-path caller that drove it was removed in Phase 0.

## Efficacy Validation via Full Run

`validate_atom_via_full_run(atom, task_id, min_score=1.0)` (`agent/oracle_validate.py:109`) is a stronger efficacy gate than `validate_atom_via_grader`: instead of replaying a fixed plan, it re-runs the source task **end-to-end through the whole agent** with the candidate atom force-active, so the atom must actually help the live PLAN reach a grader score of `min_score`. Best-effort — any failure returns `False`, leaving the atom a candidate; it never raises. It is the default `validate_fn` of the teach bridge (see [[harness-to-oracle#Validation via full run]]).

`grade_full_run(task_id, force_active_id)` (`agent/oracle_validate.py:78`) drives it: a fresh `StartRun`, then for the matching trial it sets `ECOM_ORACLE_FORCE_ACTIVE=force_active_id` around a full `run_agent(...)` call (cleared in a `finally`, even on error) and returns `parse_score`. Unlike `grade_candidate` the agent answers the VM itself, so there is no `vm.answer` here. `run_agent` is imported lazily to break the `orchestrator → pipeline → oracle_validate` import cycle. The force-active env is read by `_active` (see [[oracle#Stage-1: Cosine Top-N]]), making the just-persisted candidate retrievable into PLAN for exactly that one run.

## Promote (Inline)

`promote()` (`agent/oracle.py:184`) flips a candidate atom to `active`, stamping `validated_by` and `validated_at`, then persists the bank. It is called by the offline `promote.py` gate and the teach bridge after validation confirms an improvement (distill → validate → promote). The earlier in-pipeline success-path promotion was removed in Phase 0; the in-run self-fill now happens via `distill_from_grader`, which writes `active` atoms directly without a separate promote step. See [[oracle#End-of-run self-fill (distill_from_grader)]].

## Promote (Offline Gate)

`agent/promote.py` is a separate offline distill→candidate→promote pass — score is only visible post-`SubmitRun`, so this never runs on production tasks. `run_promote` (`agent/promote.py:50`) iterates candidates, runs a baseline and a candidate-active pass over `source ∪ green-suite`, and applies `promote_decision`.

`promote_decision` (`agent/promote.py:28`) returns `halt` if any green-suite task regressed below its reference, `promote` if green held AND the source task improved over baseline, else `no_improve`. Only `promote` calls `oracle.promote`; any run error leaves the candidate untouched (fail-safe). `load_green_suite` reads `data/oracle/green_suite.yaml` and raises if missing — the gate must never silently proceed. A warning fires when `active > 10` but `ORACLE_TOPN >= active` (top-N must drop below the bank for cosine to filter).

## Teach bridge from hot lint checks

`scripts/harness_to_oracle.py` is a separate offline pass that seeds the bank from the lint registry rather than from working plans: it distils a `method` atom from each frequently-firing check, validates it with a full grader run, and promotes on score 1.0. See [[harness-to-oracle]], [[harness]].

## Environment Knobs

The `ORACLE_*` family tunes retrieval. All are read at call time from the environment. See the full table in [[data-files]]. (The in-pipeline distill/promote knobs `ECOM_ORACLE_DISTILL` and `ECOM_ORACLE_VALIDATE_INLINE` were removed in Phase 0 along with the success-path distill they gated — they are no longer read anywhere.)

| Var | Default | Effect |
|-----|---------|--------|
| `ECOM_ORACLE_ENABLED` | 1 | `0` → `retrieve()` returns `[]` |
| `ECOM_ORACLE_TOPN` | 10 | Stage-1 cosine candidate count |
| `ECOM_ORACLE_K` | 4 | Final atoms returned after re-rank |
| `ECOM_ORACLE_FLOOR` | 0.5 | Min cosine; below-floor candidates discarded |
| `ECOM_ORACLE_RANK_ENABLED` | 1 | `0` → skip LLM re-rank, use cosine top-k |
| `ECOM_ORACLE_FORCE_ACTIVE` | (unset) | Comma-separated atom ids forced retrievable in `_active` for one efficacy run |
| `ECOM_MODEL_EMBED` | nomic-embed-text | Embedding model id |
| `ECOM_MODEL_RANK` | `ECOM_MODEL` | Stage-2 re-rank model |
