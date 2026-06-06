# Intent: knowledge-oracle bank scaling

**Date:** 2026-06-06
**Status:** approved

## Objective
At the current scale (6 atoms, `ORACLE_TOPN=10`), the embedding machinery is dead weight:
the cosine stage returns every active atom because the bank is smaller than top-N, so vectors
filter nothing — only the LLM re-rank actually selects. Meanwhile every task re-embeds all
atoms + the query (no persisted cache), the bank cannot grow without hand-editing
`atoms.yaml`, and `nomic-embed-text` is called without the task prefixes it requires.

Scale the bank now to make vector retrieval genuinely functional. Three converging drivers:
- **(a)** raise overall benchmark score (baseline 32.32%) — bank as cross-task knowledge transfer;
- **(b)** remove manual labour — auto distill+promote instead of hand-writing atoms;
- **(c)** prove vector-retrieval actually works in this agent (currently unexercised).

## Desired Outcomes
- Bank grows to ~50–200 active atoms (from 6) without manual yaml editing.
- Cosine stage actually filters (top-N < bank size); discards visible in logs.
- Redundant embed calls eliminated: each atom embedded once, then served from cache
  (`embedding_hash` persisted in yaml).
- Benchmark score rises vs baseline 32.32% on a full run.
- Every distilled atom passes a validation gate before promotion (no garbage in the bank).

## Health Metrics
- **Fail-safe oracle** — pipeline never crashes due to oracle (existing try/except preserved).
- **LLM call budget per task** stays at 1/2/7 — distill/re-rank must not inflate the hot path
  (auto-distill stays opt-in, post-LEARN, off the hot path).
- **Already-green tasks** (t01, t51 = 1.0) must not regress from a new bad atom in the bank.
- **Run wall-clock** (~3h/run) must not grow from extra embed calls — cache should reduce it.
- **Prompt-engineering rule** — task-specific knowledge flows only through atoms/LEARN,
  never into `data/prompts/`.

**Hard requirement:** promote-validation MUST exclude regression of green tasks. An atom does
not become `active` until proven not to break already-solved tasks.

## Strategic Context
- Interacts with: `pipeline.py` (retrieve→codegen, distill after LEARN), DESIGN phase
  (new knowledge injection point), LEARN mechanism (source of distilled rules), Ollama
  embeddings endpoint, grader-harness (source of truth for promote-validation — requires
  running the task).
- Priority trade-off: **trust** — atom quality over everything. 20 verified atoms beat 200
  noisy ones. Promote is strict; a noisy atom is expensive on every future run.

## Constraints
### Steering (behavioral guidance)
- Atom = reusable method/fact, stripped of run-specific values (ids, paths, skus, amounts) —
  distill already does this cleaning.
- Keep top-N below bank size so cosine genuinely filters.
- Cosine relevance floor: an atom below the floor is not injected even within top-k.

### Hard (architectural enforcement)
- Oracle never crashes the pipeline (existing try/except preserved).
- Task-specific knowledge only in atoms/LEARN, never in `data/prompts/`.
- A candidate (`status: candidate`) becomes `active` only via promote-validation with a
  regression gate (green tasks must not break).
- nomic task prefixes: `search_document:` for atom content, `search_query:` for the query —
  asymmetric retrieval degrades without them.
- Embedding cache keyed by `content_hash`, persisted into the `embedding_hash` yaml field.
- Two-phase lifecycle: distill writes `candidate` (never active); promote is a separate step.

## Autonomy Zones
- **Full autonomy** (reversible, low risk): embedding cache fix, nomic prefixes, cosine floor,
  DESIGN-phase injection, lowering `ORACLE_TOPN`. Pure code, test-covered. Also **full-auto
  promote** candidate→active — the regression gate is the trust guarantee, no human in the loop.
- **Guarded** (log + threshold): auto-distill of a candidate after LEARN — writes `candidate`,
  logs, stays inactive.
- **Proposal-first** (needs approval): none.
- **No autonomy** (human only): editing `data/prompts/`, deleting existing validated atoms.

## Stop Rules
- **Halt if:** promote-validation breaks any green task → atom stays `candidate`, escalate.
- **Escalate if:** bank fails to grow over N runs (distill yields garbage) OR score drops vs baseline.
- **Done when:** cache + prefixes + floor + DESIGN-injection implemented and tested; the
  distill→candidate→promote loop works end-to-end; ≥1 distilled atom passes the regression gate
  and raises or holds the score.
