# Prompts / Rules / Security Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `data/rules/` (8 yaml) and `data/security/` (2 yaml) from eval_log findings, and patch three prompt files with five additions to `sdd.md`, one to `answer.md`, one to `learn.md`.

**Architecture:** Pure data-file changes — no Python code modified. Assembler picks up rules via `RulesLoader.get_rules_markdown(phase="sql_plan")` and security gates via `load_security_gates()`; both are already wired into `prompt_assembler.py:_build_sources()`. Prompt md files are read at runtime by `prompt.py:load_prompt()`.

**Tech Stack:** Python/pytest (tests), yaml (rules + security), markdown (prompts). Run tests with `uv run python -m pytest tests/ -v`.

---

## File Map

| Action | Path |
|--------|------|
| Create | `tests/test_data_files.py` |
| Create | `data/rules/sql-015.yaml` |
| Create | `data/rules/sql-016.yaml` |
| Create | `data/rules/sql-017.yaml` |
| Create | `data/rules/sql-031.yaml` |
| Create | `data/rules/sql-032.yaml` |
| Create | `data/rules/sql-sku-required.yaml` |
| Create | `data/rules/sql-retry-divergence.yaml` |
| Create | `data/rules/sql-count-with-sample.yaml` |
| Create | `data/security/sec-write-detect-001.yaml` |
| Create | `data/security/sec-capability-keys.yaml` |
| Modify | `data/prompts/sdd.md` — 5 new sections |
| Modify | `data/prompts/answer.md` — 1 paragraph in Clarification guard |
| Modify | `data/prompts/learn.md` — 1 new section |

---

## Task 1: Test infrastructure

**Files:**
- Create: `tests/test_data_files.py`

- [ ] **Step 1: Write the failing test file**

```python
# tests/test_data_files.py
"""Content-verification tests for data/ directory files."""
from pathlib import Path
import yaml
import pytest

DATA_DIR = Path(__file__).parent.parent / "data"
RULES_DIR = DATA_DIR / "rules"
SECURITY_DIR = DATA_DIR / "security"
PROMPTS_DIR = DATA_DIR / "prompts"

EXPECTED_RULE_IDS = {
    "sql-015", "sql-016", "sql-017", "sql-031", "sql-032",
    "sql-sku-required", "sql-retry-divergence", "sql-count-with-sample",
}


def _load_all_rules() -> dict:
    rules = {}
    for f in RULES_DIR.glob("*.yaml"):
        r = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(r, dict):
            rules[r["id"]] = r
    return rules


# ── Rules ────────────────────────────────────────────────────────────────────

def test_all_expected_rule_ids_present():
    loaded = _load_all_rules()
    missing = EXPECTED_RULE_IDS - set(loaded.keys())
    assert not missing, f"Missing rule IDs: {missing}"


def test_all_rules_verified_and_phase_sql_plan():
    loaded = _load_all_rules()
    for rule_id, rule in loaded.items():
        assert rule.get("verified") is True, f"{rule_id}: verified != True"
        assert rule.get("phase") == "sql_plan", f"{rule_id}: phase != sql_plan"
        assert rule.get("content"), f"{rule_id}: content is empty"


def test_rules_loader_returns_all_verified():
    from agent.rules_loader import RulesLoader
    loader = RulesLoader(RULES_DIR)
    md = loader.get_rules_markdown(phase="sql_plan", verified_only=True)
    for rule_id in EXPECTED_RULE_IDS:
        rule = _load_all_rules()[rule_id]
        # Each rule's content snippet should appear in assembled markdown
        first_20 = rule["content"][:20]
        assert first_20 in md, f"Rule {rule_id} content not in assembled markdown"


def test_sql015_scoped_to_products():
    rules = _load_all_rules()
    content = rules["sql-015"]["content"]
    assert "products" in content
    assert "COUNT" in content
    assert "name" in content


def test_sql017_kinds_table_and_products_fallback():
    rules = _load_all_rules()
    content = rules["sql-017"]["content"]
    assert "kinds" in content
    assert "products.name" in content


def test_sql_count_with_sample_scoped_to_products():
    rules = _load_all_rules()
    content = rules["sql-count-with-sample"]["content"]
    assert "products" in content
    assert "sku" in content
    assert "path" in content


# ── Security gates ───────────────────────────────────────────────────────────

def test_security_gates_load_both_files():
    from agent.sql_security import load_security_gates
    gates = load_security_gates(SECURITY_DIR)
    ids = {g["id"] for g in gates}
    assert "sec-write-detect-001" in ids
    assert "sec-capability-keys" in ids


def test_write_detect_pattern_blocks_sql_mutations():
    from agent.sql_security import check_sql_queries, load_security_gates
    gates = load_security_gates(SECURITY_DIR)
    mutations = [
        "INSERT INTO products VALUES (1)",
        "DELETE FROM products WHERE sku='X'",
        "DROP TABLE products",
        "UPDATE products SET name='X' WHERE sku='Y'",
        "TRUNCATE TABLE products",
        "ALTER TABLE products ADD COLUMN x TEXT",
    ]
    for sql in mutations:
        err = check_sql_queries([sql], gates)
        assert err is not None, f"Mutation not blocked: {sql}"


def test_write_detect_does_not_block_select():
    from agent.sql_security import check_sql_queries, load_security_gates
    gates = [g for g in load_security_gates(SECURITY_DIR) if g["id"] == "sec-write-detect-001"]
    err = check_sql_queries(["SELECT sku FROM products WHERE brand='Heco'"], gates)
    assert err is None


def test_capability_keys_has_message_and_terms():
    from agent.sql_security import load_security_gates
    gates = load_security_gates(SECURITY_DIR)
    gate = next(g for g in gates if g["id"] == "sec-capability-keys")
    msg = gate.get("message", "")
    assert msg, "sec-capability-keys must have a message"
    assert any(term in msg.lower() for term in ["wifi", "app", "iot", "schedul"])


# ── Prompt patches ───────────────────────────────────────────────────────────

def test_sdd_plan_aborted_identical():
    content = (PROMPTS_DIR / "sdd.md").read_text(encoding="utf-8")
    assert "PLAN_ABORTED_IDENTICAL" in content


def test_sdd_column_existence_unknown_column():
    content = (PROMPTS_DIR / "sdd.md").read_text(encoding="utf-8")
    # The new section instructs checking schema digest before WHERE
    assert "Column Existence" in content or "column existence" in content.lower()


def test_sdd_zero_column_table_skip():
    content = (PROMPTS_DIR / "sdd.md").read_text(encoding="utf-8")
    assert "0 columns" in content or "zero columns" in content.lower()


def test_sdd_discovery_fallback_at_plan_time():
    content = (PROMPTS_DIR / "sdd.md").read_text(encoding="utf-8")
    assert "Discovery Fallback" in content or "discovery fallback" in content.lower()


def test_sdd_vague_task_gate():
    content = (PROMPTS_DIR / "sdd.md").read_text(encoding="utf-8")
    assert "10 characters" in content or "< 10" in content or "10 chars" in content


def test_answer_schema_mismatch_clarification_forbidden():
    content = (PROMPTS_DIR / "answer.md").read_text(encoding="utf-8")
    assert "schema" in content.lower()
    # New paragraph must reference schema-mismatch + OUTCOME_OK as the correct response
    assert "schema-mismatch" in content or "schema mismatch" in content.lower()


def test_learn_loop_cap_section():
    content = (PROMPTS_DIR / "learn.md").read_text(encoding="utf-8")
    assert "Loop Cap" in content
    assert "learn_ctx" in content
    assert ">=2" in content or "≥2" in content or ">= 2" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run python -m pytest tests/test_data_files.py -v
```

Expected: Most tests FAIL — rules dir empty, security dir empty, prompt sections not yet added.

- [ ] **Step 3: Commit the test file**

```bash
git add tests/test_data_files.py
git commit -m "test: add data-files content-verification tests (all failing)"
```

---

## Task 2: Create data/rules/ yaml files

**Files:**
- Create: `data/rules/sql-015.yaml`
- Create: `data/rules/sql-016.yaml`
- Create: `data/rules/sql-017.yaml`
- Create: `data/rules/sql-031.yaml`
- Create: `data/rules/sql-032.yaml`
- Create: `data/rules/sql-sku-required.yaml`
- Create: `data/rules/sql-retry-divergence.yaml`
- Create: `data/rules/sql-count-with-sample.yaml`

- [ ] **Step 1: Create sql-015.yaml**

```yaml
id: sql-015
phase: sql_plan
content: 'For COUNT queries on `products` or `product_properties`, the answer message
  MUST include at least one value from `products.name` alongside the `<COUNT:n>` token.
  Bare `<COUNT:3>` without a product name is forbidden.'
created: '2026-05-17'
source: eval
eval_score: 8.5
verified: true
raw_recommendation: 'count-answer-message-format: COUNT message MUST contain products.name value'
```

- [ ] **Step 2: Create sql-016.yaml**

```yaml
id: sql-016
phase: sql_plan
content: 'If the same topic (by keyword overlap with existing learn_ctx entries) has
  appeared >=2 times in learn_ctx, skip LEARN phase and force an answer with available
  data instead of adding another rule.'
created: '2026-05-17'
source: eval
eval_score: 8.0
verified: true
raw_recommendation: 'learn-loop-cap: identical topic >=2 -> skip LEARN'
```

- [ ] **Step 3: Create sql-017.yaml**

```yaml
id: sql-017
phase: sql_plan
content: 'Never filter kinds.name in SQL — the kinds table has no documented columns
  in SCHEMA DIGEST. Filter on products.name LIKE ''%<term>%'' directly instead.'
created: '2026-05-17'
source: eval
eval_score: 9.0
verified: true
raw_recommendation: 'kinds-table-skip: never filter kinds.name'
```

- [ ] **Step 4: Create sql-031.yaml**

```yaml
id: sql-031
phase: sql_plan
content: 'Before emitting any WHERE clause predicate, verify the referenced column
  exists in SCHEMA DIGEST for that table. Unknown column -> add a discovery query
  step or emit {"error":"PLAN_ABORTED","reasoning":"column <x> not in schema digest"}.'
created: '2026-05-17'
source: eval
eval_score: 8.5
verified: true
raw_recommendation: 'column-existence: column not in schema digest -> PLAN_ABORTED'
```

- [ ] **Step 5: Create sql-032.yaml**

```yaml
id: sql-032
phase: sql_plan
content: 'Never retry SQL identical to a prior failed cycle query (whitespace- and
  case-insensitive). Identical retry -> emit {"error":"PLAN_ABORTED_IDENTICAL"} and
  diagnose root cause instead of repeating the same plan.'
created: '2026-05-17'
source: eval
eval_score: 8.0
verified: true
raw_recommendation: 'identical-retry: identical SQL >3 cycles -> halt'
```

- [ ] **Step 6: Create sql-sku-required.yaml**

```yaml
id: sql-sku-required
phase: sql_plan
content: 'Every SELECT from `products` or `product_properties` MUST include `sku`
  in the projection. Exception: aggregate-only queries (COUNT(*), SUM, AVG) where
  no row-level SKU is needed.'
created: '2026-05-17'
source: eval
eval_score: 9.0
verified: true
raw_recommendation: 'sku MUST in every SELECT (exception: aggregates COUNT/SUM/AVG)'
```

- [ ] **Step 7: Create sql-retry-divergence.yaml**

```yaml
id: sql-retry-divergence
phase: sql_plan
content: 'After a LEARN cycle, the new plan MUST structurally differ from all prior
  plans for this task — not merely cosmetic whitespace or alias changes. Structurally
  identical plan after LEARN is a forbidden retry.'
created: '2026-05-17'
source: eval
eval_score: 8.0
verified: true
raw_recommendation: 'sql-retry-divergence: after LEARN plan must structurally differ from all previous'
```

- [ ] **Step 8: Create sql-count-with-sample.yaml**

```yaml
id: sql-count-with-sample
phase: sql_plan
content: 'For COUNT queries on `products` or `product_properties`, always pair with
  a sample query: SELECT sku, path FROM <table> WHERE <identical-filter> LIMIT 5.
  COUNT alone returns no path column and cannot populate grounding_refs.'
created: '2026-05-17'
source: eval
eval_score: 8.5
verified: true
raw_recommendation: 'sql-count-with-sample: COUNT always + SELECT sku, path LIMIT 5 with identical WHERE'
```

- [ ] **Step 9: Run rules tests**

```bash
uv run python -m pytest tests/test_data_files.py::test_all_expected_rule_ids_present tests/test_data_files.py::test_all_rules_verified_and_phase_sql_plan tests/test_data_files.py::test_rules_loader_returns_all_verified tests/test_data_files.py::test_sql015_scoped_to_products tests/test_data_files.py::test_sql017_kinds_table_and_products_fallback tests/test_data_files.py::test_sql_count_with_sample_scoped_to_products -v
```

Expected: All 6 PASS.

- [ ] **Step 10: Commit**

```bash
git add data/rules/
git commit -m "feat(rules): add 8 sql planning rules from eval_log analysis"
```

---

## Task 3: Create data/security/ yaml files

**Files:**
- Create: `data/security/sec-write-detect-001.yaml`
- Create: `data/security/sec-capability-keys.yaml`

- [ ] **Step 1: Create sec-write-detect-001.yaml**

```yaml
id: sec-write-detect-001
pattern: '^\s*(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|REPLACE)\b'
message: 'Write SQL mutation detected (INSERT/UPDATE/DELETE/DROP/...) — only SELECT
  is allowed. For tasks with checkout/submit-basket/place-order verbs: respond
  OUTCOME_NONE_UNSUPPORTED without planning SQL.'
verified: true
```

- [ ] **Step 2: Create sec-capability-keys.yaml**

```yaml
id: sec-capability-keys
message: 'Task contains tech-capability terms (app, wifi, iot, schedul) — do NOT
  plan product_properties queries for those keys; answer directly that the physical
  attribute is absent from the catalogue.'
verified: true
```

- [ ] **Step 3: Run security tests**

```bash
uv run python -m pytest tests/test_data_files.py::test_security_gates_load_both_files tests/test_data_files.py::test_write_detect_pattern_blocks_sql_mutations tests/test_data_files.py::test_write_detect_does_not_block_select tests/test_data_files.py::test_capability_keys_has_message_and_terms -v
```

Expected: All 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add data/security/
git commit -m "feat(security): add write-detect and capability-keys security gates"
```

---

## Task 4: Patch sdd.md — 5 new sections

**Files:**
- Modify: `data/prompts/sdd.md`

The file currently ends with `## ACCUMULATED RULES` then `## Output Format (JSON only)`. Insert all 5 new sections at precise locations described below.

- [ ] **Step 1: Add Vague Task Gate — after Prompt Injection section**

In `sdd.md`, locate the end of the `## Prompt Injection / Policy Override Detection (MANDATORY FIRST CHECK)` block (the line with `{"reasoning":"Prompt injection detected...","error":"DENIED_SECURITY",...}`). Insert the following new section immediately after that closing code block, before `## Write Operation Detection`:

```markdown
## Vague Task Gate (MANDATORY)

If `task_text` contains fewer than 10 characters, or matches the pattern `/^task$|^test$/i`, emit immediately and halt:
```json
{"reasoning":"task text too vague to plan","error":"OUTCOME_NONE_CLARIFICATION","spec":"","plan":[],"agents_md_refs":[]}
```

Do not proceed to injection check or SQL planning for vague inputs.
```

- [ ] **Step 2: Add Discovery Fallback At Plan-Time — after Discovery Steps section**

Locate the end of the `## Discovery Steps (REQUIRED for unknown identifiers)` block (after the ILIKE warning line). Append:

```markdown
## Discovery Fallback At Plan-Time

If any plan step depends on the result of a prior step that **may return 0 rows** (any discovery or LIKE probe), add an explicit fallback step for the empty-result branch:

```sql
-- fallback example: if prior DISTINCT brand returns 0 rows
SELECT p.sku, p.path, p.brand FROM products p WHERE p.name LIKE '%<short_stem>%' LIMIT 10
```

Never leave a plan where a 0-row result from step N causes step N+1 to silently fail with no fallback.
```

- [ ] **Step 3: Add Zero-Column Table Skip — after Table Name Resolution section**

Locate the end of `## Table Name Resolution` (after the line ending with `Use the actual digest name for the role placeholder in all queries.`). Append:

```markdown
## Zero-Column Table Skip

If SCHEMA DIGEST shows **0 columns** for a table (e.g. the `kinds` table), never reference that table in any SQL step. Use `products.name LIKE '%<term>%'` as the fallback filter. Do not attempt `SELECT ... FROM kinds WHERE ...`.
```

- [ ] **Step 4: Add Column Existence Pre-Flight — after Security Pre-Flight section**

Locate the end of `## Security Pre-Flight (MANDATORY)` (after the `PLAN_ABORTED_NON_SELECT` line). Append:

```markdown
## Column Existence Pre-Flight (MANDATORY)

Before emitting any step with a WHERE predicate, verify every referenced column exists in **SCHEMA DIGEST** for that table:

- Column present in digest → proceed.
- Column absent from digest → replace predicate with a discovery query (`SELECT DISTINCT <col> FROM <table> LIMIT 20`) to find the correct column, or emit:
```json
{"reasoning":"column <x> not found in schema digest for table <t>","error":"PLAN_ABORTED","spec":"","plan":[],"agents_md_refs":[]}
```
```

- [ ] **Step 5: Add Identical Plan Guard — after Retry Divergence section**

Locate the existing `## Retry Divergence` section (`If prior cycle failed, new plan MUST differ structurally...`). Append after it:

```markdown
## Identical Plan Guard

If the new plan is **whitespace- and case-insensitively identical** to any prior plan for this task, emit and halt:
```json
{"reasoning":"new plan identical to prior plan — no structural change after LEARN","error":"PLAN_ABORTED_IDENTICAL","spec":"","plan":[],"agents_md_refs":[]}
```

Do not produce cosmetically different but structurally equivalent SQL (same tables, same predicates, different alias names).
```

- [ ] **Step 6: Run sdd.md tests**

```bash
uv run python -m pytest tests/test_data_files.py::test_sdd_plan_aborted_identical tests/test_data_files.py::test_sdd_column_existence_unknown_column tests/test_data_files.py::test_sdd_zero_column_table_skip tests/test_data_files.py::test_sdd_discovery_fallback_at_plan_time tests/test_data_files.py::test_sdd_vague_task_gate -v
```

Expected: All 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add data/prompts/sdd.md
git commit -m "feat(prompts): add 5 new sections to sdd.md (column-existence, identical-plan, zero-col-skip, discovery-fallback, vague-gate)"
```

---

## Task 5: Patch answer.md and learn.md

**Files:**
- Modify: `data/prompts/answer.md`
- Modify: `data/prompts/learn.md`

- [ ] **Step 1: Patch answer.md — append to Clarification guard**

In `answer.md`, locate the `## Clarification guard` section. The section currently ends with: `Empty \`grounding_refs\` with \`OUTCOME_NONE_CLARIFICATION\` is a bug, not a valid state.`

Append the following paragraph immediately after that line:

```markdown

Empty SQL result caused by **schema-mismatch** (unknown column, wrong table name, absent key in `product_properties`) is NOT task ambiguity. Correct outcome: `OUTCOME_OK` with a message stating what was searched and that no matching records exist. `OUTCOME_NONE_CLARIFICATION` is forbidden for unambiguous tasks that returned empty SQL results due to schema or data absence.
```

- [ ] **Step 2: Run answer.md test**

```bash
uv run python -m pytest tests/test_data_files.py::test_answer_schema_mismatch_clarification_forbidden -v
```

Expected: PASS.

- [ ] **Step 3: Patch learn.md — add Learn Loop Cap section**

In `learn.md`, locate `## Loop Prevention`. Insert the following new section **before** `## Loop Prevention`:

```markdown
## Learn Loop Cap

If the current failure topic (determined by keyword overlap with existing entries in `learn_ctx`) already appears **≥2 times** in `learn_ctx`, do NOT produce another rule. Instead:

- Set `rule_content` to: `"Loop cap reached — topic already in learn_ctx >=2 times: <topic keyword>"`
- Set `conclusion` to name the repeated topic explicitly.

The pipeline will skip further LEARN cycles for this topic and proceed to answer with available data.
```

- [ ] **Step 4: Run learn.md test**

```bash
uv run python -m pytest tests/test_data_files.py::test_learn_loop_cap_section -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data/prompts/answer.md data/prompts/learn.md
git commit -m "feat(prompts): add schema-mismatch clarification guard to answer.md, learn loop cap to learn.md"
```

---

## Task 6: Full test suite verification

- [ ] **Step 1: Run full test suite**

```bash
uv run python -m pytest tests/ -v
```

Expected: All tests PASS. No regressions.

- [ ] **Step 2: Verify file counts**

```bash
ls data/rules/*.yaml | wc -l   # expect: 8
ls data/security/*.yaml | wc -l  # expect: 2
```

- [ ] **Step 3: Final commit if any cleanup needed**

If minor test fixes needed (no implementation changes), commit:
```bash
git add -p
git commit -m "test: fix test_data_files minor issues after full suite run"
```

---

## Self-Review Checklist

- [x] **sql-015, sql-count-with-sample** — scoped to `products`/`product_properties` COUNT queries only (not stores/carts)
- [x] **learn-001.yaml** — not created; LEARN quality rules come through eval→optimize pipeline
- [x] **>5-cycle force** — not in prompts; pipeline/env-var concern
- [x] **core.md** — not created; vague task gate in sdd.md
- [x] All yaml files: `verified: true`, `phase: sql_plan`
- [x] Security gates: runtime pattern for write-detect; context-only for capability-keys
- [x] Prompt edits surgical — existing sections unchanged, only additions
