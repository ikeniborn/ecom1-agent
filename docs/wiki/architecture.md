# Architecture

The ecom1-agent is a benchmark harness client that drives an LLM agent against the BitGN evaluation service. `main.py` is the entry point: it connects to the harness, runs each trial, and (optionally) loops training cycles. Per task, `agent/orchestrator.py:run_agent()` opens a VM, reads `/AGENTS.MD`, gathers deterministic pre-phase facts, and dispatches to the one pipeline. See [[pipeline]] for what happens after dispatch.

## Entry Point and Bootstrapping

`main.py` is the executable entry. Before any imports of the agent, it calls `_setup_logging()` (`main.py:88`) to create a timestamped run directory under `logs/`, open `main.log`, and wrap stdout so each line is prefixed with the active `[task_id]`. It then reads `models.json` and requires `ECOM_MODEL` to be set.

`__main__` (`main.py:453`) dispatches on argv: `--promote` routes to `_promote_entry()` (the offline atom-promotion gate, see [[oracle]]), otherwise `main()` runs the benchmark. `_setup_logging()` runs at import time (`main.py:88`), parsing `.env` itself to resolve `ECOM_MODEL`/`ECOM_LOG_LEVEL` for the run-dir name. Run config comes from env: `BITGN_URL`/`ECOM_BENCHMARK_HOST`, `ECOM_BENCHMARK_ID`, `ECOM_BITGN_API_KEY`, `ECOM_PARALLEL_TASKS`, and `ECOM_TRAIN_MAX_CYCLES` (`main.py:103`–`109`).

## BitGN Harness Driving

`main()` drives the harness through the generated `HarnessServiceClientSync` ([[proto-api]]). It first calls `Status` and `GetBenchmark` to print the policy, task count, and description (`main.py:291`–`297`), then enters the training loop. Each pass is one `StartRun → trial loop → SubmitRun`.

`_run_one_pass()` (`main.py:240`) issues `StartRunRequest` to obtain `run_id` and `trial_ids`, then submits each trial to a `ThreadPoolExecutor` sized by `ECOM_PARALLEL_TASKS`. As futures complete they are collected into `pending`, keyed by `task_id`. The `finally` block always calls `SubmitRunRequest(run_id, force=True)` — so the run is submitted even on partial failure — and hands the result to `_settle_scores()`.

## Per-Trial Execution

`_run_single_task()` (`main.py:130`) runs one trial. It calls `StartTrial` to get the `task_id` and `instruction`; if a `task_filter` is active and the task is excluded, it immediately calls `EndTrial` and returns a "filtered" marker. Otherwise it sets up a per-task `TraceLogger`, invokes the agent, and always calls `EndTrial` for the trial.

The trace filename is `{task_id}.jsonl` on the first cycle and `{task_id}.c{N}.jsonl` on later training cycles so passes don't overwrite each other (`main.py:146`). The agent itself is invoked as `run_agent({}, trial.harness_url, instruction, task_id=task_id)` (`main.py:156`); any exception is caught and printed so one task's failure doesn't abort the pool. The returned token/cycle stats are propagated back for scoring and the final table.

## Training-Mode Outer Loop

`main()` wraps the StartRun/SubmitRun pass in an outer loop over `cycle = 1..TRAIN_MAX_CYCLES` (`main.py:306`). With the default `ECOM_TRAIN_MAX_CYCLES=1` this is a single pass. When greater than 1, each cycle is a fresh `StartRun → SubmitRun`, and later cycles retry only the tasks that scored `< 1.0` in the prior pass.

After each pass, `main()` walks the settled scores: every task is recorded in `final_state`, and any task with `score < 1.0` is appended to `next_filter`. For those failing tasks, when not on the final cycle, `learn_from_grader(task_id, detail)` distills the grader feedback into a LEARN rule without re-running INTENT/PLAN (`main.py:326`, see [[learning]]). The loop breaks early when `next_filter` is empty (all targeted tasks passed). The narrowed `next_filter` becomes the next cycle's `current_filter`.

## Score Settlement and Persistence

Scores are not known at trial completion — they arrive only at `SubmitRun`. `_settle_scores()` (`main.py:354`) matches `SubmitRunResponse.trials` back to the `pending` per-task data by `task_id`, computes the score (`0.0` when unavailable), and finalizes each trace via `_finalize_task_trace()`.

For any task that scored `< 1.0` with a score available, it calls `save_last_run()` (status `failure`) and `write_verdict()` to persist the grader verdict alongside the submitted answer ([[data-files]], [[learning]]). It also counts incomplete trials and closes traces for tasks the submit response never echoed back (e.g. sealed/blind eval runs that return no per-trial scores). `main()` then prints the final statistics table and the final benchmark score if available (`main.py:337`–`346`).

## Orchestrator: run_agent

`run_agent()` (`orchestrator.py:548`) is the per-task seam between harness and pipeline. It constructs an `EcomRuntimeClientSync` from the trial's `harness_url`, reads `/AGENTS.MD` inline via `_read_agents_md()` (trying both `/AGENTS.MD` and `/AGENTS.md`), then wraps the raw client in a `VMAdapter` ([[vm]]).

It gathers deterministic pre-phase facts via `gather_prephase_facts()`, logs them to the trace (guarded so observability can never break a run), augments the AGENTS.MD text with the discovered DB schema and sample rows via `_augment_agents_md()`, and calls `run_pipeline(vm, instruction, task_id, agents_md_text, facts)` ([[pipeline]]). It returns a metrics dict — `model_used`, `cycles_used`, `outcome`, token counts, and the answer message/refs — consumed by `main.py` for scoring and tracing.

## Pre-Phase Fact Gathering

`gather_prephase_facts()` (`orchestrator.py:393`) builds a `PrePhaseFacts` object (`orchestrator.py:230`) entirely deterministically — zero LLM calls in the typical path — so the pipeline starts with concrete VM context instead of an exploratory step. Every fact records an `ok | empty | error(...)` status in `gather_status` (no silent empties).

It discovers the SQLite schema and table names via `/bin/sql`, samples top-N rows only from instruction-relevant tables (`_relevant_tables`, gated by lexical match plus learned `prephase_deep_read` hints), parses caller identity from `/bin/id` and classifies it structurally (`customer`/`employee`/`guest`), walks the `/docs` tree for a doc inventory, and loads policy docs (`security.md`, path-named docs, plus entity-token `Search` hits). It also resolves `target_records` by probing VM-discovered `/proc/<subdir>/<id>.json` files for record-id literals, and renders literal-path directory listings. The only LLM touch is `_doc_select_fallback()` ([[llm]]), invoked solely when entity-token `Search` returns no doc hits. Cost is bounded by env-tunable caps (`ECOM_PREPHASE_PATH_LITERALS`, `ECOM_PREPHASE_LISTING_BYTES`, `ECOM_PREPHASE_SAMPLE_ROWS`, `ECOM_PREPHASE_SAMPLE_ROW_CHARS`).

## Per-Task Execution Flow (High Level)

There is exactly one pipeline: the deterministic Plan-IR interpreter. Once `run_agent` calls `run_pipeline`, the flow is INTENT → loop[PLAN → lint → interpret → verify → answer-once] → CLARIFICATION, with `vm.answer` invoked exactly once per task.

INTENT is a single reason-tier LLM call, frozen for the run. The loop runs up to `ECOM_INTERPRETER_MAX_STEPS` cycles: each cycle a PLAN call emits a `PlanIR`, which is repaired (`repair_sql_stdin`) then linted via the registry dispatcher (`lint`), interpreted against the VM (no LLM), then checked by the deterministic `verify()` gate — the only quality gate before answering. Pass calls `vm.answer` exactly once (idempotency guard) and persists artifacts; fail feeds an iLEARN step and retries. Loop exhaustion or a no-progress (identical-plan) short-circuit yields a terminal clarification. Full detail lives in [[pipeline]], with the executor in [[interpreter]], the lint registry in [[harness]], knowledge injection in [[oracle]], and the LEARN mechanism in [[learning]].

## Policy-doc flow and observability backbone

Two cross-cutting additions landed with the agent-observability workstream. First, **policy-doc content now reaches PLAN**: `_PLAN_KEYS` in `agent/reason.py` includes `policies`, so `_facts_block(..., tier="plan")` renders each loaded policy as a `## POLICY {path}` block in the PLAN user message, and the orchestrator reads `/docs` literal bodies into `facts.policies` (not just their paths). This means a task requiring a policy rule to resolve correctly no longer needs PLAN to perform a separate `Read` discovery step for the policy doc. See [[pipeline#Tiered pre-phase facts]].

Second, **trace schema v2** (`agent/trace.py`) provides a structured observability backbone: every JSONL record carries a global monotonic `seq` and a `step_type` from a fixed taxonomy, VM RPCs log `validation`/`bytes`/`has_data`/`duration_ms`, and deterministic gate verdicts (LINT/INTERPRET/VERIFY) emit `gate` records. Reasoning capture (`agent/reasoning_capture.py`) tees chain-of-thought into `llm_call` records when `ECOM_TRACE_REASONING=1`. The explicit tool catalog (`agent/tools.py`) grounds the PLAN prompt and validates every RPC dispatch structurally. See [[tooling#Trace schema v2]], [[tooling#Tool catalog]], [[tooling#Reasoning capture]], and [[tooling#Agent report]].

## Makefile Targets

The `Makefile` provides thin `uv run` wrappers kept aligned with the README so a fresh checkout runs trivially. See [[tooling]] for the broader command surface.

- `make sync` → `uv sync` (install all deps).
- `make run` → `uv run python main.py` (run all benchmark tasks).
- `make report` → `uv run python scripts/run_report.py` (generate the run report).
- `make task TASKS='t01 t03'` → `uv run python main.py $(TASKS)`; errors out with a usage hint if `TASKS` is empty (`Makefile:15`).
- `make promote` → `uv run python main.py --promote`, the offline atom-promotion gate ([[oracle]]).
