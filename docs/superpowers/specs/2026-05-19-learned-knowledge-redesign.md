# Spec: Learned Knowledge Redesign

**Date:** 2026-05-19  
**Status:** approved  
**Topic:** Replace data/rules + data/security with permanent per-task knowledge base in data/learned

---

## Problem

Current architecture splits knowledge across three locations:

- `data/rules/*.yaml` — global SQL planning rules (verified, shared across tasks)
- `data/security/*.yaml` — global security gates (hard blocks)
- `data/learned/{task_id}.yaml` — per-task transient rules (cleared on success)

This creates duplication, drift between global and per-task knowledge, and requires a separate offline optimization pipeline (`propose_optimizations.py` + `eval_log`) to promote learned knowledge into rules.

---

## Goals

1. Single knowledge store per task — `data/learned/{task_id}.yaml`
2. Permanent accumulation — never cleared, grows across runs and cycles
3. LLM-driven consolidation — dedup + contradiction resolution on every rule addition
4. Rules have lifecycle status (active/inactive) for audit trail without data loss
5. Simpler pipeline — no eval_log, no evaluator, no offline optimization script

---

## Data Schema: `data/learned/{task_id}.yaml`

```yaml
task_id: t01
entries:
  - id: r001
    content: "Always SELECT sku alongside product.name in COUNT queries"
    status: active          # active | inactive
    source: learn           # learn | manual | security
    created: "2026-05-19"
    reasoning: "COUNT query returned no product.name — SKU needed for grounding_refs"
    deactivated_reason: null

  - id: r002
    content: "Use equality not LIKE for exact product codes"
    status: inactive
    source: learn
    created: "2026-05-18"
    reasoning: "Equality used initially but missed variants"
    deactivated_reason: "Superseded by r003: LIKE pattern captures full range"
```

**ID generation:** `r` + zero-padded 3-digit counter, monotonically increasing, never reused.

**Loading:** only `status: active` entries. Returns `list[str]` of `content` values.

**Invariants:**
- File never deleted (no `clear_learned_ctx()`)
- `inactive` entries retained forever for audit trail
- Manual deactivation: human sets `status: inactive` + `deactivated_reason` directly in YAML

---

## LEARN Phase: Extended LearnOutput

`learn.md` is extended to include consolidation logic. The LEARN LLM call receives existing active rules and returns an extended output:

**Input to LLM (added to user message):**
```
EXISTING_RULES:
  - id: r001
    content: "Always SELECT sku..."
  - id: r002
    content: "Use LIKE for..."
```

**Extended `LearnOutput` JSON:**
```json
{
  "rule_content": "Always include ORDER BY when using LIMIT",
  "reasoning": "Query returned arbitrary row — deterministic ordering required",
  "agents_md_anchor": null,
  "compacted_ctx": null,
  "deactivate": ["r002"],
  "deactivate_reason": "New rule supersedes — more specific ordering constraint",
  "skip": false,
  "skip_reason": null
}
```

**Consolidation logic in `_run_learn()`:**
1. Existing LLM call with extended `learn.md` → extended `LearnOutput`
2. If `skip=true`: log reason, return (no write)
3. If `skip=false`:
   - Append new entry with next available id, `status=active`, `source=learn`
   - For each id in `deactivate`: set `status=inactive`, `deactivated_reason=...`
   - Write YAML
4. Update in-memory `learn_ctx` to reflect active entries after mutation

---

## Pipeline Changes (`pipeline.py`)

**Removed:**
- `_rules_loader_cache`, `_get_rules_loader()`
- `_security_gates_cache`, `_get_security_gates()`
- `clear_learned_ctx()` call on success
- `EVAL_ENABLED` branch and evaluator invocation
- All imports: `RulesLoader`, `load_security_gates`

**Changed:**
- `load_learned_ctx(task_id)` → reads only `status: active` entries → `list[str]`
- `save_learned_ctx()` renamed to `_apply_learn_diff()` — applies diff (add + deactivate)
- `_run_learn()` → receives `existing_entries: list[dict]` (id + content of active rules) → passes to LLM → applies diff

**On success:** pipeline completes normally. No file deletion. `learn_ctx` retains session rules — they are already persisted from each `_run_learn()` call.

**On exhaustion:** same as current — all accumulated rules already persisted per-cycle.

---

## Assembler Changes (`prompt_assembler.py`)

**Removed sections:**
- `## RULES` — RulesLoader calls deleted
- `## SECURITY` — security gates calls deleted
- `## PROMPT_BLOCKS` — `load_task_blocks()` deleted

**Remaining sections (in priority order):**
```
## LEARNED      ← active content from data/learned/{task_id}.yaml
## VAULT        ← agents_md from VM (unchanged)
## SCHEMA_DIGEST + DB_SCHEMA  ← from prephase (unchanged)
## AGENT_CONTEXT ← metadata (unchanged)
```

`assembler.md` updated to reflect new section list (no RULES/SECURITY/PROMPT_BLOCKS).

---

## Deleted Artifacts

| Artifact | Action |
|----------|--------|
| `data/rules/*.yaml` | Delete directory |
| `data/security/*.yaml` | Delete directory |
| `data/config/task_blocks.yaml` | Delete (already staged as deleted) |
| `data/eval_log.jsonl` | Delete |
| `data/.eval_optimizations_processed` | Delete |
| `data/prompts/pipeline_evaluator.md` | Delete |
| `scripts/propose_optimizations.py` | Delete |
| `scripts/.graphify/` | Delete (already staged) |
| `MODEL_EVALUATOR` env var | Remove from `.env.example`, docs |
| `EVAL_ENABLED` env var | Remove from `.env.example`, docs |

---

## Updated Prompts (`data/prompts/`)

All task-specific content (SQL, ECOM, SKU references) removed. Prompts describe only:
- Agent role and pipeline phase purpose
- Tool interaction rules and output format
- Phase-specific constraints (e.g., SDD must produce structured plan)

| File | Action |
|------|--------|
| `assembler.md` | Update — remove RULES/SECURITY/PROMPT_BLOCKS section descriptions |
| `sdd.md` | Clean — remove SQL/ECOM-specific hints |
| `learn.md` | Extend — add consolidation logic (deactivate/skip fields) |
| `tdd.md` | Clean — remove task-specific references |
| `answer.md` | Clean — remove task-specific references |
| `pipeline_evaluator.md` | Delete |

---

## Deleted Env Vars

| Var | Removed from |
|-----|-------------|
| `MODEL_EVALUATOR` | `.env.example`, `.secrets.example`, `CLAUDE.md` |
| `EVAL_ENABLED` | `.env.example`, `CLAUDE.md` |

---

## Testing Impact

- `reset_pipeline_caches()` fixture in `tests/conftest.py`: remove `_rules_loader_cache` and `_security_gates_cache` resets (no longer exist)
- Tests for `propose_optimizations.py`: delete
- Tests for `RulesLoader`, `load_security_gates`: delete or adapt
- New tests: `_apply_learn_diff()` logic — add/deactivate/skip cases
- New tests: `load_learned_ctx()` — only active entries returned

---

## Migration Notes

- Existing `data/learned/{task_id}.yaml` files (current flat `list[str]` format) must be migrated to new schema. Migration script: read existing list, convert each string to entry with `id=rNNN`, `status=active`, `source=learn`, `created=<today>`, `reasoning=""`, `deactivated_reason=null`.
- No rollback path for deleted rules — archive `data/rules/` and `data/security/` in git history before deletion.
