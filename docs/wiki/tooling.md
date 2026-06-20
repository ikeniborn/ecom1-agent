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

`scripts/trace_t38.py` runs ONE benchmark task through the real pipeline and records an enriched JSONL trace that — beyond the built-in `agent.trace` records — captures the model's chain-of-thought reasoning and the un-stripped raw response per LLM call. It exists because the production trace discards reasoning before it lands (see [[learning#trace.py (JSONL trace files)]]): `agent/llm.py` strips `<think>…</think>` and the Anthropic path keeps only `type="text"` blocks; the claude-code path requests `--output-format json`, whose envelope carries only the final text.

Invoke from anywhere (the script `chdir`s to the repo root): `uv run python scripts/trace_t38.py [task_id] [model]` — defaults `t38` / `deepseek-v4-flash:cloud`; CC example `… t38 claude-code/haiku`. It forces `ECOM_MODEL` before importing `agent.llm`, locates the named task's trial (StartRun → start each trial, end non-matching), runs it with an enriched `ReasoningTrace`, then SubmitRun for the grader score. No repo source is modified — only runtime monkeypatches.

Reasoning capture is per-provider: Ollama (`<think>` inline / `reasoning_content` / `reasoning`) and OpenRouter are teed at the OpenAI client `.create` seam; Anthropic thinking blocks at `messages.create`; claude-code is captured by swapping the spawn to `--output-format stream-json --verbose` and sniffing `thinking` blocks while `cc_client._parse_envelope` still reads the terminal `result` line unchanged. Outputs (under `logs/trace_<task>_<ts>_<model>/`): `<task>.jsonl` (enriched: `seq`, `cycle`, `phase`, `prev_llm_seq`, `reasoning`, `raw_response_full`), the auto `<task>.detail.log`, and `<task>.reasoning.md` (system/user/reasoning/response interleave). See [[pipeline#run_pipeline]] for the phases traced; an analysis built from these traces lives at `docs/reports/t38-trace-analysis.html`.

## Migrate Learned

`scripts/migrate_learned.py` is a one-time, idempotent migration converting flat-list `data/learned/{task_id}.yaml` files into the current entry-schema format used by the [[learning]] store.

Run once via `uv run python scripts/migrate_learned.py` before the first pipeline run after deploying the learned-knowledge redesign; it is safe to re-run because it skips any file already containing an `entries` key (`scripts/migrate_learned.py:30`). For each old file it reads the `learn_ctx` list and rewrites it as `entries`, one per non-empty rule string, assigning `id` (`r001`, `r002`, …), `status: active`, `source: learn`, today's `created` date, and empty `reasoning`/`deactivated_reason` (`scripts/migrate_learned.py:38`). It prints a per-file MIGRATED/SKIP line and a final count.

## Migrate Rules to Atoms

`scripts/migrate_rules_to_atoms.py` is a one-off operator step that distils existing per-task learned rules into general knowledge-oracle atoms as **candidates** — nothing is promoted automatically.

Run with `uv run python -m scripts.migrate_rules_to_atoms`. As written, `main()` (`scripts/migrate_rules_to_atoms.py:23`) walks `data/learned/*.yaml` and prints the intended pipeline: run `KnowledgeOracle().distill` per active rule, then `dedup_by_cosine`. The module ships a working `dedup_by_cosine` helper (`scripts/migrate_rules_to_atoms.py:13`) that drops any atom whose cosine similarity to an already-kept atom meets a threshold, reusing `agent.oracle._cosine`. Distilled candidates land in `data/oracle/atoms.yaml`; the LLM + embeddings backend is required. See [[learning]] for how atoms are retrieved into PLAN.

## Generate Excalidraw

`tools/gen_excalidraw.py` is a deterministic Excalidraw generator for the agent architecture guide: same input → byte-identical output (no time, no randomness), so the diagram can be regenerated and committed reproducibly.

Run with `uv run python tools/gen_excalidraw.py`, writing `docs/architecture/agent-architecture.excalidraw` (`tools/gen_excalidraw.py:475`). It emits one canvas of four stacked frame regions plus a legend strip (`tools/gen_excalidraw.py:479`): Diagram 1 — end-to-end harness → IR-only pipeline flow; Diagram 2 — the PLAN → lint → interpret → verify cycle and gates; Diagram 3 — `interpret()` + `verify()` internals; Diagram 4 — cross-cutting subsystems (LEARN store, oracle, LLM routing, trace). Diagrams are declared as `Node`/`Edge`/`Diagram` specs (`tools/gen_excalidraw.py:89`); `render_diagram` places rows top-down, sizes nodes to fit their labels, wraps them in a frame, and routes orthogonal edges through inter-row gaps or a right-side gutter lane (`tools/gen_excalidraw.py:222`). All ids and seeds are derived purely from element ids via an FNV-style hash (`tools/gen_excalidraw.py:48`), and `unique_ids` / `arrow_bindings_valid` (`tools/gen_excalidraw.py:317`) assert document validity. The shape vocabulary mirrors [[architecture]]: blue=LLM call, grey=deterministic gate, green=storage, yellow=branch, red-rounded=terminal.
