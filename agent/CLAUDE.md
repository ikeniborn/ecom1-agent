# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Authoritative CLAUDE.md is `../CLAUDE.md` (repo root). This file covers agent-package internals.**

## Commands

```bash
uv sync                                          # install all deps
uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline.py -v         # single test file

EVAL_ENABLED=1 uv run python main.py            # run with evaluator
LOG_LEVEL=DEBUG uv run python main.py           # full LLM response logging
```

Key env vars:
- `MODEL` — primary LLM (e.g. `anthropic/claude-sonnet-4-6`)
- `EVAL_ENABLED=1` + `MODEL_EVALUATOR` — post-task LLM evaluation (success-only)
- `MAX_STEPS` — max pipeline retry cycles (default: 3)

## Agent Package Architecture

Entry: `orchestrator.py:run_agent()` → `prephase.py` → `pipeline.py`

**Phase execution order (per cycle, up to `MAX_STEPS` cycles):**

1. **ASSEMBLE** (`prompt_assembler.py:assemble_prompt()`) — 1 LLM call; merges `learn_ctx` + rules + security gates + vault + schema into `unified_context` string
2. **SDD** — LLM call with `[unified_context, sdd_guide]` → `json_extract.py` → `SddOutput` (queries + agents_md_refs)
3. **AGENTS.MD refs check** — if `agents_md_refs` empty but index terms appear in task → LEARN
4. **SCHEMA** (`schema_gate.py:check_schema_compliance()`) — unknown columns, unverified literals, double-key JOINs on `product_properties`
5. **VALIDATE** — `EXPLAIN <query>` via VM exec
6. **TDD** (`test_runner.py`) — always runs; generates SQL + answer tests, executes them
7. **EXECUTE** — runs queries; empty result set triggers LEARN
8. **ANSWER** — LLM with `[unified_context, answer_guide]` → `AnswerOutput` → `vm.answer()`
9. **LEARN** (on any failure) — LLM with `[unified_context, learn_guide]` → appends rule to `learn_ctx` → `continue` to next cycle

On **success**: writes eval_log (with `learn_ctx`), calls `clear_learned_ctx(task_id)`.
On **exhaustion**: calls `save_learned_ctx(task_id, learn_ctx)` → persisted to `data/learned/{task_id}.yaml` for next run.

**Pydantic models** (`models.py`):
- `SddOutput` — `queries`, `agents_md_refs`, `reasoning`, `error`
- `TestOutput` — `sql_tests`, `answer_tests`
- `LearnOutput` — `rule_content`, `agents_md_anchor`, `reasoning`
- `AnswerOutput` — `message`, `outcome`, `grounding_refs`
- `PipelineEvalOutput` — evaluator scoring model

**LLM routing** (`llm.py:call_llm_raw()`): provider prefix → tier.
- `anthropic/` → Anthropic SDK (prompt caching via `cache_control` blocks)
- `openrouter/` → OpenRouter (OpenAI-compatible)
- bare name / `ollama/` → local Ollama
- `CC_ENABLED=1` → `cc_client.py` subprocess (Claude Code tier)

Transient errors (503, rate-limit, timeout) retry with exponential backoff.

**Prompt assembly** (`prompt_assembler.py`):
- `assemble_prompt()` — main entry; loads persisted learn_ctx, merges with in-session, calls LLM assembler
- `load_learned_ctx(task_id)` / `save_learned_ctx(task_id, ctx)` / `clear_learned_ctx(task_id)` — `data/learned/` persistence
- Phase guides live in `data/prompts/{phase}.md`; task-type blocks configured in `data/config/task_blocks.yaml`

**Prompt loading** (`prompt.py`):
- `load_prompt(name)` — reads `data/prompts/{name}.md`; returns `""` if missing
- `load_task_blocks(task_type)` — reads `data/config/task_blocks.yaml`; returns list of block stems for the type

**Prephase** (`prephase.py:run_prephase()`): reads `/AGENTS.MD` from VM → `parse_agents_md()` → section index; executes `.schema` + PRAGMA queries to build `schema_digest`.

**Evaluator** (`evaluator.py:run_evaluator()`): LLM scores pipeline trace; returns `PipelineEvalOutput` — does NOT write to eval_log (pipeline does that on success).

**Trace logging** (`trace.py`): thread-local `TraceLogger` writes structured JSONL. Attach with `set_trace(logger)`; read with `get_trace()`. Records: `header`, `llm_call`, `gate_check`, `sql_validate`, `sql_execute`, `task_result`.

**Rules** (`rules_loader.py:RulesLoader`): loads `data/rules/*.yaml`; only `verified: true` rows injected. Cached module-level in `pipeline.py`.

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools take priority over reads
- `_run_learn` in `pipeline.py` — `error_type="llm_fail"` skips rule extraction (just restarts cycle); `"semantic"` adds rule to `learn_ctx`
- System prompt blocks passed as `list[dict]` (Anthropic multi-block format): `[{"type":"text","text":unified_context}, {"type":"text","text":guide,"cache_control":{"type":"ephemeral"}}]`
- `check_retry_loop` in pipeline is the anti-infinite-loop guard; `check_sql_queries`/`check_where_literals` were removed (security now in unified_context)
- `_rules_loader_cache` and `_security_gates_cache` are module-level in `pipeline.py` — use `tests/conftest.py:reset_pipeline_caches()` to clear between tests
- RESOLVE phase stubs remain for backward compat but are no-ops; `confirmed_values` no longer populated
