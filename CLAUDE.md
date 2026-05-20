# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                          # install all deps
uv run python main.py                            # run all benchmark tasks
make task TASKS='t01,t03'                        # run specific tasks

uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline.py -v         # single file
uv run pytest tests/test_pipeline.py::test_name -v  # single test

make proto                                       # rebuild protobuf stubs (requires buf)
```

## Environment Variables

Copy from `.env.example` + `.secrets.example`. Core vars:

| Var | Purpose |
|-----|---------|
| `MODEL` | Primary LLM (`anthropic/claude-sonnet-4-6`, `openrouter/…`, `ollama/…`, or bare Ollama name) |
| `MODEL_FALLBACK` | Fallback model after primary exhausts all tiers |
| `MODEL_ASSEMBLER` | LLM for unified_context assembly (defaults to `MODEL`) |
| `MODEL_SDD` | Override for SDD phase (defaults to `MODEL`) |
| `MODEL_PLAN` | Override for PLAN phase (defaults to `MODEL`) |
| `MODEL_LEARN` | Override for LEARN phase (defaults to `MODEL`) |
| `MAX_STEPS` | Pipeline cycle limit per task (default 3) |
| `MAX_TOKENS_SDD` | Max tokens for SDD phase response (default 8192) |
| `MAX_TOKENS_PLAN` | Max tokens for PLAN phase response (default 4096) |
| `MAX_TOKENS_LEARN` | Max tokens for LEARN phase response (default 2048) |
| `MAX_TOKENS_ANSWER` | Max tokens for ANSWER phase response (default 4096) |
| `MAX_TOKENS_ASSEMBLER` | Max tokens for ASSEMBLER phase response (default 4096) |
| `LOG_LEVEL=DEBUG` | Full LLM response logging |
| `OLLAMA_BASE_URL` | Ollama endpoint (default `http://localhost:11434/v1`) |
| `CC_ENABLED=1` | Enable Claude Code CLI tier (iclaude subprocess, OAuth) |
| `LLM_HTTP_READ_TIMEOUT_S` | HTTP read timeout in seconds (default 180) |

Credentials (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`) belong in `.secrets`, not `.env`.

## Architecture

Entry point: `main.py` → BitGN harness → `agent/orchestrator.py:run_agent()`

**Execution flow per task:**
1. `prephase.py:run_prephase()` — fetches `/AGENTS.MD` (vault rules), reads `.schema` + PRAGMA, builds `schema_digest` and `agents_md_index`
2. `pipeline.py:run_pipeline()` — main loop (max `MAX_STEPS` cycles):
   - **ASSEMBLE** → `prompt_assembler.py:assemble_prompt()` — 1 LLM call builds `unified_context` from learned knowledge, vault, and schema
   - **SDD** → LLM call with `[unified_context, sdd_guide]` → `json_extract.py` → `SddOutput`
   - **SCHEMA CHECK** → `schema_gate.py` validates column/table names
   - **VALIDATE** → EXPLAIN check for SQL syntax
   - **TDD** → `test_runner.py` generates and runs SQL+answer tests (always enabled)
   - **EXECUTE** → runs SQL on ECOM VM via Connect-RPC
   - **ANSWER** → LLM with `[unified_context, answer_guide]` → `AnswerOutput` → `vm.answer()`
   - On any phase failure: **LEARN** → LLM with `[unified_context, learn_guide]` → appends rule to `learn_ctx` → next cycle
   - On success: marks in-session learn entries active; they persist in `data/learned/{task_id}.yaml`
   - On all cycles exhausted: in-session learn entries remain written incrementally via `_apply_learn_diff`

**Prompt assembly** (`prompt_assembler.py:assemble_prompt()`):
- Called once per cycle with current `learn_ctx`
- Sources assembled: learned knowledge from `data/learned/{task_id}.yaml` (highest priority) → vault rules → schema
- LLM produces single `unified_context` doc with sections: `# LEARNED`, `# BASE`
- Each phase then gets `[unified_context, phase_guide]` as system — phase guide is `data/prompts/{phase}.md`

**LLM routing** (`llm.py`): provider prefix determines tier — `anthropic/` → Anthropic SDK; `openrouter/` → OpenRouter; `ollama/` or bare name → local Ollama; `claude-code` → CC CLI subprocess. All tiers tried in order per `models.json` before falling through to `MODEL_FALLBACK`.

**Protobuf layer:** `bitgn/` = generated stubs for harness + ECOM + PCM services. Source protos in `proto/`. Regenerate with `make proto`.

## Key Data Files

| Path | Purpose |
|------|---------|
| `data/prompts/*.md` | Phase guides: `sdd`, `tdd`, `learn`, `answer`, `assembler` |
| `data/learned/{task_id}.yaml` | Permanent per-task knowledge base; entries have active/inactive status; never deleted on success |
| `models.json` | Per-model provider hints and Ollama options (e.g. `num_ctx`) |

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools (write/delete) take priority over reads to avoid spurious tool calls
- `check_retry_loop` in `sql_security.py` is a standalone anti-infinite-loop guard
- `agent/CLAUDE.md` covers agent-package internals and mirrors this file's architecture section
