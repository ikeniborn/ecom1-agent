# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Authoritative CLAUDE.md is `../CLAUDE.md` (repo root). This file covers agent-package internals.**

## Commands

```bash
uv sync                                          # install all deps
uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline_v2.py -v      # single test file

LOG_LEVEL=DEBUG uv run python main.py           # full LLM response logging
```

Key env vars:
- `MODEL` — primary LLM (e.g. `anthropic/claude-sonnet-4-6`)
- `MAX_STEPS` — pipeline cycle limit (default: 3)
- `FIDELITY_TIMEOUT_S` — subprocess timeout for fidelity gate (default: 30)

## Agent Package Architecture

Entry: `orchestrator.py:run_agent()` → opens VM, reads `/AGENTS.MD` inline → `pipeline.py:run_pipeline()`

**Per-task execution flow:**

1. **DESIGN** (`design.py:run_design(instruction, agents_md_text)`) — 1 LLM call, frozen for the run. System prompt: `proto-api-reference.md` + `design.md` (both `cache_control: ephemeral`). Output: `DesignOutput` (intent, params, success_criteria, discovery, ops, agents_md_constraints, answer_template, outcome_override?).
2. If `outcome_override` set → `vm.answer(...)` → END.
3. **LOOP** (`cycle = 1..MAX_STEPS`):
   - **CODEGEN** (`codegen_v2.py:run_codegen(design, learn_ctx, prev_error)`) — LLM call → `CodegenOutput.script_code` (module exposing `run(vm, params)`).
   - **AST lint** — `ast.parse(script_code)`; on `SyntaxError` → LearnConsolidate → next cycle.
   - **check_retry_loop** — extract literal SQL via `ast.walk` over `vm.exec(path="/bin/sql", args=[...])`; multiset compare to prior cycle; identical → break with CLARIFICATION.
   - **Fidelity gate** (`fidelity.py:generate_fidelity_test` + `exec_fidelity_in_subprocess`) — emits deterministic expected-call test; runs script in subprocess (timeout `FIDELITY_TIMEOUT_S`). Mismatch → LearnConsolidate → next cycle.
   - Pass → break.
4. **ANSWER terminal one-shot** — exec script on real VM; the script calls `vm.answer(...)`. Any real-VM exception → terminal `OUTCOME_NONE_CLARIFICATION`.
5. Loop exhaust → terminal `OUTCOME_NONE_CLARIFICATION`.

**Persistence** (`learned_store.py`):
- `load_entries(tid)` — active entries only
- `apply_learn_diff(tid, LearnConsolidateOutput)` — write/deactivate
- `save_last_run(tid, status, outcome, cycles_used)`

**Pydantic models** (`models.py`):
- `DesignOutput` — intent, params, success_criteria, discovery[ToolOp], ops[ToolOp], agents_md_constraints[AgentsMdRef], answer_template[AnswerTemplate], outcome_override?
- `ToolOp` — rpc (Read|List|Tree|Find|Search|Exec|Write|Delete|Stat|Answer), args, bind?
- `AgentsMdRef` — anchor, rule
- `AnswerTemplate` — message, outcome, refs
- `CodegenOutput` — script_code
- `LearnConsolidateOutput` — rule_content, agents_md_anchor?, reasoning, deactivate_ids, deactivate_reason?, skip, skip_reason?
- `AnswerOutput` — message, outcome, grounding_refs

**LLM routing** (`llm.py:call_llm_raw()`): provider prefix → tier.
- `anthropic/` → Anthropic SDK (prompt caching via `cache_control` blocks)
- `openrouter/` → OpenRouter (OpenAI-compatible)
- bare name / `ollama/` → local Ollama
- `CC_ENABLED=1` → `cc_client.py` subprocess (Claude Code tier)

Transient errors (503, rate-limit, timeout) retry with exponential backoff.

**Prompt loading** (`prompt.py`):
- `load_prompt(name)` — reads `data/prompts/{name}.md`; returns `""` if missing
- Phase guides live in `data/prompts/{design,codegen,learn}.md`

**Trace logging** (`trace.py`): thread-local `TraceLogger` writes structured JSONL. Attach with `set_trace(logger)`; read with `get_trace()`. Records: `header`, `llm_call`, `gate_check`, `sql_validate`, `sql_execute`, `task_result`.

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools take priority over reads
- `check_retry_loop` in `sql_security.py` is the standalone anti-infinite-loop guard
- DESIGN signature is strictly `(instruction, agents_md_text)` — no `learn_ctx` (F-001 regression guard tests in `tests/test_design.py`)
- DESIGN is frozen for the run — `learn_ctx` updates only affect CODEGEN
- System prompt blocks passed as `list[dict]` (Anthropic multi-block format): `[{"type":"text","text":proto_ref}, {"type":"text","text":guide,"cache_control":{"type":"ephemeral"}}]`
