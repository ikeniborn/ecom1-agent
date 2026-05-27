# Intent: Heuristic-Driven Pipeline

**Date:** 2026-05-27
**Status:** draft

## Objective

Current pipeline wastes hundreds of thousands of tokens: every task — even repeated ones — runs a full LLM cycle (ASSEMBLE → IDD → SDD → PLAN → ANSWER, 3–5 LLM calls). The LLM analyzes raw data directly instead of leveraging accumulated knowledge.

Change: LLM becomes a **heuristic generator**, not a data analyzer. Code becomes the **executor**. Each task gets a self-contained Python script (`data/heuristics/{task_id}.py`) with hardcoded SQL, regex, if/else logic — baked in from schema_digest and unified_context at generation time. On repeat runs: 0 LLM calls or minimal refinement.

## Desired Outcomes

- Pipeline produces `data/heuristics/{task_id}.py` — self-contained Python script with any effective logic to solve the task: SQL queries, regex, if/else conditions, loops, string matching, data aggregation, sorting, filtering, statistical calculations, fuzzy matching, graph traversal, caching, memoization, or any other technique appropriate for the task
- Script runs in isolated sandbox; produces result without LLM data analysis
- LLM validates result (IDD/SDD/PLAN context) before calling `vm.answer()`
- Repeat task execution: no LLM calls, or minimal patch to existing heuristic
- LEARN cycle refines the heuristic script (not YAML rules) when validation fails
- Heuristics accumulate and improve across runs — never deleted

## Health Metrics

- `vm.answer()` correctness remains primary success criterion
- BitGN harness interface (`run_agent()`, protobuf) unchanged
- Existing `data/learned/*.yaml` migrated if needed (not broken)
- Soft inference SLA: ≤300s with existing heuristic (non-binding)

## Strategic Context

- Interacts with: BitGN harness, ECOM VM (Connect-RPC), `data/heuristics/`, `data/learned/`, LLM providers
- Sandbox: subprocess-level isolation, FS access restricted to `data/` only
- Script dependencies: stdlib + project packages + safe additional packages (proposal-first for new installs)
- Priority trade-off: **accuracy first** — heuristic errors trigger LEARN cycle, LLM refines script; LLM never executes task directly

## Constraints

### Steering (behavioral guidance)

- LLM generates heuristic code with all knowledge baked in (schema, data patterns, queries) — script is self-contained, not runtime-context-dependent; no restriction on technique: any Python approach that solves the task efficiently is valid
- No forbidden code patterns in generated scripts, but network access and FS outside `data/` are blocked at sandbox level
- `vm.answer()` must only be called after LLM validates heuristic output — never directly from generated script
- Generated script may call `vm.*` SQL methods directly (data reads)
- Heuristics improve via LEARN (LLM patches script) but are never deleted entirely

### Hard (architectural enforcement)

- Sandbox FS restriction: only `data/` accessible from generated scripts
- `vm.answer()` call path: always through LLM validation layer, not from heuristic script
- Heuristic scripts stored at `data/heuristics/{task_id}.py`
- No changes to BitGN harness interface
- New package installs in sandbox: proposal-first (human approval)
- Changes to `data/heuristics/` directory structure: proposal-first

## Autonomy Zones

- **Full autonomy** (reversible, low risk): generate/patch heuristic code, choose SQL queries, script structure, LEARN-driven refinements
- **Guarded** (log + confidence threshold): deciding heuristic output is "correct" before calling `vm.answer()`
- **Proposal-first** (needs approval): installing new packages in sandbox; changing `data/heuristics/` directory structure
- **No autonomy** (human only): deleting existing heuristic scripts; accessing FS outside `data/`

## Stop Rules

- Halt if: sandbox timeout or unhandled exception in heuristic script → route to LEARN
- Halt if: generated script attempts FS access outside `data/` → hard error, no LEARN
- Escalate if: MAX_STEPS cycles exhausted without valid heuristic → report failure, preserve last heuristic version
- Done when: `vm.answer()` called with LLM-validated correct result from heuristic execution
