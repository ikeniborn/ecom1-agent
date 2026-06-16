---
review:
  plan_hash: dbdd8e399b54777b
  spec_hash: 1c88947dbf3bbd92
  last_run: 2026-06-16
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: structure
      severity: INFO
      section: "Task 2: Wire _failures_table into render_html"
      section_hash: 1077ee0ce96a5b0a
      text: "Duplicate step heading 'Step 2: Static-check syntax' in Task 1 and Task 2. Cosmetic — different tasks, identical action."
      verdict: fixed
      verdict_at: 2026-06-16
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-16-run-report-failures-section-design.md
---

# Run Report: Failures — Correct Answers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Failures — Correct Answers" section to the HTML run-report that shows, per failing `(task, run)` pair, the raw grader `score_detail` (the correct answer the platform returned).

**Architecture:** Pure addition to `scripts/run_report.py` — one new render function `_failures_table` plus one line wiring it into `render_html`'s `parts` list. No new parsing, no new dataclass, no changes to existing render functions. Reuses `TaskCell.errors` (raw `score_detail`, already parsed).

**Tech Stack:** Python 3 stdlib (`html`, `dataclass`) + `pyyaml`. No test framework — project policy bans functional tests; verification is by running the real script and grepping output.

**Spec:** `docs/superpowers/specs/2026-06-16-run-report-failures-section-design.md`

> **PROJECT POLICY — No functional tests.** This plan uses run-the-real-code verification (regenerate `logs/report.html`, grep it) instead of TDD. Do **not** add pytest/unittest steps. Static checks (`py_compile`, `ruff`) are allowed and encouraged.

---

### Task 1: Add `_failures_table` render function

**Files:**
- Modify: `scripts/run_report.py` (insert new function between `_error_report` ending at line 373 and `render_html` starting at line 376)

- [ ] **Step 1: Insert the new function**

Insert this function immediately after `_error_report(...)` returns (after line 373, before the `# ── HTML rendering ──` separator is already above; place it directly before `def render_html`):

```python
def _failures_table(runs, matrix, tasks) -> str:
    """Per failing (task, run) pair, render the raw grader score_detail — the
    'correct answer' the platform returned. A cell is a failure iff cell.errors
    is non-empty (grader only populates score_detail when score < 1.0). Raw, not
    passed through normalize_error_key, so quoted expected values survive."""
    rows = []
    for tid in tasks:
        for r in runs:
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

- [ ] **Step 2: py_compile + ruff check after adding the function**

Run: `uv run python -m py_compile scripts/run_report.py`
Expected: no output, exit 0.

Run: `uv run ruff check scripts/run_report.py`
Expected: no new errors for `_failures_table` (pre-existing repo warnings, if any, unchanged).

---

### Task 2: Wire `_failures_table` into `render_html`

**Files:**
- Modify: `scripts/run_report.py:381-391` (the `parts` list inside `render_html`)

- [ ] **Step 1: Add the call to the `parts` list**

In `render_html`, the `parts` list currently ends:

```python
        _oracle_section(oracle),
        _error_report(errors),
        _FOOT,
    ]
```

Change it to insert the new section after `_error_report(errors)` and before `_FOOT`:

```python
        _oracle_section(oracle),
        _error_report(errors),
        _failures_table(runs, matrix, tasks),
        _FOOT,
    ]
```

`runs`, `matrix`, and `tasks` are all already in scope inside `render_html` (same variables passed to `_results_table` two lines above).

- [ ] **Step 2: py_compile check after wiring**

Run: `uv run python -m py_compile scripts/run_report.py`
Expected: no output, exit 0.

---

### Task 3: Verify against real logs and commit

**Files:**
- No code changes — verification + commit only.

- [ ] **Step 1: Regenerate the report**

Run: `uv run python scripts/run_report.py`
Expected: prints `wrote .../logs/report.html  (N runs, M tasks, K error categories)`.

- [ ] **Step 2: Confirm the section renders exactly once**

Run: `grep -c "Failures — Correct Answers" logs/report.html`
Expected: `1`

- [ ] **Step 3: Confirm raw correct-answer survives verbatim**

Run: `grep -F "Answer should contain &#x27;&lt;NO&gt;&#x27;" logs/report.html`
Expected: a matching line — t01's grader feedback rendered through `_esc`
(`html.escape` with `quote=True`: `'` → `&#x27;`, `<`/`>` → `&lt;`/`&gt;`).

> Note: this exact match depends on a t01 failure existing in `logs/`. If `logs/`
> has been cleared or contains no t01 failure, instead confirm the empty state:
> `grep -F "no failures recorded" logs/report.html` → matching line.

- [ ] **Step 4: Visual spot-check (optional)**

Open `logs/report.html` in a browser. Confirm a "Failures — Correct Answers" table
appears at the bottom (after Error Report), listing failing `(task, run)` rows with
left-aligned, readable grader feedback.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_report.py
git commit -m "feat(run-report): add Failures — Correct Answers section

Show raw grader score_detail (the correct answer the platform returns)
per failing (task, run) pair. Pure addition: new _failures_table +
one line in render_html. Reuses TaskCell.errors; not normalized, so
quoted expected values (e.g. '<NO>') survive verbatim.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Goal (show raw `score_detail` for failures) → Task 1 (`_failures_table`) + Task 2 (wiring). ✓
- Decisions: source = raw `score_detail` → uses `cell.errors`, no `normalize_error_key`. ✓
- Decisions: placement = new Failures — Correct Answers section, at end → Task 2 inserts after `_error_report`, before `_FOOT`. ✓
- Decisions: scope = every failing `(task, run)` with non-empty `score_detail` → Task 1 loop `if cell is None or not cell.errors: continue`. ✓
- Decisions: no submitted answer → not rendered. ✓
- Spec Verification section → Task 3 steps 1-4 mirror it (grep counts + verbatim match + empty-state fallback). ✓
- Isolation (no signature changes, one added line) → respected; only `parts` list gains one entry. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to". All code shown in full. ✓

**Type/name consistency:** `_failures_table(runs, matrix, tasks)` defined in Task 1, called with the same arg order/names in Task 2. H2 string `Failures — Correct Answers` matches the grep in Task 3 step 2 and the spec canonical name. `_esc`, `TaskCell.errors`, `r.label` all exist in the current file. ✓
