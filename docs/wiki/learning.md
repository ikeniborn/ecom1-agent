# Learning

The learning and persistence layer captures per-task knowledge between and within runs. `learned_store.py` holds durable per-task rules and run metadata in `data/learned/{task_id}.yaml`; `trace.py` records a structured JSONL trace of every pipeline cycle. Both feed the LEARN seam described in [[pipeline]].

## Overview

Two complementary surfaces persist what a task run produced. `agent/learned_store.py` is the durable store of LEARN rules, grader verdicts, and `last_run` metadata. `agent/trace.py` is the per-run forensic log. See [[architecture]] for where they sit, [[data-files]] for on-disk layout.

The learned store is the write target of the LEARN seam (`pipeline._ilearn` → `apply_learn_diff`), while the trace is attached thread-locally for the whole task and torn down at the end. Neither requires an LLM call.

## load_entries (active only)

`load_entries(tid, surface=None)` returns only entries whose `status == "active"`, optionally filtered by `surface` ('ir' | 'codegen'). Untagged legacy entries default to `'codegen'`. Inactive (superseded) rules are never returned (`learned_store.py:64`).

This is the single read surface PLAN consumes: every active rule is shown to the planner. Verdict entries (`source: verdict`, `content: null`) are also stored in the same `entries[]` list and surface through this loader. The `surface` filter exists for the codegen-era split but the live pipeline reads the single combined surface.

## apply_learn_diff(tid, LearnConsolidateOutput)

`apply_learn_diff(tid, out, surface="codegen")` appends one new active rule and deactivates listed prior ids. It is a no-op when `out.skip` is set or `tid` is empty. New content is validated before writing (`learned_store.py:79`).

Validation gate: the trimmed `rule_content` must be at least `_MIN_CONTENT_LEN` (20) chars and start with one of `_VALID_RULE_STARTS` (`never`, `always`, `use`, `do not`, `when`, `if`, `prefer`); otherwise nothing is written (`learned_store.py:84`). Ids in `out.deactivate_ids` get `status="inactive"` plus a `deactivated_reason` (`out.deactivate_reason` or `"superseded"`). The appended entry carries a fresh id from `_next_entry_id` (`r001`, `r002`, …), the content, `agents_md_anchor`, `reasoning`, `status="active"`, `surface`, and a `created` date. See [[pipeline]] for the calling LEARN seam.

## save_last_run (status/outcome/cycles_used/date)

`save_last_run(tid, status, outcome, cycles_used)` writes a single `last_run` block onto the task's YAML, merging into existing data (`learned_store.py:113`). It records only `status`, `outcome`, `cycles_used`, and today's `date` — no `heuristic_valid`, no `schema_hash`.

It is a no-op for an empty `tid`. The block overwrites any prior `last_run`, so the YAML always reflects the most recent run's terminal state. This is the metadata consulted by tooling and reporting in [[tooling]].

## data/learned/{task_id}.yaml format

Each task's YAML carries `task_id`, an `entries` list (active + inactive rules and verdicts), and a `last_run` block. Reads tolerate missing/corrupt files by returning `{}`; writes use `yaml.dump(allow_unicode=True, default_flow_style=False)` (`learned_store.py:17`, `learned_store.py:29`). See [[data-files]].

A rule entry has `id` (`rNNN`), `content`, `agents_md_anchor`, `reasoning`, `status` (`active`/`inactive`), `surface`, `created`, and `deactivated_reason`. A verdict entry (written by `write_verdict`) has `id` (`vNNN`), `source: verdict`, `score`, `score_detail`, `submitted_message`/`submitted_outcome`/`submitted_refs`, `status`, `created`, and `content: null` — the null content flags it as a fact, bypassing the `apply_learn_diff` rule validation. Only one verdict is active at a time; a new one deactivates prior verdicts. The file may also hold `prephase_deep_read` (a unioned list of table names or `/literal/paths`) managed by `append_prephase_deep_read` / `load_prephase_deep_read`.

## trace.py (JSONL trace files)

`trace.py` provides a thread-local `TraceLogger` that writes one structured JSON record per line to a per-task `.jsonl` file, attached via `set_trace`/`get_trace` and cycle-stamped via `set_cycle` (`trace.py:43`). Records cover the full pipeline: header, facts, llm_call, vm_call, sql/test/gate events, answer, and task_result.

Each `_write` stamps `ts` (UTC ISO) and `task_id`, appends to an in-memory list, and (best-effort) re-renders a readable sibling `{tid}.detail.log` live so the run is `tail -f`-watchable (`trace.py:57`, `trace.py:64`). System prompts are deduplicated by SHA-256: a `header_system` record is emitted once per distinct system, and `llm_call` records reference it by `system_sha256` (`trace.py:79`). Long bodies are truncated by caps (`_VM_HEAD_CAP=1000`, `_FACT_HEAD_CAP=2000`); `vm_call` keeps only whitelisted arg keys (`_VM_ARG_KEYS`). `render_trace` (`trace.py:291`) turns a jsonl path or record list into readable (optionally ANSI-colored) text, shared by the auto detail log and `scripts/trace_view.py` — see [[tooling]].

## c{N} naming across training cycles

Trace filenames encode the training cycle. The first pass writes `{task_id}.jsonl`; subsequent training cycles (`TRAIN_MAX_CYCLES > 1`) write `{task_id}.c{N}.jsonl`, so each re-run is preserved separately (`main.py:146`).

The logic is `f"{task_id}.jsonl" if train_cycle <= 1 else f"{task_id}.c{train_cycle}.jsonl"`. Because each cycle is a fresh `StartRun → SubmitRun` (see [[pipeline]]), the `c2`, `c3`, … traces let you diff how a task's plan evolved after `learn_from_grader` distilled grader feedback into a LEARN rule. The persisted [[oracle]] atoms and `data/heuristics/*` artifacts are the other cross-cycle carriers; the trace is the per-cycle record.
