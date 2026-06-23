# Decide

Deterministic outcome-decision layer (`agent/decide.py`, 0 LLM): PLAN proposes a plan, code disposes the outcome. The outcome enum (`OUTCOME_OK` / `OUTCOME_DENIED_SECURITY` / `OUTCOME_NONE_UNSUPPORTED` / `OUTCOME_NONE_CLARIFICATION`) is sourced from the frozen `IntentSpec` (constraints + success_criteria + outcome_space) and the live `/bin/id` identity — never PLAN's free choice — so a weak model can neither over-refuse, under-refuse, nor give up on a solvable task. Best-effort: a mis-typed predicate degrades to "does not hold" (logged, never raised). Wired into [[pipeline]] at two sites; [[interpreter#verify() — the deterministic quality gate]] re-checks consistency afterward.

## _holds — guarded predicate evaluation

`_holds(expr, env)` is the never-raise guard around `predicates.evaluate`: `None` or any exception → `False` (logged). Every predicate the decide layer reads (`deny_when`, `unsupported_when`, `clarify_when`, each `success_criteria` entry) goes through it, so a bad constraint falls back to the model's outcome rather than crashing the task. See [[interpreter#Predicates]].

## identity_of — /bin/id only

`identity_of(vm, facts)` returns the VM identity, preferring the pre-phase-parsed `facts.identity` and falling back to a fresh `/bin/id` exec (lazy `orchestrator._parse_identity`, avoiding an import cycle). A claimed authority in the task text is NEVER an identity. Never raises → `{}` on total failure. The identity feeds every `deny_when` over `$identity.kind`.

## has_protected_action — blast-radius gate

`has_protected_action(intent, result=None)` is True when a mutation already landed OR a constraint was marked `protected_action`. It gates the injection blast radius: a constraint marked `requires_protected_action` fires only when a protected action is in play, so a read-only task with pasted override text answers the real question instead of refusing.

## security_deny

`security_deny(intent, env, protected)` returns the first `security` constraint whose `deny_when` holds, else `None`. A constraint is SKIPPED when `requires_protected_action` and `not protected`, OR when its `deny_when` is **identity-only** and `not protected` (the blast-radius gate, see below); non-security constraints are ignored. This is the deny rung shared by `decide_outcome` and `security_preflight`, so the gate applies uniformly pre-loop and post-interpret.

## _is_identity_only — blast-radius gate predicate

`_is_identity_only(expr)` is True iff the predicate references identity ALONE: it walks the `PredExpr` tree (`lhs`, `rhs`, recursing `args`), collects every `$`-prefixed operand, and returns True iff there is ≥1 such ref AND every ref's parsed path-root ∈ {`identity`, `_facts.identity`} (parsed first segment, not `startswith`). A predicate with no `$`-refs, or one mixing identity with a plan binding (e.g. a customer-ownership deny over `$record.customer_id`), is NOT identity-only and still fires unconditionally. WHY: a weak INTENT over-authors identity-only security denies (e.g. `$_facts.identity.kind == "guest"`); gating them off read-only tasks (`not protected`) stops the decide layer from amplifying that over-refusal — a genuine protected action (a landed mutation, or a constraint INTENT marked `protected_action`) sets `protected=True` and the deny fires as normal. `verify` ([[interpreter#verify() — the deterministic quality gate]]) applies the SAME gate so decide and verify never diverge.

## unsupported_or_clarify

`unsupported_or_clarify(intent, env)` is the deterministic negative-outcome split: a terminal-state `unsupported_when` outranks a genuine-ambiguity `clarify_when`. It returns `OUTCOME_NONE_UNSUPPORTED` / `OUTCOME_NONE_CLARIFICATION` only when that outcome is in `intent.outcome_space`, else `None`.

## anti_give_up_ok — false-OK mitigation

`anti_give_up_ok(intent, result, env)` forces `OUTCOME_OK` only when OK is reachable AND `success_criteria["OUTCOME_OK"]` is non-empty AND every criterion holds AND no unresolved `$`-ref remains. Empty criteria → `False` (it cannot fabricate an OK). The model cannot downgrade a solved task; code cannot invent one. Complements the interpreter's own [[interpreter#Anti-give-up gate]].

## decide_outcome — the ladder

`decide_outcome(intent, result, vm, facts) -> (outcome, refs)` reconciles the plan's outcome with the frozen IntentSpec + identity via the load-bearing ladder `security_deny > unsupported_or_clarify > anti_give_up_ok > the plan's own outcome`. On a deny it merges the deciding constraint's refs, grounds `required_refs["OUTCOME_DENIED_SECURITY"]` (`_required_outcome_refs`), and appends `SECURITY_POLICY_DOC` (`/docs/security.md`) — so a denial cites the task-relevant policy doc INTENT declared (e.g. `/docs/checkout.md`), not only the generic security policy. Runs between [[grounding]] and verify, so verify is a consistency gate, not where outcomes are born. See [[pipeline#Security preflight and decide-outcome]].

## security_preflight — pre-loop terminal deny

`security_preflight(intent, vm, facts) -> (outcome, message, refs) | None` is a pre-loop terminal security gate. It builds a facts-only env (`intent.params` + `_facts` + identity); plan-produced bindings do not exist yet, so only identity/facts-based `deny_when` can fire. Because it routes through the same `security_deny`, an identity-only deny fires here ONLY when a constraint is marked `protected_action` (so `has_protected_action(intent, None)` is True) — an unmarked identity-only deny is gated and the pipeline proceeds to the loop instead of terminally refusing. On a deny the pipeline answers once with `cycles_used=0` (refs also grounded via `_required_outcome_refs`) and skips the loop (and any mutation) entirely.

## _decision_env and _merge_constraint_refs

`_decision_env(intent, result, vm, facts)` builds the post-interpret env: the plan's bound `result.env` plus the identity and an `answer` binding (`message`/`outcome`/`refs`) so `success_criteria` over `$answer.*` resolve. `_merge_constraint_refs(base, c, env)` appends a deciding constraint's anchored `RefSpec` refs, deduped: a `policy_doc` ref contributes its literal `path`; a `record_path` ref resolves `$source` against env (dropped when unresolved). `_required_outcome_refs(intent, outcome, env)` mirrors it over `intent.required_refs[outcome]` so the deny path also cites the policy doc / record INTENT declared for `OUTCOME_DENIED_SECURITY` — together they make a denial cite the exact policy doc and offending record.
