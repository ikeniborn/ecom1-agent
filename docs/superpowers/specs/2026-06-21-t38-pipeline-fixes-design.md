---
review:
  spec_hash: b342c02a7b3fd966
  last_run: 2026-06-21
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings: []
chain:
  intent: null
---
# t38 Pipeline Robustness & Correctness Fixes — Design

**Date:** 2026-06-21
**Branch (origin):** `heuristics`
**Trigger:** Analysis of `logs/20260621_091749_claude-code-sonnet/t38.jsonl` (model `claude-code/sonnet`).
**Companion report:** `docs/reports/t38-analysis.html`

## 1. Problem

Task `t38` scored `0.0` — `OUTCOME_NONE_CLARIFICATION` instead of `OUTCOME_OK`, after 1934 s.

Phase wall-clock breakdown (from the trace):

| Phase | Calls | Seconds | % |
|-------|------:|--------:|--:|
| PLAN (both empty) | 2 | 1464.2 | 76.2% |
| INVESTIGATE | 20 | 284.8 | 14.8% |
| INTENT | 1 | 126.0 | 6.6% |
| RERANK | 4 | 44.1 | 2.3% |
| PREPHASE_GATHER | 3 | 3.5 | 0.2% |

The run failed **mechanically**, not logically: the PLAN phase returned an empty body
twice (`PlanEmptyError: "PLAN LLM returned empty response"`), so no PlanIR was ever
built, the interpreter never ran, `vm.answer` was never called, and the loop fell through
to a terminal clarification.

## 2. Root-cause findings (verified against the code)

### Confirmed mechanical failure
- Empty PLAN body → `PlanEmptyError` raised at `agent/reason.py:171`.
- Caught at `agent/pipeline.py:425`: increments `empty_streak`, **skips iLEARN**, `continue`;
  breaks to CLARIFICATION after `_EMPTY_PLAN_MAX = 2` consecutive empties.
- **732 s per call explained:** the CC subprocess timeout is **180 s**
  (`agent/cc_client.py:218`, `ECOM_CC_DEFAULT_TIMEOUT_S`), but `cc_complete` retries
  internally (~4×) → ~732 s total. The `models.json` `cc_timeout_s` / `cc_options` are
  **unreachable** because `agent/reason.py:169` calls `_call_llm_raw(..., model, {}, ...)`
  with an empty `cfg`.
- **No fallback fired:** `ECOM_MODEL_FALLBACK` only triggers when *all* tiers return `None`
  (`agent/llm.py:595`). For a `claude-code/sonnet` model only the CC tier runs; on empty it
  returns `None` and would dispatch the env fallback — but `ECOM_MODEL_FALLBACK` was unset,
  so it never ran.

### INVESTIGATE sufficiency gap
- The sufficiency gate (`agent/investigate.py:159-176`) checks an env key
  `policy_doc:<path>` that is set by the **digest LLM output**, not by deterministic code.
- The run read `/docs/security.md` but the *governing fraud doc* was a different, unread
  source → `policy_doc_read` stayed false → records were selected by a 3DS proxy
  (`customer_abandoned` / `challenge_timeout`) rather than the authority-confirmed signal.
  This is exactly the anti-pattern that the active learned rule `r015` targets.

### Two earlier mis-diagnoses (corrected — NOT bugs)
- **Token accounting is correct.** `tokens_in=3424` constant is the *fresh* (non-cached)
  input under prompt caching; the cached portion lives in `cache_read`
  (`agent/cc_client.py:75-125`, FIX-N). The only gap: the run summary rolls up
  `tokens_in/out` and ignores cache fields, so per-call cost *looks* flat.
- **`parsed_output=null` is by design.** `call_llm_raw` is the raw funnel and always logs
  `parsed_output=None` (`agent/llm.py:621`); parsing happens downstream. Logging a parsed
  object requires threading it back from the phase call sites.

## 3. Scope

All eight items, grouped into three clusters. Cluster A is code + config.

| Cluster | Items | Files | Priority |
|---------|-------|-------|----------|
| A — PLAN robustness | H1, C2, C1 | `agent/llm.py`, `agent/cc_client.py`, `agent/reason.py` | 🔴 critical |
| B — INVESTIGATE correctness | H2, H3, M3 | `agent/investigate.py` (+ LEARN channel) | 🟠 high |
| C — Observability | M1, M2 | `agent/trace.py`, run-summary builder | 🟡 low |

## 4. Design — Cluster A (PLAN robustness)

### H1 — Reachable CC config + bounded internal retries
**Goal:** an empty/timed-out PLAN fails fast (≤ one timeout window), not after ~732 s.

- Resolve per-model `cfg` from `models.json` **inside `agent/llm.py`** keyed by the resolved
  model id, instead of relying on callers passing `cfg`. The phase call sites
  (`agent/reason.py`) currently pass `{}`; after this change `cc_options.cc_timeout_s` and
  `cc_model` from `models.json` reach `cc_complete`.
- Bound the CC wall-clock: add `ECOM_CC_MAX_RETRIES` (default `1`) consumed in
  `agent/cc_client.py` so internal retries cannot multiply 180 s → 732 s.

**Verify:** unit test asserts the CC path receives a non-empty resolved `cfg` (timeout from
`models.json`); a forced-empty CC call returns within one timeout window, not four.

### C2 — Cross-provider fallback on empty (code, not just `.env`)
**Goal:** an empty PLAN auto-recovers without depending on a hand-set `ECOM_MODEL_FALLBACK`.

- When `claude-code/<X>` returns empty/`None` **and** `ECOM_ANTHROPIC_API_KEY` is present,
  retry once via `anthropic/<X>` (same model, different transport). Then fall through to the
  existing `ECOM_MODEL_FALLBACK` path (`agent/llm.py:595`).
- **Fallback order:** OAuth CC (cheap) → `anthropic/<same-model>` (API credits) → env
  `ECOM_MODEL_FALLBACK`.
- **Tradeoff (accepted):** the CC tier uses OAuth (no API billing); the `anthropic/<X>`
  retry consumes API credits. Accepted because it only fires on a CC failure that would
  otherwise zero the task.
- Gate the new behavior behind an env flag (e.g. `ECOM_CC_API_FALLBACK`, default `1`) so it
  can be disabled.

**Verify:** unit test with a mocked CC tier returning empty asserts the `anthropic/<X>`
retry is dispatched and its result is used; a second test with the flag off asserts no
API retry.

### C1 — Fail-fast
Covered by H1 (don't burn 732 s/call) + C2 (the first empty triggers fallback within the
same call instead of waiting for `empty_streak == 2`). No separate change.

## 5. Design — Cluster B (INVESTIGATE correctness)

### H2 — Deterministic governing-doc grounding
**Goal:** reading the governing policy doc grounds the sufficiency gate deterministically.

- In the investigate loop (`agent/investigate.py`), after `run_tool` performs a `Read` whose
  path matches an `intent.required_refs` entry of kind `policy_doc`, set
  `env["policy_doc:<path>"] = true` in code — independent of the digest LLM.
- Add a pre-router prioritization: if a required `policy_doc` ref is still ungrounded, force a
  `Read` of that path before free-form routing.
- **Dependency:** both hooks assume `intent.required_refs` names the governing doc path
  (sourced from `docs_inventory`, which INTENT sees). If INTENT cannot name the governing doc
  at all, that is a separate INTENT-side grounding gap — out of scope here; this design only
  makes a *named* required `policy_doc` deterministically grounded and prioritized.

**Verify:** unit test with a mock VM — reading the governing doc sets the env key without LLM
participation; `sufficient()` then returns true.

### H3 — Authority-confirmed signal over proxy
- Primarily resolved by H2: once the governing doc is read, the confirmed-fraud signal
  column/value is available, so PLAN can filter on it instead of a 3DS proxy.
- Reinforced by the existing active rule `r015`.
- **No `data/prompts/` patch** — `CLAUDE.md` forbids task-specific rules in system prompts;
  task knowledge flows through the LEARN channel only.
- **Verify:** integration re-run of t38 (records selected by the confirmed signal, not the
  proxy); covered by the §7 gate.

### M3 — Merge digest + next-router into one call
**Goal:** cut per-step LLM cost from 3 (router + digest + oracle rerank) toward ~2.

- The router (pre-tool) and digest (post-tool) cannot merge *within* a step (the tool runs
  between them). Instead merge `digest(step N)` with `router(step N+1)` into a single LLM
  call that condenses the last observation **and** picks the next tool.

**Verify:** unit test — the merged call returns both the digest fields (observation_digest,
lesson, env_updates) and the next action; investigation reaches sufficiency within
`ECOM_INVESTIGATE_MAX_STEPS`.

## 6. Design — Cluster C (Observability)

### M1 — Cache tokens in the run summary
- Add `cache_read` / `cache_creation` to the per-phase and total rollup in the run-summary
  builder so CC-tier cost is honest (not a flat `tokens_in`).
- **Verify:** summary for a CC run shows non-zero cache columns.

### M2 — Parsed output in the trace (minimal)
- Thread the parsed object from `run_intent` / `run_plan` into the `log_llm_call` event
  (currently always `None`, `agent/llm.py:621`). Scope to INTENT/PLAN only.
- **Verify:** trace event for a successful INTENT carries a non-null `parsed_output`.

## 7. Verification strategy

- **Unit:** `uv run python -m pytest tests/ -v` — each fix gets a focused test (CC cfg
  resolution, empty→fallback dispatch, deterministic doc-grounding, merged investigate call,
  summary cache columns, parsed_output threading).
- **Integration gate:** re-run t38 against the live grader (`make task TASKS='t38'`),
  expecting `score 0 → 1.0`. This is the real gate; Cluster A is necessary, Cluster B is
  sufficient for the correct answer.
- **Caveat:** grader runs are slow and another session may be looping `main.py`. Run `pgrep`
  before timed runs; do not kill the other session's runs.

## 8. New environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `ECOM_CC_MAX_RETRIES` | `1` | Cap CC subprocess internal retries (H1) |
| `ECOM_CC_API_FALLBACK` | `1` | Enable CC→`anthropic/<same-model>` retry on empty (C2) |

## 9. Non-goals / out of scope

- No `data/prompts/` task-specific patches (forbidden by `CLAUDE.md`).
- No change to the prompt-caching token semantics (M1 was a mis-diagnosis; accounting is
  correct — only the summary rollup changes).
- No rework of the CC envelope parser (`cc_client.py` FIX-N) — it is correct.
- Not investigating *why* the CC CLI returns empty on large PLAN prompts; the robustness
  fixes (fail-fast + fallback) recover regardless of the underlying cause.

## 10. Implementation order

1. **Cluster A** (`llm.py`, `cc_client.py`, `reason.py`) — isolated, low risk, unblocks runs.
2. **Cluster B** (`investigate.py`) — medium risk, changes the ReAct loop.
3. **Cluster C** (`trace.py`, summary) — minimal risk.
