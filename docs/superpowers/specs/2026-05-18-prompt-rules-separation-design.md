# Prompt / Rules Separation — Design Spec

**Date:** 2026-05-18  
**Status:** Approved

## Problem

`data/prompts/*.md` contain two classes of content mixed together:

1. **Structural**: role definition, output format, phase workflow, error code semantics
2. **Business rules**: SQL planning patterns, discovery patterns, column constraints — rules discovered via eval_log and learned sessions

Business rules in prompts cause:
- **Contradictions**: `sec-write-detect-001` said "checkout → OUTCOME_NONE_UNSUPPORTED", `sdd.md` said "checkout → plan basket discovery". LLM followed security (higher perceived priority) → t21 bug, score 0.
- **Maintenance divergence**: same rule updated in two places, or only one place, silently diverging.
- **Dead weight**: deleted `data/rules/` files leave prompt duplicates that stay active — no single source of truth.

## Goal

**Prompts contain only**: role, output format, phase workflow, error code semantics.  
**`data/rules/`**: all SQL planning constraints, discovery patterns, query shapes.  
**`data/security/`**: detection gates and blocking rules.

## Architecture

```
assembler.md (unchanged) 
  → builds unified_context from:
       # LEARNED   (data/learned/ + in-session)
       # RULES     (data/rules/*.yaml, verified=true)
       # SECURITY  (data/security/*.yaml, verified=true)
       # BASE      (vault / agents_md / schema)

sdd.md (thin) + unified_context → SDD phase
learn.md (thin) + unified_context → LEARN phase
answer.md (thin) + unified_context → ANSWER phase
tdd.md (unchanged) → TDD phase
```

## What Changes

### sdd.md: 215 → ~55 lines

**Stays**: role, `/no_think`, OUTPUT RULE, plan step types (sql/read/compute/exec), exec tool restriction (structural: "only tools in important_tools", no hardcoded paths), prompt injection detection (structural output format for DENIED_SECURITY), vague task gate, write operation detection + checkout exception, security pre-flight (SELECT check), output format JSON.

**Moves to `data/rules/`**:

| sdd.md section | destination |
|---|---|
| Table Name Resolution + Zero-Column Table Skip | `sql-017.yaml` (restore) |
| Discovery Steps patterns | `sql-discovery-patterns.yaml` (new) |
| Discovery Fallback At Plan-Time | `sql-discovery-fallback.yaml` (new) |
| Multi-Attribute Filtering (EXISTS subqueries) | `sql-multi-attribute-exists.yaml` (new) |
| SKU and Path Projection | `sql-sku-required.yaml` (restore) |
| Store Name Discovery | `sql-store-discovery.yaml` (new) |
| Inventory Query Rules | `sql-inventory-projection.yaml` (new) |
| Count Questions | `sql-count-with-sample.yaml` (restore) |
| Cart Queries | `sql-cart-query.yaml` (new) |
| Column Existence Pre-Flight | `sql-031.yaml` (restore) |
| Retry Divergence / Identical Plan Guard | `sql-retry-divergence.yaml` (restore) |
| Product Line Column Mapping | `sql-product-line-model.yaml` (new) |
| NOT FOUND Rule | `sql-not-found.yaml` (new) |

### learn.md: 92 → ~45 lines

**Stays**: role, output format (all fields), reasoning field discipline, conclusion specificity, context compaction instructions, loop prevention.

**Moves to `data/rules/`**:

| learn.md section | destination |
|---|---|
| Common failure patterns (JOIN bug, wrong column, value type, key discovery) | `sql-learn-patterns.yaml` (new) |
| Discovery Fallback Rule | merge into `sql-discovery-fallback.yaml` |
| Learn Loop Cap (≥2 times) | `sql-016.yaml` (restore) |

### answer.md: 87 → ~40 lines

**Stays**: role, output rules (pure JSON), outcome definitions (OUTCOME_OK / NONE_CLARIFICATION / NONE_UNSUPPORTED / DENIED_SECURITY), checkout outcome note, clarification guard, reasoning chain requirement, output format JSON.

**Moves to `data/rules/`**:

| answer.md section | destination |
|---|---|
| Grounding Refs mandatory rules (≥1 SKU, source restriction, forbidden constructions) | `sql-grounding-refs.yaml` (new) |
| Model Name Fidelity | `sql-model-name-fidelity.yaml` (new) |
| Key Existence vs SKU Match | `sql-key-existence-vs-sku.yaml` (new) |
| Missing Numeric Field → LEARN Cycle | `sql-missing-numeric-field.yaml` (new) |
| Store Scope Validation Before Inventory Sum | `sql-store-scope.yaml` (new) |
| Cart Answers grounding_refs rules | merge into `sql-cart-query.yaml` |

### tdd.md: unchanged

Anti-patterns and test writing rules are process rules for the TDD phase, not SQL planning business logic.

### assembler.md: unchanged

Already clean — process only.

### Security gates: restore + fix

**Restore** (deleted from disk, in git HEAD):
- `sec-capability-keys.yaml`
- `sec-learn-041.yaml`  
- `sec-learn-066.yaml`
- `sec-write-detect-001.yaml` — **with message fix**

**Fix `sec-write-detect-001`**: remove "For tasks with checkout/submit-basket/place-order verbs: respond OUTCOME_NONE_UNSUPPORTED without planning SQL." Checkout exception logic lives exclusively in `sdd.md`. Security gate only blocks SQL mutations (INSERT/UPDATE/DELETE/DROP/...).

## File Inventory

**Restore from git** (11 files):
- `data/rules/`: sql-015, sql-016, sql-017, sql-031, sql-count-with-sample, sql-retry-divergence, sql-sku-required
- `data/security/`: sec-capability-keys, sec-learn-041, sec-learn-066, sec-write-detect-001

**Create new** (14 rules files):
- `data/rules/sql-discovery-patterns.yaml`
- `data/rules/sql-discovery-fallback.yaml`
- `data/rules/sql-multi-attribute-exists.yaml`
- `data/rules/sql-store-discovery.yaml`
- `data/rules/sql-inventory-projection.yaml`
- `data/rules/sql-cart-query.yaml`
- `data/rules/sql-product-line-model.yaml`
- `data/rules/sql-not-found.yaml`
- `data/rules/sql-learn-patterns.yaml`
- `data/rules/sql-grounding-refs.yaml`
- `data/rules/sql-model-name-fidelity.yaml`
- `data/rules/sql-key-existence-vs-sku.yaml`
- `data/rules/sql-missing-numeric-field.yaml`
- `data/rules/sql-store-scope.yaml`

**Trim**:
- `data/prompts/sdd.md` — remove 13 sections listed above
- `data/prompts/learn.md` — remove 3 sections listed above
- `data/prompts/answer.md` — remove 6 sections listed above

## Verification

After implementation:
1. `uv run python -m pytest tests/ -v` — all tests pass
2. `make task TASKS='t21'` — t21 scores > 0 (checkout plans basket discovery, ANSWER refs basket path)
3. `data/rules/` и `data/security/` — non-empty, all `verified: true`
4. Each removed prompt section has corresponding rule file with `verified: true`

## Out of Scope

- `tdd.md` content (anti-patterns stay — TDD process rules)
- `assembler.md` (already clean)
- Pipeline code changes
- Adding new tasks or eval data
