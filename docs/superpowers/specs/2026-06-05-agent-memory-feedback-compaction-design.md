---
review:
  spec_hash: 53502fa773295cee
  last_run: 2026-06-05
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: WARNING
      section: "Changes: agent/pipeline.py"
      section_hash: 57fbbd67420caff5
      text: "submitted_outcome wiring gap: pipeline §1 sets token_stats[answer_message] and [answer_refs] only; main.py reads token_stats.get('outcome',''). submitted_outcome always empty. Pipeline must also surface outcome (e.g. token_stats['outcome'] = _captured['outcome'])."
      verdict: fixed
      verdict_at: 2026-06-05
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "Decisions"
      section_hash: 95a4292ff9324ccd
      text: "test_runner pre-submit gate dropped vs intent. Intent Desired Outcome + Steering + Stop Rule mandate mock-test gate before vm.answer(). Design replaces with learn_ctx injection and marks gate N/A. Conscious divergence from approved intent — confirm acceptance."
      verdict: fixed
      verdict_at: 2026-06-05
    - id: F-003
      phase: coverage
      severity: INFO
      section: "Changes: agent/pipeline.py"
      section_hash: 57fbbd67420caff5
      text: "Compaction trigger is entry-count (COMPACTION_THRESHOLD=15), not '% of context' per intent. Defensible simplification; flag for awareness."
      verdict: fixed
      verdict_at: 2026-06-05
    - id: F-004
      phase: clarity
      severity: INFO
      section: "Changes: main.py"
      section_hash: 0d1015085734c06d
      text: "Snippet uses ellipsis placeholders outcome=... / cycles_used=... — values unspecified (presumably existing run values). Minor; tighten or annotate."
      verdict: fixed
      verdict_at: 2026-06-05
chain:
  intent: docs/superpowers/intents/2026-06-05-agent-memory-feedback-compaction-intent.md
---

# Design: Agent Memory — Verdict Feedback Loop + Context Compaction

**Date:** 2026-06-05
**Status:** approved
**Intent:** `docs/superpowers/intents/2026-06-05-agent-memory-feedback-compaction-intent.md`

## Problem

Two coupled gaps:

1. **Verdict feedback loop.** After submission, `_settle_scores` in `main.py` receives `score` + `score_detail` from the platform but discards both. On `score < 1.0`, only `status/outcome/cycles_used` are persisted. The next run of the same task starts blind — no knowledge of what the grader rejected.

2. **Context compaction.** `learn_ctx` (active rule entries from `data/learned/{tid}.yaml`) grows unboundedly. No deliberate management — just a flat list passed verbatim to every LLM call. Additionally, `script_code[:4000]` in `_learn_consolidate` is a blind hard slice.

## Decisions

- Verdict record: written as an `entries[]` item with `source: verdict` (bypasses `_apply_learn_diff` validation). Not a separate YAML key.
- No subprocess gate (no `test_runner` invocation). Verdict record injected into `learn_ctx` directly; CODEGEN+LEARN see it as a rule.
  - *Deviation from intent (accepted).* The intent mandates a `test_runner` mock-gate before `vm.answer()` with asserts derived from `score_detail`. Dropped because: (a) the platform returns only `score` + `score_detail` (free-text problem descriptions), not a machine-parseable correct answer — synthesising reliable asserts from free text is brittle (intent's own "Escalate if score_detail does not parse" risk); (b) the pipeline already has a deterministic **fidelity gate** in-loop, so a second subprocess gate duplicates execution cost against intent's Speed/critical metric; (c) injecting the verdict into `learn_ctx` makes CODEGEN+LEARN correct the script at generation time — earlier than a post-hoc assert. The feedback loop stays cross-run (verdict read in `main.py` post-submit), satisfying the intent's "failing task's score rises on re-run" outcome via a different mechanism.
- Compaction: LLM summarization of older entries when `len(learn_ctx) > COMPACTION_THRESHOLD`. In-memory only — YAML not rewritten.

## Schema: `data/learned/{tid}.yaml`

Verdict entry format (added to `entries[]`):

```yaml
- id: v001
  source: verdict
  score: 0.5
  score_detail:
    - "answer missing field customer_id"
    - "wrong total: expected 3, got 1"
  submitted_message: "Found 1 basket."
  submitted_outcome: OUTCOME_OK
  submitted_refs: ["ref://basket/42"]
  status: active
  created: "2026-06-05"
  content: null
```

Rules:
- `id` uses `v`-prefix (`v001`, `v002`, …), separate counter from `r`-prefix rule entries.
- One active verdict per task at a time. Writing a new verdict deactivates all prior `source: verdict` entries for that `tid`.
- `content: null` — verdict is a fact, not a rule. `apply_learn_diff` validation (`_MIN_CONTENT_LEN`, `_VALID_RULE_STARTS`) is bypassed entirely.

Prompt injection format (in `learn_ctx` block):
```
  - [v001] VERDICT score=0.5: answer missing field customer_id; wrong total: expected 3, got 1
```

Verdict entries have `content: null`, so callers that build `rules_lines` must handle them specially. In `pipeline.py`, wherever `learn_ctx` is serialized (currently `f"  - [{e['id']}] {e.get('content', '')}"`) add a branch:

```python
def _format_entry(e: dict) -> str:
    if e.get("source") == "verdict":
        detail = "; ".join(e.get("score_detail") or [])
        return f"  - [{e['id']}] VERDICT score={e.get('score', '?')}: {detail}"
    return f"  - [{e.get('id', '?')}] {e.get('content', '')}"
```

Used in `_learn_consolidate` and `run_codegen` wherever `rules_lines` is built.

## Changes: `agent/learned_store.py`

### New function: `write_verdict`

```python
def write_verdict(
    tid: str,
    score: float,
    score_detail: list[str],
    submitted_message: str,
    submitted_outcome: str,
    submitted_refs: list[str],
) -> None:
```

Logic:
1. Read YAML.
2. Deactivate all existing entries where `source == "verdict"`.
3. Append new verdict entry with next `v{N:03d}` id.
4. Write YAML.

### Modified: `_next_entry_id`

Split into two counters: `r`-prefix for rules, `v`-prefix for verdicts. `write_verdict` calls a `_next_verdict_id` variant.

### `load_entries` — no change

Returns all `status: active` entries including verdict entries. Callers (CODEGEN, LEARN) receive verdict records transparently.

## Changes: `main.py`

In `_settle_scores`, after `save_last_run`:

```python
if t.score_available and score < 1.0:
    save_last_run(
        task_id,
        status="failure",
        outcome=token_stats.get("outcome", ""),
        cycles_used=token_stats.get("cycles_used", 0),
    )
    write_verdict(
        task_id,
        score=score,
        score_detail=detail,
        submitted_message=token_stats.get("answer_message", ""),
        submitted_outcome=token_stats.get("outcome", ""),
        submitted_refs=token_stats.get("answer_refs", []),
    )
```

`outcome` / `cycles_used` come from the run's existing `token_stats` (same values `save_last_run` already persisted today); `detail` is the platform `score_detail` list.

Import: `from agent.learned_store import save_last_run, write_verdict`

## Changes: `agent/pipeline.py`

### 1. Surface answer data into `token_stats`

`_AnswerGuard` captures submitted answer on successful `vm.answer()` call:

```python
self._captured: dict = {}

def answer(self, *, message, outcome, refs=None):
    ...  # existing validation
    self._vm.answer(message=message, outcome=outcome, refs=refs_list)
    self._captured = {"message": message, "outcome": outcome, "refs": refs_list}
```

`run_pipeline` writes captured data into the returned dict:

```python
token_stats["answer_message"] = guarded_vm._captured.get("message", "")
token_stats["outcome"] = guarded_vm._captured.get("outcome", "")
token_stats["answer_refs"] = guarded_vm._captured.get("refs", [])
```

The key is `outcome` (not `answer_outcome`) — `main.py:_settle_scores` reads `token_stats.get("outcome", "")` for `submitted_outcome`. All three keys must be written here or `submitted_outcome` is silently empty.

### 2. Compaction: `_compact_learn_ctx`

```python
def _compact_learn_ctx(
    learn_ctx: list[dict],
    token_out: dict | None = None,
) -> list[dict]:
```

Logic:
- `threshold = int(os.environ.get("COMPACTION_THRESHOLD", "15"))`
- `keep_recent = int(os.environ.get("COMPACTION_KEEP_RECENT", "5"))`
- If `len(learn_ctx) <= threshold`: return unchanged.
- `older = learn_ctx[:-keep_recent]`, `recent = learn_ctx[-keep_recent:]`
- LLM call: system = `data/prompts/compact.md` + `ephemeral` cache; user = serialized `older` entries.
- On success: return `[{"id": "compacted", "content": summary, "source": "compaction"}] + recent`
- On empty/failed LLM response: log warning, return unchanged (safe fallback).

Called once at start of `run_pipeline`, after `load_entries`:

```python
learn_ctx = load_entries(task_id)
learn_ctx = _compact_learn_ctx(learn_ctx, token_out=_tk)
```

Compaction is **in-memory only**. YAML is not rewritten. Each run compacts fresh from the full stored list.

*Threshold is entry-count, not context-%* (intent says "% of context"). `learn_ctx` is a homogeneous list of short rule/verdict lines, so count is a direct proxy for size and avoids tokeniser-dependent % math. If entries ever vary widely in length, switch `COMPACTION_THRESHOLD` to a token budget — out of scope here.

### 3. Remove blind slice

`_learn_consolidate`: remove `[:4000]` from `script_code` in user_msg construction.

`_terminal_clarify`: `message[:800]` — **keep** (VM-facing protocol limit, not context issue).

## New file: `data/prompts/compact.md`

System prompt for compaction LLM call. Content guidance:
- Output a single paragraph of key conclusions derived from the provided rules.
- No reasoning, no examples, no task-specific details.
- Preserve action directives ("never X", "always Y") in condensed form.
- Output plain text only (no JSON, no code blocks).

## Env Vars

| Var | Default | Purpose |
|-----|---------|---------|
| `COMPACTION_THRESHOLD` | `15` | Entry count triggering compaction |
| `COMPACTION_KEEP_RECENT` | `5` | Verbatim recent entries after compaction |

Add to `.env.example` and `CLAUDE.md` env table.

## Files Changed

| File | Change |
|------|--------|
| `agent/learned_store.py` | `write_verdict()`, `_next_verdict_id()` helper |
| `agent/pipeline.py` | `_AnswerGuard` capture, `_compact_learn_ctx`, remove `[:4000]` |
| `main.py` | `_settle_scores` → `write_verdict(...)` |
| `data/prompts/compact.md` | New compaction system prompt |
| `.env.example` | `COMPACTION_THRESHOLD`, `COMPACTION_KEEP_RECENT` |
| `CLAUDE.md` | Env table update |

Not changed: `agent/models.py`, `agent/test_runner.py`, `data/prompts/{design,codegen,learn}.md`, proto/harness.

## Health Metrics

- Green tasks (`score = 1.0`) must not regress — compaction fallback (return unchanged on failure) guards this.
- Verdict record visible in next run's `learn_ctx` — verified by reading YAML post-run.
- `script_code` no longer truncated in LEARN — verified by trace log showing full script in user_msg.

## Stop Rules (from intent)

- Halt if mock-test gate starts failing previously-green tasks. *(N/A — no subprocess gate in this design.)*
- Halt if green tasks regress after compaction.
- Done when: a failing task's score rises on re-run AND green tasks do not regress AND blind `[:4000]` truncation removed.
