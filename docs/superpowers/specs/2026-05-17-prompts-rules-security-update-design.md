# Design: Prompts / Rules / Security Update (eval_log analysis)

**Date:** 2026-05-17  
**Source:** `docs/analysis/eval_log_report.md` (134 eval entries)  
**Approach:** Full package — 8 yaml rules + 2 security gates + 3 prompt patches, single commit.

---

## 1. Scope

Three delivery areas, all derived from eval_log failure patterns:

| Area | Files | Count |
|------|-------|-------|
| `data/rules/` | new yaml rule files | 8 |
| `data/security/` | new yaml security gate files | 2 |
| `data/prompts/` | patches to existing md files | 3 |

No code changes. No new prompt files. `core.md` not created — vague-task gate goes into `sdd.md`; >5-cycle force-OUTCOME_OK is pipeline/env-var concern, not a prompt.

---

## 2. data/rules/ — 8 new yaml files

Format (from `.worktrees/mock-validation/data/rules/sql-001.yaml`):
```yaml
id: <id>
phase: sql_plan
content: '<rule text>'
created: '2026-05-17'
source: eval
eval_score: 8.0
verified: true
raw_recommendation: '<original recommendation>'
```

All rules use `phase: sql_plan` — assembler queries only this phase via `get_rules_markdown(phase="sql_plan")`.

### sql-015.yaml — count-answer-message-format
**Scoped to product count queries.**  
Content: For COUNT queries on `products` or `product_properties`, the answer message MUST include at least one value from `products.name` alongside the `<COUNT:n>` token. Bare `<COUNT:3>` without a product name is forbidden.

### sql-016.yaml — learn-loop-cap
Content: If the same topic (by keyword overlap with existing learn_ctx entries) has appeared ≥2 times in `learn_ctx`, skip LEARN phase and force an answer with available data instead of adding another rule.

### sql-017.yaml — kinds-table-skip
Content: Never filter `kinds.name` in SQL — the `kinds` table has no documented columns in SCHEMA DIGEST. Filter on `products.name LIKE '%<term>%'` directly.

### sql-031.yaml — column-existence
Content: Before emitting any WHERE clause predicate, verify the referenced column exists in SCHEMA DIGEST for that table. Unknown column → add a discovery query step instead, or emit `{"error":"PLAN_ABORTED"}`.

### sql-032.yaml — identical-retry
Content: Never retry SQL identical to a prior failed cycle query (whitespace- and case-insensitive comparison). Identical retry → emit `{"error":"PLAN_ABORTED_IDENTICAL"}` and diagnose root cause instead.

### sql-sku-required.yaml — sku-in-projection
Content: Every SELECT from `products` or `product_properties` MUST include `sku` in the projection. Exception: aggregate-only queries (`COUNT(*)`, `SUM`, `AVG`) where no row-level SKU is needed.

### sql-retry-divergence.yaml — structural-divergence-after-learn
Content: After a LEARN cycle, the new plan MUST structurally differ from all prior plans for this task — not merely cosmetic whitespace or alias changes. Structurally identical plan after LEARN is a forbidden retry.

### sql-count-with-sample.yaml — count-with-sample
**Scoped to product count queries.**  
Content: For COUNT queries on `products` or `product_properties`, always pair with a sample query: `SELECT sku, path FROM <table> WHERE <identical-filter> LIMIT 5`. COUNT alone returns no `path` column and cannot populate `grounding_refs`.

---

## 3. data/security/ — 2 new yaml files

Format: `id`, `message`, `verified: true`, optionally `pattern` (regex on SQL strings).  
Assembler includes all gates in `## SECURITY` of `unified_context` as `- [id] message`.

### sec-write-detect-001.yaml — write-operation-guard
- **Runtime:** `pattern` matching SQL mutation keywords (`INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|REPLACE`) — defense-in-depth against mutations slipping through SDD.
- **LLM context:** message instructs that task with bare imperative verbs (checkout, submit basket, place order) → respond `OUTCOME_NONE_UNSUPPORTED`.

### sec-capability-keys.yaml — tech-capability-attribute-guard
- **Runtime:** none (no `pattern` or `check` — context-only gate).
- **LLM context:** message instructs that task containing tech-capability terms (`app`, `wifi`, `iot`, `schedul`) → do NOT plan `product_properties` queries for those keys; answer directly that the physical attribute is absent from the catalogue.

---

## 4. data/prompts/ — 3 file patches

### sdd.md — 5 additions

All additions are new named sections inserted before `## ACCUMULATED RULES`.

**4.1 Column Existence Pre-Flight (MANDATORY)**  
Before emitting any step with a WHERE clause, verify every referenced column/table exists in SCHEMA DIGEST. If column absent → replace predicate with a discovery query (`SELECT DISTINCT <col>...`) or emit `{"error":"PLAN_ABORTED","reasoning":"column <x> not in schema digest"}`.

**4.2 Identical Plan Guard**  
After the Retry Divergence section: if new plan is identical to any prior plan for this task (whitespace- and case-insensitive) → emit `{"error":"PLAN_ABORTED_IDENTICAL","reasoning":"..."}`. Do not repeat.

**4.3 Zero-Column Table Skip**  
If SCHEMA DIGEST shows 0 columns for a table → never reference that table in SQL. Use `products.name LIKE '%<term>%'` as fallback. Applies to `kinds` table specifically.

**4.4 Discovery Fallback At Plan-Time**  
If any plan step depends on the result of a prior step that may return 0 rows, add an explicit fallback step in the plan for the empty-result branch (e.g., broader LIKE probe or alternative column search).

**4.5 Vague Task Gate (MANDATORY FIRST CHECK)**  
Inserted immediately after the existing Prompt Injection check: if `task_text` is fewer than 10 characters, or matches `/^task$|^test$/i`, emit `{"error":"OUTCOME_NONE_CLARIFICATION","reasoning":"task text too vague to plan"}` before any other processing.

### answer.md — 1 addition

Append to the existing **Clarification guard** section:

> Empty SQL result caused by schema-mismatch (unknown column, wrong table name, absent key) is NOT task ambiguity. Correct outcome: `OUTCOME_OK` with message stating what was searched and that no matching records exist. `OUTCOME_NONE_CLARIFICATION` is forbidden for unambiguous tasks that returned empty SQL results.

### learn.md — 1 addition

New section **Learn Loop Cap** inserted before `## Loop Prevention`:

> If the current failure topic (by keyword overlap with existing entries) already appears ≥2 times in `learn_ctx`, do NOT produce another LEARN rule. Instead set `rule_content` to `"Loop cap reached — topic already in learn_ctx ≥2 times"` and `conclusion` to name the repeated topic. Pipeline will skip further LEARN cycles for this topic and proceed to answer with available data.

---

## 5. What is NOT in scope

- No changes to `pipeline.py`, `sql_security.py`, or any Python code.
- No new prompt files (`core.md` not created).
- `learn-001.yaml` NOT hand-crafted — LEARN quality rules must emerge via eval_log → `propose_optimizations.py` pipeline.
- >5-cycle force-OUTCOME_OK: already a pipeline/env-var concern (`MAX_STEPS`), not a prompt concern.
- Existing prompt content not modified beyond the specified additions — surgical patches only.

---

## 6. Acceptance criteria

- `data/rules/` contains exactly 8 new `.yaml` files, all with `verified: true` and `phase: sql_plan`.
- `data/security/` contains exactly 2 new `.yaml` files, both with `verified: true`.
- `sdd.md` gains 5 new named sections; existing sections unchanged.
- `answer.md` Clarification guard section gains 1 paragraph.
- `learn.md` gains 1 new section (Learn Loop Cap).
- All tests pass: `uv run python -m pytest tests/ -v`.
