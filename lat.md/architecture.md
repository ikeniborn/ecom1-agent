# Architecture

ecom1-agent is an LLM-driven benchmark agent that answers e-commerce queries by executing a multi-phase pipeline against a remote ECOM VM over Connect-RPC.

## Entry Point

`main.py` feeds tasks to the BitGN harness via `orchestrator.py:run_agent()`. Each task gets its own isolated pipeline run: prephase → pipeline cycles → `vm.answer()`.

## Prephase

`prephase.py:run_prephase()` hydrates `PrephaseResult` before every task. All steps are best-effort — failures produce empty fields, not hard errors.

Fetches `/AGENTS.MD` (vault policy), runs `.schema` + PRAGMA queries for `schema_digest`, reads `/bin/id` + `/bin/date` for agent identity. Store ID extracted from `/proc/employees/{emp_id}.json`.

## Pipeline Loop

`pipeline.py:run_pipeline()` runs up to `MAX_STEPS` cycles. On any phase failure: LEARN → CONSOLIDATE → next cycle.

Each cycle:
1. ASSEMBLE — builds `unified_context` via `prompt_assembler.py`
2. IDD — extracts intent, expectations, scope_estimate; can hard-stop before SDD
3. SDD — produces candidate `actions` list and `error_code`
4. PLAN — selects single `action` from SDD output
5. EXECUTE — runs the action against the VM
6. BATCH EXECUTE — runs additional file reads when SDD proposed extras or primary was search/tree
7. ANSWER — formats final response with outcome and `grounding_refs`

## LLM Routing

`llm.py:call_llm_raw()` dispatches by provider prefix. Per-phase model overrides via `MODEL_{PHASE}` env vars.

Providers: `anthropic/` → Anthropic SDK (prompt caching), `openrouter/` → OpenRouter, `ollama/` or bare name → local Ollama, `CC_ENABLED=1` → CC CLI subprocess. Transient errors retry with exponential backoff.

## Prompt Assembly

`prompt_assembler.py:assemble_prompt()` merges all knowledge sources into `unified_context` per cycle via a dedicated LLM call.

Sources in priority order: learned rules (`data/learned/{task_id}.yaml`) → vault (`/AGENTS.MD`) → schema digest → agent context.

## Learned Knowledge

Per-task rules persist in `data/learned/{task_id}.yaml` as YAML entries with `active`/`inactive` status.

`_apply_learn_diff()` writes entries incrementally after each LEARN phase. CONSOLIDATE merges redundant active rules. Entries survive across runs — never deleted on success.

## Data Flow

End-to-end execution path for one task.

```
task_text
  → run_prephase() → PrephaseResult
  → run_pipeline() [cycle loop]:
      assemble_prompt() → unified_context
      IDD → IddOutput (intent + gate)
      SDD → SddOutput (actions + error_code)
      PLAN → PlanOutput (single action)
      _run_execute() → ExecuteOutput
      BATCH EXECUTE (extras)
      ANSWER → AnswerOutput → vm.answer()
      [on failure] LEARN + CONSOLIDATE → next cycle
```
