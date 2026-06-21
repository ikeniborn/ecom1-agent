# Interpreter

The Plan-IR interpreter is the single deterministic execution engine of ecom1-agent: it runs a `PlanIR` against the VM with zero LLM calls, then hands a captured answer to [[pipeline#Verify and answer-once]] before it is ever submitted. See [[architecture]] for where it sits.

## PlanIR data model

`PlanIR` (`agent/ir_models.py:171`) is the SDD-layer artifact the PLAN phase emits. It has seven fields executed in a fixed order: `discovery`, `rowsets`, `compute`, `decision`, `ops`, `answer`, `custom_extract`. Every sub-model forbids extra keys.

- **discovery** (`list[Step]`, `ir_models.py:95`) — read-only RPC calls (`rpc`, `args`, optional `bind`) run in order to gather VM state into `env`.
- **rowsets** (`list[RowSet]`, `ir_models.py:108`) — parse a bound payload (`from`) into `list[dict]` under `into`, with `format` (`auto_delim`/`csv`/`tsv`/`pipe`/`json`) and `columns` (`ColResolve` header aliasing).
- **compute** (`list[ComputeStep]`, `ir_models.py:116`) — a pure `prim` over resolved `args`, result bound to `into`.
- **decision** (`DecisionTree`, `ir_models.py:129`) — ordered `branches` (`when` PredExpr → `label`) plus a `default_label`; first matching branch wins.
- **ops** (`list[GuardedOp]`, `ir_models.py:148`) — mutating/side-effecting RPCs, optionally gated by `guard_label` and classified by `outcome_from_exit`.
- **answer** (`dict[str, AnswerTemplateIR]`, `ir_models.py:157`) — label-keyed templates (`message`, `outcome`, `refs`).
- **custom_extract** (`list[CustomExtract]`, `ir_models.py:164`) — named-parser escape hatch (`name`, `input`, `into`).

## repair_sql_stdin

`repair_sql_stdin(plan)` (`agent/interpreter.py:217`) is a deterministic pre-lint repair (F3) that runs before `lint()` in the pipeline. It moves SQL from `args` to `stdin` for every `Exec /bin/sql` step where `stdin` is empty and `args` carries SQL strings. The `args` channel is nondeterministic — the `/bin/sql` tool intermittently returns its usage banner rather than executing, so `stdin` is the reliable channel.

The repair is idempotent: it mutates `step.args` in place and returns the plan. After repair, `_plan_signature` is computed over the normalised plan, so a before/after repair that differs only in SQL delivery channel is still recognised as the same plan for the no-progress guard. See [[pipeline#Plan signature and no-progress guard]] and [[harness#Check Kinds (handlers)]] for the `sql_stdin` lint check that catches any plan still carrying SQL in `args` after repair.

## lint_security_first

`lint_security_first(plan)` (`agent/interpreter.py:199`) is the H3 security invariant, called as defense-in-depth inside `interpret()` and also as a registered check in the harness lint registry (kind `security_first`). It guarantees that every decision branch whose label maps to an `OUTCOME_DENIED_SECURITY` template precedes all non-denied branches.

It collects denied labels from `plan.answer`, finds the last denied branch index and the first non-denied index, and raises `InterpretError` if a denied branch follows a non-denied one (`interpreter.py:211`). This enforces "deny before allow" so a security gate can never be bypassed by branch ordering. The pipeline now calls `lint(plan)` (the registry dispatcher) rather than `lint_security_first` directly; `lint_security_first` remains as the inner check inside `interpret()` and as the `security_first` handler. See [[harness#Check Kinds (handlers)]].

## lint — registry-driven lint dispatcher

`lint(plan)` (`agent/interpreter.py:232`) is the F8 registry-driven dispatcher called by `pipeline.run_pipeline` after `repair_sql_stdin` and before `interpret()`. It iterates every non-`inactive` entry in `data/harness/checks.yaml`, resolves the handler via `harness.handler_for(kind)`, and runs it.

Violation disposition: an `active` + `error`-severity violation raises `InterpretError` (blocks the cycle, routes to iLEARN); a `candidate` or `warn`-severity violation logs only. An unknown `kind` or a handler exception is a logged no-op — it never crashes the pipeline. See [[harness]] for the full handler catalogue and [[data-files#Harness Check Catalogue]] for the spec format.

Each fired check — blocking **and** warn — also emits a `lint_fire` telemetry record into the active trace via `log_lint_fire_auto` (`agent/interpreter.py:277`), placed after the block/warn decision and before the raise/print, so it is purely additive and cannot alter lint semantics. This surfaces warn-level fires that the aggregate `gate` record omits. Because `lint()` raises on the first blocking check, a second blocker in the same cycle is not recorded — acceptable for telemetry, since the first blocker is the actionable one. See [[tooling#Trace schema v2]] for the record shape and [[tooling#Lint Report]] for the offline aggregator that ranks fires across a run.

## interpret() — executing the plan against the VM

`interpret(plan, intent, vm, facts)` (`agent/interpreter.py:259`) is the deterministic executor. It seeds `env` from `intent.params` (plus `_facts`), then runs the seven phases in order. It NEVER calls `vm.answer` — it returns a `CapturedAnswer` inside an `InterpretResult` for [[pipeline]] to submit after verify. See [[vm]] for the RPC surface.

Phase order: discovery (read-only RPCs, SQL payloads tracked into `sql_results`), rowsets (`_parse_rowset`), compute + custom_extract, decision (first matching branch), guarded ops (`decide-then-guard` via `guard_label`; `mutate-then-classify` via `outcome_from_exit`), and answer assembly. RPCs are dispatched by `getattr(vm, rpc.lower())(**kwargs)` with args resolved via `_resolve_args`. A landed mutation (`Write`/`Delete`, or `/bin/*` Exec other than `/bin/sql`) sets `mutation_landed`, which makes a later retry unsafe. The refuse invariant raises if an `OUTCOME_OK` answer has an unresolved required `record_path` ref.

### Answer-ref assembly

Answer refs are assembled from two sources merged (deduped) in `_resolve_authored_refs(authored, env)` (`interpreter.py`):

1. **Enforced projection** — `_project_required_refs(intent, outcome, env)` maps `intent.required_refs[outcome]` into concrete refs; an `OUTCOME_OK` answer with an unresolved required `record_path` ref raises (F5 refuse invariant, preserved).
2. **Conditional authored refs** — `_resolve_authored_refs` resolves each `$ref` in the selected answer template's `tmpl.refs` against `env`. A `$ref` that resolves to `None` or `""` is silently **dropped** (not refused), so a PLAN-authored conditional ref (e.g. a `record_path` present only on the found branch) can be omitted on the not-found branch without aborting the run. The two sets are merged after resolution.

WHY: `required_refs` is per-outcome and cannot express a conditional ref (e.g. a path present only when a record is found). PLAN authors per-branch refs for conditional grounding while always-required refs stay in `intent.required_refs`. See [[pipeline#INTENT — run_intent]] for how `required_refs` originates, and `data/prompts/plan.md` for the authoring convention.

**Runtime SQL-banner backstop:** after each `/bin/sql` Exec in both discovery and ops, `_is_sql_banner(payload)` (`interpreter.py:102`) checks whether the tool returned its usage banner (`# /bin/sql` prefix or `"Send SQL on stdin"` substring) instead of data. If so, `_refuse(...)` raises a retryable `InterpretError` (mutation_landed False), so the pipeline iLEARNs and retries rather than silently parsing an empty rowset. The pre-lint `repair_sql_stdin` eliminates the root cause before execution; this backstop handles any residual runtime slip.

**F1 — compute and custom_extract wrap:** the compute and custom_extract loops catch `TypeError`, `AttributeError`, `KeyError`, and `IndexError` and convert them into `_refuse(...)` calls (`interpreter.py:295–301`). Since compute runs before any mutating op, `mutation_landed` is still False at that point, so the pipeline always retries on a type-mismatch (e.g. passing a scalar dict from `first`/`get` to `column`/`sum_col`). This converts what would have been a bare Python traceback — misclassified as a real-VM exception by the pipeline — into a clean, labelled `InterpretError` that feeds iLEARN. See also `_require_rows` in [[interpreter#Primitives]].

## Primitives

`agent/primitives.py` is a registry of 13 pure compute primitives over already-resolved args, dispatched by name via `run_primitive(name, args)` (`primitives.py:68`). Adding capability is a new registry entry, never new grammar.

The `PRIMITIVES` table (`primitives.py:50`) covers numeric (`abs_diff`, `div`, `to_number`, `sum_col`), collection (`count`, `column`, `first`, `get`, `dedupe`, `concat`), boolean (`all_true`, `any_true`), and row (`filter_rows`, which evaluates a PredExpr per row) operations. `filter_rows` reuses the predicate engine; `dedupe` requires hashable elements.

**`_require_rows` guard (F1):** `sum_col`, `column`, and `filter_rows` all call `_require_rows(prim, rows)` (`primitives.py:22`) before iterating. If `rows` is `None` it returns `[]` (preserving the previous empty-list behaviour). If `rows` is a non-list (scalar or dict — the typical symptom of passing `first`/`get` output directly into a list-consuming primitive), it raises a clear `TypeError` with an actionable message. This `TypeError` is caught by the F1 compute-wrap in `interpret()` and converted into a retryable `InterpretError`, and is also the target of the `primitive_contract` check kind in [[harness#Check Kinds (handlers)]].

## Custom-extract parsers

Parsers are the only bounded escape hatch (H2): `(text, params) -> list[dict]` functions in `PARSERS`, dispatched by `run_parser(name, text, params)` (`agent/primitives.py:82`). They handle extraction that primitives cannot express cleanly.

The sole registered parser is `fuzzy_sku_receipt` (`primitives.py:66`), which extracts SKU tokens from receipt text and emits `{raw, normalized}` rows using an OCR-confusion translation map. Values are method-grounded, not baked in.

## Predicates

`agent/predicates.py` is the pure predicate engine shared by `decision`, `success_criteria`, security `deny_when`, and `filter_rows`. `evaluate(expr, env) -> bool` (`predicates.py:41`) has no I/O and no LLM. The grammar is fixed in `ir_models.py` (`LEAF_OPS`, `BOOL_OPS`).

`resolve(value, env)` (`predicates.py:10`) treats a `$name.path.idx` string as an env lookup (dicts by key, lists by int index, objects by attr) and anything else as a literal. Bool ops (`and`/`or`/`not`) recurse over `args`; leaf ops cover comparisons (`eq`/`ne`/`lt`/`le`/`gt`/`ge` with numeric coercion and graceful fallback), emptiness (`nonempty`/`isnull`), and membership/string ops (`contains_any`, `in_set`, `startswith`, `endswith`, `regex_match`).

## json_extract priority (mutations over reads — load-bearing)

`_extract_json_from_text(text)` (`agent/json_extract.py:60`) pulls the most actionable JSON object from free-form model output. The priority order is load-bearing: a mutation candidate always wins over a read, preventing a spurious read tool call from masking an intended write/delete.

Priority (highest first): (1) a ` ```json ` fenced block returns immediately; (2) the first object whose tool is a mutation — `write`/`delete`/`exec` per `_MUTATION_TOOLS` (`json_extract.py:24`); (3) any bare object with a known `tool` key; (4) the richest valid object by key count (`_richness_key`); (5) a YAML fallback. The scanner is string-aware (braces inside JSON string values do not move depth), supports `Req_Xxx({...})` tool inference (FIX-150) and EOF bracket-balance repair (FIX-401). See [[data-files]] for prompt/tool conventions.

## verify() — the deterministic quality gate

`verify(result, intent)` (`agent/verify.py:12`) is the sole pre-answer quality gate and uses zero LLM calls. It runs the same predicate engine as the interpreter over `env` plus an injected `answer` binding, returning `(ok, error)` where the error string feeds [[pipeline#_ilearn retry seam]]. Pass → the pipeline calls `vm.answer` once; fail → iLEARN and retry.

Checks, in order: **I2** — `outcome` must be within `intent.outcome_space` (`verify.py:18`); **I1** — on `OUTCOME_OK`, no ref may be an unresolved `$` placeholder and the ref count must meet `required_refs` (defense-in-depth, since the interpreter already projects refs); **I3** — an independent security re-check from the frozen `IntentSpec` (`constraints` with `security` + `deny_when`) demanding `OUTCOME_DENIED_SECURITY` when a deny predicate holds; finally every `success_criteria` PredExpr **for the chosen outcome** must hold (`verify.py:41`). `success_criteria` is a `dict[str, list[PredExpr]]` keyed by outcome, so verify applies only `success_criteria.get(ans.outcome, [])` — a valid negative outcome with no criteria passes here (it is still gated by I2). Security re-grounding here complements [[oracle]] knowledge injected upstream.

## IntentSpec D6 guard (outcome_space must include OUTCOME_OK)

`IntentSpec` has a `@model_validator(mode="after")` that enforces the D6 invariant (`agent/ir_models.py:101`): `outcome_space` must include `"OUTCOME_OK"` unless at least one `Constraint` carries `security=True` and a `deny_when` predicate. This closes the frozen-clarification failure mode where INTENT pre-commits an OK-less outcome_space and no in-loop iLEARN can recover (INTENT is frozen for the run). On violation Pydantic raises a `ValidationError`, which surfaces as an `IntentError` in `run_intent` and causes a terminal `OUTCOME_NONE_CLARIFICATION`. The exception for security-deny constraints preserves legitimate "deny-only" flows (e.g. tasks where every outcome is a denial by policy). See [[pipeline#INTENT retry and hard failure]] for the retry and terminal path.

## Tool validation

`_validate_dispatch(rpc, args, mutation_landed)` (`agent/interpreter.py:172`) is called before every VM dispatch in both the `discovery` loop and the `ops` loop. It delegates to `validate_step(rpc, args)` from `agent/tools.py` (see [[tooling#Tool catalog]]). On a violation it emits a `fail(reason)` `vm_call` trace record for observability and raises `InterpretError` (tagged with `mutation_landed`) so the pipeline routes the error to iLEARN. Unknown rpc names, extra arg keys, and missing required args are all caught here before the actual VM call is made. A valid pair returns `None` and execution continues normally.

## Anti-give-up gate

The anti-give-up gate (A3) runs inside `interpret()` after answer assembly (`agent/interpreter.py:367`). If the assembled `outcome` is `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_OK` is in `intent.outcome_space`, and the plan has neither `discovery` steps nor `rowsets`, the gate raises `InterpretError` with the message `"attempt grounded discovery before clarifying (clarify-only plan rejected while OUTCOME_OK is reachable)"`. This prevents a plan that skipped all grounding from prematurely clarifying when a correct answer is achievable. The error routes to iLEARN, which should produce a rule instructing the next cycle to attempt grounded discovery first. See [[pipeline#Gate records]] for the `INTERPRET` gate record that captures this failure.

## InterpretError vs PlanError handling

The interpreter raises only `InterpretError` (`agent/interpreter.py:49`), a `RuntimeError` carrying a `mutation_landed` flag set by `_refuse(...)` (`interpreter.py:144`). `PlanError` is a separate, structural/lint failure surfaced elsewhere in the loop; both route into the LEARN seam, but retry-safety differs.

`mutation_landed` is the load-bearing distinction: when a mutation has already landed, a retry could double-apply it, so [[pipeline]] breaks to a terminal `OUTCOME_NONE_CLARIFICATION` instead of re-running the cycle. A read-only `InterpretError` (or a retryable real-VM exception) is retried via `_ilearn` into the next PLAN cycle. The refuse invariant deliberately propagates `mutation_landed` on an OK answer with unresolved refs (`interpreter.py:278`) so partial side effects are not silently re-attempted.
