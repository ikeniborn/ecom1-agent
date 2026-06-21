# Lint-Firing Telemetry — Design

**Date:** 2026-06-21
**Status:** Approved (design), pending implementation plan
**Topic:** First slice of a future harness→oracle feedback bridge — instrument which
`data/harness/checks.yaml` checks fire, so the bridge direction can be decided from real data.

## Background / Problem

The agent has two learnable knowledge stores with **opposite polarity and opposite consumption**:

| | `oracle` (`data/oracle/atoms.yaml`) | `harness` (`data/harness/checks.yaml`) |
|---|---|---|
| unit | NL atom (`content` + `domain` + `polarity`) | structural check-spec keyed by `kind` |
| consumed by | PLAN prompt — soft, LLM may ignore, retrieval-ranked | `interpreter.lint()` — hard, deterministic gate |
| polarity (today) | **all `method`** (positive "how to") | **all negative** ("don't do X") |
| validation | live grader round-trip (expensive) | pure structural handler-eval (cheap) |
| trust anchor | open NL | **closed code-set of `kind` handlers** |

These are **not redundant** — they are a clean two-sided system: oracle steers generation
(soft, positive); harness rejects bad output (hard, negative). They form a generate-then-check
loop.

**Why not merge harness into the oracle:** merging would force one mechanism onto both
polarities — either harness checks fall under semantic retrieval (and can fail to be retrieved,
losing the always-on enforcement guarantee), or checks are injected into the PLAN prompt as prose
(losing the code-backed trust anchor — the exact anti-pattern recorded in project memory:
"strengthen the agent through GENERAL code-backed harness checks, never task-specific prose").
The correct relationship is a **feedback loop, not a merge**.

**The only feedback direction with fuel today is "teach":** a harness check that keeps firing
means the LLM keeps hitting an anti-pattern. The hard gate blocks it (good) but teaches nothing,
so the mistake recurs across tasks, each time costing a blocked plan cycle. The missing positive
`method` atom — distilled from the firing check and injected into PLAN — would steer generation
away from the mistake from cycle 1. (The opposite direction, hardening an oracle `anti`-atom into
a check, has **no fuel**: there are zero `anti`-atoms.)

**Blocker:** the bridge needs a signal that does not exist. `interpreter.lint()` only `print()`s
warnings. The LINT gate verdict *is* already traced (`trace.log_gate`), but only as an aggregate
`passed/blocked + reason` — it omits the specific check `id`/`kind`/`severity`, and **warn-level
fires are invisible entirely** (the gate still "passes").

## Scope

Instrument lint firing and produce an offline report. **Telemetry only.** This slice deliberately
ships no distillation, no oracle change, no auto-promotion, no env gate. Its product is *data* with
which to choose the bridge direction later.

## Non-Goals

- Distilling `method` atoms from firing checks (the eventual bridge — separate slice).
- Any write to `data/oracle/`, any auto-promotion, any new env var.
- Hardening `anti`-atoms into checks (no `anti`-atoms exist; no fuel).
- A new always-on event file (the empty, unused `data/oracle/history.jsonl` is the cautionary
  precedent — reuse the live trace channel instead).

## Architecture

Three independent units, each testable in isolation.

### 1. Emit (`agent/trace.py`)

New best-effort helper mirroring `log_gate_auto`:

```
log_lint_fire_auto(check_id, kind, severity, blocking, message) -> None
```

Reads the thread-local logger via `get_trace()` and the active cycle via `current_cycle()`.
Writes one record and **never raises** into a run (observability is non-fatal). Record shape:

```json
{"type": "lint_fire", "cycle": <int>, "check_id": "...", "kind": "...",
 "severity": "error|warn", "blocking": <bool>, "message": "..."}
```

`task_id`, `seq`, `ts` are stamped by `TraceLogger._write` (existing behavior). A new
`TraceLogger.log_lint_fire(...)` method writes the record; `log_lint_fire_auto` is the
thread-local wrapper.

### 2. Wire-in (`agent/interpreter.py:lint()`)

For **every** fired check — both `blocking` and `warn` — call `log_lint_fire_auto(...)` before
acting on it. Concretely, inside the existing per-spec loop, after `violations` is computed and
found non-empty: emit, then keep the current behavior (`raise InterpretError` if blocking, else
`print` warn). This captures warn fires that are invisible today.

**Known limitation:** `lint()` raises on the first blocking check, so if two checks would block in
the same cycle only the first is recorded. Acceptable for telemetry — the first blocker is the
actionable one. Documented, not fixed, in this slice.

### 3. Report (`scripts/lint_report.py`)

Offline aggregator (no LLM, no grader). Scans a directory of trace files (`{tid}.jsonl`,
`{tid}.c{N}.jsonl`), collects `lint_fire` records, and prints a table ranked by total fires:

```
check_id            kind                fires  blocked  warned  tasks  sample
chk_column_on_scalar primitive_contract    14       14       0      6   "'column' expects list[dict]…"
…
```

Columns: `check_id`, `kind`, total `fires`, `blocked` count, `warned` count, distinct-task count,
one sample message. Takes the trace directory as an argument (default: the project's trace output
dir). This is the instrument for choosing the bridge direction from real benchmark data.

## Data Flow

```
interpreter.lint(plan)
  └─ per fired check ─► trace.log_lint_fire_auto(...)  ─► {tid}.jsonl  (lint_fire records)
                                                          └─ render_trace ─► {tid}.detail.log (human-readable line)
benchmark run (many tasks) ─► many {tid}.jsonl
  └─ scripts/lint_report.py <trace_dir> ─► ranked stdout table
```

## Rendering

Add a `lint_fire` branch to `render_trace()`'s `event()` dispatcher so the record shows in the
auto `{tid}.detail.log`:

```
  · [lint_fire] c<cycle> <check_id> [BLOCK|warn] <message-head>
```

## Error Handling

- `log_lint_fire_auto` swallows all exceptions (matches `log_vm_auto` / `log_gate_auto`): a trace
  failure must never break a run.
- `lint()` behavior is otherwise unchanged — emit is additive and precedes the existing
  raise/print, so block/warn semantics are identical.
- `scripts/lint_report.py` tolerates malformed/partial JSONL lines (skip-and-continue) and an empty
  trace dir (prints "no lint_fire records").

## Testing

- **Emit:** unit test — set a `TraceLogger`, run `lint()` over a plan that trips one `error` and
  one `warn`/`candidate` check; assert two `lint_fire` records with correct `blocking` flags, and
  that the run still raises on the blocking one.
- **No-trace safety:** call `log_lint_fire_auto` with no active logger → no-op, no raise.
- **Render:** feed a record list containing a `lint_fire` through `render_trace`; assert the line
  format.
- **Report:** point `scripts/lint_report.py` at a fixture dir of two trace files; assert the
  aggregate counts (fires/blocked/warned/distinct-tasks) per `check_id`.

## Open Questions

None blocking. Report output is stdout table by default; an HTML variant via the `html-report`
skill is a trivial follow-up if the tally proves worth sharing.
