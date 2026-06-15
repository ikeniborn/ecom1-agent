---
review:
  spec_hash: e5bca072453d969d
  last_run: 2026-06-15
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "### Error categorization (shared by ERRORS map and Error Report)"
      section_hash: f11c4ce1ea8c5aaf
      text: "'truncating to the stable message stem' underspecifies the category key. Strip rules (digits/quotes/paths) are deterministic, but the truncation step is not defined — risks unstable bucketing."
      verdict: fixed
      verdict_at: 2026-06-15
chain:
  intent: null
---

# Run-Report Heatmaps — Design

**Date:** 2026-06-15
**Status:** Approved (design phase)
**Target:** `scripts/run_report.py` + `tests/test_run_report.py`

## Purpose

Generate a single self-contained HTML report from `logs/` for analyzing benchmark
runs over time. Rows = tasks (`t01…tNN`), columns = runs (one per run directory).
The report grows automatically as new run directories appear under `logs/`.

Sections in one HTML file — four heatmaps plus two summary sections:

1. **RESULTS** heatmap — per-task outcome status per run.
2. **CYCLES** heatmap — pipeline cycles used per task per run.
3. **ERRORS** heatmap — count of unique error categories per task per run.
4. **LEARNED** heatmap — learned rules created per task per run.
5. **Oracle** section — knowledge-bank typing snapshot.
6. **Error Report** — aggregated, categorized error rollup across all runs.

## Constraints

- **Dependencies:** stdlib + `pyyaml` only (already in the project). No matplotlib /
  pandas / plotly. HTML is built as a string with inline-styled tables.
- **Read-only over logs/data.** The only write outside the output file is appending an
  oracle snapshot line to `data/oracle/history.jsonl`.
- **No grader scores exist in logs.** RESULTS encodes outcome status, not a 0–1 score.
- Thin-script style, consistent with `scripts/trace_view.py`.

## Data Sources

### Run logs — `logs/<YYYYMMDD_HHMMSS_model>/`

Directory name parses into a run: date (`YYYY-MM-DD`), time, and model label. Each run
holds per-task files `tNN.jsonl`, `tNN.trace.log`, `tNN.detail.log`.

Both files are parsed (they carry different signal):

- **`tNN.jsonl`** — structured events. Relevant types:
  - `header` → `task_text`, `ts`.
  - `answer` → `outcome` (`OUTCOME_OK` / `OUTCOME_NONE_CLARIFICATION` / …) and `cycle`
    (cycles used). Absence of an `answer` event ⇒ run was interrupted for that task.
- **`tNN.trace.log`** — human pipeline log. Sole source of in-loop pipeline errors
  (these are NOT emitted as jsonl events). Error lines match `[pipeline] … failed`
  (e.g. `answer refs check failed`, `real-vm exec failed: read failed`,
  `loop broken at cycle …`). Final `[tNN] trial done …` line carries duration.

> `llm_call.success` in the jsonl reflects LLM-call health, not cycle pass/fail, so it
> is NOT used as an error signal.

### Learned rules — `data/learned/<task_id>.yaml`

`entries[]` each with `id`, `created` (date), `status` (`active`/`inactive`),
`surface` (e.g. `codegen`). `last_run` with `outcome`, `cycles_used`, `date`.

### Oracle atoms — `data/oracle/atoms.yaml`

Flat list of atoms. Each: `id`, `domain` (list of type tags — the knowledge typing),
`status` (`candidate`/`validated`), `source` (`distilled`/…), `source_task`.

## Cell Semantics

| Map | Cell value | Color scale |
|-----|-----------|-------------|
| RESULTS | `OK` (`answer.outcome==OUTCOME_OK`) / `CLARIFY` (`OUTCOME_NONE_CLARIFICATION`) / `INCOMPLETE` (no `answer` event) / empty (task absent in run) | green / amber / grey / blank |
| CYCLES | `answer.cycle` (fallback: max `cycle` seen in events) | white→red gradient, scaled to the max cycle observed across the report (data-driven, not env-bound) |
| ERRORS | count of **unique** error categories for that task/run (dedup repeats of the same normalized message) | white→red gradient |
| LEARNED | number of learned rules whose `created` date equals the run's date, attributed to that task | white→blue gradient |

Rows = union of task ids across all runs, sorted by numeric suffix. A task missing from
a run renders as a blank cell.

### Error categorization (shared by ERRORS map and Error Report)

Normalize each `[pipeline] … failed` line into a category key by, in order:
(1) drop the leading `[pipeline] ` prefix; (2) remove quoted strings (`'…'`, `"…"`);
(3) remove path-like tokens (any run of non-space chars containing `/`); (4) remove
digit runs; (5) collapse internal whitespace to single spaces and strip ends. The
category key is the resulting string verbatim — no truncation. Examples of resulting
categories: `answer refs check failed`,
`real-vm exec failed: read failed`, `loop broken at cycle`. New categories
(`SyntaxError`, `fidelity drift`, intent-test failures) bucket automatically — no
hard-coded category list.

- ERRORS cell = count of **distinct** category keys for that task/run.
- Error Report = global rollup: one row per category with total occurrences, count of
  distinct tasks affected, which runs it appeared in, and one example message.

## Oracle Section (snapshot + typing)

Rendered from the current `atoms.yaml` (single snapshot; no per-run history yet):

- Top-N `domain` tags as a horizontal bar (div widths proportional to count).
- Breakdown tables by `status` and by `source_task`.

`snapshot_oracle()` appends one line to `data/oracle/history.jsonl`:
`{date, total, by_status, top_domains}`. Re-running the report on later dates builds a
growth series so a future revision can render oracle growth over time. Today this is a
single data point.

## Module Layout

```
scripts/run_report.py
  discover_runs(logs_dir)      -> list[Run]                 # parse dir names
  parse_run(run)               -> dict[task_id, TaskCell]   # jsonl + trace.log
  parse_learned(learned_dir)   -> list[Rule]
  parse_oracle(atoms_path)     -> OracleStats
  snapshot_oracle(stats, hist) -> None                      # append history.jsonl
  build_error_report(cells)    -> list[ErrorCategory]
  render_html(runs, matrix, learned, oracle, errors) -> str
  main()                       -> argparse + write output
tests/test_run_report.py       # parsing on fixtures + smoke render
```

Each function has one responsibility, takes plain inputs, returns plain data; only
`main()` touches argv and the filesystem output. Rendering is a pure function of the
parsed data, so it is testable without real logs.

## CLI

```bash
uv run python scripts/run_report.py                       # scan logs/ -> logs/report.html
uv run python scripts/run_report.py --out r.html --logs logs/
```

- `--logs` (default `logs/`) — root holding run directories.
- `--out` (default `logs/report.html`) — output HTML path.

## Rendering

Pure-stdlib HTML string. Each heatmap is an HTML `<table>`; cells colored via inline
`style="background:#rrggbb"`. Color scales computed in Python (numeric maps interpolate
white→target; RESULTS uses a fixed status→color map). Oracle bars are `<div>` widths.
The Error Report is an HTML table. All sections concatenated into one document with a
small inline `<style>` block — no external assets, no JavaScript required.

## Testing

`tests/test_run_report.py`:

- Fixture run dir with two synthetic tasks (one `OUTCOME_OK`, one with no `answer` +
  repeated error lines) asserts: RESULTS statuses, cycles, unique-error dedup count.
- `parse_learned` / `parse_oracle` on small fixtures assert counts and typing buckets.
- `render_html` smoke test: output is non-empty, contains each section heading, and
  every task row.

## Out of Scope

- No grader-score ingestion (absent from logs).
- No interactivity / JS / live dashboard.
- No oracle growth chart yet (only the snapshot + history-file seeding for the future).
- No changes to the pipeline or logging format.
