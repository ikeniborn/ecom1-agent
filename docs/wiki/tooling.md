# Tooling

Developer-facing scripts that live outside the pipeline: HTML run reports, JSONL trace inspection, two one-off data migrations, and a deterministic diagram generator. Each is a standalone CLI run via `uv`. See [[architecture]] for the pipeline they observe.

## Run Report

`scripts/run_report.py` builds one self-contained HTML page from `logs/` — rows are tasks, columns are runs (one per `logs/<YYYYMMDD_HHMMSS_model>/` dir). It uses stdlib + pyyaml only.

Invoke it as `uv run python scripts/run_report.py` (defaults `logs/` → `logs/report.html`), with optional `--out`, `--logs`, `--learned`, `--atoms`, `--history` overrides. `main()` (`scripts/run_report.py:425`) discovers runs (`scripts/run_report.py:36`), parses each task's latest `.jsonl` — preferring the highest training cycle `tNN.cN` (`scripts/run_report.py:138`) — reads the final `task_result`/`answer` record for outcome, cycles, and `score_detail` (`scripts/run_report.py:100`), then renders the page (`scripts/run_report.py:399`).

The page stacks: a **RESULTS** status grid, **CYCLES** and **ERRORS** heatmaps, a **LEARNED** per-day rule-creation heatmap (a cell lights only when a rule's `created` date equals the run's date — creation, not cumulative; `scripts/run_report.py:323`), an **Oracle** section over `data/oracle/atoms.yaml` (status / source-task / domain breakdowns; `scripts/run_report.py:342`), an **Error Report** of normalized error categories, and a **Failures — Correct Answers** section. Errors are categorized by `normalize_error_key` (`scripts/run_report.py:56`): drop `[pipeline] ` prefix, strip quoted strings, drop path-like tokens, remove digit runs, collapse whitespace — no truncation. Each report run also appends a growth line to `data/oracle/history.jsonl` (`scripts/run_report.py:197`).

## Failures — Correct Answers section

A dedicated table in the run report listing every failing `(task, run)` pair alongside the raw grader `score_detail` — the "correct answer" the platform returned for a failed task.

Built by `_failures_table` (`scripts/run_report.py:376`). A cell counts as a failure iff `cell.errors` is non-empty, since the grader only populates `score_detail` when `score < 1.0`. Unlike the Error Report, the feedback is rendered **raw** (not passed through `normalize_error_key`), so quoted expected values survive verbatim — making it directly useful for debugging the [[learning]] loop and `learn_from_grader`.

## Trace View

`scripts/trace_view.py` pretty-prints a per-task trace JSONL (`logs/<run>/<task_id>.jsonl`). It is a thin CLI over `agent.trace.render_trace` — the same renderer that writes the auto `{task_id}.detail.log`.

Invoke with a file path to render one trace, or a run directory to list available traces (`scripts/trace_view.py:42`): `uv run python scripts/trace_view.py logs/<run>/t09.jsonl`. The script inserts the repo root on `sys.path` so it runs from anywhere (`scripts/trace_view.py:23`). The timeline shows pre-phase facts, each VM RPC and result head, the LLM conversation per phase/cycle, the projected/captured answer (message + outcome + refs), and the final result. Flags: `--phase <NAME>` to filter one phase, `--no-system` / `--full-system` to control system-prompt display, `--llm-only` to hide non-LLM events, and `--max-chars N` to truncate bodies. See [[proto-api]] for the RPCs that appear in the timeline.

## Reasoning Trace

`scripts/trace_t38.py` is a thin harness that runs ONE benchmark task through the real pipeline against a live trial, recording an enriched JSONL trace that includes chain-of-thought reasoning and un-stripped raw responses per LLM call. The reasoning capture now delegates entirely to the production `agent/reasoning_capture.py` machinery (active when `ECOM_TRACE_REASONING=1`) — no monkeypatching; the script sets the env var and imports the agent normally.

Invoke from anywhere (the script `chdir`s to the repo root): `uv run python scripts/trace_t38.py [task_id] [model]` — defaults `t38` / `deepseek-v4-flash:cloud`; CC example `… t38 claude-code/haiku`. It forces `ECOM_MODEL` and `ECOM_TRACE_REASONING=1` before importing `agent.llm`, locates the named task's trial (StartRun → start each trial, end non-matching), runs it, then SubmitRun for the grader score. Outputs (under `logs/trace_<task>_<ts>_<model>/`): `<task>.jsonl` (v2 trace with `seq`, `prev_llm_seq`, `reasoning`, `raw_response_full`, `cache_read`/`cache_creation`), the auto `<task>.detail.log`. See [[tooling#Reasoning capture]] for the per-provider capture seams; see [[pipeline#run_pipeline]] for the phases traced.

## Migrate Learned

`scripts/migrate_learned.py` is a one-time, idempotent migration converting flat-list `data/learned/{task_id}.yaml` files into the current entry-schema format used by the [[learning]] store.

Run once via `uv run python scripts/migrate_learned.py` before the first pipeline run after deploying the learned-knowledge redesign; it is safe to re-run because it skips any file already containing an `entries` key (`scripts/migrate_learned.py:30`). For each old file it reads the `learn_ctx` list and rewrites it as `entries`, one per non-empty rule string, assigning `id` (`r001`, `r002`, …), `status: active`, `source: learn`, today's `created` date, and empty `reasoning`/`deactivated_reason` (`scripts/migrate_learned.py:38`). It prints a per-file MIGRATED/SKIP line and a final count.

## Migrate Rules to Atoms

`scripts/migrate_rules_to_atoms.py` is a one-off operator step that distils existing per-task learned rules into general knowledge-oracle atoms as **candidates** — nothing is promoted automatically.

Run with `uv run python -m scripts.migrate_rules_to_atoms`. As written, `main()` (`scripts/migrate_rules_to_atoms.py:23`) walks `data/learned/*.yaml` and prints the intended pipeline: run `KnowledgeOracle().distill` per active rule, then `dedup_by_cosine`. The module ships a working `dedup_by_cosine` helper (`scripts/migrate_rules_to_atoms.py:13`) that drops any atom whose cosine similarity to an already-kept atom meets a threshold, reusing `agent.oracle._cosine`. Distilled candidates land in `data/oracle/atoms.yaml`; the LLM + embeddings backend is required. See [[learning]] for how atoms are retrieved into PLAN.

## Trace schema v2

Every JSONL record in `logs/<run>/<task>.jsonl` carries a global monotonic `seq` (scoped to the task logger, incremented on every `_write`) and a `step_type` from a fixed taxonomy: `PREPHASE_GATHER`, `DOC_SELECT`, `ORACLE_RETRIEVE`, `INTENT`, `PLAN`, `LINT`, `INTERPRET`, `VERIFY`, `ILEARN`, `ANSWER`, `DISTILL`, `TASK_RESULT`. Record types and their v2 fields:

- **`llm_call`** — phase, `step_type` (via `_PHASE_TO_STEP_TYPE`; `RERANK`→`ORACLE_RETRIEVE`, `LEARN`→`ILEARN`), `prev_llm_seq` (links to prior LLM call in the same task), `reasoning`/`reasoning_available`, `raw_response_full` (unstripped), `cache_read`/`cache_creation` token counts (`agent/trace.py:148`).
- **`vm_call`** — `validation` (`ok` or `fail(reason)` from the tool-catalog check), `bytes`, `has_data`, `duration_ms`; `step_type` mirrored to `phase` for backward-compatible readers (`agent/trace.py:279`).
- **`gate`** — `cycle`, `step_type` (`LINT`|`INTERPRET`|`VERIFY`), `passed`, `reason`. Emitted by `log_gate_auto` after each deterministic gate in the pipeline. Supersedes the older `gate_check` record type.
- **`lint_fire`** — `cycle`, `check_id`, `kind`, `severity`, `blocking`, `message`. One record per fired `data/harness/checks.yaml` check — blocking **and** warn-level — emitted by `log_lint_fire_auto` inside `lint()` (`agent/interpreter.py:277`), written by `TraceLogger.log_lint_fire` (`agent/trace.py:314`), and rendered as a `· [lint_fire] c<cycle> <check_id> [BLOCK|warn] <msg>` line by `render_trace` (`agent/trace.py:486`). Where `gate` records only the aggregate LINT pass/block, `lint_fire` captures every individual check that fired, including non-blocking warns the gate hides. Consumed by [[tooling#Lint Report]].

Thread-local helpers `log_vm_auto` / `log_gate_auto` / `log_lint_fire_auto` (`agent/trace.py:514`) read the active `TraceLogger` and the thread-local `cycle`/`step_type` (set via `set_step_type`/`set_cycle`); they are best-effort and never raise into a run. The orchestrator sets `step_type=PREPHASE_GATHER`; `interpret()` sets `step_type=INTERPRET` (see [[vm#VM-layer trace logging]]). See [[interpreter#Tool validation]] for how validation failures appear in `vm_call` records, and [[pipeline#Gate records]] for where `gate` records are emitted.

## Lint Report

`scripts/lint_report.py` is an offline aggregator over the `lint_fire` telemetry (see [[tooling#Trace schema v2]]). It scans a directory of trace JSONL files recursively and prints a table ranked by total fires, so the most-frequently-firing `data/harness/checks.yaml` checks are visible across a whole benchmark run — the signal for deciding which harness anti-pattern most needs a positive [[oracle]] method-atom (a future harness→oracle feedback bridge).

Invoke as `uv run python scripts/lint_report.py [trace_dir]` (default `logs`). `aggregate(trace_dir)` (`scripts/lint_report.py:20`) tallies per `check_id`: total fires, blocked vs warned counts, distinct tasks, and a sample message; malformed JSONL lines and unreadable files are skipped (telemetry never crashes). `render(stats)` (`scripts/lint_report.py:53`) emits the ranked table, or `no lint_fire records` when empty. Pure stdlib — no LLM, no grader. See [[harness]] for the checks whose firings it counts and [[interpreter#lint — registry-driven lint dispatcher]] for where the records originate.

## Reasoning capture

`agent/reasoning_capture.py` tees per-provider chain-of-thought into a thread-local sink, active only when `ECOM_TRACE_REASONING=1`. Provider seams: Ollama/OpenRouter wrap the OpenAI `.chat.completions.create` call and extract `reasoning_content`/`reasoning` fields or `<think>…</think>` inline; Anthropic wraps `messages.create` and collects `thinking`-type blocks; claude-code swaps the spawn to `--output-format stream-json --verbose` and parses `thinking`/`redacted_thinking` blocks from the stream.

`install()` (`reasoning_capture.py:155`) is idempotent and wraps all three provider seams at import time (triggered by `agent.llm` import). `call_llm_raw` calls `pop_capture()` after each LLM call and folds the result into the `llm_call` record's `reasoning` / `raw_response_full` fields. On any failure, `reasoning_available=false` is recorded; the capture never interferes with the run. See [[llm#Named phases]] for how `phase=` is threaded through `call_llm_raw`.

## Tool catalog

`agent/tools.py` is the single source of truth for the VM RPC surface. `TOOL_CATALOG` is a declarative dict keyed by RPC name (`Read`, `List`, `Tree`, `Find`, `Search`, `Exec`, `Write`, `Delete`, `Stat`) with `purpose`, `required`/`optional` arg key sets, `mode` (`read`|`mutate`), `when_to_use`, `example`, and an optional `note` (the `/bin/sql` stdin requirement for `Exec`).

`validate_step(rpc, args)` (`tools.py:93`) returns `None` on a valid (rpc, args) pair, or a precise error string: unknown rpc, extra arg key, or missing required arg. `build_tool_catalog_block()` (`tools.py:116`) renders the catalog as a Markdown block injected into the PLAN system prompt by `run_plan` (`reason.py:149`), replacing the ad-hoc RPC table that was previously inline in `data/prompts/plan.md`. A drift-guard test keeps catalog arg-key declarations ⊆ actual proto fields. See [[interpreter#Tool validation]] for how `validate_step` is called before every dispatch.

## Agent report

`scripts/agent_report.py` builds a self-contained HTML report directly from v2 JSONL traces (no `logs/` run-dir convention; any JSONL file works). It includes a **run-overview grid** (outcome/score/cycles/tokens including cache_read+cache_creation/elapsed/facts-overlap), error and tool-usage summaries, and a **per-task drill-down**: a `seq`-ordered timeline colored by `step_type`, inline cycle SVG, tool-call table with validation status, and collapsible reasoning panels.

The **prompt-redundancy metric** (`facts_overlap`) is a `difflib.SequenceMatcher` ratio over the shared `PRE-PHASE FACTS:` block extracted from the INTENT and PLAN user messages. A high ratio flags wasted tokens (PLAN pays to re-read facts INTENT already consumed). Invoke as `uv run python scripts/agent_report.py --logs logs/<run_dir> --out docs/reports/agent-report.html`. The parser halts on an unreadable trace rather than fabricating data. See [[tooling#Trace schema v2]] for the record types it consumes.

## Generate Excalidraw

`tools/gen_excalidraw.py` is a deterministic Excalidraw generator for the agent architecture guide: same input → byte-identical output (no time, no randomness), so the diagram can be regenerated and committed reproducibly.

Run with `uv run python tools/gen_excalidraw.py`, writing `docs/architecture/agent-architecture.excalidraw` (`tools/gen_excalidraw.py:475`). It emits one canvas of four stacked frame regions plus a legend strip (`tools/gen_excalidraw.py:479`): Diagram 1 — end-to-end harness → IR-only pipeline flow; Diagram 2 — the PLAN → lint → interpret → verify cycle and gates; Diagram 3 — `interpret()` + `verify()` internals; Diagram 4 — cross-cutting subsystems (LEARN store, oracle, LLM routing, trace). Diagrams are declared as `Node`/`Edge`/`Diagram` specs (`tools/gen_excalidraw.py:89`); `render_diagram` places rows top-down, sizes nodes to fit their labels, wraps them in a frame, and routes orthogonal edges through inter-row gaps or a right-side gutter lane (`tools/gen_excalidraw.py:222`). All ids and seeds are derived purely from element ids via an FNV-style hash (`tools/gen_excalidraw.py:48`), and `unique_ids` / `arrow_bindings_valid` (`tools/gen_excalidraw.py:317`) assert document validity. The shape vocabulary mirrors [[architecture]]: blue=LLM call, grey=deterministic gate, green=storage, yellow=branch, red-rounded=terminal.
