# Constraints and Invariants

Non-obvious rules that are load-bearing in the current implementation. Violating any of these causes silent failures or infinite loops.

## JSON Extraction Priority

Mutation tool types (write/delete) take priority over reads in `json_extract.py`.

Reversing this ordering causes spurious read tool calls to shadow mutation tools, producing wrong execution.

## Single Answer per Task

`vm.answer()` is called **exactly once** per task — either the success path (verify passed) or one terminal CLARIFICATION. Every early-exit routes through `_terminal_clarification()`; a second `answer` is a protocol error.

## Frozen INTENT

`IntentSpec` is produced once and frozen for the whole run. `learn_ctx` updates between cycles affect only subsequent PLAN calls, never INTENT — so a cycle cannot re-interpret the task mid-run.

## Anti-Infinite-Loop Guard

`_plan_signature(plan)` in `pipeline.py` is the only anti-loop guard. See [[security-lint]].

It hashes discovery + ops (SQL whitespace/case-normalized, other args verbatim); two consecutive identical signatures ⇒ no progress ⇒ break with CLARIFICATION. A↔B oscillation is bounded by `INTERPRETER_MAX_STEPS`.

## LEARN Rule Validation

`apply_learn_diff()` (`learned_store.py`) rejects rules shorter than `_MIN_CONTENT_LEN` or not starting with a `_VALID_RULE_STARTS` prefix.

Valid starts: `("never", "always", "use", "do not", "when", "if", "prefer")`. Prevents placeholder content polluting the knowledge base.

## Prompt Engineering Boundary

`data/prompts/*.md` contain only structural rules. Task-specific rules must flow through LEARN into `data/learned/{task_id}.yaml`.

Allowed in prompts: output format, action forms, SQL constraints, generic patterns. Forbidden: task-specific heuristics. Patching prompts to fix a task failure is explicitly wrong — fix the LEARN trigger or learned rule instead.

## System Prompt Block Format

System prompt is a single cache-controlled block: `[{"type":"text","text":guide,"cache_control":{"type":"ephemeral"}}]`.

The phase guide carries `cache_control` for prompt caching; facts and prior context go in the user message, not a second system block. (There is no `unified_context` system block — the legacy assembler was removed.)
