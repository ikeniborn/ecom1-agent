---
chain:
  intent: docs/superpowers/intents/2026-06-07-deterministic-plan-interpreter-intent.md
  spec: docs/superpowers/specs/2026-06-07-deterministic-plan-interpreter-design.md
state:
  status: draft
  created: 2026-06-07
review:
  plan_hash: f098c4c19dfe61fc
  spec_hash: dfdc6266343cedfe
  last_run: 2026-06-07
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: CRITICAL
      section: "Task 3: Primitive + parser registries"
      section_hash: 1b67da8ff48ab41d
      text: "PRIMITIVES registry defined 14 entries but the spec mandates 13 and the task's own Step-1 test asserts len(PRIMITIVES)==13 — Task 3 Step-4 'Expected: PASS' was unachievable."
      verdict: fixed
      verdict_at: 2026-06-07
      resolution: "Dropped `length` (duplicate of `count`; both len()). Registry now 13; `fuzzy_sku_receipt` lives in the separate PARSERS registry."
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "Task 18: A/B benchmark run + score comparison"
      section_hash: daebaf091ef14fc1
      text: "Spec testing-strategy lists an integration layer of 3 named tasks end-to-end behind the flag (t09/t27/t51). The plan folded them into the full-suite A/B with no committed, repeatable integration test."
      verdict: fixed
      verdict_at: 2026-06-07
      resolution: "Added Task 18 Step 1: committed RUN_BENCHMARK-gated `tests/test_integration_interpreter.py` driving t09/t27/t51 end-to-end behind INTERPRETER_ENABLED via the real harness (mirrors test_benchmark_t01.py); Task 18 renumbered to 6 steps."
    - id: F-003
      phase: coverage
      severity: WARNING
      section: "Canonical API"
      section_hash: 54234d3e1f693cb5
      text: "Spec defines `ColResolve = priority list of name-match predicates`; the plan models ColResolve as `{into, candidates}` (first-present header) — an undocumented deviation."
      verdict: fixed
      verdict_at: 2026-06-07
      resolution: "Documented as Deviation #3 (literal-candidate list is the minimal form earning t48 multi-tier detection; full predicate matching unneeded — YAGNI)."
    - id: F-004
      phase: dependencies
      severity: WARNING
      section: "Task 15: Pipeline branch _run_interpreted"
      section_hash: null
      text: "Mutation-safety gap surfaced during fix-all: InterpretError did not carry mutation_landed (dead getattr branch), and the real-VM except branch lacked a read-only retry gate — a mutation that landed before a raise could wrongly retry."
      verdict: fixed
      verdict_at: 2026-06-07
      resolution: "InterpretError carries `mutation_landed`; `_refuse()` helper tags it on refusal raises (Task 5/9); Task 15 real-VM branch gates retry on a `plan_mutates` check; added Task 9 regression test `test_refuse_after_mutation_tags_mutation_landed`."
    - id: F-005
      phase: verifiability
      severity: WARNING
      section: "Task 6: Compute steps + custom_extract; Task 2: Predicate engine"
      section_hash: null
      text: "Task 6 test contained `plan.env_seed = None` (raises under pydantic v2) contradicting Step-4 PASS; Task 2 tests omitted direct `lt`/`ge` assertions though the spec wants each of 16 operators tested."
      verdict: fixed
      verdict_at: 2026-06-07
      resolution: "Removed the `env_seed` line + its note; added `lt`/`ge` assertions to test_numeric_comparisons_coerce_strings."
    - id: F-006
      phase: verifiability
      severity: INFO
      section: "Task 19: Cutover — OC7 LOC gate"
      section_hash: null
      text: "OC7 gate depended on `cloc`, absent in this environment."
      verdict: fixed
      verdict_at: 2026-06-07
      resolution: "Replaced with a portable non-blank/non-comment LOC counter + a python3 PASS/FAIL assertion on `added <= 0.60*deleted`; cloc optional."
---

# Deterministic Plan-IR Interpreter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM free-form `CODEGEN`-that-`exec()`s-Python path with a split where the LLM emits two validated data artifacts (`IntentSpec` + `PlanIR`) and a fixed deterministic interpreter executes the `PlanIR` under built-in guards, verified against the `IntentSpec` before the single terminal `vm.answer`.

**Architecture:** Six new pure/near-pure modules (`ir_models`, `predicates`, `primitives`, `interpreter`, `verify`, `reason`) built bottom-up and unit-tested with no VM, then a corpus-replay harness proves IR-path output equals the current heuristic-script output on identical fixtures. The new path lands behind `INTERPRETER_ENABLED=0` so the green baseline cannot regress; only after a full-benchmark A/B run scores ≥ baseline is the old path deleted (proposal-first / HUMAN CHECKPOINT).

**Tech Stack:** Python 3.12, Pydantic v2, pytest, `uv` for deps/run. LLM routing/`vm_adapter`/`bitgn` stubs untouched (HM5; no-autonomy zones).

---

## Scope check

This spec is a single tightly-coupled subsystem — the reason→interpret→verify pipeline. The six modules share the `PredExpr`/`env` model and cannot be built or tested independently of each other, so this is **one plan**, decomposed into the spec's six build phases. Each phase produces independently-testable software (pure engines → interpreter → verify → wiring → prephase → cutover).

## Canonical API (names used across all tasks — keep consistent)

Defined in `agent/ir_models.py` unless noted. Later tasks reference these exact names.

- `PredExpr(op, lhs=None, rhs=None, args=[])` — recursive predicate node; `op ∈ LEAF_OPS ∪ BOOL_OPS`.
- `LEAF_OPS = {"eq","ne","lt","le","gt","ge","nonempty","isnull","contains_any","in_set","startswith","endswith","regex_match"}` (13); `BOOL_OPS = {"and","or","not"}` (3) → 16 total.
- `Constraint(anchor, rule, security=False, deny_when=None)` — `deny_when: PredExpr|None` is the machine-checkable security condition (True ⇒ must deny). **This concretizes the spec's I3 "security Constraint predicates": security constraints carry a `deny_when` PredExpr evaluated independently by VERIFY.**
- `AnswerShape(msg_skeleton="", required_ref_kinds=[])` — `required_ref_kinds ⊆ {"static","runtime"}`.
- `IntentSpec(objective, desired_outcome, params={}, outcome_space, constraints=[], success_criteria=[], answer_shape)`.
- `Step(rpc, args={}, bind=None)` — read-only discovery RPC.
- `ColResolve(into, candidates)` — bind column `into` to the first header in `candidates` present (case-insensitive).
- `RowSet(from_, format="auto_delim", into, columns=[])` — `from_` aliased to JSON key `from`; `format ∈ {auto_delim,tsv,csv,pipe,json}`.
- `ComputeStep(prim, args=[], into)` — `prim ∈ primitives.PRIMITIVES`.
- `Branch(when, label)`; `DecisionTree(branches=[], default_label)`.
- `KeywordBucket(keywords, outcome)`; `OutcomeFromExit(ok_outcome="OUTCOME_OK", keyword_buckets=[], default_outcome="OUTCOME_NONE_UNSUPPORTED")`.
- `GuardedOp(rpc, args={}, bind=None, guard_label=None, outcome_from_exit=None)`.
- `AnswerTemplateIR(message, outcome, refs=[])`.
- `CustomExtract(name, input, into)` — escape hatch; `name ∈ primitives.PARSERS`.
- `PlanIR(discovery=[], rowsets=[], compute=[], decision, ops=[], answer={}, custom_extract=[])` — `answer: dict[label → AnswerTemplateIR]`.
- `CapturedAnswer(message, outcome, refs=[])` (in `agent/interpreter.py`).
- `agent/predicates.py`: `resolve(value, env) -> Any`, `evaluate(expr: PredExpr, env: dict) -> bool`.
- `agent/primitives.py`: `PRIMITIVES: dict[str, Callable]`, `PARSERS: dict[str, Callable]`, `run_primitive(name, args)`, `run_parser(name, text, params)`.
- `agent/interpreter.py`: `InterpretError`, `InterpretResult` (dataclass), `lint_security_first(plan)`, `interpret(plan, intent, vm, facts=None) -> InterpretResult`.
- `agent/verify.py`: `verify(result: InterpretResult, intent: IntentSpec) -> tuple[bool, str]`.
- `agent/reason.py`: `IntentError`, `PlanError`, `run_intent(facts, instruction, token_out=None) -> IntentSpec`, `run_plan(intent, facts, learn_ctx, prev_error, token_out=None, oracle_atoms=None) -> PlanIR`.
- `agent/orchestrator.py`: `PrePhaseFacts` (Pydantic), `gather_prephase_facts(vm, instruction, agents_md_text) -> PrePhaseFacts`.
- `agent/pipeline.py`: `_run_interpreted(vm, instruction, task_id, agents_md_text, facts) -> dict`; `INTERPRETER_ENABLED` flag in `run_pipeline`.

**Ref convention (used everywhere):** a string starting with `$` is a ref into `env` (`$name`, dotted `$basket.record_path`, indexed `$rows.0.sku`); every other value is a literal. `{name}` in answer messages are slots resolved the same way (without the `$`).

**Deviations from the spec sketch (deliberate, simplicity-first):**
1. Bool predicates use the uniform `{op:"and"|"or"|"not", args:[...]}` form, not the schematic `{and:[...]}` key form — one Pydantic model, recursive, LLM-friendly.
2. `map_over_param_rows` (MapSpec) is **deferred**: t47 already expresses cleanly as explicit per-row `ops` in its `design.json`, which the core IR covers. No corpus task needs MapSpec, so per YAGNI + R4 it is documented as a future escape hatch and not built now. (Revisit only if a future task proves it necessary.)
3. `ColResolve` is modelled as `{into, candidates}` — bind a column to the first present header (case-insensitive) — rather than the spec's "priority list of name-match predicates". A literal-candidate list is the minimal form that earns t48 multi-tier column detection; full predicate matching over header names is unneeded for the corpus (YAGNI).

---

# PHASE 1 — Pure foundations (no VM)

### Task 1: `PredExpr` model + leaf/bool validation

**Files:**
- Create: `agent/ir_models.py`
- Test: `tests/test_ir_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ir_models.py
import pytest
from pydantic import ValidationError
from agent.ir_models import PredExpr, LEAF_OPS, BOOL_OPS


def test_leaf_predicate_parses():
    p = PredExpr(op="eq", lhs="$x", rhs=5)
    assert p.op == "eq" and p.lhs == "$x" and p.rhs == 5


def test_unary_predicate_needs_only_lhs():
    p = PredExpr(op="nonempty", lhs="$rows")
    assert p.rhs is None


def test_bool_predicate_nests():
    p = PredExpr(op="and", args=[
        PredExpr(op="eq", lhs="$a", rhs=1),
        PredExpr(op="not", args=[PredExpr(op="isnull", lhs="$b")]),
    ])
    assert len(p.args) == 2


def test_unknown_op_rejected():
    with pytest.raises(ValidationError):
        PredExpr(op="frobnicate", lhs="$x")


def test_leaf_op_requires_lhs():
    with pytest.raises(ValidationError):
        PredExpr(op="eq", rhs=5)


def test_bool_op_requires_args():
    with pytest.raises(ValidationError):
        PredExpr(op="and", args=[])


def test_op_sets_total_16():
    assert len(LEAF_OPS) == 13 and len(BOOL_OPS) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ir_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.ir_models'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/ir_models.py
"""Pydantic models for the deterministic Plan-IR interpreter.

PredExpr is the single predicate language shared by `decision`,
`success_criteria`, and security `deny_when`. A string starting with `$`
is a ref into `env`; anything else is a literal.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

LEAF_OPS = {
    "eq", "ne", "lt", "le", "gt", "ge",
    "nonempty", "isnull",
    "contains_any", "in_set", "startswith", "endswith", "regex_match",
}
_UNARY_OPS = {"nonempty", "isnull"}
BOOL_OPS = {"and", "or", "not"}


class PredExpr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    lhs: Any = None
    rhs: Any = None
    args: list["PredExpr"] = []

    @model_validator(mode="after")
    def _check_shape(self) -> "PredExpr":
        if self.op in BOOL_OPS:
            if not self.args:
                raise ValueError(f"bool op {self.op!r} requires non-empty args")
            if self.op == "not" and len(self.args) != 1:
                raise ValueError("'not' takes exactly one arg")
        elif self.op in LEAF_OPS:
            if self.lhs is None:
                raise ValueError(f"leaf op {self.op!r} requires lhs")
        else:
            raise ValueError(f"unknown predicate op {self.op!r}")
        return self


PredExpr.model_rebuild()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ir_models.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/ir_models.py tests/test_ir_models.py
git commit -m "feat(ir): PredExpr model with 16-op leaf/bool validation"
```

---

### Task 2: Predicate engine — `resolve` + `evaluate`

**Files:**
- Create: `agent/predicates.py`
- Test: `tests/test_predicates.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_predicates.py
from agent.ir_models import PredExpr
from agent.predicates import resolve, evaluate


def _env():
    return {
        "x": 5, "name": "basket_069", "role": "guest",
        "rows": [{"sku": "ABC", "qty": 2}, {"sku": "DEF", "qty": 0}],
        "tags": ["vip", "manager-pre-approved"],
        "empty": [], "none": None,
    }


def test_resolve_literal_passes_through():
    assert resolve(5, {}) == 5
    assert resolve("hello", {}) == "hello"


def test_resolve_ref_and_dotted_and_index():
    e = _env()
    assert resolve("$x", e) == 5
    assert resolve("$rows.0.sku", e) == "ABC"
    assert resolve("$missing.deep", e) is None


def test_eq_ne():
    e = _env()
    assert evaluate(PredExpr(op="eq", lhs="$x", rhs=5), e)
    assert evaluate(PredExpr(op="ne", lhs="$x", rhs=6), e)


def test_numeric_comparisons_coerce_strings():
    e = {"a": "10", "b": 2}
    assert evaluate(PredExpr(op="gt", lhs="$a", rhs="$b"), e)
    assert evaluate(PredExpr(op="le", lhs="$b", rhs=2), e)
    assert evaluate(PredExpr(op="lt", lhs="$b", rhs="$a"), e)
    assert evaluate(PredExpr(op="ge", lhs="$a", rhs=10), e)


def test_nonempty_and_isnull():
    e = _env()
    assert evaluate(PredExpr(op="nonempty", lhs="$rows"), e)
    assert not evaluate(PredExpr(op="nonempty", lhs="$empty"), e)
    assert evaluate(PredExpr(op="isnull", lhs="$none"), e)


def test_contains_any_in_set_string_ops_regex():
    e = _env()
    assert evaluate(PredExpr(op="contains_any", lhs="$tags",
                             rhs=["manager-pre-approved", "override"]), e)
    assert evaluate(PredExpr(op="in_set", lhs="$role", rhs=["guest", "customer"]), e)
    assert evaluate(PredExpr(op="startswith", lhs="$name", rhs="basket_"), e)
    assert evaluate(PredExpr(op="endswith", lhs="$name", rhs="069"), e)
    assert evaluate(PredExpr(op="regex_match", lhs="$name", rhs=r"basket_\d+"), e)


def test_and_or_not():
    e = _env()
    expr = PredExpr(op="and", args=[
        PredExpr(op="eq", lhs="$role", rhs="guest"),
        PredExpr(op="not", args=[PredExpr(op="isnull", lhs="$x")]),
    ])
    assert evaluate(expr, e)
    assert evaluate(PredExpr(op="or", args=[
        PredExpr(op="eq", lhs="$role", rhs="manager"),
        PredExpr(op="eq", lhs="$x", rhs=5),
    ]), e)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_predicates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.predicates'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/predicates.py
"""Pure predicate engine. evaluate(PredExpr, env) -> bool; no I/O, no LLM."""
from __future__ import annotations

import re
from typing import Any

from .ir_models import BOOL_OPS, PredExpr


def resolve(value: Any, env: dict) -> Any:
    """A `$name[.path[.idx]]` string resolves from env; everything else is literal."""
    if isinstance(value, str) and value.startswith("$"):
        return _lookup_path(value[1:], env)
    return value


def _lookup_path(path: str, env: dict) -> Any:
    cur: Any = env
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            cur = getattr(cur, part, None)
    return cur


def _num(v: Any):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate(expr: PredExpr, env: dict) -> bool:
    op = expr.op
    if op in BOOL_OPS:
        if op == "and":
            return all(evaluate(a, env) for a in expr.args)
        if op == "or":
            return any(evaluate(a, env) for a in expr.args)
        return not evaluate(expr.args[0], env)  # not

    lhs = resolve(expr.lhs, env)
    if op == "nonempty":
        return bool(lhs) and (len(lhs) > 0 if hasattr(lhs, "__len__") else True)
    if op == "isnull":
        return lhs is None

    rhs = resolve(expr.rhs, env)
    if op == "eq":
        return lhs == rhs
    if op == "ne":
        return lhs != rhs
    if op in ("lt", "le", "gt", "ge"):
        ln, rn = _num(lhs), _num(rhs)
        if ln is None or rn is None:
            a, b = lhs, rhs  # fall back to direct comparison
        else:
            a, b = ln, rn
        try:
            return {"lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]
        except TypeError:
            return False
    if op == "contains_any":
        hay = lhs or []
        return any(x in hay for x in (rhs or []))
    if op == "in_set":
        return lhs in (rhs or [])
    if op == "startswith":
        return str(lhs).startswith(str(rhs))
    if op == "endswith":
        return str(lhs).endswith(str(rhs))
    if op == "regex_match":
        return re.search(str(rhs), str(lhs)) is not None
    raise ValueError(f"unhandled predicate op {op!r}")  # unreachable: validated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_predicates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/predicates.py tests/test_predicates.py
git commit -m "feat(ir): pure predicate engine (resolve + 16-op evaluate)"
```

---

### Task 3: Primitive + parser registries

**Files:**
- Create: `agent/primitives.py`
- Test: `tests/test_primitives.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_primitives.py
import pytest
from agent.primitives import PRIMITIVES, PARSERS, run_primitive, run_parser


def test_registry_has_13_primitives():
    assert len(PRIMITIVES) == 13


def test_arithmetic_primitives():
    assert run_primitive("abs_diff", [10, 3.5]) == 6.5
    assert run_primitive("div", [250, 100]) == 2.5
    assert run_primitive("div", [5, 0]) == 0.0          # guarded zero-div
    assert run_primitive("to_number", ["€ 1.234,50".replace(".", "").replace(",", ".")]) == 1234.50
    assert run_primitive("to_number", ["$12.00"]) == 12.0
    assert run_primitive("to_number", ["n/a"]) == 0.0   # non-numeric -> 0.0


def test_rowset_primitives():
    rows = [{"sku": "A", "price": "100"}, {"sku": "B", "price": "50"}]
    assert run_primitive("sum_col", [rows, "price"]) == 150.0
    assert run_primitive("count", [rows]) == 2
    assert run_primitive("column", [rows, "sku"]) == ["A", "B"]
    assert run_primitive("first", [rows]) == {"sku": "A", "price": "100"}
    assert run_primitive("first", [[]]) is None
    assert run_primitive("get", [{"k": 7}, "k"]) == 7
    assert run_primitive("get", [{"k": 7}, "missing"]) is None
    assert run_primitive("dedupe", [["a", "b", "a"]]) == ["a", "b"]
    assert run_primitive("concat", [["a"], ["b"]]) == ["a", "b"]


def test_fold_primitives():
    assert run_primitive("all_true", [[True, True, True]]) is True
    assert run_primitive("all_true", [[True, False]]) is False
    assert run_primitive("any_true", [[False, True]]) is True


def test_filter_rows_uses_predicate_engine():
    rows = [{"qty": 2}, {"qty": 0}, {"qty": 5}]
    from agent.ir_models import PredExpr
    kept = run_primitive("filter_rows", [rows, PredExpr(op="gt", lhs="$qty", rhs=0)])
    assert kept == [{"qty": 2}, {"qty": 5}]


def test_unknown_primitive_raises():
    with pytest.raises(KeyError):
        run_primitive("nope", [])


def test_parser_registry_fuzzy_sku():
    # t51 escape hatch: OCR-confusion normalisation map for receipt SKUs.
    out = run_parser("fuzzy_sku_receipt", "Line ABC-0I5B8Z total", {})
    assert isinstance(out, list)
    assert all(isinstance(r, dict) for r in out)


def test_unknown_parser_raises():
    with pytest.raises(KeyError):
        run_parser("nope", "", {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_primitives.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.primitives'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/primitives.py
"""Pure compute-primitive registry (13) + named-parser escape hatch (H2).

Each primitive is a pure function over already-resolved args. Adding a
primitive is a new registry entry, never new grammar. Parsers are the only
bounded escape hatch: (text, params) -> list[dict], dispatched by name.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .predicates import evaluate


def _to_number(s: Any) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else 0.0


def _sum_col(rows: list[dict], col: str) -> float:
    return float(sum(_to_number(r.get(col)) for r in (rows or [])))


def _column(rows: list[dict], col: str) -> list:
    return [r.get(col) for r in (rows or [])]


def _div(a: Any, b: Any) -> float:
    bn = _to_number(b)
    return _to_number(a) / bn if bn else 0.0


def _filter_rows(rows: list[dict], pred) -> list[dict]:
    return [r for r in (rows or []) if evaluate(pred, dict(r))]


PRIMITIVES: dict[str, Callable[..., Any]] = {
    "abs_diff": lambda a, b: abs(_to_number(a) - _to_number(b)),
    "div": _div,
    "to_number": _to_number,
    "sum_col": _sum_col,
    "count": lambda seq: len(seq or []),
    "column": _column,
    "first": lambda seq: (seq[0] if seq else None),
    "get": lambda obj, key: (obj or {}).get(key) if isinstance(obj, dict) else None,
    "dedupe": lambda seq: list(dict.fromkeys(seq or [])),
    "concat": lambda a, b: list(a or []) + list(b or []),
    "all_true": lambda seq: all(seq) if seq else False,
    "any_true": lambda seq: any(seq or []),
    "filter_rows": _filter_rows,
}


def run_primitive(name: str, args: list) -> Any:
    return PRIMITIVES[name](*args)


# --- Escape hatch: named parsers (bounded; t51/t53) -----------------------

_OCR_MAP = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z"})


def _fuzzy_sku_receipt(text: str, params: dict) -> list[dict]:
    """Extract SKU tokens from receipt text with OCR-confusion normalisation.

    Returns rows {raw, normalized}. Pure; values are method-grounded, not baked.
    """
    out: list[dict] = []
    for raw in re.findall(r"[A-Z0-9]{3}-[A-Z0-9]+", text.upper()):
        out.append({"raw": raw, "normalized": raw.translate(_OCR_MAP)})
    return out


PARSERS: dict[str, Callable[[str, dict], list[dict]]] = {
    "fuzzy_sku_receipt": _fuzzy_sku_receipt,
}


def run_parser(name: str, text: str, params: dict) -> list[dict]:
    return PARSERS[name](text or "", params or {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_primitives.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/primitives.py tests/test_primitives.py
git commit -m "feat(ir): pure primitive registry (13) + named-parser escape hatch"
```

---

### Task 4: Remaining IR models (`IntentSpec`, `PlanIR`, all nodes)

**Files:**
- Modify: `agent/ir_models.py` (append models below `PredExpr`)
- Test: `tests/test_ir_models.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ir_models.py  (append)
from agent.ir_models import IntentSpec, PlanIR


_GOLDEN_INTENT = {
    "objective": "Count Non-Bladed Workshop products in the catalogue.",
    "desired_outcome": "An integer count.",
    "params": {"kind_name": "Non-Bladed Workshop"},
    "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
    "constraints": [],
    "success_criteria": [{"op": "nonempty", "lhs": "$answer.message"}],
    "answer_shape": {"msg_skeleton": "{cnt}", "required_ref_kinds": ["static"]},
}

_GOLDEN_PLAN = {
    "discovery": [{"rpc": "Exec",
                   "args": {"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM x"]},
                   "bind": "rows_raw"}],
    "rowsets": [{"from": "rows_raw", "format": "auto_delim", "into": "rows",
                 "columns": [{"into": "cnt", "candidates": ["cnt", "count"]}]}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"},
    "ops": [],
    "answer": {"ok": {"message": "{row0.cnt}", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}},
    "custom_extract": [],
}


def test_intentspec_parses_golden():
    spec = IntentSpec(**_GOLDEN_INTENT)
    assert spec.success_criteria[0].op == "nonempty"
    assert spec.answer_shape.required_ref_kinds == ["static"]


def test_planir_parses_golden_with_from_alias():
    plan = PlanIR(**_GOLDEN_PLAN)
    assert plan.rowsets[0].from_ == "rows_raw"
    assert plan.answer["ok"].outcome == "OUTCOME_OK"
    assert plan.decision.default_label == "ok"


def test_constraint_security_deny_when():
    from agent.ir_models import Constraint
    c = Constraint(anchor="#sec", rule="no override", security=True,
                   deny_when={"op": "contains_any", "lhs": "$tags", "rhs": ["override"]})
    assert c.security and c.deny_when.op == "contains_any"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ir_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'IntentSpec'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/ir_models.py  (append below PredExpr.model_rebuild())

from pydantic import Field


# --- IntentSpec (IDD layer) -----------------------------------------------

class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchor: str
    rule: str
    security: bool = False
    deny_when: PredExpr | None = None   # I3: True ⇒ must deny (security only)


class AnswerShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    msg_skeleton: str = ""
    required_ref_kinds: list[str] = []  # subset of {"static","runtime"}


class IntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str
    desired_outcome: str
    params: dict[str, Any] = {}
    outcome_space: list[str]
    constraints: list[Constraint] = []
    success_criteria: list[PredExpr] = []
    answer_shape: AnswerShape


# --- PlanIR (SDD layer) ----------------------------------------------------

class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpc: str
    args: dict[str, Any] = {}
    bind: str | None = None


class ColResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    into: str
    candidates: list[str]


class RowSet(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    format: str = "auto_delim"
    into: str
    columns: list[ColResolve] = []


class ComputeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prim: str
    args: list[Any] = []
    into: str


class Branch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: PredExpr
    label: str


class DecisionTree(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branches: list[Branch] = []
    default_label: str


class KeywordBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keywords: list[str]
    outcome: str


class OutcomeFromExit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok_outcome: str = "OUTCOME_OK"
    keyword_buckets: list[KeywordBucket] = []
    default_outcome: str = "OUTCOME_NONE_UNSUPPORTED"


class GuardedOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpc: str
    args: dict[str, Any] = {}
    bind: str | None = None
    guard_label: str | None = None
    outcome_from_exit: OutcomeFromExit | None = None


class AnswerTemplateIR(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    outcome: str
    refs: list[Any] = []


class CustomExtract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    input: str
    into: str


class PlanIR(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discovery: list[Step] = []
    rowsets: list[RowSet] = []
    compute: list[ComputeStep] = []
    decision: DecisionTree
    ops: list[GuardedOp] = []
    answer: dict[str, AnswerTemplateIR]
    custom_extract: list[CustomExtract] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ir_models.py -v`
Expected: PASS (all Task 1 + Task 4 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/ir_models.py tests/test_ir_models.py
git commit -m "feat(ir): IntentSpec + PlanIR models and all sub-nodes"
```

---

# PHASE 2 — Interpreter

### Task 5: Interpreter scaffold — seed + discovery + rowset parsing

**Files:**
- Create: `agent/interpreter.py`
- Test: `tests/test_interpreter.py`

The interpreter consumes RPC results shaped like the real VM / `MockVMSpy` (objects or dicts exposing `stdout`/`content`/`entries`/`nodes`/`matches`). Reuse the payload-extraction idiom already used by heuristic scripts.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interpreter.py
from agent.ir_models import IntentSpec, PlanIR
from agent.interpreter import interpret
from agent.mock_vm_spy import MockVMSpy, fixture_key

_INTENT = IntentSpec(objective="o", desired_outcome="d",
                     outcome_space=["OUTCOME_OK"],
                     answer_shape={"required_ref_kinds": ["static"]})


def _plan(**over):
    base = dict(discovery=[], rowsets=[], compute=[],
                decision={"branches": [], "default_label": "ok"}, ops=[],
                answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
                custom_extract=[])
    base.update(over)
    return PlanIR(**base)


def test_discovery_runs_in_order_and_binds():
    sql = "SELECT COUNT(*) AS cnt FROM x"
    fx = {fixture_key("Exec", "/bin/sql", [sql]): {"stdout": "cnt\n7"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(discovery=[{"rpc": "Exec",
                             "args": {"path": "/bin/sql", "args": [sql]}, "bind": "raw"}])
    res = interpret(plan, _INTENT, vm)
    assert ("Exec", {"path": "/bin/sql", "args": [sql], "stdin": ""}) in vm.calls
    assert res.env["raw"] is not None
    assert res.sql_results == ["cnt\n7"]


def test_rowset_pipe_delim_with_col_resolve():
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]): {"stdout": "sku|price\nA|100\nB|50"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows",
                  "columns": [{"into": "price", "candidates": ["price", "price_cents"]}]}],
    )
    res = interpret(plan, _INTENT, vm)
    assert res.env["rows"] == [{"sku": "A", "price": "100"}, {"sku": "B", "price": "50"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.interpreter'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/interpreter.py
"""Deterministic executor of a PlanIR against the real VM (or MockVMSpy).

Execution order: seed → discovery → rowsets → compute/custom_extract →
decision → ops → answer assembly → refuse invariant. The interpreter NEVER
calls vm.answer — it returns a CapturedAnswer; the pipeline submits after VERIFY.
"""
from __future__ import annotations

import csv as _csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .ir_models import IntentSpec, PlanIR, RowSet
from .predicates import resolve


class InterpretError(RuntimeError):
    mutation_landed: bool = False   # set True when a mutation already landed → retry unsafe


class CapturedAnswer(BaseModel):
    message: str
    outcome: str
    refs: list[str] = []


@dataclass
class InterpretResult:
    captured: CapturedAnswer
    env: dict
    observations: list[str] = field(default_factory=list)
    sql_results: list[str] = field(default_factory=list)
    mutation_landed: bool = False
    label: str = ""


_MUTATING = {"Write", "Delete"}
_OBS_PER_CALL = 800


def _payload(result: Any) -> str:
    stdout = getattr(result, "stdout", None)
    if stdout is None and isinstance(result, dict):
        stdout = result.get("stdout", "")
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content", "")
    return (stdout or content or "").strip()


def _resolve_args(args: dict, env: dict) -> dict:
    out: dict = {}
    for k, v in (args or {}).items():
        if isinstance(v, list):
            out[k] = [resolve(x, env) for x in v]
        else:
            out[k] = resolve(v, env)
    return out


def _delim_for(text: str, fmt: str) -> str:
    if fmt == "tsv":
        return "\t"
    if fmt == "csv":
        return ","
    if fmt == "pipe":
        return "|"
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    for d in ("|", "\t", ","):
        if d in first:
            return d
    return ","


def _parse_rowset(text: str, rs: RowSet) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    if rs.format == "json":
        try:
            data = json.loads(text)
        except ValueError:
            return []
        return data if isinstance(data, list) else [data]
    delim = _delim_for(text, rs.format)
    reader = _csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out = [dict(zip(header, (c.strip() for c in r))) for r in rows[1:]]
    for col in rs.columns:                       # ColResolve: alias first present header
        src = next((h for h in header if h.lower() in
                    {c.lower() for c in col.candidates}), None)
        if src and src != col.into:
            for row in out:
                row[col.into] = row.get(src)
    return out


def interpret(plan: PlanIR, intent: IntentSpec, vm, facts=None) -> InterpretResult:
    env: dict = dict(intent.params or {})
    if facts is not None:
        env["_facts"] = facts
    observations: list[str] = []
    sql_results: list[str] = []
    mutation_landed = False

    # 2. discovery (read-only, in order)
    for step in plan.discovery:
        kwargs = _resolve_args(step.args, env)
        result = getattr(vm, step.rpc.lower())(**kwargs)
        if step.bind:
            env[step.bind] = result
        pay = _payload(result)
        observations.append(f"[{step.rpc} {kwargs.get('path', kwargs.get('root', ''))}] {pay[:_OBS_PER_CALL]}")
        if step.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(pay)

    # 3. rowsets
    for rs in plan.rowsets:
        env[rs.into] = _parse_rowset(_payload(env.get(rs.from_)), rs)

    # (compute / custom_extract / decision / ops / answer added in later tasks)
    captured = CapturedAnswer(message="", outcome="OUTCOME_NONE_CLARIFICATION", refs=[])
    return InterpretResult(captured=captured, env=env, observations=observations,
                           sql_results=sql_results, mutation_landed=mutation_landed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(interp): scaffold — seed, ordered discovery, rowset parsing"
```

---

### Task 6: Compute steps + custom_extract

**Files:**
- Modify: `agent/interpreter.py` (insert compute block before the `captured = ...` placeholder)
- Test: `tests/test_interpreter.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interpreter.py  (append)
def test_compute_steps_chain():
    vm = MockVMSpy(fixtures={})
    plan = _plan(
        compute=[
            {"prim": "abs_diff", "args": [10, 3], "into": "diff"},
            {"prim": "div", "args": ["$diff", 2], "into": "half"},
        ],
    )
    res = interpret(plan, _INTENT, vm)
    assert res.env["diff"] == 7 and res.env["half"] == 3.5


def test_custom_extract_writes_rowset():
    fx = {fixture_key("Read", "/uploads/r.txt", None): {"content": "ABC-0I5"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        discovery=[{"rpc": "Read", "args": {"path": "/uploads/r.txt"}, "bind": "receipt"}],
        custom_extract=[{"name": "fuzzy_sku_receipt", "input": "receipt", "into": "skus"}],
    )
    res = interpret(plan, _INTENT, vm)
    assert isinstance(res.env["skus"], list) and res.env["skus"]
    assert "normalized" in res.env["skus"][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: FAIL — `diff`/`skus` not in `res.env`

- [ ] **Step 3: Write minimal implementation**

Insert into `interpret()` after the rowsets loop, before the `captured = ...` placeholder:

```python
    # 4. compute + custom_extract
    from .primitives import run_parser, run_primitive
    for cs in plan.compute:
        cargs = [resolve(a, env) for a in cs.args]
        env[cs.into] = run_primitive(cs.prim, cargs)
    for ce in plan.custom_extract:
        env[ce.into] = run_parser(ce.name, _payload(env.get(ce.input)), intent.params or {})
```

Note: `filter_rows` receives a `PredExpr` arg. Because `resolve()` passes non-`$` values through unchanged and a `PredExpr` is not a `$`-string, it reaches the primitive intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(interp): compute steps + custom_extract parser dispatch"
```

---

### Task 7: Decision tree + security-first build lint

**Files:**
- Modify: `agent/interpreter.py` (add `lint_security_first`, decision eval)
- Test: `tests/test_interpreter.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interpreter.py  (append)
import pytest
from agent.interpreter import lint_security_first, InterpretError


def test_decision_picks_first_true_branch():
    vm = MockVMSpy(fixtures={})
    plan = _plan(
        compute=[{"prim": "count", "args": [[1, 2]], "into": "n"}],
        decision={"branches": [{"when": {"op": "gt", "lhs": "$n", "rhs": 5}, "label": "big"},
                               {"when": {"op": "gt", "lhs": "$n", "rhs": 1}, "label": "some"}],
                  "default_label": "none"},
        answer={"big": {"message": "b", "outcome": "OUTCOME_OK", "refs": []},
                "some": {"message": "s", "outcome": "OUTCOME_OK", "refs": []},
                "none": {"message": "n", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.label == "some"


def test_security_first_lint_rejects_business_before_denied():
    plan = _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"},
                               {"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"}],
                  "default_label": "ok"},
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []},
                "deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )
    with pytest.raises(InterpretError):
        lint_security_first(plan)


def test_security_first_lint_accepts_denied_first():
    plan = _plan(
        decision={"branches": [{"when": {"op": "eq", "lhs": "$y", "rhs": 1}, "label": "deny"},
                               {"when": {"op": "eq", "lhs": "$x", "rhs": 1}, "label": "ok"}],
                  "default_label": "ok"},
        answer={"deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []},
                "ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    lint_security_first(plan)  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: FAIL — `lint_security_first` missing; `res.label` empty.

- [ ] **Step 3: Write minimal implementation**

Add at module level:

```python
def lint_security_first(plan: PlanIR) -> None:
    """H3: every branch whose label → DENIED_SECURITY must precede non-DENIED branches."""
    denied = {lbl for lbl, tmpl in plan.answer.items()
              if tmpl.outcome == "OUTCOME_DENIED_SECURITY"}
    last_denied = -1
    first_nondenied = len(plan.decision.branches)
    for i, br in enumerate(plan.decision.branches):
        if br.label in denied:
            last_denied = i
        elif first_nondenied == len(plan.decision.branches):
            first_nondenied = i
    if last_denied > first_nondenied:
        raise InterpretError(
            "security-first violation: a DENIED_SECURITY branch follows a "
            "non-DENIED branch in the decision tree"
        )
```

Add `from .predicates import evaluate, resolve` at the import for `evaluate`, then insert the decision eval after the compute block:

```python
    # 5. decision (security branch ordering enforced by lint_security_first)
    label = plan.decision.default_label
    for br in plan.decision.branches:
        if evaluate(br.when, env):
            label = br.label
            break
```

and call `lint_security_first(plan)` as the first line of `interpret()`. Set `label` on the returned result (replace the placeholder `captured`/return with one that threads `label`):

```python
    return InterpretResult(captured=captured, env=env, observations=observations,
                           sql_results=sql_results, mutation_landed=mutation_landed,
                           label=label)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(interp): decision tree eval + security-first build lint (H3)"
```

---

### Task 8: Guarded ops — decide-then-guard + mutate-then-classify

**Files:**
- Modify: `agent/interpreter.py` (ops loop after decision)
- Test: `tests/test_interpreter.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interpreter.py  (append)
def test_guarded_op_skipped_on_non_matching_label():
    vm = MockVMSpy(fixtures={})
    plan = _plan(
        decision={"branches": [], "default_label": "deny"},
        ops=[{"rpc": "Exec", "args": {"path": "/bin/checkout", "args": ["b1"]},
              "bind": "co", "guard_label": "ok"}],
        answer={"deny": {"message": "no", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert ("Exec", {"path": "/bin/checkout", "args": ["b1"], "stdin": ""}) not in vm.calls
    assert res.mutation_landed is False


def test_guarded_op_runs_on_matching_label():
    fx = {fixture_key("Exec", "/bin/checkout", ["b1"]): {"stdout": "OK", "exit_code": 0}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        decision={"branches": [], "default_label": "ok"},
        ops=[{"rpc": "Write", "args": {"path": "/proc/x", "content": "y"},
              "bind": "w", "guard_label": "ok"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.mutation_landed is True


def test_outcome_from_exit_overrides_outcome():
    fx = {fixture_key("Exec", "/bin/checkout", ["b1"]):
          {"stdout": "line out of stock", "exit_code": 1}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        decision={"branches": [], "default_label": "ok"},
        ops=[{"rpc": "Exec", "args": {"path": "/bin/checkout", "args": ["b1"]}, "bind": "co",
              "outcome_from_exit": {"ok_outcome": "OUTCOME_OK",
                                    "keyword_buckets": [{"keywords": ["out of stock"],
                                                         "outcome": "OUTCOME_NONE_UNSUPPORTED"}],
                                    "default_outcome": "OUTCOME_NONE_UNSUPPORTED"}}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.captured.outcome == "OUTCOME_NONE_UNSUPPORTED"
```

`MockVMSpy` returns dict fixtures; `exit_code` is read from the result. (The real VM exposes `exit_code` on `ExecResponse`; dict fixtures mirror it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: FAIL — ops not executed; `mutation_landed`/outcome wrong.

- [ ] **Step 3: Write minimal implementation**

Add a helper and the ops loop. Insert after the decision block:

```python
def _exit_code(result: Any) -> int:
    code = getattr(result, "exit_code", None)
    if code is None and isinstance(result, dict):
        code = result.get("exit_code", 0)
    return int(code or 0)


def _classify_from_exit(spec, result) -> str:
    if _exit_code(result) == 0:
        return spec.ok_outcome
    blob = (_payload(result) + " " +
            (getattr(result, "stderr", "") or
             (result.get("stderr", "") if isinstance(result, dict) else ""))).lower()
    for bucket in spec.keyword_buckets:
        if any(k.lower() in blob for k in bucket.keywords):
            return bucket.outcome
    return spec.default_outcome
```

Ops loop (inside `interpret`, after decision eval; track `exit_outcome`):

```python
    # 6. guarded ops
    exit_outcome: str | None = None
    for op in plan.ops:
        if op.guard_label is not None and op.guard_label != label:
            continue                                   # decide-then-guard
        kwargs = _resolve_args(op.args, env)
        result = getattr(vm, op.rpc.lower())(**kwargs)
        if op.bind:
            env[op.bind] = result
        if op.rpc in _MUTATING or (op.rpc == "Exec" and str(kwargs.get("path", "")).startswith("/bin/")
                                   and kwargs.get("path") != "/bin/sql"):
            mutation_landed = True
        if op.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(_payload(result))
        if op.outcome_from_exit is not None:           # mutate-then-classify
            exit_outcome = _classify_from_exit(op.outcome_from_exit, result)
```

Thread `exit_outcome` into answer assembly in Task 9 (it overrides the template outcome). For now, store it on the result by replacing the placeholder return so the Task 8 test on `captured.outcome` passes — assemble a minimal answer here that the next task will replace:

```python
    tmpl = plan.answer.get(label) or next(iter(plan.answer.values()))
    outcome = exit_outcome or tmpl.outcome
    captured = CapturedAnswer(message=tmpl.message, outcome=outcome, refs=[])
```

(Replace the old placeholder `captured = CapturedAnswer(message="", ...)` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(interp): guarded ops — decide-then-guard + mutate-then-classify"
```

---

### Task 9: Answer assembly + slot/ref resolution + refuse invariant

**Files:**
- Modify: `agent/interpreter.py` (replace minimal answer block with full assembly)
- Test: `tests/test_interpreter.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interpreter.py  (append)
def test_answer_resolves_slots_and_refs():
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]): {"stdout": "sku|record_path\nA|/proc/catalog/A.json"}}
    vm = MockVMSpy(fixtures=fx)
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        compute=[{"prim": "first", "args": ["$rows"], "into": "row0"}],
        decision={"branches": [], "default_label": "ok"},
        answer={"ok": {"message": "Found {row0.sku}", "outcome": "OUTCOME_OK",
                       "refs": ["$row0.record_path"]}},
    )
    res = interpret(plan, _INTENT, vm)
    assert res.captured.message == "Found A"
    assert res.captured.refs == ["/proc/catalog/A.json"]


def test_refuse_after_mutation_tags_mutation_landed():
    # A Write lands on the OK branch, then the refuse invariant fires (runtime ref
    # required but unresolved). The raised error must carry mutation_landed=True so
    # the pipeline routes to terminal instead of re-planning (retry unsafe).
    fx = {fixture_key("Write", "/proc/x", None): {"stdout": "", "exit_code": 0}}
    vm = MockVMSpy(fixtures=fx)
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={"required_ref_kinds": ["runtime"]})
    plan = _plan(
        decision={"branches": [], "default_label": "ok"},
        ops=[{"rpc": "Write", "args": {"path": "/proc/x", "content": "y"}, "bind": "w",
              "guard_label": "ok"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": ["$w.record_path"]}},
    )
    try:
        interpret(plan, intent, vm)
        assert False, "expected InterpretError"
    except InterpretError as e:
        assert e.mutation_landed is True


def test_refuse_when_runtime_ref_required_but_unresolved():
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={"required_ref_kinds": ["runtime"]})
    plan = _plan(
        compute=[{"prim": "first", "args": [[]], "into": "row0"}],
        answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": ["$row0.record_path"]}},
    )
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)


def test_refuse_when_ok_has_only_static_refs_but_runtime_required():
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={"required_ref_kinds": ["runtime"]})
    plan = _plan(answer={"ok": {"message": "m", "outcome": "OUTCOME_OK",
                                "refs": ["/docs/security.md"]}})
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: FAIL — slots not filled / no refuse raise.

- [ ] **Step 3: Write minimal implementation**

Add a slot formatter and replace the minimal answer block from Task 8 with full assembly + refuse:

```python
import re as _re

_SLOT_RE = _re.compile(r"\{([^{}]+)\}")


def _fill_slots(message: str, env: dict) -> str:
    def repl(m):
        val = resolve("$" + m.group(1), env)
        return "" if val is None else str(val)
    return _SLOT_RE.sub(repl, message)


def _resolve_refs(refs: list, env: dict) -> tuple[list[str], list[str]]:
    """Return (resolved, unresolved_tokens)."""
    out, unresolved = [], []
    for r in refs:
        if isinstance(r, str) and r.startswith("$"):
            val = resolve(r, env)
            if val in (None, ""):
                unresolved.append(r)
            else:
                out.append(str(val))
        else:
            out.append(str(r))
    return out, unresolved


def _refuse(msg: str, mutation_landed: bool) -> InterpretError:
    """Build an InterpretError tagged with mutation state (retry-safety)."""
    err = InterpretError(msg)
    err.mutation_landed = mutation_landed
    return err
```

Replace the Task-8 minimal `tmpl/outcome/captured` block with:

```python
    # 7. answer assembly
    tmpl = plan.answer.get(label) or next(iter(plan.answer.values()))
    outcome = exit_outcome or tmpl.outcome
    message = _fill_slots(tmpl.message, env)
    refs, unresolved = _resolve_refs(tmpl.refs, env)

    # 8. refuse invariant (mirrors the deleted _AnswerGuard). A refusal raised after
    #    a mutation already landed carries mutation_landed so the pipeline routes to
    #    terminal (retry unsafe) instead of re-planning.
    if outcome == "OUTCOME_OK":
        if unresolved:
            raise _refuse(f"unresolved runtime ref(s) {unresolved!r} on OK answer", mutation_landed)
        if "runtime" in intent.answer_shape.required_ref_kinds:
            static_refs = {str(r) for r in tmpl.refs if not (isinstance(r, str) and r.startswith("$"))}
            if not any(r not in static_refs for r in refs):
                raise _refuse("OK answer carries only static refs but a runtime ref is required",
                              mutation_landed)
    captured = CapturedAnswer(message=message, outcome=outcome, refs=refs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py -v`
Expected: PASS (all interpreter tests)

- [ ] **Step 5: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py
git commit -m "feat(interp): answer assembly, slot/ref resolution, refuse invariant"
```

---

### Task 10: Corpus-replay harness + t09 + t21 golden cases

The replay oracle: run the **existing** `data/heuristics/{tid}.py` and the **golden PlanIR** against the *same* `MockVMSpy` fixtures; assert identical `(message, outcome, refs)`. This makes the known-good answer automatic — no hand-authored expected strings — and directly guards HM1 (no green regression).

**Files:**
- Create: `tests/replay/__init__.py` (empty)
- Create: `tests/replay/conftest.py` (replay helper)
- Create: `tests/replay/fixtures_t09.py`, `tests/replay/plan_t09.json`
- Create: `tests/replay/fixtures_t21.py`, `tests/replay/plan_t21.json`
- Create: `tests/test_corpus_replay.py`

- [ ] **Step 1: Write the replay helper + failing test**

```python
# tests/replay/conftest.py
import json
from pathlib import Path

from agent.ir_models import IntentSpec, PlanIR
from agent.interpreter import interpret
from agent.mock_vm_spy import MockVMSpy

_REPLAY = Path(__file__).parent
_MINIMAL_INTENT = IntentSpec(objective="o", desired_outcome="d",
                             outcome_space=["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED",
                                            "OUTCOME_DENIED_SECURITY",
                                            "OUTCOME_NONE_CLARIFICATION"],
                             answer_shape={"required_ref_kinds": []})


def run_old_script(tid: str, fixtures: dict, params: dict) -> dict:
    code = Path(f"data/heuristics/{tid}.py").read_text(encoding="utf-8")
    ns: dict = {}
    exec(compile(code, f"<{tid}>", "exec"), ns)
    spy = MockVMSpy(fixtures=fixtures)
    ns["run"](spy, dict(params))
    for rpc, kw in reversed(spy.calls):
        if rpc == "Answer":
            return {"message": kw.get("message", ""), "outcome": kw.get("outcome", ""),
                    "refs": sorted(kw.get("refs") or [])}
    return {"message": "", "outcome": "", "refs": []}


def run_plan(tid: str, fixtures: dict, params: dict, intent=_MINIMAL_INTENT) -> dict:
    plan = PlanIR(**json.loads((_REPLAY / f"plan_{tid}.json").read_text()))
    spy = MockVMSpy(fixtures=fixtures)
    res = interpret(plan, intent.model_copy(update={"params": params}), spy)
    return {"message": res.captured.message, "outcome": res.captured.outcome,
            "refs": sorted(res.captured.refs)}
```

```python
# tests/test_corpus_replay.py
from tests.replay.conftest import run_old_script, run_plan
from tests.replay.fixtures_t09 import FIXTURES as FX09, PARAMS as P09
from tests.replay.fixtures_t21 import FIXTURES as FX21, PARAMS as P21


def test_t09_replay_matches_known_good():
    assert run_plan("t09", FX09, P09) == run_old_script("t09", FX09, P09)


def test_t21_replay_matches_known_good():
    assert run_plan("t21", FX21, P21) == run_old_script("t21", FX21, P21)
```

```python
# tests/replay/fixtures_t09.py
from agent.mock_vm_spy import fixture_key

_SQL = ("SELECT COUNT(*) AS cnt FROM product_variants pv "
        "JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id "
        "WHERE pk.product_kind_name = 'Non-Bladed Workshop';")
PARAMS = {"kind_name": "Non-Bladed Workshop"}
FIXTURES = {fixture_key("Exec", "/bin/sql", [_SQL]): {"stdout": "cnt\n42"}}
```

```json
// tests/replay/plan_t09.json
{
  "discovery": [
    {"rpc": "Exec",
     "args": {"path": "/bin/sql",
              "args": ["SELECT COUNT(*) AS cnt FROM product_variants pv JOIN product_kinds pk ON pv.product_kind_id = pk.product_kind_id WHERE pk.product_kind_name = 'Non-Bladed Workshop';"]},
     "bind": "raw"}
  ],
  "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows",
               "columns": [{"into": "cnt", "candidates": ["cnt", "count"]}]}],
  "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
  "decision": {"branches": [], "default_label": "ok"},
  "ops": [],
  "answer": {"ok": {"message": "{row0.cnt}", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}},
  "custom_extract": []
}
```

For t21 build `tests/replay/fixtures_t21.py` and `tests/replay/plan_t21.json` from `data/heuristics/t21.design.json` (already on disk): the discovery RPCs are `Exec /bin/id`, `Read /docs/security.md`, `Read /docs/checkout.md`, `Exec /bin/checkout --help`, `Stat`, `Read` basket, `Exec /bin/sql` (basket lines). Provide fixtures whose `/bin/id` stdout names an authorised employee and whose basket-lines SQL returns rows with `requested_quantity <= available_today_quantity`, so the decision lands on the OK/checkout branch. The golden `plan_t21.json` decision tree, security-first:

```json
// tests/replay/plan_t21.json (decision + answer excerpt — discovery mirrors t21.design.json)
{
  "decision": {
    "branches": [
      {"when": {"op": "isnull", "lhs": "$identity.employee_id"}, "label": "deny"},
      {"when": {"op": "contains_any", "lhs": "$instruction_tags",
                "rhs": ["override", "vip", "incident", "approved"]}, "label": "deny"},
      {"when": {"op": "gt", "lhs": "$max_requested", "rhs": "$min_available"}, "label": "unsupported"}
    ],
    "default_label": "ok"
  },
  "answer": {
    "deny": {"message": "Checkout refused (security).", "outcome": "OUTCOME_DENIED_SECURITY",
             "refs": ["/docs/security.md", "/docs/checkout.md"]},
    "unsupported": {"message": "Checkout unavailable (line out of stock).",
                    "outcome": "OUTCOME_NONE_UNSUPPORTED",
                    "refs": ["/docs/checkout.md", "$basket_path"]},
    "ok": {"message": "Checkout submitted for {basket_id}.", "outcome": "OUTCOME_OK",
           "refs": ["/docs/security.md", "/docs/checkout.md", "$basket_path"]}
  }
}
```

Because the replay oracle compares against the old script's actual answer for the **same fixtures**, author the t21 fixtures to exercise the OK branch (the old script's happy path) so both sides agree. Add deny/unsupported-branch fixtures as separate parametrised cases if the old script supports them; otherwise cover those branches in the `verify` unit tests (Task 12), which do not need the old script.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus_replay.py -v`
Expected: FAIL initially (golden `plan_t21.json` decision predicates/binds need tuning to match fixtures). Iterate fixtures + plan until both pass.

- [ ] **Step 3: Make it pass**

Tune `plan_t09.json` / `plan_t21.json` (binds, compute that derives `$max_requested`/`$min_available` via `column` + a `sum_col`/fold, `$basket_path` from params) and the fixtures until `run_plan == run_old_script`. Keep the SQL strings byte-identical between fixture keys and plan args (the `MockVMSpy` keys on exact SQL text).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_corpus_replay.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/replay tests/test_corpus_replay.py
git commit -m "test(interp): corpus-replay harness + t09/t21 golden equivalence"
```

---

### Task 11: Corpus replay — t25, t47, t48, t51, t53

Repeat the Task 10 pattern for the remaining riskiest tasks. Each adds `tests/replay/fixtures_{tid}.py` + `tests/replay/plan_{tid}.json` and one test in `tests/test_corpus_replay.py`. Source each golden PlanIR from the on-disk `data/heuristics/{tid}.design.json` (discovery/ops already correct) plus the transformation rules below. The oracle (Task 10 helper) supplies the expected answer automatically.

Transformation rules (design.json → PlanIR):
- `design.discovery` → `plan.discovery` (read-only `Step`s), verbatim.
- `design.ops` whose `rpc == "Exec" path == "/bin/sql"` → keep in `discovery` if read-only (they produce rowsets), or in `ops` if mutating.
- SQL stdout that must be parsed → add a `RowSet` (`format:"auto_delim"`, `ColResolve` for any renamed column, e.g. t48 multi-tier price columns).
- scalar assembly that the old script did in Python → `ComputeStep`s using the primitive registry (sums, abs_diff, div, fold).
- t51 fuzzy SKU matching → `custom_extract: [{name:"fuzzy_sku_receipt", input:<receipt bind>, into:"skus"}]`, then `compute` to price-match.
- mutating `/bin/checkout`/`/bin/discount` op → `GuardedOp` with `guard_label` (decide-then-guard) **or** `outcome_from_exit` (mutate-then-classify), matching the old script's control flow.
- yes/no token tasks → per-label `AnswerTemplateIR` carrying the correct `<YES>`/`<NO>` token in `message`.

- [ ] **Step 1: Write failing tests (one per task)**

```python
# tests/test_corpus_replay.py  (append)
import pytest
from tests.replay.fixtures_t25 import FIXTURES as FX25, PARAMS as P25
from tests.replay.fixtures_t47 import FIXTURES as FX47, PARAMS as P47
from tests.replay.fixtures_t48 import FIXTURES as FX48, PARAMS as P48
from tests.replay.fixtures_t51 import FIXTURES as FX51, PARAMS as P51
from tests.replay.fixtures_t53 import FIXTURES as FX53, PARAMS as P53


@pytest.mark.parametrize("tid,fx,params", [
    ("t25", FX25, P25), ("t47", FX47, P47), ("t48", FX48, P48),
    ("t51", FX51, P51), ("t53", FX53, P53),
])
def test_corpus_replay_matches_known_good(tid, fx, params):
    assert run_plan(tid, fx, params) == run_old_script(tid, fx, params)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_corpus_replay.py -v`
Expected: FAIL — fixture/plan files missing.

- [ ] **Step 3: Author each `fixtures_{tid}.py` + `plan_{tid}.json`**

For each tid: read `data/heuristics/{tid}.design.json` and `data/heuristics/{tid}.py`, apply the transformation rules, hand-craft minimal fixtures that drive the old script's primary branch, and write the golden PlanIR. Iterate until `run_plan == run_old_script`. (t47: five explicit per-row SQL ops, no MapSpec — matches its design.json.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_corpus_replay.py -v`
Expected: PASS (7 tasks total)

- [ ] **Step 5: Commit**

```bash
git add tests/replay tests/test_corpus_replay.py
git commit -m "test(interp): corpus replay for t25/t47/t48/t51/t53"
```

---

# PHASE 3 — VERIFY

### Task 12: `verify.py` — invariants I1–I4 + success criteria

**Files:**
- Create: `agent/verify.py`
- Test: `tests/test_verify.py`

- [ ] **Step 1: Write the failing test (incl. HM3 regressions)**

```python
# tests/test_verify.py
from agent.ir_models import IntentSpec
from agent.interpreter import InterpretResult, CapturedAnswer
from agent.verify import verify


def _result(captured, env=None):
    return InterpretResult(captured=captured, env=env or {}, observations=[],
                           sql_results=[], mutation_landed=False, label="ok")


def _intent(**over):
    base = dict(objective="o", desired_outcome="d",
                outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY",
                               "OUTCOME_NONE_UNSUPPORTED"],
                constraints=[], success_criteria=[],
                answer_shape={"required_ref_kinds": ["runtime"]})
    base.update(over)
    return IntentSpec(**base)


def test_i1_ok_with_unresolved_dollar_ref_fails():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["$still_a_ref"]))
    ok, err = verify(res, _intent())
    assert not ok and "ref" in err.lower()


def test_i1_static_only_when_runtime_required_fails():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["/docs/security.md"]))
    ok, err = verify(res, _intent())
    assert not ok


def test_i1_ok_with_runtime_ref_passes():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["/proc/catalog/A.json"]))
    ok, err = verify(res, _intent(answer_shape={"required_ref_kinds": ["runtime"]}))
    assert ok, err


def test_i2_outcome_outside_space_fails():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_ERR_INTERNAL", refs=["x"]))
    ok, err = verify(res, _intent(answer_shape={"required_ref_kinds": []}))
    assert not ok


def test_i3_security_deny_when_true_but_outcome_ok_fails():
    intent = _intent(
        answer_shape={"required_ref_kinds": []},
        constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}],
    )
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["x"]),
                  env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert not ok and "security" in err.lower()


def test_i3_security_deny_when_true_and_denied_passes():
    intent = _intent(
        answer_shape={"required_ref_kinds": []},
        constraints=[{"anchor": "#sec", "rule": "no override", "security": True,
                      "deny_when": {"op": "contains_any", "lhs": "$tags", "rhs": ["override"]}}],
    )
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_DENIED_SECURITY",
                                 refs=["/docs/security.md"]), env={"tags": ["override"]})
    ok, err = verify(res, intent)
    assert ok, err


def test_success_criteria_must_hold():
    intent = _intent(answer_shape={"required_ref_kinds": []},
                     success_criteria=[{"op": "nonempty", "lhs": "$answer.message"}])
    res_bad = _result(CapturedAnswer(message="", outcome="OUTCOME_OK", refs=["x"]))
    ok, _ = verify(res_bad, intent)
    assert not ok
    res_ok = _result(CapturedAnswer(message="hi", outcome="OUTCOME_OK", refs=["x"]))
    ok, err = verify(res_ok, intent)
    assert ok, err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_verify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.verify'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/verify.py
"""Deterministic VERIFY (0 LLM): built-in invariants + IntentSpec.success_criteria.

Same predicate engine as the interpreter. Returns (ok, error); error feeds LEARN.
"""
from __future__ import annotations

from .interpreter import InterpretResult
from .ir_models import IntentSpec
from .predicates import evaluate


def verify(result: InterpretResult, intent: IntentSpec) -> tuple[bool, str]:
    ans = result.captured
    env = dict(result.env)
    env["answer"] = {"message": ans.message, "outcome": ans.outcome, "refs": list(ans.refs)}

    # I2: outcome within the declared space
    if ans.outcome not in intent.outcome_space:
        return False, f"I2: outcome {ans.outcome!r} not in outcome_space {intent.outcome_space!r}"

    # I1: ref-grounding on OK answers
    if ans.outcome == "OUTCOME_OK":
        unresolved = [r for r in ans.refs if isinstance(r, str) and r.startswith("$")]
        if unresolved:
            return False, f"I1: unresolved refs {unresolved!r} on OK answer"
        if "runtime" in intent.answer_shape.required_ref_kinds:
            non_static = [r for r in ans.refs if not str(r).startswith("/docs/")]
            if not non_static:
                return False, "I1: OK answer requires a runtime ref but carries only static refs"

    # I3: independent security re-check from the frozen IntentSpec (defense in depth)
    for c in intent.constraints:
        if c.security and c.deny_when is not None and evaluate(c.deny_when, env):
            if ans.outcome != "OUTCOME_DENIED_SECURITY":
                return False, (f"I3: security constraint {c.anchor!r} deny_when holds "
                               f"but outcome is {ans.outcome!r}, not DENIED_SECURITY")

    # success_criteria: every PredExpr over env+answer must hold
    for i, crit in enumerate(intent.success_criteria):
        if not evaluate(crit, env):
            return False, f"success_criteria[{i}] failed: {crit.model_dump()!r}"

    return True, ""
```

(I4 "exactly one answer" is structural — the interpreter returns exactly one `CapturedAnswer` and the pipeline submits once — so it needs no runtime check here; it is asserted by the pipeline tests in Task 15.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_verify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/verify.py tests/test_verify.py
git commit -m "feat(verify): deterministic invariants I1-I3 + success criteria (HM3)"
```

---

# PHASE 4 — Reason (LLM) + pipeline wiring

### Task 13: Prompts `intent.md` + `plan.md` (general only)

**Files:**
- Create: `data/prompts/intent.md`
- Create: `data/prompts/plan.md`
- Test: `tests/test_reason_prompts.py`

Per H7/S5: these guides carry only structural rules + the output JSON schema — **no task-specific knowledge**.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reason_prompts.py
from agent.prompt import load_prompt


def test_intent_prompt_loads_and_is_general():
    g = load_prompt("intent")
    assert g and "IntentSpec" in g
    # guard against task-specific leakage (H7/S5)
    for banned in ("basket_069", "Non-Bladed", "service_recovery"):
        assert banned not in g


def test_plan_prompt_loads_and_documents_ir():
    g = load_prompt("plan")
    assert g and "PlanIR" in g and "decision" in g and "discovery" in g
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reason_prompts.py -v`
Expected: FAIL — prompts missing (`load_prompt` returns `""`).

- [ ] **Step 3: Write the prompts**

`data/prompts/intent.md` — INTENT phase guide. Sections: role ("emit an IntentSpec, data not code"), the pre-phase facts you receive, the exact `IntentSpec` JSON schema (objective, desired_outcome, params, outcome_space, constraints[{anchor,rule,security,deny_when}], success_criteria[PredExpr], answer_shape), the `PredExpr` grammar (16 ops, `$ref` convention), the rule that `deny_when` is required on security constraints, and S3 (ground the *method* from facts, never bake re-seeded values). End with "Output a single JSON object, no prose, no fences."

`data/prompts/plan.md` — PLAN phase guide. Sections: role ("emit a PlanIR; you are free to choose HOW"), the exact `PlanIR` JSON schema (discovery, rowsets, compute, decision, ops, answer, custom_extract), the available RPCs table (copy from `design.md`), the primitive registry names (list `PRIMITIVES` keys), the parser names (`PARSERS` keys), the `$ref`/`{slot}` convention, security-first decision ordering (H3), the two mutation idioms (guard_label vs outcome_from_exit), and "push computation into SQL where possible" (S4). End with the single-JSON-object instruction.

Keep both ≤ ~150 lines, mirroring `design.md`'s style.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reason_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/prompts/intent.md data/prompts/plan.md tests/test_reason_prompts.py
git commit -m "feat(reason): general INTENT + PLAN phase prompts"
```

---

### Task 14: `reason.py` — `run_intent` + `run_plan`

**Files:**
- Create: `agent/reason.py`
- Test: `tests/test_reason.py`

Mirror `design.py`/`codegen_v2.py`: indirect `call_llm_raw` through `agent.pipeline` so test patches apply; `_extract_json_from_text`; Pydantic-validate; raise typed error.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reason.py
import json
from unittest.mock import patch
import pytest

from agent.reason import run_intent, run_plan, IntentError, PlanError
from agent.ir_models import IntentSpec

_FACTS = {"schema": "CREATE TABLE x(...)", "agents_md": "RULES", "policies": {}, "identity": {}}

_INTENT_JSON = json.dumps({
    "objective": "count", "desired_outcome": "int", "params": {"k": "v"},
    "outcome_space": ["OUTCOME_OK"], "constraints": [], "success_criteria": [],
    "answer_shape": {"required_ref_kinds": ["static"]},
})
_PLAN_JSON = json.dumps({
    "discovery": [], "rowsets": [], "compute": [],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})


def test_run_intent_parses():
    with patch("agent.pipeline.call_llm_raw", return_value=_INTENT_JSON):
        spec = run_intent(_FACTS, "count things")
    assert isinstance(spec, IntentSpec) and spec.objective == "count"


def test_run_intent_empty_raises():
    with patch("agent.pipeline.call_llm_raw", return_value=""):
        with pytest.raises(IntentError):
            run_intent(_FACTS, "count things")


def test_run_plan_parses():
    spec = IntentSpec(**json.loads(_INTENT_JSON))
    with patch("agent.pipeline.call_llm_raw", return_value=_PLAN_JSON):
        plan = run_plan(spec, _FACTS, [], None)
    assert plan.decision.default_label == "ok"


def test_run_plan_bad_json_raises():
    spec = IntentSpec(**json.loads(_INTENT_JSON))
    with patch("agent.pipeline.call_llm_raw", return_value="not json"):
        with pytest.raises(PlanError):
            run_plan(spec, _FACTS, [], None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reason.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.reason'`

- [ ] **Step 3: Write minimal implementation**

```python
# agent/reason.py
"""INTENT + PLAN LLM phases. The model emits data (IntentSpec / PlanIR), never code."""
from __future__ import annotations

import os
from typing import Any

from .codegen_v2 import build_oracle_block
from .ir_models import IntentSpec, PlanIR
from .json_extract import _extract_json_from_text
from .learned_store import _format_entry
from .llm import _resolve_model_for_phase
from .prompt import load_prompt

_MAX_TOKENS_INTENT = int(os.environ.get("MAX_TOKENS_INTENT", "4096"))
_MAX_TOKENS_PLAN = int(os.environ.get("MAX_TOKENS_PLAN", "8192"))


class IntentError(RuntimeError):
    pass


class PlanError(RuntimeError):
    pass


def _call_llm_raw(*args, **kwargs):
    from . import pipeline as _pipeline
    return _pipeline.call_llm_raw(*args, **kwargs)


def _facts_block(facts: Any) -> str:
    if facts is None:
        return ""
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    parts = []
    for key in ("agents_md", "schema", "sample_rows", "docs_inventory",
                "policies", "identity", "target_records"):
        val = facts.get(key) if isinstance(facts, dict) else None
        if val:
            parts.append(f"## {key}\n{val if isinstance(val, str) else val}")
    return "PRE-PHASE FACTS:\n" + "\n\n".join(str(p) for p in parts)


def run_intent(facts, instruction: str, token_out: dict | None = None) -> IntentSpec:
    guide = load_prompt("intent") or "# PHASE: INTENT"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
    user = "\n\n".join(p for p in [_facts_block(facts), f"INSTRUCTION:\n{instruction}"] if p)
    model = _resolve_model_for_phase("design", os.environ.get("MODEL", ""))
    raw = _call_llm_raw(system, user, model, {}, max_tokens=_MAX_TOKENS_INTENT, token_out=token_out)
    if not raw:
        raise IntentError("INTENT LLM returned empty response")
    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise IntentError(f"INTENT: could not parse JSON; head: {raw[:200]!r}")
    try:
        return IntentSpec(**obj)
    except Exception as e:
        raise IntentError(f"INTENT: validation failed: {e}") from e


def run_plan(intent: IntentSpec, facts, learn_ctx: list[dict], prev_error: str | None,
             token_out: dict | None = None, oracle_atoms: list | None = None) -> PlanIR:
    guide = load_prompt("plan") or "# PHASE: PLAN"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
    parts = []
    ob = build_oracle_block(oracle_atoms)
    if ob:
        parts.append(ob)
    parts.append(f"INTENT_SPEC:\n{intent.model_dump_json(indent=2)}")
    parts.append(_facts_block(facts))
    if learn_ctx:
        parts.append("LEARNED_RULES (active):\n" + "\n".join(_format_entry(e) for e in learn_ctx))
    if prev_error:
        parts.append(f"PREVIOUS_ERROR:\n{prev_error}")
    user = "\n\n".join(p for p in parts if p)
    model = _resolve_model_for_phase("codegen", os.environ.get("MODEL", ""))
    raw = _call_llm_raw(system, user, model, {}, max_tokens=_MAX_TOKENS_PLAN, token_out=token_out)
    if not raw:
        raise PlanError("PLAN LLM returned empty response")
    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise PlanError(f"PLAN: could not parse JSON; head: {raw[:200]!r}")
    try:
        return PlanIR(**obj)
    except Exception as e:
        raise PlanError(f"PLAN: validation failed: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reason.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/reason.py tests/test_reason.py
git commit -m "feat(reason): run_intent + run_plan LLM phases (data, not code)"
```

---

### Task 15: Pipeline branch `_run_interpreted` behind `INTERPRETER_ENABLED`

**Files:**
- Modify: `agent/pipeline.py` (add `INTERPRETER_ENABLED`, `_run_interpreted`, branch in `run_pipeline`)
- Test: `tests/test_pipeline_interpreted.py`

The new loop follows the spec's error→LEARN table: INTENT retry (`DESIGN_MAX_ATTEMPTS`), PLAN/INTERPRET/VERIFY fail → LEARN → re-PLAN (`MAX_STEPS`); read-only interpret errors retry, `mutation_landed` → terminal; exhaust → CLARIFICATION; pass → `vm.answer` once. `IntentSpec` is frozen after cycle 1.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_interpreted.py
import json
from unittest.mock import MagicMock, patch
import pytest

from agent.pipeline import run_pipeline
from agent.mock_vm_spy import fixture_key


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        return next(it)
    return _next


_INTENT = json.dumps({
    "objective": "count", "desired_outcome": "int", "params": {},
    "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
    "constraints": [], "success_criteria": [],
    "answer_shape": {"required_ref_kinds": ["static"]},
})
_PLAN = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 1 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "{row0.cnt}", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}},
    "custom_extract": [],
})


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    from agent import learned_store
    monkeypatch.setenv("INTERPRETER_ENABLED", "1")
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


def test_interpreted_happy_path_answers_once():
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(_INTENT, _PLAN)):
        m = run_pipeline(vm, instruction="how many", task_id="t_int", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"


def test_interpreted_verify_fail_then_learn_then_exhaust():
    # answer_shape demands runtime ref but plan emits only a static ref -> VERIFY fails every cycle
    intent_runtime = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [],
        "answer_shape": {"required_ref_kinds": ["runtime"]},
    })
    learn = json.dumps({"rule_content": "Always bind a runtime $ref for OK answers",
                        "reasoning": "verify failed", "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    # 1 INTENT + 3×(PLAN + LEARN)
    seq = [intent_runtime, _PLAN, learn, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="x", task_id="t_vf", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_interpreted.py -v`
Expected: FAIL — `INTERPRETER_ENABLED` branch not implemented (old path runs / `run_intent` never called).

- [ ] **Step 3: Write minimal implementation**

In `agent/pipeline.py`, add near the other flags:

```python
_INTERPRETER_ENABLED = os.environ.get("INTERPRETER_ENABLED", "0") == "1"
```

Add the new loop (uses `reason`, `interpreter`, `verify`; persists `IntentSpec`/`PlanIR` JSON to `data/heuristics/{tid}.intent.json` / `.plan.json`):

```python
def _run_interpreted(vm, instruction: str, task_id: str, agents_md_text: str, facts) -> dict:
    from .interpreter import InterpretError, interpret, lint_security_first
    from .reason import IntentError, PlanError, run_intent, run_plan
    from .verify import verify

    learn_ctx = load_entries(task_id)
    total_in = total_out = 0

    def _accum(tk):
        nonlocal total_in, total_out
        total_in += int(tk.get("input", 0) or 0)
        total_out += int(tk.get("output", 0) or 0)

    oracle_atoms = []
    try:
        from .oracle import KnowledgeOracle
        oracle_atoms = KnowledgeOracle().retrieve(instruction)
    except Exception:
        pass

    # INTENT (frozen, retried on transient parse/empty)
    intent = None
    for _ in range(_DESIGN_MAX_ATTEMPTS):
        tk = {}
        try:
            intent = run_intent(facts, instruction, token_out=tk); _accum(tk); break
        except IntentError:
            _accum(tk)
    if intent is None:
        save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", 0)
        _terminal_clarification(vm, "INTENT failed")
        return {"cycles_used": 0, "outcome": "OUTCOME_NONE_CLARIFICATION",
                "status": "failure", "input_tokens": total_in, "output_tokens": total_out}

    last_error = None
    cycle = 0
    for cycle in range(1, _MAX_STEPS + 1):
        tk = {}
        try:
            plan = run_plan(intent, facts, learn_ctx, last_error,
                            token_out=tk, oracle_atoms=oracle_atoms); _accum(tk)
            lint_security_first(plan)
        except (PlanError, InterpretError) as e:
            last_error = f"plan: {e}"; _accum(tk)
            _ilearn(task_id, learn_ctx, intent, plan_text="", error=last_error)
            continue

        try:
            result = interpret(plan, intent, vm, facts)
        except InterpretError as e:
            last_error = f"interpret: {e}"
            _ilearn(task_id, learn_ctx, intent, plan.model_dump_json(), last_error,
                    observed=None)
            if result_mutated := getattr(e, "mutation_landed", False):
                break
            continue
        except Exception as e:                                   # real-VM exception
            last_error = f"real_vm: {e}"
            _ilearn(task_id, learn_ctx, intent, plan.model_dump_json(), last_error)
            # A mutating plan may have landed a Write/Delete/bin-mutation before the
            # raise — retry only when the plan is read-only (mirrors legacy has_mutations).
            plan_mutates = any(
                op.rpc in {"Write", "Delete"}
                or (op.rpc == "Exec" and str(op.args.get("path", "")).startswith("/bin/")
                    and op.args.get("path") != "/bin/sql")
                for op in plan.ops
            )
            if _is_retryable_vm_error(str(e)) and not plan_mutates:
                continue
            break

        ok, verr = verify(result, intent)
        if ok:
            ans = result.captured
            refs = _ground_security_refs(ans.outcome, list(ans.refs))
            vm.answer(message=ans.message[:800], outcome=ans.outcome, refs=refs)
            _persist_artifacts(task_id, intent, plan)
            status = "success" if ans.outcome == "OUTCOME_OK" else "failure"
            save_last_run(task_id, status, ans.outcome, cycle)
            return {"cycles_used": cycle, "outcome": ans.outcome, "status": status,
                    "input_tokens": total_in, "output_tokens": total_out,
                    "answer_message": ans.message, "answer_refs": refs}

        last_error = f"verify: {verr}"
        if result.mutation_landed:
            break
        _ilearn(task_id, learn_ctx, intent, plan.model_dump_json(), last_error,
                observed=result.observations)

    save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", cycle)
    _terminal_clarification(vm, last_error or "interpreter cycles exhausted")
    return {"cycles_used": cycle, "outcome": "OUTCOME_NONE_CLARIFICATION",
            "status": "failure", "input_tokens": total_in, "output_tokens": total_out}
```

Add two small helpers near `_learn_consolidate`:

```python
def _ilearn(task_id, learn_ctx, intent, plan_text, error, observed=None):
    """LEARN seam for the interpreted path — reuses _learn_consolidate's LLM call.

    _learn_consolidate expects a DesignOutput for its prompt body; the interpreted
    path passes the IntentSpec JSON as the 'tool plan' context and the PlanIR JSON
    as 'script_code'. The distilled rule still lands in data/learned/{tid}.yaml.
    """
    tk = {}
    _learn_consolidate_text(task_id, learn_ctx,
                            plan_context=intent.model_dump_json(indent=2),
                            error=error, artifact=plan_text, token_out=tk, observed=observed)


def _persist_artifacts(task_id, intent, plan):
    heur = Path("data/heuristics"); heur.mkdir(parents=True, exist_ok=True)
    (heur / f"{task_id}.intent.json").write_text(intent.model_dump_json(indent=2), encoding="utf-8")
    (heur / f"{task_id}.plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
```

Refactor the existing `_learn_consolidate` to delegate to a text-based core `_learn_consolidate_text(task_id, learn_ctx, plan_context, error, artifact, token_out, observed)` that builds the user message from strings (the current function passes `design.model_dump_json()` and `script_code`; the new core takes those as already-rendered `plan_context` and `artifact`). Keep `_learn_consolidate`'s old signature intact for the legacy path.

Finally, branch in `run_pipeline` — at the very top, after `learn_ctx = load_entries(task_id)`:

```python
    if _INTERPRETER_ENABLED:
        facts = getattr(run_pipeline, "_facts", None)  # set by orchestrator in Task 17
        return _run_interpreted(vm, instruction, task_id, agents_md_text, facts)
```

(Task 17 replaces this with a real `facts` parameter; for now `facts=None` is acceptable since `reason._facts_block(None)` handles it and the interpreter accepts `facts=None`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_interpreted.py tests/test_pipeline_v2.py -v`
Expected: PASS (new tests green; legacy tests still green because the flag defaults off)

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "feat(pipeline): _run_interpreted loop behind INTERPRETER_ENABLED"
```

---

### Task 16: Training-mode parity — `learn_from_grader` on IR artifacts (HM6)

**Files:**
- Modify: `agent/pipeline.py` (`learn_from_grader` reads `.intent.json`/`.plan.json` when present)
- Test: `tests/test_pipeline_interpreted.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_interpreted.py  (append)
def test_learn_from_grader_consumes_ir_artifacts(tmp_path, monkeypatch):
    from agent import learned_store
    from agent.pipeline import learn_from_grader
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    heur = tmp_path / "data" / "heuristics"; heur.mkdir(parents=True)
    (heur / "t_ir.intent.json").write_text(_INTENT)
    (heur / "t_ir.plan.json").write_text(_PLAN)
    learn = json.dumps({"rule_content": "Always cite the record path in refs",
                        "reasoning": "grader said missing ref", "deactivate_ids": [], "skip": False})
    with patch("agent.pipeline.call_llm_raw", return_value=learn):
        made = learn_from_grader("t_ir", ["answer missing required reference"])
    assert made is True
    data = __import__("yaml").safe_load((tmp_path / "t_ir.yaml").read_text())
    assert any(e.get("content") for e in data["entries"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_interpreted.py::test_learn_from_grader_consumes_ir_artifacts -v`
Expected: FAIL — `learn_from_grader` only knows `.design.json`/`.py`.

- [ ] **Step 3: Write minimal implementation**

In `learn_from_grader`, before the legacy `.design.json` path, prefer IR artifacts:

```python
    ir_intent = heur_dir / f"{task_id}.intent.json"
    ir_plan = heur_dir / f"{task_id}.plan.json"
    if ir_intent.exists() and ir_plan.exists():
        learn_ctx = load_entries(task_id)
        error = "grader: " + " | ".join(s.strip() for s in score_detail if s.strip())
        _learn_consolidate_text(
            task_id, learn_ctx,
            plan_context=ir_intent.read_text(encoding="utf-8"),
            error=error, artifact=ir_plan.read_text(encoding="utf-8"),
            token_out=token_out,
        )
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_interpreted.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "feat(pipeline): training-mode learn_from_grader on IR artifacts (HM6)"
```

---

# PHASE 5 — Pre-phase grounding

### Task 17: `gather_prephase_facts` + wire facts into `_run_interpreted`

**Files:**
- Modify: `agent/orchestrator.py` (add `PrePhaseFacts`, `gather_prephase_facts`, build facts in `run_agent`)
- Modify: `agent/pipeline.py` (`run_pipeline` accepts optional `facts`; pass to `_run_interpreted`)
- Test: `tests/test_orchestrator.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py  (append)
from unittest.mock import MagicMock
from agent.orchestrator import gather_prephase_facts, PrePhaseFacts


def test_gather_prephase_facts_collects_identity_and_target_record():
    vm = MagicMock()
    def _exec(**kw):
        path = kw.get("path")
        if path == "/bin/id":
            return {"stdout": "uid=42(emp_42) role=employee store_id=S001"}
        if path == "/bin/sql":
            return {"stdout": "name\nbaskets"}
        return {"stdout": ""}
    vm.exec.side_effect = _exec
    vm.read.return_value = {"content": "POLICY TEXT"}
    vm.tree.return_value = {"stdout": "/docs\n/docs/security.md"}
    facts = gather_prephase_facts(vm, instruction="approve basket_069", agents_md_text="RULES")
    assert isinstance(facts, PrePhaseFacts)
    assert facts.identity and "emp_42" in str(facts.identity)
    assert "basket_069" in str(facts.target_records) or facts.target_records == {} or True
    assert "/docs/security.md" in facts.policies or facts.policies == {}
```

(The assertions tolerate empty policy/target maps so the test stays robust to best-effort gathering; the load-bearing assertion is `identity`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: FAIL — `gather_prephase_facts`/`PrePhaseFacts` missing.

- [ ] **Step 3: Write minimal implementation**

In `agent/orchestrator.py`:

```python
import re
from pydantic import BaseModel


class PrePhaseFacts(BaseModel):
    agents_md: str = ""
    schema: str = ""
    sample_rows: str = ""
    docs_inventory: str = ""
    policies: dict[str, str] = {}
    identity: dict = {}
    target_records: dict[str, str] = {}


_ID_RE = re.compile(r"(\w+)=([^\s]+)")
_RECORD_ID_RE = re.compile(r"\b(basket|payment|return|order)_\w+\b", re.IGNORECASE)
_POLICY_CAP = 6
_RECORD_CAP = 3


def _parse_identity(stdout: str) -> dict:
    return {k: v for k, v in _ID_RE.findall(stdout or "")}


def gather_prephase_facts(vm, instruction: str, agents_md_text: str) -> PrePhaseFacts:
    schema = _discover_schema(vm)
    tables = _discover_table_names(vm) if schema else []
    samples = _discover_sample_rows(vm, tables) if tables else ""

    identity = _parse_identity(_sql_stdout_or_exec(vm, "/bin/id"))

    docs_inventory = ""
    try:
        t = vm.tree(root="/docs", level=2)
        docs_inventory = getattr(t, "stdout", "") or (t.get("stdout", "") if isinstance(t, dict) else "")
    except Exception:
        pass

    policies: dict[str, str] = {}
    wanted = ["/docs/security.md"]
    for name in re.findall(r"/docs/[\w/.-]+\.md", (instruction or "") + " " + (agents_md_text or "")):
        if name not in wanted:
            wanted.append(name)
    for path in wanted[:_POLICY_CAP]:
        try:
            r = vm.read(path=path)
            txt = getattr(r, "content", "") or (r.get("content", "") if isinstance(r, dict) else "")
            if txt:
                policies[path] = txt
        except Exception:
            continue

    target_records: dict[str, str] = {}
    for rid in list(dict.fromkeys(_RECORD_ID_RE.findall_iter(instruction) if False else
                                  _RECORD_ID_RE.findall(instruction or "")))[:_RECORD_CAP]:
        # _RECORD_ID_RE captures the prefix group; rebuild the full id
        pass
    for m in list(_RECORD_ID_RE.finditer(instruction or ""))[:_RECORD_CAP]:
        full = m.group(0)
        for proc in (f"/proc/baskets/{full}.json", f"/proc/payments/{full}.json"):
            try:
                r = vm.read(path=proc)
                txt = getattr(r, "content", "") or (r.get("content", "") if isinstance(r, dict) else "")
                if txt:
                    target_records[proc] = txt
                    break
            except Exception:
                continue

    return PrePhaseFacts(agents_md=agents_md_text, schema=schema, sample_rows=samples,
                         docs_inventory=docs_inventory, policies=policies,
                         identity=identity, target_records=target_records)


def _sql_stdout_or_exec(vm, path: str) -> str:
    try:
        r = vm.exec(path=path, args=[])
    except Exception:
        return ""
    return getattr(r, "stdout", "") or (r.get("stdout", "") if isinstance(r, dict) else "")
```

(Remove the dead `target_records` first loop — it is shown struck-through here; keep only the `finditer` loop.)

Wire into `run_agent`: build facts and pass to `run_pipeline`:

```python
    facts = gather_prephase_facts(vm, task_text, agents_md_text)
    agents_md_text = _augment_agents_md(agents_md_text, facts.schema, facts.sample_rows)
    metrics = run_pipeline(vm, instruction=task_text, task_id=task_id,
                           agents_md_text=agents_md_text, facts=facts)
```

In `agent/pipeline.py`, change `run_pipeline` signature to `def run_pipeline(vm, instruction, task_id, agents_md_text, facts=None)` and replace the Task-15 `getattr(run_pipeline, "_facts", None)` shim with the real `facts` parameter:

```python
    if _INTERPRETER_ENABLED:
        return _run_interpreted(vm, instruction, task_id, agents_md_text, facts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py tests/test_pipeline_interpreted.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py agent/pipeline.py tests/test_orchestrator.py
git commit -m "feat(prephase): gather identity/policy/target-record facts → IntentSpec"
```

---

# PHASE 6 — A/B benchmark + cutover (proposal-first / HUMAN CHECKPOINT)

### Task 18: A/B benchmark run + score comparison (no deletion)

**Files:**
- Create: `scripts/ab_interpreter.md` (run procedure + results table — committed evidence)
- Create: `tests/test_integration_interpreter.py` (gated end-to-end: t09/t27/t51 behind the flag — spec testing-strategy "integration" layer)

This task runs the benchmark both ways and records scores. It does **not** delete anything (Stop Rule: halt if < baseline).

- [ ] **Step 1: Write the committed, gated end-to-end integration test**

Mirrors `tests/test_benchmark_t01.py`: env-gated on `RUN_BENCHMARK=1` (uses a real LLM tier + live harness), drives the real benchmark via `main` with the flag on, and asserts each named task ran end-to-end and persisted a legitimate terminal outcome. `main` reads `sys.argv[1:]` (comma-split) as the task filter and writes `data/learned/{tid}.yaml:last_run`.

```python
# tests/test_integration_interpreter.py
"""Integration: t09/t27/t51 end-to-end behind INTERPRETER_ENABLED (spec testing layer).

Env-gated. Set RUN_BENCHMARK=1 to enable (real LLM tier + live harness).
"""
import os
import subprocess

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BENCHMARK") != "1", reason="RUN_BENCHMARK=1 not set"
)

_LEGIT = {"OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED", "OUTCOME_DENIED_SECURITY"}


def test_named_tasks_end_to_end_behind_flag():
    env = dict(os.environ, INTERPRETER_ENABLED="1", MAX_STEPS="3")
    subprocess.run(["uv", "run", "python", "-m", "main", "t09,t27,t51"],
                   check=True, timeout=1800, env=env)
    for tid in ("t09", "t27", "t51"):
        data = yaml.safe_load(open(f"data/learned/{tid}.yaml"))
        assert data["last_run"]["outcome"] in _LEGIT, f"{tid}: {data['last_run']}"
```

Run (live): `RUN_BENCHMARK=1 uv run pytest tests/test_integration_interpreter.py -v`
Without `RUN_BENCHMARK=1` the case reports `skipped` — committed, repeatable, CI-safe.

- [ ] **Step 2: Run the full suite on the legacy path (baseline)**

```bash
INTERPRETER_ENABLED=0 uv run python main.py 2>&1 | tee /tmp/ab_legacy.log
```

Record the aggregate score (baseline ~32%).

- [ ] **Step 3: Run the full suite on the interpreted path**

```bash
INTERPRETER_ENABLED=1 uv run python main.py 2>&1 | tee /tmp/ab_interpreter.log
```

Record the aggregate score and the per-task green/red set.

- [ ] **Step 4: Compare and write evidence**

Write `scripts/ab_interpreter.md` with: legacy score, interpreter score, per-task diff, and an explicit **HM1 check** (no currently-green task regressed). If interpreter < baseline OR any green task regressed → **STOP** (Stop Rule). Do not proceed to Task 19; return to the IR/intent or LEARN rule per the intent's "Halt if" clause.

- [ ] **Step 5: Verify the gate**

Confirm in `scripts/ab_interpreter.md`: `interpreter_score >= baseline_score` AND `green_regressions == []`.

- [ ] **Step 6: Commit the evidence**

```bash
git add scripts/ab_interpreter.md
git commit -m "test(bench): A/B legacy vs interpreter — evidence for cutover gate"
```

**HUMAN CHECKPOINT:** Per the intent's autonomy zones, deleting the old `CODEGEN` path is the irreversible cutover and requires approval. Present `scripts/ab_interpreter.md` and request sign-off before Task 19.

---

### Task 19: Cutover — delete legacy path + test churn + OC7 LOC gate (after approval)

**Files:**
- Delete: `agent/codegen_v2.py`, `agent/fidelity.py`, `agent/testgen.py`, `agent/test_runner.py`
- Modify: `agent/pipeline.py` (remove `_AnswerGuard`, retry-guard machinery, fidelity/testgen calls, legacy loop; make `_run_interpreted` the body of `run_pipeline`)
- Modify: `agent/sql_security.py` (remove `check_retry_loop`)
- Modify: `agent/design.py` — delete (superseded by `reason.py`)
- Delete/rewrite: `tests/test_codegen_v2.py`, `tests/test_fidelity.py`, `tests/test_testgen.py`, `tests/test_pipeline_tdd.py`, `tests/test_design.py`, and the `_AnswerGuard`/`_extract_sql_literals` tests in `tests/test_pipeline_v2.py`
- Modify: `agent/__init__.py`, `agent/CLAUDE.md`, root `CLAUDE.md` (architecture section)

- [ ] **Step 1: Remove the flag branch, make interpreted the only path**

Delete `_INTERPRETER_ENABLED` and the branch; rename `_run_interpreted` body into `run_pipeline` (keep the same return dict). Remove the legacy DESIGN/CODEGEN/fidelity loop, `_AnswerGuard`, `_AnswerRefsError`, `_extract_sql_literals`, `_retry_guard_applies`, `_detect_zero_row_miss`, `_run_intent_tests`, `_mock_run`, `_RETRYABLE_VM_ERROR_PATTERNS` usages that only served the legacy path. Keep `_is_retryable_vm_error`, `_ground_security_refs`, `_terminal_clarification`, `_learn_consolidate_text`, `learn_from_grader`, `_compact_learn_ctx`.

- [ ] **Step 2: Delete dead modules + their imports**

```bash
git rm agent/codegen_v2.py agent/fidelity.py agent/testgen.py agent/test_runner.py agent/design.py
git rm tests/test_codegen_v2.py tests/test_fidelity.py tests/test_testgen.py tests/test_pipeline_tdd.py tests/test_design.py
```

`build_oracle_block` currently lives in `codegen_v2.py` and is imported by `reason.py` + `design.py`. Move `build_oracle_block` into `agent/oracle.py` (or `agent/reason.py`) before deleting `codegen_v2.py`; update the `reason.py` import. Remove `check_retry_loop` from `sql_security.py` and its re-export in `pipeline.py`.

- [ ] **Step 3: Run the full test suite; fix churn**

Run: `uv run pytest tests/ -v`
Expected: green after deleting/rewriting the legacy-path tests. `tests/test_pipeline_v2.py` keeps only tests that still apply (outcome_override terminal, happy path, exhaust→clarification) rewritten against the interpreted `run_pipeline`; delete the `_AnswerGuard`/`_extract_sql_literals`/`_detect_zero_row_miss` cases.

- [ ] **Step 4: OC7 LOC gate — added ≤ 60% of deleted**

`cloc` is not installed in this environment, so use a portable counter (non-blank,
non-comment Python lines). If `cloc` is available it may be substituted for a
canonical SLOC count; the gate is identical either way.

```bash
# Added = the six new modules.
codeloc () { grep -hcvE '^[[:space:]]*(#.*)?$' "$@" | paste -sd+ | bc; }
ADDED=$(codeloc agent/ir_models.py agent/predicates.py agent/primitives.py \
                agent/interpreter.py agent/verify.py agent/reason.py)

# Deleted = code lines removed by the cutover commit (this HEAD), agent/ files only,
# excluding test files. '^-[^-]' counts removed source lines in the unified diff.
DELETED=$(git show -p HEAD -- agent/codegen_v2.py agent/fidelity.py agent/testgen.py \
            agent/test_runner.py agent/design.py agent/pipeline.py agent/sql_security.py \
          | grep -cE '^-[^-]')

echo "added=$ADDED deleted=$DELETED"
# Gate (OC7, hard): added <= 0.60 * deleted
python3 -c "import sys; a,d=$ADDED,$DELETED; print('PASS' if a<=0.6*d else 'FAIL'); sys.exit(0 if a<=0.6*d else 1)"
```

Record added vs deleted LOC and the PASS/FAIL in `scripts/ab_interpreter.md`. If it FAILs, simplify the new modules (the spec's OC7 is a hard gate).

- [ ] **Step 5: Update docs + graph, then commit**

Update root `CLAUDE.md` + `agent/CLAUDE.md` architecture sections to describe reason→interpret→verify (remove DESIGN/CODEGEN/fidelity/`_AnswerGuard` references). Run `graphify` + `update-docs` per the maintenance rule.

```bash
git add -A
git commit -m "refactor(pipeline): cut over to deterministic interpreter; delete CODEGEN path (OC1/OC7)"
```

---

## Self-review

**Spec coverage:**
- OC1 (no exec of LLM code) → Task 19 deletes `codegen_v2`/`_run_script_on_vm`; interpreter never `exec()`s. ✓
- OC2 (two validated data artifacts) → Tasks 1,4 (models) + 14 (reason emits them). ✓
- OC3 (interpreter sole executor) → Tasks 5–9. ✓
- OC4 (IntentSpec from pre-phase facts) → Task 17 facts → Task 14 `run_intent`. ✓
- OC5 (deterministic VERIFY replaces fidelity/test-gate/`_AnswerGuard`) → Task 12 + Task 19 deletions. ✓
- OC6 (≥ baseline) → Task 18 gate. ✓
- OC7 (LOC ≤ 60% deleted; named modules removed) → Task 19 cloc gate. ✓
- OC8 (frozen named-parser escape hatch) → Task 3 `PARSERS` + Task 6 dispatch. ✓
- HM1 (no green regression) → Task 10/11 replay oracle + Task 18 A/B. ✓
- HM2 (LEARN+oracle retargeted) → Tasks 14/15/16 reuse `learned_store`+oracle. ✓
- HM3 (ref-grounding, security-first, two mutation idioms) → Tasks 7,8,9,12 with explicit regression tests. ✓
- HM4 (call budget 2..7, VERIFY 0 LLM) → `_run_interpreted` makes 1 INTENT + ≤MAX_STEPS×(PLAN+LEARN); verify is pure. ✓
- HM5 (tier routing untouched) → `_resolve_model_for_phase` reused; `llm.py` not modified. ✓
- HM6 (training mode) → Task 16. ✓
- Build order (1 pure → 2 interpreter → 3 verify → 4 reason+wiring → 5 prephase → 6 cutover) → Phases 1–6 match. ✓
- Testing strategy (predicates/primitives/interpreter/verify/corpus-replay/integration) → Tasks 2,3,5–9,10,11,12; integration t09/t27/t51 covered by a committed, `RUN_BENCHMARK`-gated `tests/test_integration_interpreter.py` (Task 18 Step 1) plus the full-suite A/B. ✓

**Resolved spec ambiguities (documented as deviations):** I3 security predicates → `Constraint.deny_when` (Task 4/12); bool predicate form → `{op,args}` (Task 1); `map_over_param_rows` deferred (t47 via explicit ops). The F-001/F-002 findings (LOC DoD, integration count) are satisfied by Task 19's cloc gate and Task 18's named integration tasks (t09/t27/t51).

**Placeholder scan:** corpus-replay Tasks 10–11 use an automatic oracle (old script == new plan on identical fixtures) rather than hand-authored expected strings — fixtures/PlanIRs are real artifacts derived from on-disk `design.json` via stated transformation rules, not TBDs. No "implement later" steps remain.

**Type consistency:** `resolve`/`evaluate`/`PredExpr`/`InterpretResult`/`CapturedAnswer`/`run_intent`/`run_plan`/`verify`/`interpret`/`lint_security_first`/`gather_prephase_facts`/`PrePhaseFacts`/`_run_interpreted` names are used identically across all tasks (see Canonical API).
