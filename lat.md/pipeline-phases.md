# Pipeline Phases

Each pipeline cycle executes phases in fixed order. Phase failures route to LEARN; LEARN failure increments cycle. All phases produce structured Pydantic output parsed from LLM JSON.

## IDD — Intent-Driven Development

IDD is Layer 1: extracts WHAT and WHY before SDD decides HOW. Fires before SDD every cycle.

Receives `unified_context` + `idd.md` guide. Produces `IddOutput` with `intent_type`, `reformulated_task`, `success_criteria`, `scope_estimate`, and `decision`.

`decision = "hard_stop"` calls `vm.answer()` immediately with `stop_code` and skips SDD. `decision = "proceed"` passes `IddOutput` to SDD as structured context. `scope_estimate.files_to_read` drives adaptive batch cap: `ceil(files / remaining_cycles) + 5`, clamped to [24, 80].

## SDD — Structured Decision Design

SDD receives `unified_context` + `sdd.md` + `IddOutput`-derived user message. Produces `SddOutput`.

`error_code = "DENIED_SECURITY"` → immediate `vm.answer()` with security outcome. `error_code = "UNSUPPORTED"` → immediate `vm.answer()` with unsupported outcome. On success, `actions` list drives PLAN selection.

## PLAN

PLAN selects a single `action` string from SDD candidates. Receives `unified_context` + `plan.md` + SDD JSON.

`PlanOutput.action` is coerced from list to scalar if LLM returns an array.

## EXECUTE

`_run_execute()` infers action type from string prefix and dispatches to the correct VM call.

`SELECT` → sql (EXPLAIN pre-check first), `/path` → read, `list:` → list, `search:` → search, `find:` → find, `tree:` → tree, else → exec. Returns `ExecuteOutput` or error string.

Empty results from data-returning actions (sql, read, search, list, find, tree) trigger LEARN. Exec-type (`/bin/`) may return empty on success — not an error.

## Batch Execute

After primary EXECUTE succeeds, extra candidates are executed in the same cycle when action is read/tree/list/search/find.

Sources: SDD `actions` extras, search-match paths, tree-discovered files. Adaptive cap from `scope_estimate`.

## ANSWER

ANSWER formats final response. Receives `unified_context` + `answer.md` + `ExecuteOutput` + all prior results.

Produces `AnswerOutput` with `message`, `outcome`, and `grounding_refs`. On `OUTCOME_NONE_CLARIFICATION` with cycles remaining, retries without calling `vm.answer()`. LEARN fires only when output is empty or signals incomplete reads.

## LEARN

`_run_learn()` fires on any phase failure. Appends new rule to `learn_ctx` and YAML.

Receives error context + phase outputs + existing learned entries. `error_type = "llm_fail"` skips rule extraction and restarts cycle. `agents_md_anchor` triggers vault section lookup instead of new rule.

## CONSOLIDATE

`_run_consolidate()` fires after every LEARN when ≥2 active entries exist.

Merges redundant rules via LLM, deactivates originals in YAML, keeps `learn_ctx` in sync.
