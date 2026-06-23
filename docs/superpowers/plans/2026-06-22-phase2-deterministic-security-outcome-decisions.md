---
review:
  plan_hash: 1ca59f43676983ae
  spec_hash: 31b00e7bb2d94e03
  last_run: 2026-06-22
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      severity: WARNING
      phase: verifiability
      section: "Task 9 — wiki-ingest DoD"
      section_hash: cd2d1924620bb103
      verdict: wontfix
      text: "Task 9 Step 3 (iwiki:iwiki-ingest) is a skill invocation with no standalone command DoD; its output is verified transitively by Step 4 (test -f docs/wiki/decide.md + git status --porcelain docs/wiki/) and Step 5 (/iwiki-lint). wontfix: a skill-invocation step cannot carry an independent assertion; Steps 4-5 are the measurable gate."
    - id: F-002
      severity: WARNING
      phase: consistency
      section: "Task 8 — preflight return-dict shape"
      section_hash: 010f60987539e2fe
      verdict: wontfix
      text: "The preflight-deny return dict includes answer_message/answer_refs, matching the success-path shape (pipeline.py:448-450) but not the INTENT-None failure guard (320-321) which omits them. Pre-existing codebase asymmetry inherited, not introduced; including the keys is the more-complete choice. wontfix."
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-22-phase2-deterministic-security-outcome-design.md
---
# Phase 2 — Deterministic Security / Outcome Decisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the outcome-enum decision (`OUTCOME_OK` / `OUTCOME_DENIED_SECURITY` / `OUTCOME_NONE_UNSUPPORTED` / `OUTCOME_NONE_CLARIFICATION`) out of the LLM's free choice into a deterministic layer (`agent/decide.py`) driven by the frozen `IntentSpec` constraints + the live `/bin/id` identity, so a weak model can neither over-refuse, under-refuse, nor give up on a solvable task.

**Architecture:** A new `agent/decide.py` exposes pure helpers (`security_deny`, `unsupported_or_clarify`, `anti_give_up_ok`) and two orchestrators: `security_preflight(intent, vm, facts)` runs **before** the PLAN loop (terminal deny from identity/facts), and `decide_outcome(intent, result, vm, facts)` runs **after** `interpret` + `ground_refs` and **before** `verify`, overwriting `result.captured.outcome`/`refs` via the ladder `security_deny > unsupported_or_clarify > anti_give_up_ok > the plan's own outcome`. `verify.py` I3 is generalised to a both-directions consistency check. `IntentSpec.Constraint` gains the data fields (`requires_protected_action`, `protected_action`, `unsupported_when`, `clarify_when`, `refs`) that the predicates need; INTENT/LEARN populate them (no `data/prompts/` task-specific patch).

**Tech Stack:** Python 3, Pydantic v2 (`agent/ir_models.py`), the shared predicate engine (`agent/predicates.py:evaluate`/`resolve`), pytest, `MockVMSpy` (`agent/mock_vm_spy.py`) for VM doubles. All VM calls are kwargs-style.

**Branch:** Builds on `determinism` (Phase 1 already merged). Implement on a `dev/*` branch cut from `determinism`; PR back into `determinism` (NOT `master`).

## Global Constraints

- **Branch workflow:** never commit to `master`/`determinism` directly. Cut `dev/phase2-decide` from `determinism`; PR into `determinism`.
- **Prompt-engineering rule:** NEVER add task-specific domain rules to `data/prompts/*.md`. The new `Constraint` predicate fields are populated by INTENT (which reads `learn_ctx`) and the LEARN mechanism — not by a prompt patch. This plan touches NO file under `data/prompts/`.
- **`vm.answer` is called exactly once per task** (the `answer_once` guard in `pipeline.py`). A preflight deny must return before the loop and answer once; it must not also let the loop answer.
- **Deterministic, never-raise:** every predicate evaluation in `decide.py` goes through the `_holds` guard (a mis-typed constraint degrades to "does not hold" and is logged, never crashes the task). `identity_of` swallows VM errors → `{}`.
- **Keep docs current (MANDATORY):** after the code lands, regenerate the affected `docs/wiki/` page via `iwiki:iwiki-ingest` and run `/iwiki-lint`. Docs/comments/commits in English.
- **Surgical changes:** touch only the four files named in the spec's "Components touched" plus their tests and the wiki. Do not refactor adjacent code.

---

## Background the executor MUST read first

You know nothing about this codebase. Read these before Task 1:

- `docs/superpowers/specs/2026-06-22-phase2-deterministic-security-outcome-design.md` — the spec this plan implements.
- `agent/ir_models.py` lines 21–131 — `PredExpr` (the predicate language), `Constraint` (lines 49–54, what you extend), `RefSpec` (62–95), `IntentSpec` (98–131, note the `_require_ok_outcome` validator).
- `agent/predicates.py` (whole file, 83 lines) — `evaluate(expr, env) -> bool` and `resolve(value, env)`. A `$name.path.idx` string resolves from `env`; everything else is a literal. `evaluate` raises only on an unhandled op (validated away); your `_holds` wrapper guards anyway.
- `agent/verify.py` (whole file, 48 lines) — the gate you generalise. Note it builds `env` from `result.env` + an `answer` binding; today it has the forward I3 only.
- `agent/interpreter.py` lines 35–52 (`InterpretError`, `CapturedAnswer`, `InterpretResult` — fields `captured`, `env`, `observations`, `sql_results`, `mutation_landed`, `label`), 126–145 (`_project_required_refs`), 284–390 (`interpret`: how `env` is seeded with `intent.params` + `env["_facts"]=facts`, how the outcome is assembled, the existing CLARIFICATION-only anti-give-up `_refuse` at 369–374).
- `agent/pipeline.py` lines 276–465 (`run_pipeline` — the INTENT guard at 310–321, the INVESTIGATE block at 323–334, the interpret→ground_refs→verify→answer block at 400–460, and `_ground_security_refs`/`_SECURITY_POLICY_REF` at 506–516). These are your two wiring sites.
- `agent/orchestrator.py` lines 234–246 (`PrePhaseFacts`: `.identity` is a `dict`), 310–339 (`_parse_identity`, `_identity_kind` — `kind` ∈ {`customer`,`employee`,`guest`}).
- `agent/mock_vm_spy.py` (whole file) — `MockVMSpy(fixtures=...)`, `fixture_key(rpc, path, args)`. An absent fixture returns `_DEFAULT_STUB` (no `path`/`paths` key). `/bin/id` is a non-mutating exec; key it `fixture_key("Exec", "/bin/id")`.
- `tests/test_verify.py`, `tests/test_grounding.py`, `tests/test_pipeline_interpreted.py` — the test idioms you will mirror (`_intent(**over)` builders, `MockVMSpy` fixtures, `call_llm_raw` patched with a `_seq(...)` side-effect).

### Key facts that shape the design

1. **The decision is data-driven, not a hardcoded chain.** Every branch reads `intent.constraints` / `intent.success_criteria` / `intent.outcome_space`. The CODE supplies the *mechanism*; the *predicates* come from INTENT/LEARN. A constraint whose `deny_when`/`unsupported_when`/`clarify_when` is `None` simply never fires that branch.

2. **Pre-loop env is facts-only.** `security_preflight` builds `env = {**intent.params, "_facts": facts, "identity": <id>}`. Plan-produced bindings do not exist yet, so a `deny_when` referencing them resolves to `None` (predicate does not hold) — only identity/facts-based denials fire before the loop. This is the safe, intended degradation.

3. **Identity is `/bin/id` only.** `facts.identity` is already the parsed `/bin/id` (orchestrator pre-phase). `identity_of` prefers it and only re-execs `/bin/id` as a fallback. A claimed authority in the task text is NEVER an identity.

4. **Blast-radius gate.** A constraint marked `requires_protected_action=True` (an injection/system-override check) fires only when `has_protected_action` is True — i.e. a mutation already landed OR a constraint is marked `protected_action=True`. A read-only task with pasted injection text therefore answers the real question instead of refusing.

5. **Anti-give-up is strictly gated.** `anti_give_up_ok` forces `OUTCOME_OK` ONLY when OK is in the outcome space AND `success_criteria["OUTCOME_OK"]` is non-empty AND every criterion holds against the env AND no unresolved `$`-ref remains. Empty criteria → it returns False (it cannot fabricate an OK). This is the spec's false-OK mitigation.

6. **Ladder ordering is load-bearing.** `security_deny` outranks everything (a real deny is never downgraded); `unsupported_or_clarify` outranks anti-give-up (a terminal-state/ambiguous task is not forced OK); anti-give-up outranks the plan's own outcome (the model cannot give up on a solved task). When nothing fires, the plan's outcome stands.

7. **`verify` becomes a consistency gate.** After `decide_outcome` sets the outcome, `verify` checks it is consistent: forward I3 (a holding `deny_when` ⇒ must be DENIED) AND a new reverse I3 (DENIED ⇒ some declared `deny_when` must hold, when any are declared). It does NOT re-decide.

8. **`_ground_security_refs` timing.** Today `pipeline._ground_security_refs` appends `/docs/security.md` to a DENIED answer *after* `verify`. If `decide_outcome` newly flips an answer to DENIED, `verify` runs first and could miss a `required_refs["OUTCOME_DENIED_SECURITY"]` doc. So `decide_outcome` itself appends `SECURITY_POLICY_DOC` in its deny branch (the post-verify append in the pipeline then becomes idempotent). Keep `pipeline._SECURITY_POLICY_REF` as-is (do not refactor).

### Design decisions (read before coding)

- **Five new `Constraint` fields, all optional with defaults** → fully back-compatible with persisted `data/heuristics/{tid}.intent.json` (missing keys take defaults; `extra="forbid"` rejects only *unknown* keys, not missing optionals).
- **`refs: list[RefSpec]` is a forward reference** (`RefSpec` is defined after `Constraint`). Add an explicit `Constraint.model_rebuild()` after `RefSpec` is declared.
- **`decide.py` imports only `ir_models` + `predicates`** (both import-cycle-free). `identity_of`'s `/bin/id` fallback does a LAZY `from .orchestrator import _parse_identity` inside the function to avoid any import cycle.
- **`SECURITY_POLICY_DOC = "/docs/security.md"`** lives in `decide.py` (mirrors `pipeline._SECURITY_POLICY_REF`; a one-line constant duplicated rather than cross-imported to avoid a `decide ↔ pipeline` cycle).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `agent/ir_models.py` | Pydantic IR models | Extend `Constraint` with 5 fields + `model_rebuild()` |
| `agent/decide.py` | **New** — deterministic outcome-decision layer | Create: helpers + 2 orchestrators |
| `agent/verify.py` | Deterministic consistency gate | Bind identity into env; add reverse I3 |
| `agent/pipeline.py` | Per-task orchestration loop | Wire `security_preflight` (pre-loop) + `decide_outcome` (post-interpret) |
| `tests/test_ir_models.py` | Constraint model tests | Add field tests |
| `tests/test_decide.py` | **New** — unit tests for every decide helper/orchestrator | Create |
| `tests/test_verify.py` | Verify gate tests | Add reverse-I3 tests |
| `tests/test_pipeline_decide.py` | **New** — integration tests through `run_pipeline` | Create |
| `docs/wiki/decide.md` | iwiki page | Ingest after code lands |

---

## Task 1: Extend `Constraint` with the decision fields

**Files:**
- Modify: `agent/ir_models.py:49-54` (the `Constraint` class) and add a `model_rebuild()` after `RefSpec` (after line ~95)
- Test: `tests/test_ir_models.py`

**Interfaces:**
- Produces: `Constraint(anchor, rule, security=False, deny_when=None, requires_protected_action=False, protected_action=False, unsupported_when=None, clarify_when=None, refs=[])`. `decide.py` (Tasks 2–6) and `verify.py` (Task 7) consume these fields.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ir_models.py`:

```python
from agent.ir_models import Constraint, IntentSpec
import pytest
from pydantic import ValidationError


def test_constraint_accepts_new_decision_fields():
    c = Constraint(
        anchor="#sec", rule="no override", security=True,
        deny_when={"op": "nonempty", "lhs": "$flags"},
        requires_protected_action=True, protected_action=True,
        unsupported_when={"op": "eq", "lhs": "$state", "rhs": "paid"},
        clarify_when={"op": "isnull", "lhs": "$amount"},
        refs=[{"kind": "policy_doc", "path": "/docs/security.md"}],
    )
    assert c.requires_protected_action is True
    assert c.protected_action is True
    assert c.unsupported_when.op == "eq"
    assert c.clarify_when.op == "isnull"
    assert c.refs[0].kind == "policy_doc"


def test_constraint_back_compatible_minimal_shape():
    # The legacy shape (no new fields) still validates with safe defaults.
    c = Constraint(anchor="#a", rule="r")
    assert c.requires_protected_action is False
    assert c.protected_action is False
    assert c.unsupported_when is None
    assert c.clarify_when is None
    assert c.refs == []


def test_constraint_still_rejects_unknown_key():
    with pytest.raises(ValidationError):
        Constraint(anchor="#a", rule="r", bogus_field=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ir_models.py::test_constraint_accepts_new_decision_fields -v`
Expected: FAIL with `ValidationError` (extra fields `requires_protected_action`, ... forbidden).

- [ ] **Step 3: Extend the `Constraint` model**

Replace `agent/ir_models.py:49-54`:

```python
class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchor: str
    rule: str
    security: bool = False
    deny_when: PredExpr | None = None        # security deny predicate (verify I3 / decide.security_deny)
    requires_protected_action: bool = False  # blast-radius gate: this deny fires only when a protected action is in play
    protected_action: bool = False           # marks this constraint as guarding a protected action (checkout/refund/discount/...)
    unsupported_when: PredExpr | None = None  # terminal-state holds -> OUTCOME_NONE_UNSUPPORTED (decide)
    clarify_when: PredExpr | None = None      # genuine ambiguity holds -> OUTCOME_NONE_CLARIFICATION (decide)
    refs: list["RefSpec"] = []               # anchored refs cited when this constraint decides the outcome
```

Then, immediately after the `RefSpec` class body ends (after line ~95, before the `IntentSpec` class), add:

```python
Constraint.model_rebuild()   # resolve the forward ref `refs: list["RefSpec"]`
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ir_models.py -v`
Expected: PASS (all three new tests + every pre-existing test).

- [ ] **Step 5: Run the IR-model regression to prove no break**

Run: `uv run pytest tests/test_ir_models.py tests/test_verify.py tests/test_interpreter.py -q`
Expected: PASS (persisted-intent shape and verify still validate unchanged).

- [ ] **Step 6: Commit**

```bash
git add agent/ir_models.py tests/test_ir_models.py
git commit -m "feat(ir): extend Constraint with decision fields for Phase 2 decide layer"
```

---

## Task 2: `decide.py` — identity + protected-action helpers

**Files:**
- Create: `agent/decide.py`
- Test: `tests/test_decide.py`

**Interfaces:**
- Consumes: `IntentSpec`/`Constraint` (Task 1), `predicates.evaluate`/`resolve`, `orchestrator._parse_identity` (lazy), `MockVMSpy`.
- Produces: `SECURITY_POLICY_DOC: str`, `_holds(expr, env) -> bool`, `identity_of(vm, facts) -> dict`, `has_protected_action(intent, result=None) -> bool`. Tasks 3–6 build on these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_decide.py`:

```python
from agent.decide import identity_of, has_protected_action, _holds
from agent.ir_models import IntentSpec
from agent.interpreter import InterpretResult, CapturedAnswer
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _intent(**over):
    base = dict(objective="o", desired_outcome="d",
                outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY",
                               "OUTCOME_NONE_UNSUPPORTED", "OUTCOME_NONE_CLARIFICATION"],
                constraints=[], success_criteria={}, answer_shape={}, required_refs={})
    base.update(over)
    return IntentSpec(**base)


def _result(outcome="OUTCOME_OK", refs=None, env=None, message="m", mutation=False):
    return InterpretResult(
        captured=CapturedAnswer(message=message, outcome=outcome, refs=refs or []),
        env=env or {}, observations=[], sql_results=[], mutation_landed=mutation, label="x")


class _Facts:
    def __init__(self, identity):
        self.identity = identity


def test_holds_guards_none_and_eval_errors():
    assert _holds(None, {}) is False
    # contains_any on a non-iterable lhs would raise inside evaluate -> guarded to False
    bad = {"op": "contains_any", "lhs": "$x", "rhs": ["a"]}
    from agent.ir_models import PredExpr
    assert _holds(PredExpr(**bad), {"x": 5}) in (True, False)  # never raises


def test_identity_prefers_facts_identity():
    vm = MockVMSpy(fixtures={})
    assert identity_of(vm, _Facts({"kind": "customer", "customer_id": "cust_016"})) == \
        {"kind": "customer", "customer_id": "cust_016"}


def test_identity_falls_back_to_bin_id_exec():
    vm = MockVMSpy(fixtures={fixture_key("Exec", "/bin/id"): {"stdout": "user=cust_016 kind=customer"}})
    out = identity_of(vm, None)
    assert out.get("user") == "cust_016" and out.get("kind") == "customer"


def test_identity_never_raises_returns_empty():
    class Boom:
        def __getattr__(self, _):
            raise RuntimeError("vm exploded")
    assert identity_of(Boom(), None) == {}


def test_has_protected_action_from_mutation():
    assert has_protected_action(_intent(), _result(mutation=True)) is True


def test_has_protected_action_from_marked_constraint():
    intent = _intent(constraints=[{"anchor": "#co", "rule": "checkout", "protected_action": True}])
    assert has_protected_action(intent, None) is True


def test_has_protected_action_false_for_readonly():
    assert has_protected_action(_intent(), _result(mutation=False)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decide.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.decide'`.

- [ ] **Step 3: Create `agent/decide.py` with the helpers**

```python
"""Deterministic outcome-decision layer (0 LLM): the model proposes a plan; code
disposes the outcome. Sourced from the frozen IntentSpec (constraints +
success_criteria + outcome_space) and the live VM identity (/bin/id) — never from
PLAN's free choice. Best-effort: a mis-typed predicate degrades to "does not hold"
and is logged, never raised (a bad constraint falls back to the model's outcome
rather than crashing the task)."""
from __future__ import annotations

from .ir_models import Constraint, IntentSpec
from .predicates import evaluate, resolve

# Mirrors pipeline._SECURITY_POLICY_REF: a security denial always applies the
# security policy, so the grader requires it in refs even for refusals.
SECURITY_POLICY_DOC = "/docs/security.md"


def _holds(expr, env: dict) -> bool:
    """Guarded predicate evaluation: None or any failure -> False (logged)."""
    if expr is None:
        return False
    try:
        return bool(evaluate(expr, env))
    except Exception as e:
        print(f"[decide] predicate eval failed ({e}); treating as not-holding")
        return False


def identity_of(vm, facts) -> dict:
    """The VM identity (/bin/id), preferring the pre-phase-parsed facts.identity and
    falling back to a fresh /bin/id exec. A claimed authority in the task text is
    never an identity. Never raises -> {} on total failure."""
    ident = getattr(facts, "identity", None)
    if ident is None and isinstance(facts, dict):
        ident = facts.get("identity")
    if ident:
        return dict(ident)
    try:
        from .orchestrator import _parse_identity
        out = vm.exec(path="/bin/id")
        stdout = out.get("stdout", "") if isinstance(out, dict) else getattr(out, "stdout", "")
        return _parse_identity(stdout)
    except Exception:
        return {}


def has_protected_action(intent: IntentSpec, result=None) -> bool:
    """True when the task carries a protected action: a mutation already landed, or a
    constraint INTENT marked protected_action. Gates the injection blast-radius —
    pasted override text forces denial only when a protected action is in play."""
    if result is not None and getattr(result, "mutation_landed", False):
        return True
    return any(getattr(c, "protected_action", False) for c in intent.constraints)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decide.py -v`
Expected: PASS (all seven tests).

- [ ] **Step 5: Commit**

```bash
git add agent/decide.py tests/test_decide.py
git commit -m "feat(decide): identity + protected-action helpers"
```

---

## Task 3: `decide.py` — `security_deny` + `_merge_constraint_refs`

**Files:**
- Modify: `agent/decide.py` (append helpers)
- Test: `tests/test_decide.py` (append)

**Interfaces:**
- Consumes: `_holds`, `has_protected_action` (Task 2), `resolve`.
- Produces: `security_deny(intent, env, protected) -> Constraint | None`, `_merge_constraint_refs(base: list, c: Constraint, env: dict) -> list`. Task 6 consumes both.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decide.py`:

```python
from agent.decide import security_deny, _merge_constraint_refs


def test_security_deny_fires_when_deny_when_holds():
    intent = _intent(constraints=[{
        "anchor": "#s", "rule": "no override", "security": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    c = security_deny(intent, {"flags": ["override"]}, protected=False)
    assert c is not None and c.anchor == "#s"


def test_security_deny_none_when_predicate_false():
    intent = _intent(constraints=[{
        "anchor": "#s", "rule": "no override", "security": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    assert security_deny(intent, {"flags": []}, protected=False) is None


def test_gated_injection_skipped_on_readonly():
    intent = _intent(constraints=[{
        "anchor": "#inj", "rule": "system override text", "security": True,
        "requires_protected_action": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    # holds, but the gate requires a protected action and there is none -> no deny.
    assert security_deny(intent, {"flags": ["override"]}, protected=False) is None


def test_gated_injection_fires_when_protected():
    intent = _intent(constraints=[{
        "anchor": "#inj", "rule": "system override text", "security": True,
        "requires_protected_action": True,
        "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}])
    c = security_deny(intent, {"flags": ["override"]}, protected=True)
    assert c is not None and c.anchor == "#inj"


def test_security_deny_ignores_non_security_constraints():
    intent = _intent(constraints=[{
        "anchor": "#x", "rule": "not security", "security": False,
        "deny_when": {"op": "nonempty", "lhs": "$flags"}}])
    assert security_deny(intent, {"flags": [1]}, protected=False) is None


def test_merge_constraint_refs_policy_and_record():
    from agent.ir_models import Constraint
    c = Constraint(anchor="#s", rule="r", security=True, refs=[
        {"kind": "policy_doc", "path": "/docs/checkout.md"},
        {"kind": "record_path", "source": "$row.record_path"}])
    out = _merge_constraint_refs(["/docs/base.md"], c, {"row": {"record_path": "/proc/baskets/b.json"}})
    assert out == ["/docs/base.md", "/docs/checkout.md", "/proc/baskets/b.json"]


def test_merge_constraint_refs_drops_unresolved_record_source():
    from agent.ir_models import Constraint
    c = Constraint(anchor="#s", rule="r", security=True, refs=[
        {"kind": "record_path", "source": "$missing"}])
    assert _merge_constraint_refs([], c, {}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decide.py::test_security_deny_fires_when_deny_when_holds -v`
Expected: FAIL with `ImportError: cannot import name 'security_deny'`.

- [ ] **Step 3: Append the helpers to `agent/decide.py`**

```python
def security_deny(intent: IntentSpec, env: dict, protected: bool) -> Constraint | None:
    """First security constraint whose deny_when holds, else None. A constraint marked
    requires_protected_action is skipped unless `protected` (the injection blast-radius
    gate). Predicate failures -> not-holding (never raises)."""
    for c in intent.constraints:
        if not (c.security and c.deny_when is not None):
            continue
        if getattr(c, "requires_protected_action", False) and not protected:
            continue
        if _holds(c.deny_when, env):
            return c
    return None


def _merge_constraint_refs(base: list, c: Constraint, env: dict) -> list:
    """Append a deciding constraint's anchored refs (RefSpec) to base, deduped.
    policy_doc -> literal path; record_path -> resolve($source, env) when it lands."""
    out = list(base)
    for r in getattr(c, "refs", []) or []:
        if r.kind == "policy_doc" and r.path:
            v = r.path
        elif r.kind == "record_path":
            rv = resolve(r.source, env)
            v = str(rv) if rv not in (None, "") else None
        else:
            v = None
        if v and v not in out:
            out.append(v)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decide.py -v`
Expected: PASS (all Task 2 + Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/decide.py tests/test_decide.py
git commit -m "feat(decide): security_deny with blast-radius gate + constraint-ref merge"
```

---

## Task 4: `decide.py` — `unsupported_or_clarify`

**Files:**
- Modify: `agent/decide.py` (append)
- Test: `tests/test_decide.py` (append)

**Interfaces:**
- Consumes: `_holds` (Task 2), `intent.outcome_space`.
- Produces: `unsupported_or_clarify(intent, env) -> str | None`. Task 6 consumes it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decide.py`:

```python
from agent.decide import unsupported_or_clarify


def test_unsupported_when_maps_to_unsupported():
    intent = _intent(constraints=[{
        "anchor": "#paid", "rule": "already paid", "security": False,
        "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}}])
    assert unsupported_or_clarify(intent, {"state": "paid"}) == "OUTCOME_NONE_UNSUPPORTED"


def test_clarify_when_maps_to_clarification():
    intent = _intent(constraints=[{
        "anchor": "#amb", "rule": "amount only", "security": False,
        "clarify_when": {"op": "isnull", "lhs": "$basket"}}])
    assert unsupported_or_clarify(intent, {"basket": None}) == "OUTCOME_NONE_CLARIFICATION"


def test_unsupported_outranks_clarify():
    intent = _intent(constraints=[
        {"anchor": "#paid", "rule": "paid", "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}},
        {"anchor": "#amb", "rule": "amb", "clarify_when": {"op": "isnull", "lhs": "$basket"}}])
    assert unsupported_or_clarify(intent, {"state": "paid", "basket": None}) == "OUTCOME_NONE_UNSUPPORTED"


def test_outcome_gated_by_space():
    # unsupported_when holds but OUTCOME_NONE_UNSUPPORTED is not in the space -> None.
    intent = _intent(outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
                     constraints=[{"anchor": "#p", "rule": "p",
                                   "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}}])
    assert unsupported_or_clarify(intent, {"state": "paid"}) is None


def test_no_predicate_returns_none():
    assert unsupported_or_clarify(_intent(), {"state": "open"}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decide.py::test_unsupported_when_maps_to_unsupported -v`
Expected: FAIL with `ImportError: cannot import name 'unsupported_or_clarify'`.

- [ ] **Step 3: Append the helper to `agent/decide.py`**

```python
def unsupported_or_clarify(intent: IntentSpec, env: dict) -> str | None:
    """Deterministic negative-outcome split. Terminal-state conditions
    (unsupported_when) outrank genuine ambiguity (clarify_when). Returns an outcome
    only if it is in the declared outcome_space, else None."""
    space = intent.outcome_space or []
    for c in intent.constraints:
        if _holds(getattr(c, "unsupported_when", None), env):
            if "OUTCOME_NONE_UNSUPPORTED" in space:
                return "OUTCOME_NONE_UNSUPPORTED"
    for c in intent.constraints:
        if _holds(getattr(c, "clarify_when", None), env):
            if "OUTCOME_NONE_CLARIFICATION" in space:
                return "OUTCOME_NONE_CLARIFICATION"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decide.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add agent/decide.py tests/test_decide.py
git commit -m "feat(decide): unsupported-vs-clarification deterministic split"
```

---

## Task 5: `decide.py` — `anti_give_up_ok`

**Files:**
- Modify: `agent/decide.py` (append)
- Test: `tests/test_decide.py` (append)

**Interfaces:**
- Consumes: `_holds` (Task 2), `intent.success_criteria`, `intent.outcome_space`, `result.captured.refs`.
- Produces: `anti_give_up_ok(intent, result, env) -> bool`. Task 6 consumes it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decide.py`:

```python
from agent.decide import anti_give_up_ok


def test_anti_give_up_forces_ok_when_criteria_hold():
    intent = _intent(success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(message="5 in stock")
    env = {"answer": {"message": "5 in stock"}}
    assert anti_give_up_ok(intent, res, env) is True


def test_anti_give_up_false_when_criteria_fail():
    intent = _intent(success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(message="")
    env = {"answer": {"message": ""}}
    assert anti_give_up_ok(intent, res, env) is False


def test_anti_give_up_false_when_no_criteria():
    # empty criteria -> cannot assert solved -> never fabricate OK.
    assert anti_give_up_ok(_intent(success_criteria={}), _result(message="x"), {}) is False


def test_anti_give_up_false_when_ok_not_in_space():
    intent = _intent(outcome_space=["OUTCOME_DENIED_SECURITY"],
                     constraints=[{"anchor": "#s", "rule": "r", "security": True,
                                   "deny_when": {"op": "nonempty", "lhs": "$x"}}],
                     success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    assert anti_give_up_ok(intent, _result(message="x"), {"answer": {"message": "x"}}) is False


def test_anti_give_up_false_when_unresolved_ref_present():
    intent = _intent(success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(message="x", refs=["$still_a_ref"])
    assert anti_give_up_ok(intent, res, {"answer": {"message": "x"}}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decide.py::test_anti_give_up_forces_ok_when_criteria_hold -v`
Expected: FAIL with `ImportError: cannot import name 'anti_give_up_ok'`.

- [ ] **Step 3: Append the helper to `agent/decide.py`**

```python
def anti_give_up_ok(intent: IntentSpec, result, env: dict) -> bool:
    """True iff OK is reachable and the plan produced a grounded result satisfying
    EVERY success_criteria[OUTCOME_OK]. Strictly gated: empty criteria or any
    unresolved $-ref -> False (cannot fabricate OK). This is the spec's false-OK
    mitigation — the model cannot downgrade a solved task, and code cannot invent one."""
    if "OUTCOME_OK" not in (intent.outcome_space or []):
        return False
    crits = intent.success_criteria.get("OUTCOME_OK", [])
    if not crits:
        return False
    refs = getattr(result.captured, "refs", []) or []
    if any(isinstance(r, str) and r.startswith("$") for r in refs):
        return False
    return all(_holds(c, env) for c in crits)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decide.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add agent/decide.py tests/test_decide.py
git commit -m "feat(decide): strictly-gated anti-give-up OK grant"
```

---

## Task 6: `decide.py` — `decide_outcome` + `security_preflight` orchestrators

**Files:**
- Modify: `agent/decide.py` (append)
- Test: `tests/test_decide.py` (append)

**Interfaces:**
- Consumes: every helper from Tasks 2–5.
- Produces:
  - `decide_outcome(intent, result, vm, facts) -> tuple[str, list]` — `(outcome, refs)`.
  - `security_preflight(intent, vm, facts) -> tuple[str, str, list] | None` — `(outcome, message, refs)` or None.

  Task 8 (`pipeline.py`) consumes both.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_decide.py`:

```python
from agent.decide import decide_outcome, security_preflight


def test_decide_security_deny_outranks_all():
    intent = _intent(
        constraints=[{"anchor": "#s", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}],
        success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(outcome="OUTCOME_OK", env={"flags": ["override"]}, message="x")
    out, refs = decide_outcome(intent, res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_DENIED_SECURITY"
    assert "/docs/security.md" in refs


def test_decide_unsupported_outranks_anti_give_up():
    intent = _intent(
        constraints=[{"anchor": "#p", "rule": "paid",
                      "unsupported_when": {"op": "eq", "lhs": "$state", "rhs": "paid"}}],
        success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(outcome="OUTCOME_OK", env={"state": "paid"}, message="x")
    out, _ = decide_outcome(intent, res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_NONE_UNSUPPORTED"


def test_decide_anti_give_up_flips_over_refusal_to_ok():
    # The 5-over-refusal class: PLAN authored DENIED, but no deny_when holds and the OK
    # criteria are satisfied -> forced OK.
    intent = _intent(
        constraints=[{"anchor": "#s", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$flags", "rhs": ["override"]}}],
        success_criteria={"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]})
    res = _result(outcome="OUTCOME_DENIED_SECURITY", env={"flags": []}, message="5 in stock")
    out, _ = decide_outcome(intent, res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_OK"


def test_decide_falls_back_to_plan_outcome():
    # Nothing fires (no criteria, no predicates) -> the plan's own outcome stands.
    res = _result(outcome="OUTCOME_NONE_CLARIFICATION", message="need more info")
    out, _ = decide_outcome(_intent(), res, MockVMSpy(fixtures={}), None)
    assert out == "OUTCOME_NONE_CLARIFICATION"


def test_preflight_terminal_deny_from_identity():
    intent = _intent(
        outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        constraints=[{"anchor": "#g", "rule": "guests not authorized", "security": True,
                      "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    out = security_preflight(intent, MockVMSpy(fixtures={}), _Facts({"kind": "guest"}))
    assert out is not None
    outcome, msg, refs = out
    assert outcome == "OUTCOME_DENIED_SECURITY"
    assert "guests not authorized" in msg
    assert "/docs/security.md" in refs


def test_preflight_none_when_no_deny():
    intent = _intent(
        constraints=[{"anchor": "#g", "rule": "guests not authorized", "security": True,
                      "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}])
    assert security_preflight(intent, MockVMSpy(fixtures={}), _Facts({"kind": "customer"})) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decide.py::test_decide_security_deny_outranks_all -v`
Expected: FAIL with `ImportError: cannot import name 'decide_outcome'`.

- [ ] **Step 3: Append the orchestrators to `agent/decide.py`**

```python
def _decision_env(intent: IntentSpec, result, vm, facts) -> dict:
    """Env for post-interpret decisions: the plan's bound env + the /bin/id identity +
    the assembled answer (so success_criteria over $answer.* resolve)."""
    env = dict(result.env)
    env["identity"] = identity_of(vm, facts)
    cap = result.captured
    env["answer"] = {"message": cap.message, "outcome": cap.outcome, "refs": list(cap.refs)}
    return env


def decide_outcome(intent: IntentSpec, result, vm, facts) -> tuple[str, list]:
    """Reconcile the plan's outcome with the frozen IntentSpec + /bin/id identity.
    Ladder: security_deny > unsupported_or_clarify > anti_give_up_ok > the plan's own
    outcome. Returns (outcome, refs); refs default to the grounded answer.refs.

    verify (Task 7) re-checks consistency afterwards — this is where outcomes are
    decided, not where they are validated."""
    env = _decision_env(intent, result, vm, facts)
    base_refs = list(result.captured.refs or [])
    protected = has_protected_action(intent, result)

    c = security_deny(intent, env, protected)
    if c is not None:
        refs = _merge_constraint_refs(base_refs, c, env)
        if SECURITY_POLICY_DOC not in refs:
            refs.append(SECURITY_POLICY_DOC)
        return "OUTCOME_DENIED_SECURITY", refs

    uc = unsupported_or_clarify(intent, env)
    if uc is not None:
        return uc, base_refs

    if anti_give_up_ok(intent, result, env):
        return "OUTCOME_OK", base_refs

    return result.captured.outcome, base_refs


def security_preflight(intent: IntentSpec, vm, facts) -> tuple[str, str, list] | None:
    """Pre-loop terminal security gate. Builds a facts-only env (plan-produced bindings
    do not exist yet, so only identity/facts-based deny_when can fire) and returns
    (outcome, message, refs) when a security deny holds, else None (proceed to loop)."""
    env: dict = dict(intent.params or {})
    env["_facts"] = facts
    env["identity"] = identity_of(vm, facts)
    protected = has_protected_action(intent, None)
    c = security_deny(intent, env, protected)
    if c is None:
        return None
    refs = _merge_constraint_refs([], c, env)
    if SECURITY_POLICY_DOC not in refs:
        refs.append(SECURITY_POLICY_DOC)
    return "OUTCOME_DENIED_SECURITY", f"Denied by security policy: {c.rule}", refs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decide.py -v`
Expected: PASS (the whole `test_decide.py` suite).

- [ ] **Step 5: Commit**

```bash
git add agent/decide.py tests/test_decide.py
git commit -m "feat(decide): decide_outcome ladder + pre-loop security_preflight"
```

---

## Task 7: `verify.py` — generalise I3 to both directions

**Files:**
- Modify: `agent/verify.py:12-47`
- Test: `tests/test_verify.py` (append)

**Interfaces:**
- Consumes: `evaluate`, `intent.constraints`, `result.env["_facts"].identity`.
- Produces: an unchanged `verify(result, intent) -> tuple[bool, str]` signature whose I3 now also rejects a spurious DENIED.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_verify.py`:

```python
def test_i3_reverse_denied_without_holding_predicate_fails():
    # A declared security deny_when exists but does NOT hold, yet the outcome is DENIED
    # -> spurious over-refusal -> verify rejects (the 5-over-refusal class).
    intent = _intent(constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                                    "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env={"tags": []})
    ok, err = verify(res, intent)
    assert not ok and "DENIED_SECURITY" in err


def test_i3_reverse_denied_with_no_declared_predicate_passes():
    # No declared security deny_when at all -> the model's denial is not second-guessed.
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]))
    ok, err = verify(res, _intent())
    assert ok, err


def test_i3_reverse_denied_with_holding_predicate_passes():
    intent = _intent(constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                                   "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}])
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert ok, err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_verify.py::test_i3_reverse_denied_without_holding_predicate_fails -v`
Expected: FAIL — today verify returns `(True, "")` for a DENIED answer regardless of whether any deny_when holds.

- [ ] **Step 3: Generalise I3 in `agent/verify.py`**

After the existing `env["answer"] = {...}` line (currently line 15), add the identity binding:

```python
    # Phase 2: bind /bin/id identity for parity with decide.py's deny_when env so the
    # consistency re-check evaluates the same predicates the decision layer did.
    _facts = env.get("_facts")
    _ident = getattr(_facts, "identity", None)
    if _ident is None and isinstance(_facts, dict):
        _ident = _facts.get("identity")
    env["identity"] = _ident or {}
```

Then, immediately AFTER the existing forward-I3 loop (currently lines 34-38, the `for c in intent.constraints:` block ending with the DENIED_SECURITY check), add the reverse direction:

```python
    # I3 reverse: a DENIED_SECURITY outcome must be justified by a declared security
    # deny_when that holds. When the intent declares security deny_when predicates and
    # NONE hold, the denial is a spurious over-refusal -> fail. When NO security
    # deny_when is declared, the model's denial is not second-guessed (the predicate
    # machinery is simply not in play).
    if ans.outcome == "OUTCOME_DENIED_SECURITY":
        _sec = [c for c in intent.constraints if c.security and c.deny_when is not None]
        if _sec and not any(evaluate(c.deny_when, env) for c in _sec):
            return False, ("I3: outcome DENIED_SECURITY but no declared security "
                           "deny_when predicate holds (spurious over-refusal)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_verify.py -v`
Expected: PASS — the 3 new tests AND every pre-existing verify test (forward I3 untouched; `test_i3_security_deny_when_true_and_denied_passes` still green because its predicate holds).

- [ ] **Step 5: Commit**

```bash
git add agent/verify.py tests/test_verify.py
git commit -m "feat(verify): generalise I3 to reject spurious DENIED over-refusals"
```

---

## Task 8: `pipeline.py` — wire preflight (pre-loop) + decide_outcome (post-interpret)

**Files:**
- Modify: `agent/pipeline.py` — the local import block (283-287), the post-INTENT site (after 321), the interpret→verify block (433-440)
- Test: `tests/test_pipeline_decide.py` (new)

**Interfaces:**
- Consumes: `decide_outcome`, `security_preflight` (Task 6).
- Produces: the same `run_pipeline(...) -> dict` contract. New behaviour: a pre-loop terminal deny (`cycles_used=0`), and a code-decided outcome on every cycle before verify.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_pipeline_decide.py`:

```python
import json
from unittest.mock import MagicMock, patch
import pytest

from agent.pipeline import run_pipeline


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        return next(it)
    return _next


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    from agent import learned_store
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")   # skip the ReAct phase in tests
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


# A plan that runs a trivial discovery and authors an OK answer.
_PLAN_OK = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 5 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "{row0.cnt} in stock", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})
# Same, but the model over-refuses (authors DENIED) despite nothing denying.
_PLAN_DENY = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 5 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "deny"}, "ops": [],
    "answer": {"deny": {"message": "{row0.cnt} in stock", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    "custom_extract": [],
})


def test_preflight_denies_before_loop():
    # Guest identity + a security deny_when on identity.kind -> terminal deny, 0 cycles,
    # PLAN never called (only INTENT is in the LLM sequence).
    intent = json.dumps({
        "objective": "checkout", "desired_outcome": "deny", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        "constraints": [{"anchor": "#g", "rule": "guests cannot checkout", "security": True,
                         "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}],
        "success_criteria": {}, "answer_shape": {}, "required_refs": {},
    })
    vm = MagicMock()
    facts = {"identity": {"kind": "guest"}}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent)):
        m = run_pipeline(vm, instruction="check out my basket", task_id="t_pre",
                         agents_md_text="A", facts=facts)
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_DENIED_SECURITY"
    assert m["cycles_used"] == 0
    # the SQL discovery was never run because the loop never started
    vm.exec.assert_not_called()


def test_decide_flips_over_refusal_to_ok():
    # Security deny_when references identity.kind == guest, but the caller is a customer,
    # so the deny does NOT hold; PLAN over-refuses (DENIED); OK criteria are satisfied
    # -> decide_outcome forces OUTCOME_OK and verify passes.
    intent = json.dumps({
        "objective": "count stock", "desired_outcome": "int", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
        "constraints": [{"anchor": "#g", "rule": "guests cannot do this", "security": True,
                         "deny_when": {"op": "eq", "lhs": "$identity.kind", "rhs": "guest"}}],
        "success_criteria": {"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]},
        "answer_shape": {}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    facts = {"identity": {"kind": "customer", "customer_id": "cust_016"}}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_DENY)):
        m = run_pipeline(vm, instruction="how many in stock", task_id="t_flip",
                         agents_md_text="A", facts=facts)
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"


def test_happy_path_unaffected_by_decide():
    # No constraints, OK plan, OK criteria hold -> still OK (decide falls through cleanly).
    intent = json.dumps({
        "objective": "count", "desired_outcome": "int", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [],
        "success_criteria": {"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]},
        "answer_shape": {}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_OK)):
        m = run_pipeline(vm, instruction="how many", task_id="t_ok",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_decide.py -v`
Expected: FAIL — `test_preflight_denies_before_loop` fails because no preflight runs (the loop starts and `vm.exec` IS called / outcome is not a 0-cycle deny), and `test_decide_flips_over_refusal_to_ok` fails because the DENIED outcome is not flipped.

- [ ] **Step 3: Add the `decide` import**

In `agent/pipeline.py`, inside `run_pipeline`, extend the local import block (currently lines 283-287) with:

```python
    from .decide import decide_outcome, security_preflight
```

- [ ] **Step 4: Wire the pre-loop security preflight**

In `agent/pipeline.py`, immediately AFTER the INTENT-None guard block (currently ending at line 321 with the `return {...}` of the `if intent is None:` branch) and BEFORE the `# INVESTIGATE ...` comment (currently line 323), insert:

```python
    # Security preflight (Phase 2): a deterministic terminal deny BEFORE any plan runs,
    # driven by IntentSpec security constraints + /bin/id identity (never PLAN's choice).
    # Identity/facts-based deny_when can fire here; plan-derived predicates resolve to
    # None pre-loop and simply do not hold. Runs before INVESTIGATE so a clear deny does
    # not spend the ReAct budget.
    pre = security_preflight(intent, vm, facts)
    if pre is not None:
        _outcome, _msg, _refs = pre
        save_last_run(task_id, "failure", _outcome, 0)
        answer_once(_msg, _outcome, _refs)
        return {"cycles_used": 0, "outcome": _outcome, "status": "failure",
                "input_tokens": total_in, "output_tokens": total_out,
                "answer_message": _msg, "answer_refs": _refs}
```

- [ ] **Step 5: Wire `decide_outcome` between ground-refs and verify**

In `agent/pipeline.py`, in the cycle body, locate (currently lines 433-439):

```python
        result.captured.refs = ground_refs(intent, result.captured, result, vm,
                                            instruction, docs_read=_docs_read)
        ok, verr = verify(result, intent)
```

Insert the decision between them:

```python
        result.captured.refs = ground_refs(intent, result.captured, result, vm,
                                            instruction, docs_read=_docs_read)
        # Phase 2: deterministic outcome decision (security deny / unsupported / clarify
        # / anti-give-up OK) overwrites the PLAN-authored outcome BEFORE verify, which
        # then becomes the consistency gate rather than the place outcomes are born.
        _decided_outcome, _decided_refs = decide_outcome(intent, result, vm, facts)
        result.captured.outcome = _decided_outcome
        result.captured.refs = _decided_refs
        ok, verr = verify(result, intent)
```

- [ ] **Step 6: Run the new integration tests**

Run: `uv run pytest tests/test_pipeline_decide.py -v`
Expected: PASS (all three tests).

- [ ] **Step 7: Run the pipeline regression suite**

Run: `uv run pytest tests/test_pipeline_interpreted.py tests/test_pipeline_grounding.py tests/test_pipeline_v2.py tests/test_pipeline_investigate.py -q`
Expected: PASS — the happy path, grounding, and investigate integration tests are unaffected (decide falls through to the plan's outcome when no constraint/criteria fire).

- [ ] **Step 8: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_decide.py
git commit -m "feat(pipeline): wire security_preflight (pre-loop) + decide_outcome (post-interpret)"
```

---

## Task 9: Full-suite regression + docs

**Files:**
- Read-only: whole `tests/` tree
- Modify: `docs/wiki/decide.md` (ingested), `agent/CLAUDE.md` (architecture flow), `docs/wiki/.iwiki/index.jsonl` (auto by ingest)

**Interfaces:** none (verification + documentation only).

- [ ] **Step 1: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, except the one KNOWN pre-existing red `tests/test_corpus_replay.py::test_t09_replay_matches_known_good` (stale parity fixture — see memory `t09 corpus stale`; NOT a regression). If ANY other test fails, fix it before continuing — do not mark this task complete with a new red.

- [ ] **Step 2: Update the agent-package architecture doc**

In `agent/CLAUDE.md`, in the per-task execution flow (the LOOP section), document the two new deterministic steps. After the `ground-refs` bullet and before the `verify` bullet, add:

```markdown
   - **decide-outcome** (`decide.py:decide_outcome(intent, result, vm, facts)`) — no LLM.
     Overwrites the PLAN-authored `result.captured.outcome`/`refs` via the ladder
     `security_deny > unsupported_or_clarify > anti_give_up_ok > plan-outcome`, sourced
     from the frozen IntentSpec constraints + `/bin/id` identity. Runs BEFORE verify, so
     verify is a consistency gate, not where outcomes are born.
```

And, in the INTENT/INVESTIGATE preamble (before the LOOP), add a line:

```markdown
2.5 **SECURITY PREFLIGHT** (`decide.py:security_preflight`, no LLM) — between INTENT and
    the loop: a facts/identity-driven terminal `OUTCOME_DENIED_SECURITY` when a security
    constraint's `deny_when` holds pre-plan. Skips the loop (and any mutation) entirely.
```

- [ ] **Step 3: Ingest the new module into the wiki**

Run the iwiki skill (NOT a raw engine subcommand):

Invoke `iwiki:iwiki-ingest` with source path `agent/decide.py` to generate/update `docs/wiki/decide.md`, then have it re-index. Also re-ingest `agent/verify.py` (I3 changed) and `agent/pipeline.py` (wiring changed).

- [ ] **Step 4: Verify the wiki page exists and pages changed**

Run: `test -f docs/wiki/decide.md && git status --porcelain docs/wiki/`
Expected: `docs/wiki/decide.md` exists; `git status` shows `decide.md` (new) plus modified `verify.md`, `pipeline.md`, and `.iwiki/index.jsonl`.

- [ ] **Step 5: Lint the wiki graph**

Run the `/iwiki-lint` skill.
Expected: no broken `[[refs]]`, no orphan or stale pages introduced by the new `decide.md`.

- [ ] **Step 6: Commit**

```bash
git add agent/CLAUDE.md docs/wiki/
git commit -m "docs: Phase 2 decide layer (wiki ingest + architecture flow)"
```

- [ ] **Step 7: Open the PR into `determinism`**

```bash
git push -u origin dev/phase2-decide
gh pr create --base determinism --title "Phase 2: deterministic security/outcome decisions" \
  --body "Implements docs/superpowers/specs/2026-06-22-phase2-deterministic-security-outcome-design.md. Outcome enum decided in code (agent/decide.py) from IntentSpec constraints + /bin/id; verify generalised to a both-directions consistency gate."
```

---

## Validation against the spec's motivating evidence (measurement, post-merge)

The spec's success criterion is measured on the 23 outcome-mismatch tasks from run `20260621_232850`, NOT by unit tests. After merge, run the security/outcome subset and compare agent outcome to grader-expected:

```bash
make task TASKS='<the 23 mismatch task ids>'
```

Expected direction: the 5 over-refusals (`OK→DENIED_SECURITY`) and 2 under-refusals (`DENIED_SECURITY→CLARIFICATION`) move toward the grader-expected outcome. Where a task still mismatches because INTENT did not author a rich enough `deny_when`/`unsupported_when`/`clarify_when` predicate, that is the **LEARN/INTENT channel's job** (per the spec's Risks section) — feed the gap back through LEARN, NOT through a `data/prompts/` patch or a code special-case. Log which tasks lack the needed predicate.

This validation is a measurement step, not a code gate — it depends on a full benchmark pass (~hours) and on INTENT/LEARN populating the new constraint fields.

---

## Self-Review notes (already reconciled against the spec)

- **Design (1) security preflight** → Task 6 `security_preflight` + Task 8 wiring. ✓
- **Design (2) identity = /bin/id only + blast-radius gating** → Task 2 (`identity_of`, `has_protected_action`) + Task 3 (`requires_protected_action` gate). ✓
- **Design (3) UNSUPPORTED vs CLARIFICATION** → Task 4. ✓
- **Design (4) anti-give-up grant, gated on success_criteria** → Task 5 + Task 6 ladder. ✓
- **verify both-directions consistency** → Task 7. ✓
- **Components touched** (`decide.py`, `pipeline.py`, `verify.py`, `ir_models.py`) → Tasks 1–8; no `data/prompts/` patch (constraint fields populated via INTENT/LEARN). ✓
- **Error handling never-raises** → `_holds` guard + `identity_of` try/except, tested in Tasks 2/3/6. ✓
- **Testing unit + integration + regression** → Tasks 2–8 unit/integration, Task 9 full-suite + the post-merge measurement step. ✓
- **Type consistency** — `decide_outcome -> (outcome, refs)`; `security_preflight -> (outcome, message, refs) | None`; `security_deny -> Constraint | None`; `unsupported_or_clarify -> str | None`; `anti_give_up_ok -> bool`; `has_protected_action(intent, result=None) -> bool`. Used identically across Tasks 6 and 8. ✓
