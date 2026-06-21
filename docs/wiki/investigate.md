# Investigate

The read-only, step-wise investigator in `agent/investigate.py`. It runs a bounded ReAct loop between INTENT and the PLAN loop, gathering a compact evidence `Brief` (step-notes + bound `env`) that the deterministic PLAN consumes in place of a front-loaded facts dump. It NEVER mutates state. Gated by `ECOM_INVESTIGATE_ENABLED` (default 1); `=0` restores the legacy eager gather and skips the investigator. See [[pipeline]] and [[architecture]].

## Why it exists

A front-loaded pre-phase dump (all doc bodies, sample rows, listings) bloats the PLAN prompt and floods it with mostly-irrelevant context, which floundered on complex tasks (e.g. t38 PLAN timeouts). INVESTIGATE replaces the dump with a slim seed plus an agentic, on-demand evidence-gathering loop, so PLAN receives a focused brief. `interpret()`/`verify()` stay deterministic and untouched. See [[interpreter]].

## Brief and Note models

`Note` (goal, tool, args, observation_digest, lesson, refs_found) is one read-only step's condensed record; `Brief` holds an ordered `notes` list plus an `env` dict of bound facts (e.g. `incident_id`, `policy_doc:<path>`, `<row>.record_path`). Both are Pydantic models with `extra="forbid"` (matching [[data-files]]'s `ir_models` convention). `env` is the sufficiency gate's ground truth.

## render_brief

`render_brief(brief)` produces the compact `INVESTIGATION_BRIEF:` text block injected into the PLAN prompt — a `## RESOLVED_ENV` section (bound facts) and a `## STEP_LESSONS` section (one line per note). An empty brief renders to `""` (a falsy marker), so `pipeline` passes `brief_block=None` and PLAN is unaffected. See [[pipeline#INVESTIGATE phase]].

## Read-only gate — is_readonly / run_tool

`is_readonly(tool, args)` is the single security gate: the read RPCs `{read, list, tree, stat, search}` are always allowed; `exec` is allowed ONLY for `/bin/sql` running a SELECT/CTE query (or `/bin/id` for the read-only identity probe). `run_tool(vm, tool, args)` raises `ToolRejected` BEFORE any dispatch for a non-read-only tool, so a mutation is never sent to the VM — all mutations stay in the plan's `ops`. See [[vm]].

## SQL read-only hardening

`_is_readonly_sql(sql)` defends the `exec` path beyond a leading-SELECT match: it strips string literals, rejects multi-statement SQL (a `;` before the final trailing one), and rejects any embedded DML/DDL keyword (`insert|update|delete|drop|alter|truncate|create|replace|merge|grant|revoke|attach|copy`) — so a CTE-wrapped mutation like `WITH x AS (DELETE … RETURNING) SELECT …` is rejected. The `/bin/sql` path comparison is case-normalised.

## Deterministic stall detection

`tool_signature(tool, args)` builds a stable key (SQL whitespace/case-normalised, mirroring [[pipeline#Plan signature and no-progress guard]]; other args stringified+sorted). `is_stalled(result, signature, seen_signatures)` flags a step as stalled when the tool result is empty OR its signature was already seen this run. A stall triggers a single reason-tier escalation.

## Priority action queue

Before free routing, the loop checks two forced-action layers in priority order:

1. **`_forced_doc_read(env, refs)`** — if any investigator-groundable `required_ref` (one with a `read_target`) is still ungrounded in `env`, returns a forced `read` action for its path. This ensures governing docs are fetched before free exploration.
2. **`_forced_data_probe(data_paths, probed)`** — if any seed data-path passed in via `data_paths` has not yet been probed, returns a `read` (file with `.` in basename) or `list` (directory) action. Marks the path probed immediately to enforce probe-once semantics regardless of outcome. The `_seed` key is dropped before passing to `run_tool`/`tool_signature`.

Only when both layers return `None` does the loop call `router` (priority 3). When `ECOM_INVESTIGATE_MERGE_STEPS=1`, a cached `pending_action` from the previous `digest_and_route` call is tried between data probes and the free router.

## Deterministic ref-grounding — _ground_doc_refs

`_ground_doc_refs(env, tool, args, refs)` runs after every successful `read` dispatch: if the path just read matches a `required_ref`'s `read_target()`, it writes `env[r.env_key()] = True` — independently of the digest LLM emitting an `env_updates` key. This prevents missed groundings when the digest fails to extract the ref, and makes doc-read grounding deterministic.

## Sufficiency gate

`sufficient(intent, env, data_paths, probed)` is the loop's stop condition. It returns True when:
- every `required_ref` for `intent.desired_outcome` is groundable from `env` (a `None` from `ref.grounded(env)` means PLAN produces this ref, e.g. `record_path`, and the investigator skips it), AND
- every seed `data_paths` entry has been probed (i.e. appears in `probed`).

The `data_paths`/`probed` clause is inert when `data_paths` is `None` (pre-feature behaviour). No required refs and no data paths → trivially sufficient. See [[interpreter#Answer-ref assembly]] for how `required_refs` drives ref enforcement downstream.

## Probed data paths in env

When a seed data-path probe completes, the loop calls `brief.env.setdefault("data_paths", {})[probe_seed] = observation[:200]`, surfacing the first 200 bytes of the probe result to PLAN via the brief's `RESOLVED_ENV` section. This lets PLAN know which data paths were inspected and their digest.

## router and digest (LLM steps)

`router(intent, brief, atoms, escalate)` asks the model for ONE next read-only action (`{"tool","args"}`) or `{"done": true}`; `digest(goal, tool, args, observation, escalate)` condenses a tool result into a `Note` + `env_updates`. Both run through `_call_json`, which routes to the FAST tier by default and forces the REASON tier (`think=on`) when `escalate=True`. The phase guide is `data/prompts/investigate.md` (general structural rules only). See [[llm]].

## Merged digest-and-route — digest_and_route

`digest_and_route(goal, tool, args, observation, escalate)` collapses the digest and next-action routing into a single LLM call, returning `(Note, env_updates, next_action|None)`. Enabled by `ECOM_INVESTIGATE_MERGE_STEPS=1` (default off). When active, the returned `next_action` is stored as `pending_action` and consumed at the top of the next loop iteration (priority 2.5, between data probes and free routing). This halves the LLM call budget per step at the cost of slightly less focused routing.

## The investigate() loop

`investigate(vm, intent, seed, oracle, max_steps, data_paths)` runs `cycle = 1..ECOM_INVESTIGATE_MAX_STEPS` (default 6):

1. Pick a goal (objective on step 1, else the last note's lesson).
2. Retrieve `ECOM_INVESTIGATE_ORACLE_K` (default 2) scoped oracle atoms.
3. Resolve the next action via the priority queue: forced doc read → forced data probe → pending merged action → free router.
4. If `done`, stop with `stop_reason="sufficient"`.
5. `run_tool` → stall check → optional one reason-tier escalation → if still stalled after escalation, digest and stop.
6. Record the signature in `seen`; call `digest` (or `digest_and_route` when `ECOM_INVESTIGATE_MERGE_STEPS=1`).
7. Append note + env, call `_ground_doc_refs`.
8. Check `sufficient(intent, brief.env, data_seed, probed)` — if true, stop.

It NEVER raises: a `ToolRejected` and any per-step exception are recorded as a lesson and the loop continues. `seed` is accepted for caller compatibility but is reserved/unused in v1 — slim facts still reach PLAN via `run_plan`'s `facts` argument. See [[oracle]].

## Stop reason telemetry

The loop tracks a `stop_reason` string (`"budget"`, `"sufficient"`, `"data_probed"`) and calls `log_investigate_stop_auto(stop_reason, len(data_seed), len(probed))` in the `finally` block. This emits a structured trace record regardless of whether the loop exits normally or via an exception, giving per-task observability on why the investigator terminated. See [[tooling#Trace schema v2]].

## Trace tagging

The loop wraps itself with `trace.set_step_type("INVESTIGATE")` (restoring the prior step type in a `finally`), so VM RPCs auto-emitted by the VM layer (`log_vm_auto`) and the router/digest LLM turns (mirrored by `call_llm_raw` with `phase="INVESTIGATE"`) are tagged under the INVESTIGATE phase in the per-task trace. The trace funnel and renderer are generic — no renderer change was needed. See [[tooling#Trace schema v2]].

## Model tier

INVESTIGATE is a FAST-tier phase in `llm._PHASE_TIER` — its router/digest steps request `think=off` and escalate to the REASON tier (`think=on`) on a deterministic stall. Override the model with `ECOM_MODEL_INVESTIGATE` (defaults to its tier → `ECOM_MODEL_FAST`). See [[llm]].
