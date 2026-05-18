# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                          # install all deps
uv run python main.py                            # run all benchmark tasks
make task TASKS='t01,t03'                        # run specific tasks
EVAL_ENABLED=1 uv run python main.py             # run with evaluator

uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline.py -v         # single file
uv run pytest tests/test_pipeline.py::test_name -v  # single test

uv run python scripts/propose_optimizations.py --dry-run  # preview suggestions
uv run python scripts/propose_optimizations.py            # auto-apply to data/

make proto                                       # rebuild protobuf stubs (requires buf)
```

## Environment Variables

Copy from `.env.example` + `.secrets.example`. Core vars:

| Var | Purpose |
|-----|---------|
| `MODEL` | Primary LLM (`anthropic/claude-sonnet-4-6`, `openrouter/…`, `ollama/…`, or bare Ollama name) |
| `MODEL_FALLBACK` | Fallback model after primary exhausts all tiers |
| `MODEL_EVALUATOR` | LLM for evaluation scoring; if unset evaluator is disabled |
| `MODEL_ASSEMBLER` | LLM for unified_context assembly (defaults to `MODEL`) |
| `MODEL_SDD` | Override for SDD phase (defaults to `MODEL`) |
| `MODEL_LEARN` | Override for LEARN phase (defaults to `MODEL`) |
| `EVAL_ENABLED=1` | Run evaluator after each successful task |
| `MAX_STEPS` | Pipeline cycle limit per task (default 3) |
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
   - **ASSEMBLE** → `prompt_assembler.py:assemble_prompt()` — 1 LLM call builds `unified_context` from rules, security gates, vault, schema, and `learn_ctx`
   - **SDD** → LLM call with `[unified_context, sdd_guide]` → `json_extract.py` → `SddOutput`
   - **SCHEMA CHECK** → `schema_gate.py` validates column/table names
   - **VALIDATE** → EXPLAIN check for SQL syntax
   - **TDD** → `test_runner.py` generates and runs SQL+answer tests (always enabled)
   - **EXECUTE** → runs SQL on ECOM VM via Connect-RPC
   - **ANSWER** → LLM with `[unified_context, answer_guide]` → `AnswerOutput` → `vm.answer()`
   - On any phase failure: **LEARN** → LLM with `[unified_context, learn_guide]` → appends rule to `learn_ctx` → next cycle
   - On success: writes `eval_log` entry (with `learn_ctx`), clears persisted learn_ctx, optionally runs evaluator
   - On all cycles exhausted: persists `learn_ctx` to `data/learned/{task_id}.yaml` for next run

**Prompt assembly** (`prompt_assembler.py:assemble_prompt()`):
- Called once per cycle with current `learn_ctx`
- Sources assembled: `learn_ctx` (highest priority) → `data/rules/*.yaml` → `data/security/*.yaml` → task_blocks from `data/config/task_blocks.yaml` → vault rules → schema
- LLM produces single `unified_context` doc with sections: `# LEARNED`, `# RULES`, `# SECURITY`, `# BASE`
- Each phase then gets `[unified_context, phase_guide]` as system — phase guide is `data/prompts/{phase}.md`

**LLM routing** (`llm.py`): provider prefix determines tier — `anthropic/` → Anthropic SDK; `openrouter/` → OpenRouter; `ollama/` or bare name → local Ollama; `claude-code` → CC CLI subprocess. All tiers tried in order per `models.json` before falling through to `MODEL_FALLBACK`.

**Optimization loop** (`scripts/propose_optimizations.py`):
- Reads `data/eval_log.jsonl` (only `outcome=ok` entries)
- Synthesizes suggestions via LLM, checks existing rules/gates to avoid duplicates
- **Auto-applies** all optimizations with `verified: true` directly to `data/`:
  - `rule_optimization` → `data/rules/sql-NNN.yaml`
  - `security_optimization` → `data/security/sec-NNN.yaml`
  - `prompt_optimization` → appended to existing `data/prompts/<target>.md`

**Protobuf layer:** `bitgn/` = generated stubs for harness + ECOM + PCM services. Source protos in `proto/`. Regenerate with `make proto`.

## Key Data Files

| Path | Purpose |
|------|---------|
| `data/rules/*.yaml` | SQL planning rules; only `verified: true` rows are loaded |
| `data/security/*.yaml` | Security gates (regex pattern or named check); `verified: true` to activate |
| `data/prompts/*.md` | Phase guides: `sdd`, `tdd`, `learn`, `answer`, `assembler`, `pipeline_evaluator` |
| `data/config/task_blocks.yaml` | Maps task_type (`sql`/`compute`/`default`) to extra prompt block stems |
| `data/learned/{task_id}.yaml` | Persisted `learn_ctx` from failed runs; loaded at next run, cleared on success |
| `data/eval_log.jsonl` | Per-task evaluation results (success-only); includes `learn_ctx` field |
| `models.json` | Per-model provider hints and Ollama options (e.g. `num_ctx`) |

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools (write/delete) take priority over reads to avoid spurious tool calls
- `check_retry_loop` in `sql_security.py` is an anti-infinite-loop guard (kept in pipeline); `check_sql_queries`/`check_where_literals` were removed — security context now flows through `unified_context`
- `_rules_loader_cache` and `_security_gates_cache` in `pipeline.py` are module-level — call `tests/conftest.py:reset_pipeline_caches()` fixture to clear between tests
- `propose_optimizations.py` synthesizers receive existing rules/prompts to prevent duplicate generation — preserve the `_existing_*` helpers if refactoring
- `eval_log` is written **only on success** (outcomes: ok, DENIED_SECURITY, UNSUPPORTED); failed/exhausted runs do not write eval_log
- RESOLVE phase stubs remain in `pipeline.py` for backward compat but are no-ops; `confirmed_values` is no longer populated
- `agent/CLAUDE.md` covers agent-package internals and mirrors this file's architecture section
