---
review:
  spec_hash: 1c88947dbf3bbd92
  last_run: 2026-06-16
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: INFO
      section: "Decisions (confirmed)"
      section_hash: 6d8da30a92ae9194
      text: "Section named three ways: 'Failures' (Decisions), 'Failures — Correct Answers' (H2 in New function/Wiring), 'Failures / Correct-Answers Section' (doc title). Cosmetic; pick one canonical name in the plan."
      verdict: fixed
      verdict_at: 2026-06-16
chain:
  intent: null
---

# Run Report: Failures — Correct Answers

**Date:** 2026-06-16
**Component:** `scripts/run_report.py`

## Problem

When a benchmark task scores `< 1.0`, the grader returns feedback strings
(`score_detail`) that encode the *correct answer* — e.g. `Answer should contain
'<NO>'`, `expected outcome OUTCOME_OK, got OUTCOME_NONE_CLARIFICATION`,
`no answer provided`. The HTML run-report does not surface this anywhere usable:

- **RESULTS** shows only the status color (OK / CLARIFY / INCOMPLETE).
- **Error Report** aggregates `score_detail` by category and *normalizes* it —
  `normalize_error_key` strips quoted strings and digit runs, so the actual
  expected value (`'<NO>'`) is destroyed before display.

There is no canonical correct-answer field in the protocol. The platform only
returns `score_detail`; that raw string **is** the correct-answer signal.

## Goal

Add a report section that shows, per failing run, the raw (un-normalized)
grader feedback — the correct answer — so a human reading the report can see
what each failed task should have produced.

## Decisions (confirmed)

| Question | Decision |
|----------|----------|
| Source of "correct answer" | Raw `score_detail` (only signal the platform returns) |
| Placement | New dedicated **Failures — Correct Answers** section |
| Scope | Every failing `(task, run)` pair with non-empty `score_detail` |
| Submitted answer alongside? | No — raw `score_detail` only (keep minimal) |

## Design

### Data source

No new parsing. `parse_run` already stores the raw `score_detail` list on each
cell as `TaskCell.errors` (see `_parse_task_file`: `errors = list(tr.get("score_detail") or [])`).

A cell is a **failure row** iff `cell.errors` is non-empty. The grader only
populates `score_detail` when it has feedback (score `< 1.0`), so non-empty
`errors` is exactly the "scored a mistake, here is the correct answer" condition.
We deliberately do **not** include status-only failures (e.g. CLARIFY with no
`score_detail`) — those carry no correct-answer signal.

### New function

```python
def _failures_table(runs, matrix, tasks) -> str:
    rows = []
    for tid in tasks:                       # sorted by _task_sort_key
        for r in runs:                      # chronological
            cell = matrix[tid].get(r.label)
            if cell is None or not cell.errors:
                continue
            detail = "<br>".join(_esc(e) for e in cell.errors)
            rows.append(
                f"<tr><td class='task'>{_esc(tid)}</td>"
                f"<td>{_esc(r.label)}</td>"
                f"<td style='text-align:left'>{detail}</td></tr>"
            )
    body = "".join(rows) or "<tr><td colspan='3'>no failures recorded</td></tr>"
    head = ("<tr><th class='task'>task</th><th>run</th>"
            "<th>grader feedback (correct answer)</th></tr>")
    return f"<h2>Failures — Correct Answers</h2><table>{head}{body}</table>"
```

- Rows ordered by task (`_task_sort_key`), then by run (chronological — `runs`
  is already sorted in `discover_runs`).
- Each cell's `score_detail` entries are HTML-escaped and joined with `<br>`.
- Feedback cell is left-aligned (long text) via inline `text-align:left`,
  overriding the centered default in `th,td`.

### Wiring

In `render_html`, append one entry to the `parts` list, **at the end**, after
`_error_report(errors)` and before `_FOOT`:

```python
parts = [
    _HEAD,
    _results_table(runs, matrix, tasks),
    _numeric_table("CYCLES", ...),
    _numeric_table("ERRORS", ...),
    _learned_table(runs, tasks, lcount, _BLUE),
    _oracle_section(oracle),
    _error_report(errors),
    _failures_table(runs, matrix, tasks),   # NEW
    _FOOT,
]
```

End placement keeps the RESULTS / CYCLES / ERRORS heatmap block visually
contiguous, and sits the per-(task,run) detail next to its aggregated companion
(Error Report).

## Isolation

- Inputs are the same `runs`, `matrix`, `tasks` already passed to
  `_results_table`. No new parsing, no new dataclass, no signature changes to
  existing functions.
- Zero edits to existing render functions; the only existing-code change is one
  added line in the `parts` list of `render_html`.
- Uses raw `cell.errors` — `normalize_error_key` is **not** applied, so quoted
  expected values survive verbatim.

## Verification (no functional tests — per project policy)

1. `uv run python scripts/run_report.py` (regenerates `logs/report.html`).
2. Confirm the section exists and carries the raw correct answer:
   - `grep -c "Failures — Correct Answers" logs/report.html` → `1`
   - `grep -F "Answer should contain &#x27;&lt;NO&gt;&#x27;" logs/report.html`
     matches — t01 feedback rendered verbatim through `_esc`
     (`html.escape` with `quote=True`: `'` → `&#x27;`, `<`/`>` → `&lt;`/`&gt;`).
3. Visual: open `logs/report.html`, confirm the Failures — Correct Answers table lists failing
   `(task, run)` rows with readable grader feedback, and shows
   `no failures recorded` when there are none.

## Out of scope

- No change to `normalize_error_key` or the aggregated Error Report.
- No display of the agent's submitted answer (deferred; source decision was
  raw `score_detail` only).
- No new protocol fields or trace-format changes.
