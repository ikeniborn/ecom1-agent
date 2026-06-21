---
review:
  spec_hash: 868e0bd29e43056b
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

**Date:** 2026-06-21 (revised after reading the live source)
**Branch (origin):** `heuristics`
**Trigger:** Analysis of `logs/20260621_091749_claude-code-sonnet/t38.jsonl` (model `claude-code/sonnet`).
**Companion report:** `docs/reports/t38-analysis.html`

> **Revision note.** The first draft of this spec was written from a sub-agent code map
> that proved partly stale. After reading the live source, several proposed "fixes" turned
> out to already exist (cross-provider fallback FIX-417, `ECOM_CC_MAX_RETRIES`, native
> `--fallback-model`, the FIX-361/FIX-390 fail-fast paths). This revision scopes the work to
> what the code *actually* lacks. See §2.

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

The run failed **mechanically**, not logically: PLAN returned an empty body twice
(`PlanEmptyError: "PLAN LLM returned empty response"`, `agent/reason.py:171`), so no PlanIR
was ever built, the interpreter never ran, `vm.answer` was never called, and the loop fell
through to a terminal clarification (`agent/pipeline.py:425`, breaks after
`_EMPTY_PLAN_MAX = 2` empties).

## 2. Root-cause findings (verified against the live source)

### What already exists (do NOT re-implement)
- **Cross-provider fallback is wired** — `call_llm_raw` (`agent/llm.py:595-601`, FIX-417):
  when the primary model returns `None`, it retries once with `_FALLBACK_MODEL`
  (`ECOM_MODEL_FALLBACK`), *any* provider including `anthropic/<X>`. It did not fire for t38
  only because `ECOM_MODEL_FALLBACK` was unset.
- **CC retries are already bounded & configurable** — `ECOM_CC_MAX_RETRIES`
  (`agent/cc_client.py:33`, default `2`) and `ECOM_CC_DEFAULT_TIMEOUT_S` (default `180`).
- **CC fail-fast paths exist** — FIX-361 (legitimately-empty `end_turn` with output tokens →
  break, no retry, `agent/cc_client.py:335`), FIX-390 (OAuth quota → break,
  `agent/cc_client.py:355`), and the native `--fallback-model` flag
  (`cc_fallback_model`, `agent/cc_client.py:297`).
- The ~732 s per PLAN call is therefore **repeated subprocess timeouts** (`fail_reason="timeout"`
  retried up to `_CC_MAX_RETRIES` times at ~180 s each), not an infinite empty-retry loop.

### The genuine code bug (this is the real Cluster A fix)
- **`cfg={}` is passed at every LLM call site**, so `models.json` per-model `cc_options` is
  dead. Call sites: `agent/reason.py:133` (INTENT), `agent/reason.py:169` (PLAN),
  `agent/investigate.py:186`, `agent/orchestrator.py:474` (DOC_SELECT),
  `agent/pipeline.py:138` (LEARN), `agent/llm.py:708`. `models.json` *contains*
  `cc_options.cc_timeout_s` / `cc_model` / `cc_fallback_model`, and `main.py:111` loads the
  file — but the per-model cfg is never threaded into `call_llm_raw`. Result: `cc_complete`
  cannot read per-model timeout, model, or CC-level fallback; only the `ECOM_CC_DEFAULT_*`
  env vars apply.

### INVESTIGATE sufficiency gap (verified in source)
- The sufficiency gate (`agent/investigate.py:159-176`) checks `env["policy_doc:<path>"]`,
  which is set **only** by the digest LLM's `env_updates` (`agent/investigate.py:229,293`).
  `run_tool`'s `read` (`agent/investigate.py:99-100`) sets no env key. So reading the
  governing doc grounds the gate only if the LLM happens to emit the right key. In t38 the
  governing fraud doc was a different, unread source → `policy_doc:<path>` stayed false →
  records were selected by a 3DS proxy (`customer_abandoned` / `challenge_timeout`) instead
  of the authority-confirmed signal — the anti-pattern that active rule `r015` targets.

### Two mis-diagnoses from the HTML report (corrected — NOT bugs)
- **Token accounting is correct.** `tokens_in=3424` constant is the *fresh* (non-cached)
  input under prompt caching; the cached portion is in `cache_read`
  (`agent/cc_client.py:75-125`, FIX-N). The only weakness: the run summary
  (`main.py:219`) rolls up `input_tokens/output_tokens` and ignores cache, so per-call cost
  *looks* flat.
- **`parsed_output=null` is by design.** `call_llm_raw` is the raw funnel and hardcodes
  `parsed_output=None` (`agent/llm.py:621`); parsing happens downstream of the trace write.

## 3. Scope

Three clusters. Cluster A is the load-bearing fix; B is correctness; C is demoted to
optional after the source review.

| Cluster | Items | Files | Priority |
|---------|-------|-------|----------|
| A — PLAN robustness | A1 cfg threading (code), A2 config | `agent/llm.py`, `agent/reason.py`, `agent/investigate.py`, `.env.example` | 🔴 critical |
| B — INVESTIGATE correctness | H2, H3, M3 | `agent/investigate.py` (+ LEARN channel) | 🟠 high |
| C — Observability (optional) | M1, M2 | `main.py`, `agent/trace.py` | 🟡 low |

## 4. Design — Cluster A (PLAN robustness)

### A1 — Thread per-model `cfg` from `models.json` into the LLM call path (code)
**Goal:** `models.json` `cc_options` (`cc_timeout_s`, `cc_model`, `cc_fallback_model`) reaches
`cc_complete`, so an empty/timed-out PLAN fails within one configured window and can use a
per-model CC fallback — instead of being silently capped by `ECOM_CC_DEFAULT_*` only.

- Add a `models.json` loader + per-model lookup in `agent/llm.py` (e.g.
  `resolve_model_cfg(model) -> dict`) that returns the config block for a model id (`{}` if
  absent). Load once at import, read live enough for tests.
- In `call_llm_raw`, when the caller passes an empty `cfg`, default it to
  `resolve_model_cfg(model)` before dispatch. This fixes all six call sites at one seam
  without touching each caller. (The existing `_FALLBACK_MODEL` retry also passes `{}`;
  apply the same resolution there.)
- **No change** to `ECOM_CC_MAX_RETRIES`, the FIX-361/390 fail-fast, or the FIX-417 fallback
  — they already work; this just lets per-model config feed them.

**Verify:** unit test — `call_llm_raw` with an empty `cfg` and a model present in `models.json`
dispatches with the resolved cfg (assert `cc_complete` receives non-empty `cfg` / the resolved
`cc_timeout_s`). A model absent from `models.json` still works (`cfg={}`).

### A2 — Configuration (config)
**Goal:** turn on the already-wired safety nets for the CC tier.

- `.env.example`: document and set sane defaults —
  `ECOM_MODEL_FALLBACK=anthropic/claude-sonnet-4-6` (cross-provider net via FIX-417),
  and document tuning `ECOM_CC_MAX_RETRIES` (e.g. `1` for PLAN-heavy runs) and
  `ECOM_CC_DEFAULT_TIMEOUT_S`.
- Optionally add `cc_fallback_model` to the relevant `claude-code/*` entry in `models.json`
  so the native CC `--fallback-model` engages once A1 makes it reachable.

**Verify:** with `ECOM_MODEL_FALLBACK` set, a unit test that forces the primary to return
`None` asserts the fallback model is dispatched (this exercises the existing FIX-417 path,
now guarded by a test).

### A3 — Fail-fast (emergent, no separate change)
With A1 (per-model timeout reachable) + A2 (fallback configured), the first empty/timeout
PLAN recovers via fallback instead of burning two full cycles. No new code.

## 5. Design — Cluster B (INVESTIGATE correctness)

### H2 — Deterministic governing-doc grounding
**Goal:** reading a required governing doc grounds the sufficiency gate deterministically,
not contingent on the digest LLM emitting the env key.

- In `investigate()` after a successful `run_tool`, if `tool` is `read` and `args["path"]`
  equals an `intent.required_refs[desired_outcome]` entry of kind `policy_doc`, set
  `brief.env[f"policy_doc:{path}"] = True` in code (alongside the digest's `env_updates`).
- Pre-router prioritization: if a required `policy_doc` ref is still ungrounded, force a
  `read` of that path as the step's action instead of free-form routing.
- **Dependency:** both hooks assume `intent.required_refs` names the governing doc path
  (sourced from `docs_inventory`, which INTENT sees, and already surfaced to the router via
  `_refs_targets`, `agent/investigate.py:202-204`). If INTENT cannot name the governing doc
  at all, that is a separate INTENT-side grounding gap — out of scope here.

**Verify:** unit test with a mock VM — reading the governing doc sets the env key without any
LLM `env_updates`; `sufficient(intent, brief.env)` then returns true.

### H3 — Authority-confirmed signal over proxy
- Primarily resolved by H2: once the governing doc is read, the confirmed-fraud signal is
  available so PLAN can filter on it, not a 3DS proxy. Reinforced by active rule `r015`.
- **No `data/prompts/` patch** — `CLAUDE.md` forbids task-specific rules in system prompts;
  task knowledge flows through the LEARN channel only.
- **Verify:** the §7 integration re-run (records selected by the confirmed signal).

### M3 — Merge digest(step N) + router(step N+1) into one call
**Goal:** cut per-step cost from `router + digest (+ oracle retrieve)` toward one
condense-and-decide call per step.

- The router (`agent/investigate.py:262`, pre-tool) and digest
  (`agent/investigate.py:291`, post-tool) are separate LLM calls; they cannot merge *within*
  a step (the tool runs between them). Restructure so the post-tool digest call **also**
  returns the next step's action (`{observation_digest, lesson, env_updates, next_action}`),
  removing the top-of-loop router call from step 2 onward.
- **Risk:** medium — touches the ReAct loop and the stall/escalation branch
  (`agent/investigate.py:272-289`). Keep behind a flag if it complicates escalation.

**Verify:** unit test — the merged call returns both the digest fields and the next action;
an integration investigate run reaches sufficiency within `ECOM_INVESTIGATE_MAX_STEPS` with
fewer LLM calls than today.

## 6. Design — Cluster C (Observability, optional)

Both items are low-value and were over-stated in the HTML report. Implement only if cheap.

### M1 — Cache tokens in the run summary
- The summary (`main.py:219`) reads `token_stats["input_tokens"/"output_tokens"]`, which come
  from the harness trial and carry **no** cache fields. Surfacing cache cost requires
  aggregating `cache_read`/`cache_creation` from the per-call trace events, not just adding a
  column. Scope: optional; if done, aggregate from the trace and add two summary columns.
- **Verify:** summary for a CC run shows non-zero cache columns.

### M2 — Parsed output in the trace (minimal)
- `parsed_output` is hardcoded `None` (`agent/llm.py:621`) and the trace is written *before*
  the caller parses. Threading it requires a post-hoc trace update or moving the log call.
  Scope: optional; if done, limit to INTENT/PLAN via a post-write patch keyed by seq.
- **Verify:** trace event for a successful INTENT carries a non-null `parsed_output`.

## 7. Verification strategy

- **Unit:** `uv run python -m pytest tests/ -v` — focused tests for cfg resolution
  (A1), fallback dispatch (A2), deterministic doc-grounding (H2), merged investigate call (M3).
- **Integration gate:** re-run t38 against the live grader (`make task TASKS='t38'`),
  expecting `score 0 → 1.0`. Cluster A is necessary (unblocks PLAN); Cluster B is sufficient
  for the correct answer.
- **Caveat:** grader runs are slow and another session may be looping `main.py`. Run `pgrep`
  before timed runs; do not kill the other session's runs.

## 8. Environment / config

| Var | Status | Purpose |
|-----|--------|---------|
| `ECOM_MODEL_FALLBACK` | **exists** (`llm.py:595`) — set in `.env` | Cross-provider fallback on empty/None (A2) |
| `ECOM_CC_MAX_RETRIES` | **exists** (`cc_client.py:33`, default 2) — tune | Cap CC subprocess retries |
| `ECOM_CC_DEFAULT_TIMEOUT_S` | **exists** (default 180) — tune | CC subprocess per-attempt timeout |
| `models.json` `cc_options` | **exists but currently dead** — unlocked by A1 | Per-model `cc_timeout_s` / `cc_model` / `cc_fallback_model` |

No *new* env vars are required. A1 is the code change that makes the existing `models.json`
config reachable.

## 9. Non-goals / out of scope

- Re-implementing the cross-provider fallback, CC retry cap, or fail-fast paths — they exist.
- No `data/prompts/` task-specific patches (forbidden by `CLAUDE.md`).
- No change to prompt-caching token semantics (the accounting is correct).
- Not investigating *why* the CC CLI times out / returns empty on large PLAN prompts; the
  robustness path (per-model timeout + configured fallback) recovers regardless.

## 10. Implementation order

1. **A1 + A2** (`llm.py` cfg seam + `.env.example`/`models.json`) — small, isolated, unblocks
   runs by making per-model timeout + fallback effective.
2. **B / H2** (`investigate.py` deterministic doc-grounding) — the correctness fix for t38.
3. **B / M3** (investigate loop merge) — medium risk, do behind a flag.
4. **C** (optional) — only if cheap.
