# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                          # install all deps
uv run python main.py                            # run all benchmark tasks
make task TASKS='t01,t03'                        # run specific tasks

uv run python -m pytest tests/ -v               # all tests
uv run pytest tests/test_pipeline_v2.py -v      # single file
uv run pytest tests/test_pipeline_v2.py::test_name -v  # single test

make proto                                       # rebuild protobuf stubs (requires buf)
```

## Environment Variables

Copy from `.env.example` + `.secrets.example`. Core vars:

| Var | Purpose |
|-----|---------|
| `MODEL` | Primary LLM (`anthropic/claude-sonnet-4-6`, `openrouter/…`, `ollama/…`, or bare Ollama name) |
| `MODEL_FALLBACK` | Fallback model after primary exhausts all tiers |
| `MODEL_LEARN` | Override for LEARN phase (defaults to `MODEL`) |
| `MODEL_CODEGEN` | Override for CODEGEN phase (defaults to `MODEL`) |
| `MAX_TOKENS_DESIGN` | Max tokens for DESIGN phase response (default 4096) |
| `MAX_TOKENS_CODEGEN` | Max tokens for CODEGEN phase response (default 8192) |
| `MAX_TOKENS_LEARN` | Max tokens for LEARN phase response (default 2048) |
| `FIDELITY_TIMEOUT_S` | Subprocess timeout for fidelity gate (default 30) |
| `MAX_STEPS` | Pipeline cycle limit per task (default 3) |
| `LOG_LEVEL=DEBUG` | Full LLM response logging |
| `OLLAMA_BASE_URL` | Ollama endpoint (default `http://localhost:11434/v1`) |
| `CC_ENABLED=1` | Enable Claude Code CLI tier (iclaude subprocess, OAuth) |
| `LLM_HTTP_READ_TIMEOUT_S` | HTTP read timeout in seconds (default 180) |

Credentials (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`) belong in `.secrets`, not `.env`.

## Architecture

Entry point: `main.py` → BitGN harness → `agent/orchestrator.py:run_agent()`

**Execution flow per task:**
1. `orchestrator.py:run_agent()` — opens VM, reads `/AGENTS.MD` directly, calls `run_pipeline`
2. `pipeline.py:run_pipeline(vm, instruction, task_id, agents_md_text)`:
   - **DESIGN** (1 LLM call, frozen for the run) — system: `design.md` + `proto-api-reference.md`. Input strictly `[instruction, AGENTS.MD]`. Output: `DesignOutput` (`intent`, `params`, `success_criteria`, `discovery`, `ops`, `agents_md_constraints`, `answer_template`, `outcome_override?`).
   - If `outcome_override` set → `vm.answer(...)` → END.
   - **LOOP** — single counter `cycle = 1..MAX_STEPS`:
     - **CODEGEN** (LLM call) — input: `[tool_plan, learn_ctx, prev_error?]`. Output: `CodegenOutput.script_code` (a module exposing `run(vm, params)`).
     - **AST lint** — `ast.parse(script_code)`; on `SyntaxError` → LEARN+CONSOLIDATE → next cycle.
     - **check_retry_loop** — extract literal SQL via `ast.walk` over `vm.exec(path="/bin/sql", args=[...])`; compare normalised multiset to prior cycle; identical → break with CLARIFICATION.
     - **Fidelity gate** — `agent/fidelity.py:generate_fidelity_test(design, task_id)` emits a deterministic test; run in subprocess (`FIDELITY_TIMEOUT_S=30s`). Mismatch → LEARN+CONSOLIDATE → next cycle.
     - Pass → break.
   - **ANSWER terminal one-shot** — exec script on real VM (`run(vm, params)`); the script calls `vm.answer(...)` itself. On any real-VM exception → terminal `OUTCOME_NONE_CLARIFICATION`.
   - On loop exhaust → terminal `OUTCOME_NONE_CLARIFICATION`.
3. `learned_store.py` — `load_entries(tid)` (active only), `apply_learn_diff(tid, LearnConsolidateOutput)`, `save_last_run(tid, status, outcome, cycles_used)`.

**LLM call budget:** 1 (hard-stop) / 2 (best happy path) / 7 (worst, `MAX_STEPS=3`).

**LLM routing** (`llm.py`): provider prefix determines tier — `anthropic/` → Anthropic SDK; `openrouter/` → OpenRouter; `ollama/` or bare name → local Ollama; `claude-code` → CC CLI subprocess. All tiers tried in order per `models.json` before falling through to `MODEL_FALLBACK`.

**Protobuf layer:** `bitgn/` = generated stubs for harness + ECOM + PCM services. Source protos in `proto/`. Regenerate with `make proto`.

## Key Data Files

| Path | Purpose |
|------|---------|
| `data/prompts/*.md` | Phase guides: `design`, `codegen`, `learn` only |
| `data/learned/{task_id}.yaml` | Per-task active+inactive LearnConsolidate rules; `last_run` carries `status/outcome/cycles_used/date` only (no `heuristic_valid`, no `schema_hash`) |
| `data/heuristics/{task_id}.py` | Last successful or last-attempted heuristic script. Reference only — pipeline always regenerates via DESIGN + CODEGEN. |
| `models.json` | Per-model provider hints and Ollama options (e.g. `num_ctx`) |

## Notable Constraints

- JSON extraction priority in `json_extract.py` is load-bearing: mutation tools (write/delete) take priority over reads to avoid spurious tool calls
- `check_retry_loop` in `sql_security.py` is a standalone anti-infinite-loop guard
- `agent/CLAUDE.md` covers agent-package internals and mirrors this file's architecture section

## Prompt Engineering Rules

**System prompts (`data/prompts/*.md`) contain only general structural rules.**

- Allowed: action forms, output format, SQL constraints, generic decision patterns
- Forbidden: task-specific domain rules, per-task-type heuristics, scenario-specific sequences

All task-specific knowledge must flow through the LEARN mechanism into `data/learned/{task_id}.yaml`.
Never patch `data/prompts/` to fix a task failure — fix the LEARN trigger or learned rule instead.
