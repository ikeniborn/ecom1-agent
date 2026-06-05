# Design: knowledge-oracle (validated knowledge bank with semantic retrieval)

**Date:** 2026-06-05
**Status:** approved
**Intent:** [2026-06-05-knowledge-oracle-intent.md](../intents/2026-06-05-knowledge-oracle-intent.md)

## Problem (from intent)

Per-task LEARN (`data/learned/{task_id}.yaml`) overfits to single-seed values and stalls in
local optima; knowledge is fragmented/duplicated across tasks, invisible to DESIGN, and
crushed by compaction. Empirically confirmed this session: the benchmark re-seeds every
StartRun (fraud device, receipt VAT rate, SKUs, totals all change), so rules pinning concrete
values pass once then break. Replace the per-task dump with a **general bank of validated
knowledge-atoms** retrieved **semantically by task analysis**, augmenting (not replacing) the
per-task store.

## Approach

**A — Sidecar module `agent/oracle.py`** (chosen). Self-contained: `retrieve` / `distill` /
`validate` / `promote`. Clean boundary, does not touch per-task mechanics, reversible
(augmentation), unit-testable in isolation. Atom count is small (tens→hundreds) → in-memory
numpy cosine, no vector DB (faiss/chroma rejected as over-engineering).

Retrieval is two-stage: Ollama embeddings + cosine recall, then a cheap LLM re-rank for
precision. Validation is hybrid: atoms seeded by curation now, confirmed by the grader-oracle
harness before being marked `validated`.

## Components

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `agent/oracle.py` (`KnowledgeOracle`) | load atoms, embed+cache, `retrieve(task_text,k)`, `distill(design,error,script)`, `validate(atom)`, `promote(atom)` | `llm.py` (embed+rank), `numpy` |
| `data/oracle/atoms.yaml` | the atom bank (general, no task_id, no seed values) | — |
| `data/oracle/embeddings.npy` + `index.json` | cached atom embedding vectors, keyed by content hash | numpy |
| `agent/oracle_validate.py` | grader-oracle harness: StartRun → answer candidate → SubmitRun → read score | `bitgn` harness client, `vm_adapter` |

New runtime dependency: `numpy` (add to `pyproject.toml`).

## Atom schema (`data/oracle/atoms.yaml`)

```yaml
- id: sql-no-name-binds
  description: "/bin/sql rejects :name bind params; inline quoted literals in IN()"
  domain: [sql, vm-io]
  content: >
    The /bin/sql tool does not accept :name bind parameters passed as
    args=[sql, 'name=value'] — it returns exit_code 1 'missing named argument'.
    Always inline values as single-quoted SQL string literals inside IN(...).
  source: investigation        # investigation | distilled | verdict
  validated_by: manual         # manual | grader | fidelity
  validated_at: '2026-06-05'
  status: active               # active | candidate
  embedding_hash: <sha256(content)>
```

Rules: atoms are **methods/facts**, never "fix error X in seed Y"; **no hardcoded seed
values** (device/customer ids, SKUs, paths, amounts); `domain` tags drive the hybrid
pre-filter.

## Retrieval flow (two-stage)

1. **Query build:** `task_text` plus a short summary of DESIGN `intent`/`ops` (when available).
2. **Embed:** call the embedding model via Ollama (`/api/embeddings`) → query vector.
3. **Stage 1 (recall):** optional `domain`-tag pre-filter (hybrid), then cosine similarity over
   cached atom vectors → top-N candidates (`ORACLE_TOPN`, default 10).
4. **Stage 2 (precision):** one cheap LLM call (`MODEL_RANK`) ranks the N candidate
   descriptions against the task → keep the final `ORACLE_K` (default 4) atom ids.
5. **Inject:** the k atoms' `content` go into CODEGEN context as a labeled
   `VALIDATED KNOWLEDGE` block, alongside the per-task `learn_ctx`.

Budget note: +1 embedding call and +1 small re-rank call per task (the re-rank sees only N
short descriptions). Net cost ≪ one full pipeline LLM call; documented as an accepted
trade-off against the per-task call budget.

## Lifecycle: validation & distillation

- **Seed (curation):** seed the bank with 4–6 atoms distilled from this session's
  investigation: (1) archived-payment fraud = single-device impossible-travel to identify the
  compromised account, then flag that account's far-from-home payments; (2) `/bin/sql` rejects
  `:name` binds → inline literals; (3) catalogue `price_cents` is ex-VAT (per discounts.md);
  (4) never `vm.read` a directory path; (5) schema facts (payment_transactions +
  customer_accounts.home_*). `source: investigation`.
- **Distill (auto):** after the LEARN consolidation step, `oracle.distill(design, error,
  script)` runs one LLM call that strips seed-specifics from the just-learned rule into a
  general method → new atom with `status: candidate`.
- **Validate (gate):** `oracle_validate` runs the grader-oracle harness — generate a script
  using the atom on a fresh StartRun, submit, read score. `score == 1.0` → `status: active,
  validated_by: grader`; otherwise the atom stays `candidate` (never retrieved into CODEGEN).
- **Promote:** `candidate → active` only after a passing validation.
- **Migrate (one-off):** a script distills existing per-task `data/learned/*.yaml` rules into
  general atoms; dedup by cosine similarity (> threshold → merge).

Only `status: active` atoms are eligible for retrieval.

## Integration points

- `agent/pipeline.py:run_pipeline` — before the CODEGEN loop: `atoms =
  oracle.retrieve(task_text, k)`; pass to codegen. After LEARN consolidation: call
  `oracle.distill(...)`.
- `agent/codegen_v2.py:run_codegen` — accept `oracle_atoms` param; prepend the
  `VALIDATED KNOWLEDGE` block to the context.
- **DESIGN unchanged** — CODEGEN-only per intent (feeding DESIGN is proposal-first, out of
  scope; preserves `tests/test_design.py` F-001 guards).
- `agent/learned_store.py` — untouched (augmentation; per-task store remains the safety net).

## Configuration

### Environment variables (new)

| Var | Purpose | Default |
|-----|---------|---------|
| `ORACLE_ENABLED` | Master toggle; `0` → pipeline behaves exactly as today | `1` |
| `EMBED_MODEL` | Embedding model id (key into `models.json`) | `nomic-embed-text` |
| `EMBED_BASE_URL` | Embeddings endpoint | falls back to `OLLAMA_BASE_URL` |
| `ORACLE_TOPN` | Stage-1 cosine candidate count | `10` |
| `ORACLE_K` | Final atom count after re-rank, injected into CODEGEN | `4` |
| `MODEL_RANK` | Model for the stage-2 re-rank call | falls back to `MODEL` |
| `ORACLE_RANK_ENABLED` | `0` → skip LLM re-rank, use cosine top-k directly | `1` |

These are documented in `CLAUDE.md` (Environment Variables table) and `.env.example` as part
of implementation.

### models.json.example update

Add an embedding-model entry plus a `_fields` note describing the embedding `kind`. Example
entry to document:

```json
"nomic-embed-text": {
  "provider": "ollama",
  "kind": "embedding",
  "_doc": "Embedding model for the knowledge-oracle. Called via Ollama /api/embeddings; returns a dense vector, not chat completions. Used only by agent/oracle.py for atom/query embeddings.",
  "ollama_options": { "num_ctx": 8192 }
}
```

`_fields.kind` is added to the example header: `"kind": "Model role: omit for chat/completion;
'embedding' for vector-embedding models used by the knowledge-oracle"`.

## Error handling

- Ollama embeddings unavailable → fall back to `domain`-tag + keyword retrieval; log a
  warning; never crash the pipeline.
- LLM re-rank fails → return the stage-1 cosine top-k directly.
- Empty / missing atom bank → `retrieve` returns `[]`; pipeline runs exactly as today.
- Embedding cache stale (atom `content` hash changed) → recompute that atom's vector only.
- `oracle_validate` network/timeout error → leave the atom as `candidate`; do not promote.

## Testing

- **Unit:** atom YAML load/parse; cosine ranking order; cache invalidation on content change;
  hybrid fallback when embeddings are down; `distill` strips a seeded value from a sample rule.
- **Integration:** `oracle.retrieve` returns the fraud atom for a t38-style query and the
  ex-VAT/bind atoms for a t51-style query (against the seeded bank).
- **Validation smoke:** `oracle_validate` returns a numeric score for a known-good candidate
  on one StartRun.
- **Regression:** `pytest tests/` green (incl. `tests/test_design.py` F-001); `t01` stays
  `1.0`.
- **Done-when (acceptance):** `t01`, `t38`, `t51` each reach score `1.0` across **≥2
  independently re-seeded runs**.

## Out of scope

- Feeding the oracle into DESIGN (proposal-first; separate spec).
- Removing the per-task LEARN store or the compaction path (kept until the oracle is proven).
- A persistent vector database (numpy in-memory is sufficient at this scale).
