# Architecture

ecom1-agent is an LLM-driven benchmark agent that answers e-commerce queries by executing a deterministic Plan-IR interpreter against a remote ECOM VM over Connect-RPC.

There is **one** pipeline: the IR interpreter. Per task — INTENT → loop[PLAN → lint → interpret → verify → answer-once] → CLARIFICATION. The legacy DESIGN→CODEGEN loop and the `INTERPRETER_ENABLED` fork were removed.

## Entry Point

`main.py` feeds tasks to the BitGN harness via `orchestrator.py:run_agent()`. Each task gets its own isolated run: open VM → read `/AGENTS.MD` inline → `gather_prephase_facts()` → `pipeline.py:run_pipeline()` → exactly one `vm.answer()`.

## Prephase

`orchestrator.py:gather_prephase_facts()` hydrates `PrePhaseFacts` before every task. All steps are best-effort — failures produce empty fields, not hard errors. See [[prephase]].

Gathers schema + table names, relevance-gated sample rows, agent identity (`/bin/id`), and docs inventory + policies. Learned `prephase_deep_read` hints (table names / literal paths) are read eagerly.

## Pipeline Loop

`pipeline.py:run_pipeline()` runs one INTENT call (frozen for the run), then up to `INTERPRETER_MAX_STEPS` cycles (default 6). See [[pipeline-phases]].

1. **INTENT** — `reason.py:run_intent()` → `IntentSpec`. Frozen for the run; retried on transient parse/empty failure. Hard failure → terminal `OUTCOME_NONE_CLARIFICATION` (no cycles run).
2. **Each cycle:**
   - PLAN — `reason.py:run_plan()` → `PlanIR` (LLM)
   - lint — `interpreter.py:lint_security_first()` (no LLM)
   - plan-signature short-circuit — `_plan_signature()` identical to prior cycle → CLARIFICATION
   - interpret — `interpreter.py:interpret()` (no LLM) runs the plan against the VM
   - verify — `verify.py:verify()` (no LLM, deterministic) checks success_criteria + required refs
   - pass → `vm.answer()` once + persist artifacts + optional distill→validate→promote
   - fail → `_ilearn()` (LEARN) → next cycle (break if a mutation landed)
3. Loop exhaust / no-progress → terminal `OUTCOME_NONE_CLARIFICATION`.

`vm.answer()` is called **exactly once** per task. `verify()` is the sole pre-answer quality gate and is deterministic — there is no LLM-graded answer check. See [[security-lint]].

## LLM Routing

`llm.py:call_llm_raw()` dispatches on two axes.

- *Transport* by `MODEL` prefix: `anthropic/` → Anthropic SDK (prompt caching), `openrouter/` → OpenRouter, `ollama/` or bare name → local Ollama, `CC_ENABLED=1` / `claude-code/` → CC CLI subprocess.
- *Per-phase model* via `_resolve_model_for_phase()`: `MODEL_<PHASE>` → tier env (`MODEL_REASON` / `MODEL_FAST` / `EMBED_MODEL`) → `MODEL`. Reason-tier phases (INTENT, PLAN, iLEARN, distill) request `think=on`; fast-tier (DOC_SELECT, oracle rerank) `think=off`.

Transient errors retry with exponential backoff before falling through to the next provider tier, then `MODEL_FALLBACK`.

## Learned Knowledge

Per-task rules persist in `data/learned/{task_id}.yaml` as YAML entries with `active`/`inactive` status. See [[data-models]].

`_ilearn()` distils a `LearnConsolidateOutput` after each failed cycle via `apply_learn_diff()`; PLAN sees all active rules (single surface). Entries survive across runs — never deleted on success.

On success, `_persist_artifacts()` writes `data/heuristics/{tid}.intent.json` + `{tid}.plan.json`, consumed by `learn_from_grader()` in training mode (`TRAIN_MAX_CYCLES > 1`).

## Knowledge Oracle

`oracle.py:KnowledgeOracle.retrieve()` semantically retrieves validated atoms from `data/oracle/atoms.yaml` into PLAN.

On success (`ORACLE_DISTILL=1`), `distill()` generalizes the working plan into a candidate atom; `ORACLE_VALIDATE_INLINE=1` grader-validates and promotes on improvement.

## Data Flow

End-to-end execution path for one task.

```
task_text
  → gather_prephase_facts() → PrePhaseFacts
  → run_pipeline():
      run_intent() → IntentSpec (frozen)
      loop [cycle 1..INTERPRETER_MAX_STEPS]:
        run_plan() → PlanIR
        lint_security_first(plan)
        _plan_signature(plan)          # identical → CLARIFICATION
        interpret(plan, intent, vm, facts) → result
        verify(result, intent)
          pass → vm.answer() once + persist + distill
          fail → _ilearn() → next cycle
      exhaust → terminal CLARIFICATION
```
