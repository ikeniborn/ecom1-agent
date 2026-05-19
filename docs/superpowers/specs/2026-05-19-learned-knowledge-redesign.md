---
review:
  spec_hash: "81d0538a886e2a98"
  last_run: "2026-05-19"
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: Updated_Prompts
      section_hash: "f6e2851514c8fd33"
      text: "«Clean — remove SQL/ECOM-specific hints» — нет DoD: по какому критерию файл считается очищённым?"
      verdict: fixed
      verdict_at: "2026-05-19"
    - id: F-002
      phase: clarity
      severity: WARNING
      section: LEARN_Phase
      section_hash: "f2e31e3031c0a8b0"
      text: "Шаг 4 «Update in-memory learn_ctx to reflect active entries» — неоднозначно: полная перезагрузка из файла, diff или только append?"
      verdict: fixed
      verdict_at: "2026-05-19"
    - id: F-003
      phase: clarity
      severity: INFO
      section: Migration_Notes
      section_hash: "b63fd2739797103f"
      text: "Migration script описан словесно, но не ясно — это обязательный deliverable или описание ручных шагов?"
      verdict: fixed
      verdict_at: "2026-05-19"
    - id: F-004
      phase: clarity
      severity: INFO
      section: LEARN_Phase
      section_hash: "f2e31e3031c0a8b0"
      text: "existing_entries в _run_learn(): источник не указан — свежая загрузка из файла или текущий in-memory learn_ctx?"
      verdict: fixed
      verdict_at: "2026-05-19"
  section_hashes:
    Problem: "5efbed197cb7dbce"
    Goals: "3996e9ec38880c41"
    Data_Schema: "f9b647f6a7fe681f"
    LEARN_Phase: "f2e31e3031c0a8b0"
    Pipeline_Changes: "c06cefd7a6d69c0c"
    Assembler_Changes: "7cdeaa776cf0bbb8"
    Deleted_Artifacts: "97b75982dd2766a9"
    Updated_Prompts: "f6e2851514c8fd33"
    Deleted_Env_Vars: "c97f47bea7bbe04d"
    Testing_Impact: "08f82ee55285da4d"
    Migration_Notes: "b63fd2739797103f"
---

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
4. Update in-memory `learn_ctx`: remove `content` values of deactivated ids, append new `rule_content` if `action=add`. Do not reload from file — apply diff to current list.

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
- `_run_learn()` → loads `existing_entries: list[dict]` (id + content) fresh from `data/learned/{task_id}.yaml` at call start (not from in-memory `learn_ctx`) → passes to LLM → applies diff

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
| `sdd.md` | Clean — remove SQL/ECOM-specific hints. DoD: no SQL keywords in examples, no domain terms (SKU, product.name, grounding_refs, inventory) |
| `learn.md` | Extend — add consolidation logic (deactivate/skip fields) |
| `tdd.md` | Clean — remove task-specific references. DoD: no SQL keywords in examples, no domain terms |
| `answer.md` | Clean — remove task-specific references. DoD: no SQL keywords in examples, no domain terms |
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

- Existing `data/learned/{task_id}.yaml` files (current flat `list[str]` format) must be migrated to new schema. **Required deliverable:** `scripts/migrate_learned.py` — reads each existing file, converts each string to an entry with `id=rNNN`, `status=active`, `source=learn`, `created=<today>`, `reasoning=""`, `deactivated_reason=null`. Must be run before the first pipeline run after deployment.
- No rollback path for deleted rules — archive `data/rules/` and `data/security/` in git history before deletion.
