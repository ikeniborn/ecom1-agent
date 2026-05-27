# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Authoritative CLAUDE.md is `../CLAUDE.md` (repo root). This file covers agent-package internals.**

## Commands

```bash
uv sync                                          # install all deps
uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline.py -v         # single test file

LOG_LEVEL=DEBUG uv run python main.py           # full LLM response logging
```

Key env vars:
- `MODEL` — primary LLM (e.g. `anthropic/claude-sonnet-4-6`)
- `MAX_STEPS` — max pipeline retry cycles (default: 3)

## Agent Package Architecture

Entry: `orchestrator.py:run_agent()` → `prephase.py` → `pipeline.py`

**Phase execution order (per cycle, up to `MAX_STEPS` cycles):**

1. **ASSEMBLE** (`prompt_assembler.py:assemble_prompt()`) — 1 LLM call; merges learned knowledge + vault + schema into `unified_context` string
2. **IDD** — LLM call → `IddOutput`; classifies intent, extracts params; may hard-stop with `vm.answer()`
3. **SDD** — LLM call with `[unified_context, sdd_guide]` → `json_extract.py` → `SddOutput`; may short-circuit on DENIED_SECURITY/UNSUPPORTED
4. **PLAN** — LLM call → `PlanOutput`; selects action; retry-loop guard applied
5. **CODEGEN** — LLM generates heuristic script + mock test → lint + mock-exec; writes `data/heuristics/{task_id}.py`
6. **ANSWER** — executes heuristic script on real VM → `vm.answer()`; no LLM call
7. **LEARN** (on any failure) — LLM with `[unified_context, learn_guide]` → appends rule to `learn_ctx` → `continue` to next cycle

**Fast path** (when `data/heuristics/{task_id}.py` exists and last run was successful): skips all LLM calls, runs existing script directly → `vm.answer()`; falls through to full path on failure.

On **success**: in-session learn entries remain in `data/learned/{task_id}.yaml` (written incrementally by `_apply_learn_diff`); no separate clear step.
On **exhaustion**: same — entries already written incrementally; no extra persist call.

**Pydantic models** (`models.py`):
- `IddOutput` — `intent_objective`, `reformulated_task`, `intent_type`, `extracted_params`, `decision`, `stop_code`, `stop_message`
- `SddOutput` — `spec_goal`, `success_criteria`, `plan`, `actions`, `error_code`
- `PlanOutput` — `approach`, `steps`, `action`
- `CodegenOutput` — `script_path`, `script_code`, `test_code`
- `LearnOutput` — `rule_content`, `agents_md_anchor`, `reasoning`, `deactivate`, `deactivate_reason`, `skip`, `skip_reason`
- `AnswerOutput` — `message`, `outcome`, `grounding_refs`

**LLM routing** (`llm.py:call_llm_raw()`): provider prefix → tier.
- `anthropic/` → Anthropic SDK (prompt caching via `cache_control` blocks)
- `openrouter/` → OpenRouter (OpenAI-compatible)
- bare name / `ollama/` → local Ollama
- `CC_ENABLED=1` → `cc_client.py` subprocess (Claude Code tier)

Transient errors (503, rate-limit, timeout) retry with exponential backoff.

**Prompt assembly** (`prompt_assembler.py`):
- `assemble_prompt()` — main entry; loads per-task learned knowledge from `data/learned/{task_id}.yaml`, merges with in-session learn_ctx, calls LLM assembler
- `_apply_learn_diff(task_id, learn_output)` — incrementally writes new/updated entries to `data/learned/{task_id}.yaml`
- Phase guides live in `data/prompts/{phase}.md`

**Prompt loading** (`prompt.py`):
- `load_prompt(name)` — reads `data/prompts/{name}.md`; returns `""` if missing

**Prephase** (`prephase.py:run_prephase()`): reads `/AGENTS.MD` from VM → `parse_agents_md()` → section index; executes `.schema` + PRAGMA queries to build `schema_digest`.

**Trace logging** (`trace.py`): thread-local `TraceLogger` writes structured JSONL. Attach with `set_trace(logger)`; read with `get_trace()`. Records: `header`, `llm_call`, `gate_check`, `sql_validate`, `sql_execute`, `task_result`.

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools take priority over reads
- `_run_learn` in `pipeline.py` — `error_type="llm_fail"` skips rule extraction (just restarts cycle); `"semantic"` adds rule to `learn_ctx`
- System prompt blocks passed as `list[dict]` (Anthropic multi-block format): `[{"type":"text","text":unified_context}, {"type":"text","text":guide,"cache_control":{"type":"ephemeral"}}]`
- `check_retry_loop` in pipeline is the standalone anti-infinite-loop guard
