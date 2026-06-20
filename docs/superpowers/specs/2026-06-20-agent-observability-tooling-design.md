---
review:
  spec_hash: 10b83de36b765939
  last_run: 2026-06-20
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - { id: F-001, phase: clarity,     severity: WARNING, section: "§5.2",     text: "reasoning-capture DoD undefined", verdict: fixed, verdict_at: 2026-06-20 }
    - { id: F-002, phase: clarity,     severity: WARNING, section: "§8",       text: "prompt-redundancy metric undefined", verdict: fixed, verdict_at: 2026-06-20 }
    - { id: F-003, phase: clarity,     severity: WARNING, section: "§7.3/§10", text: "anti-give-up DoD vs test mismatch (NONE_CLARIFICATION conjunct)", verdict: fixed, verdict_at: 2026-06-20 }
    - { id: F-004, phase: consistency, severity: WARNING, section: "§7/§11",   text: "anti-give-up gate file ownership ambiguous (verify vs interpreter)", verdict: fixed, verdict_at: 2026-06-20 }
    - { id: F-005, phase: coverage,    severity: INFO,    section: "§6",       text: "C coverage confirmation (no defect)", verdict: wontfix, verdict_at: 2026-06-20 }
    - { id: F-006, phase: clarity,     severity: INFO,    section: "§4",       text: "step_type scope for LLM phases vs VM rpc", verdict: wontfix, verdict_at: 2026-06-20 }
    - { id: F-007, phase: consistency, severity: INFO,    section: "§4/§5.3",  text: "interpreter logging seam either/or", verdict: fixed, verdict_at: 2026-06-20 }
    - { id: F-008, phase: consistency, severity: INFO,    section: "§4",       text: "gate supersedes gate_check (confirmed consistent)", verdict: wontfix, verdict_at: 2026-06-20 }
chain:
  intent: null
---

# Agent Observability, Explicit Tool Catalog & HTML Report — Design

- **Date:** 2026-06-20
- **Branch:** heuristics
- **Status:** design (awaiting user review)
- **Motivation:** failure surfaced while tracing t38 — see `docs/reports/t38-trace-analysis.html`

## 1. Problem & Context

Tracing t38 (`scripts/trace_t38.py`) across two models (`deepseek-v4-flash:cloud`,
`claude-code/haiku`) exposed three connected problems:

- **A — architectural.** Both models score 0 on t38: INTENT pre-commits
  `desired_outcome=OUTCOME_NONE_CLARIFICATION` (deepseek even sets
  `outcome_space=[OUTCOME_NONE_CLARIFICATION]`, so OK is impossible), INTENT is frozen for the
  run, PLAN emits a clarify-only Plan-IR, verify passes on it, NONE_CLARIFICATION is submitted,
  grader expects OK → 0. Root cause is twofold: PLAN never receives policy-document content
  (`reason._facts_block` `_PLAN_KEYS` excludes `policies`; `prephase_deep_read` of a `/docs` file
  logs only existence, not body), and INTENT freezes the outcome to clarification. The 11 accreted
  LEARN rules (r001–r011) all circle "ground the filter from the policy doc" — symptom treatment.
- **B — observability.** The production trace logs LLM prompts and the *stripped* assistant text,
  but: model reasoning is discarded (`_THINK_RE.sub` in `llm.py`; Anthropic keeps only `text`
  blocks; claude-code `--output-format json` carries only the final text); pre-phase VM RPCs are
  invisible (`log_vm_call` is called only from `interpreter.py`, not from
  `orchestrator.gather_prephase_facts`); oracle rerank/distill log under the generic phase `llm`;
  deterministic gates (lint/interpret/verify) are not first-class records; token input for caching
  providers is undercounted (CC reports only fresh input, the real context lands in `cache_read`).
- **C — tool selection.** PLAN emits stringly-typed `rpc`+`args` (`Step`/`GuardedOp`) with no
  contract; the model guesses RPC names, arg keys, and column names → the r012 stdin-key bug class.

## 2. Goals / Non-Goals

**Goals**
- One JSONL trace schema (v2) that records *every* sequential step with an explicit task-type tag,
  named phases, captured reasoning, and full tool-use detail.
- An explicit, validated tool catalog so PLAN's tool selection is grounded and arg/rpc errors are
  caught structurally (→ iLEARN) instead of silently returning empty rowsets.
- A self-contained HTML report (run-overview + per-task drill-down with movement and reasoning
  diagrams) generated from the v2 traces.
- The t38 architectural root cause fixed with GENERAL, code-backed levers (no task-specific prose).

**Non-Goals**
- No event-bus refactor (Approach 3 rejected — YAGNI).
- No typed-per-RPC pydantic IR rewrite now (catalog+validation first; typed schemas later if needed).
- No changes to the grader-oracle or training loop.
- No fix to pre-existing broken `[[refs]]` in unrelated wiki pages.

## 3. Decisions (from brainstorm)

| # | Decision |
|---|----------|
| D1 | One combined spec covering A+B+C (user chose), structured as 3 separable workstreams. |
| D2 | Tool contract = **declarative catalog + interpreter validation** (not typed RPC schemas, not log-only). |
| D3 | Logging lives **in the main agent** — extend `agent/trace.py`, not a side script. |
| D4 | Report covers **both levels** — run-overview + per-task drill-down, in **one** self-contained HTML. |
| D5 | A-fix is **code-backed & general** per `feedback_learn_oracle_via_harness`. |
| D6 | INTENT must include `OUTCOME_OK` in `outcome_space` unless a security constraint denies (closes the deepseek frozen-outcome leg). **Included** per recommendation; flagged for review. |

## 4. Shared Backbone — JSONL Trace Schema v2

Single source of truth: `agent/trace.py`. Backward-compatible — existing fields stay, new fields
added; `render_trace` and consumers tolerate missing new keys.

Every record carries: `ts`, `task_id`, `seq` (monotonic, global order), `cycle`, `step_type`.

**`step_type` taxonomy (the task types performed):**
`PREPHASE_GATHER · DOC_SELECT · ORACLE_RETRIEVE · INTENT · PLAN · LINT · INTERPRET · VERIFY ·
ILEARN · ANSWER · DISTILL · TASK_RESULT`

Record-type changes:
- `llm_call`: add `phase` (always named — never `llm`), `reasoning`, `reasoning_available`,
  `raw_response_full`, `prev_llm_seq`, and token fields `tokens_in`/`tokens_out`/`cache_read`/
  `cache_creation`.
- `vm_call` (the tool-call record): add `validation` (`ok` | `fail(<reason>)`), `bytes`,
  `has_data`, keep `mutated`, `duration_ms`; emitted for BOTH pre-phase and interpret.
- `gate` (new): `{step_type in (LINT|INTERPRET|VERIFY), passed: bool, reason: str}` — supersedes
  the ad-hoc `gate_check`.
- `header` / `header_system` / `facts` / `meta`: unchanged except the added `seq`.

`scripts/trace_t38.py`'s reasoning-capture seams move into production (workstream B) under an env
flag; the script becomes a thin caller of the same machinery.

## 5. Workstream B — Log every step in the main agent

Files: `agent/trace.py`, `agent/llm.py`, `agent/oracle.py`, `agent/oracle_rank.py`,
`agent/vm_adapter.py`, `agent/pipeline.py`, new `agent/reasoning_capture.py`.

1. **Name all phases.** Thread `phase=` through `call_llm_json` so `oracle_rank.llm_rerank` →
   `RERANK` and `oracle.distill` → `DISTILL`. No call_llm_raw site may default to `llm`.
2. **Reasoning capture in prod.** New `agent/reasoning_capture.py` holds the provider seams
   (Ollama `<think>`/`reasoning_content`/`reasoning`; Anthropic thinking blocks; claude-code
   stream-json spawn swap). Active only when `ECOM_TRACE_REASONING=1` (cost control: Ollama is
   cheap — reasoning already in the response; CC switches the spawn to `--output-format
   stream-json`; Anthropic requires enabling thinking → real cost). Capture is best-effort;
   failure → `reasoning_available=false`. **DoD:** `reasoning_available == true` iff the captured
   `reasoning` string is non-empty; that flag is the success criterion asserted by tests (§10).
3. **Pre-phase VM logging.** Make `VMAdapter` trace-aware: every RPC logs a `vm_call` with the
   `step_type` read from a thread-local set by the caller (`PREPHASE_GATHER` in orchestrator,
   `INTERPRET` in interpreter). Decision: the VMAdapter seam logs all RPCs; the interpreter-only
   `_trace_vm` is removed and the interpreter just sets the thread-local `step_type=INTERPRET`.
4. **Gate records.** `pipeline.run_pipeline` emits a `gate` record after lint, interpret, and
   verify with `passed` + `reason` (the existing error strings).
5. **Token accounting.** Thread `cache_read`/`cache_creation` (already in CC `token_out`) into the
   `llm_call` record so input is not undercounted for caching providers.

## 6. Workstream C — Explicit tool catalog + validation

New file `agent/tools.py`.

- `TOOL_CATALOG`: a declarative registry of VM RPCs the planner may use —
  `Exec`, `Read`, `Write`, `Delete`, `List`, `Stat`, `Tree`, `Search`, plus the `/bin/sql`
  special. Each entry: `purpose`, `args_schema` (required + optional keys with types),
  `mode` (`read` | `mutate`), `when_to_use`, and a minimal example. The r012 lesson (SQL must be
  delivered on the real stdin channel, not an inline `stdin` arg the runner drops) is encoded as a
  structural note + example on the `/bin/sql` entry.
- `build_tool_catalog_block()` → a markdown block injected into the PLAN prompt, replacing ad-hoc
  RPC prose currently inline in `plan.md` (prompt files keep only general structure per the
  Prompt Engineering Rules).
- **Interpreter validation:** before dispatching any `Step`/`GuardedOp`, validate
  `rpc ∈ TOOL_CATALOG` and `arg keys ⊆ schema` with all required present. Violations raise
  `InterpretError` (→ iLEARN) with a precise message ("rpc 'Foo' not in catalog" / "arg 'stdin'
  not accepted by Exec; SQL goes on stdin channel"). This kills the guess-the-rpc/arg-key class.
- **Tool-use logging:** each validated dispatch writes a `vm_call` with `validation=ok`, `bytes`,
  `has_data`, `mutated`, `duration_ms`; validation failures write `validation=fail(<reason>)`.

## 7. Workstream A — Architectural fix (code-backed, general)

Files: `agent/reason.py`, `agent/orchestrator.py`, `agent/interpreter.py`, `agent/ir_models.py`.
(The anti-give-up gate lives in `interpreter.py` because it raises `InterpretError → iLEARN`.)

1. **policies → PLAN.** Add `policies` to `_PLAN_KEYS` in `reason._facts_block` (or a dedicated
   CRITERIA block) so PLAN sees the criteria source. General.
2. **deep_read reads body.** In `orchestrator`, when a `prephase_deep_read` literal is a `/docs`
   file, read its content into `policies` (not just existence). General.
3. **Anti-give-up gate (code).** If `outcome_space` includes `OUTCOME_OK` and the plan is
   clarify-only (empty `discovery` AND empty `rowsets`) and the chosen outcome is
   `NONE_CLARIFICATION`, reject → `InterpretError` → iLEARN ("attempt grounded discovery before
   clarifying"). No task-specific prose.
4. **INTENT outcome guard (D6).** `IntentSpec` validation requires `OUTCOME_OK ∈ outcome_space`
   unless a security `Constraint` with `deny_when` is present. Prevents INTENT from freezing the
   run into clarification-only (the deepseek leg, where #3's iLEARN is powerless because INTENT is
   frozen). Structural change to the INTENT contract — flagged in D6 for review.

## 8. Report — `scripts/agent_report.py`

ONE self-contained HTML (per `html-report`: single file, both themes, no external resources, no
sibling-file references). Written under `docs/reports/`.

- **Run-overview (top):** task grid (outcome / score / cycles / tokens incl. cache / time), an
  error category summary, and a tool-usage summary (per-RPC counts, empty-result rate, validation
  failures).
- **Per-task drill-down (collapsible sections):** step timeline ordered by `seq`, colored by
  `step_type`; the cycle diagram (PLAN→lint→interpret→verify→iLEARN with the verify-fail branch)
  as inline SVG; a tool-usage table (rpc, count, bytes, hit/empty, validation); collapsible
  reasoning panels per `llm_call`; a prompt-redundancy metric — the facts-overlap ratio =
  `difflib.SequenceMatcher` ratio (0..1) over the shared PRE-PHASE FACTS block between the INTENT
  and PLAN `user_msg` (1.0 = byte-identical), reported per task.
- Reuses the renderer concepts from `scripts/trace_t38.py` and the grid concepts from
  `scripts/run_report.py`, generalized over the v2 schema.

## 9. Error Handling

- Logging is best-effort and MUST NEVER break a run (existing `_trace_vm` swallow pattern kept).
- Tool-catalog validation is FUNCTIONAL — it must raise (→ iLEARN), distinct from swallowed
  logging errors.
- Reasoning capture degrades silently (`reasoning_available=false`) on any provider/parse failure.
- The report generator HALTS on an unreadable or contradictory source — never fabricates data
  (per `html-report`).

## 10. Testing

- **Unit — catalog:** known rpc ok; unknown rpc / bad arg key / missing required → `InterpretError`.
- **Unit — schema v2:** `seq` monotonic; no `llm_call.phase == "llm"`; pre-phase `vm_call` present;
  `gate` records present with reasons; cache token fields populated from a stub `token_out`.
- **Unit — report renderer:** from a fixture v2 JSONL → no external `src=`/`href=`, both theme
  custom-prop sets present, overview + per-task sections + reasoning panels all rendered.
- **Integration — mock VM:** a full `run_pipeline` over MockVMSpy yields a v2 trace exercising
  every `step_type`; assert pre-phase VM logged and phases all named.
- **A-fix:** PLAN facts include `policies`; deep_read reads a `/docs` body; anti-give-up gate
  rejects a clarify-only plan whose chosen outcome is `NONE_CLARIFICATION` when `OUTCOME_OK` is in
  `outcome_space`; `IntentSpec` rejects an OK-less `outcome_space` absent a security deny.

## 11. Sequencing (suggested implementation order)

1. Schema v2 in `trace.py` (backbone) + step_type plumbing.
2. Workstream B (named phases, VMAdapter logging, gates, tokens, reasoning_capture).
3. Workstream C (tools.py catalog + interpreter validation + tool-use logging).
4. Workstream A (policies→PLAN, deep_read body, anti-give-up gate, INTENT guard).
5. `scripts/agent_report.py` consuming v2.
6. Re-run t38 with `scripts/trace_t38.py` (now thin) to verify the fix end to end via the new report.

## 12. Open / Flagged

- **D6** (INTENT must include OUTCOME_OK unless security-deny) changes the INTENT contract; included
  per recommendation, confirm at review.
- `ECOM_TRACE_REASONING` default = off (cost). Confirm whether prod runs should default it on for
  Ollama-only (cheap) providers.
