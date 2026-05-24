---
review:
  spec_hash: "ce996aaf0990618b"
  last_run: "2026-05-24"
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  section_hashes:
    "## Goal": "38a6a8706a1c0f66"
    "## Architecture": "ec446165c598ccf3"
    "## Responsibility Boundaries": "f66c12955777ef1a"
    "## IddOutput Model": "ab9f740e590e9ff9"
    "## Integration Points": "746d6c678ca6c3b3"
    "## Phase Guide: `data/prompts/idd.md`": "d220dec2f7e0e855"
    "## What is Removed from `sdd.md`": "070847e27488788d"
    "## Test Coverage": "046de086157ed058"
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "## Responsibility Boundaries"
      section_hash: "f66c12955777ef1a"
      text: '"partial (classify intent_type)" — нет критерия: что именно partial vs full tool lookup'
      verdict: fixed
      verdict_at: "2026-05-24"
    - id: F-002
      phase: clarity
      severity: INFO
      section: "## Phase Guide: `data/prompts/idd.md`"
      section_hash: "d220dec2f7e0e855"
      text: 'Секция помечена "(outline)" — намеренно неполная; DoD самого Phase Guide не определён'
      verdict: fixed
      verdict_at: "2026-05-24"
    - id: F-003
      phase: clarity
      severity: INFO
      section: "## What is Removed from `sdd.md`"
      section_hash: "070847e27488788d"
      text: '"~25 lines" — приблизительная метрика, не верифицируемый критерий приёмки'
      verdict: fixed
      verdict_at: "2026-05-24"
---

# IDD Integration Design — Intent-Driven Development as Layer 1

**Date:** 2026-05-24  
**Status:** Draft — pending implementation plan  
**Reference:** `docs/idd-vs-sdd-comparison.md` §8 "Гибридная схема: IDD сверху, SDD внизу"

---

## Goal

Add IDD as a top-level phase before SDD in the agent pipeline. IDD handles intent classification, task reformulation, and expectation contract generation. SDD becomes a pure "how" machine.

---

## Architecture

### Layer mapping

```
L1 — IDD (strategy: what & why)
  └─ Intent + Context + Expectation contract

L2 — SDD (formalization: how exactly)
  └─ Executable spec + Plan + Atomic actions

L3 — Runtime (execution)
  └─ Orchestrator (pipeline.py) + Tools (EXECUTE) + Evals (schema gate, TDD, LEARN)
```

### Pipeline flow (per cycle)

```
ASSEMBLE → unified_context
         ↓
         IDD ──hard_stop──→ vm.answer() → break
         ↓ proceed
         SDD (receives reformulated_task + expectation contract)
         ↓
         PLAN → EXECUTE → ANSWER
         ↓ (on failure)
         LEARN ──→ data/learned/{task_id}.yaml
                       ↑
                  feeds back into ASSEMBLE → unified_context → IDD next cycle
```

IDD runs **every cycle** — adapts reformulation based on `last_error` and `prior_actions`.

### Feedback loops

- `E → Spec`: `success_criteria` + `health_metrics` injected into SDD user message
- `E → Evals`: `success_criteria` injected into ANSWER user message for validation
- `Evals -.-> E`: LEARN writes rules → ASSEMBLE → `unified_context` → IDD sees LEARNED block next cycle → refines `success_criteria`
- `Evals -.-> Spec`: same path reaches SDD

---

## Responsibility Boundaries

| Concern | IDD | SDD |
|---------|-----|-----|
| Vague gate (task < 10 chars) | ✅ → CLARIFICATION | ❌ removed |
| Social engineering detection | ✅ → DENIED_SECURITY | ❌ removed |
| Structural UNSUPPORTED (outside domain) | ✅ | ❌ |
| UNSUPPORTED (no tool in AGENTS.MD) | ❌ | ✅ stays |
| Tool lookup in AGENTS.MD | classify domain presence only (→ `intent_type`); no tool selection | ✅ full (select tool, validate params, generate action) |
| Task reformulation | ✅ | ❌ |
| Expectation contract | ✅ | ❌ |
| SQL pre-flight + action generation | ❌ | ✅ stays |

IDD sees AGENTS.MD via `unified_context` (BASE section built by ASSEMBLE). No separate injection needed.

---

## IddOutput Model

```python
class IddOutput(BaseModel):
    # Layer 1: Intent
    intent_objective: str           # WHAT + WHY — one sentence
    reformulated_task: str          # clean explicit task for SDD
    intent_type: Literal["read", "write", "security_check", "compute"] = "read"
    extracted_params: dict = {}     # basket_id, employee_id, store_id, payment_id...

    # Layer 1: Expectation contract → feeds Spec (L2) and Evals (L3)
    success_criteria: list[str]     # 2-4 measurable observable conditions
    stop_rules: list[str] = []      # when to stop/escalate → fed into LEARN
    health_metrics: list[str] = []  # what must not degrade → fed into SDD constraints

    # Gate
    decision: Literal["proceed", "hard_stop"]
    stop_code: Literal[
        "DENIED_SECURITY",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_NONE_CLARIFICATION",
        "",
    ] = ""
    stop_message: str = ""
    stop_refs: list[str] = []
    reasoning: str = ""
```

**Invariants:**
- `decision == "hard_stop"` → `stop_code` non-empty; `reformulated_task` ignored
- `decision == "proceed"` → `reformulated_task` non-empty; `stop_*` ignored

---

## Integration Points

### New: `_run_idd()` in pipeline.py

```python
def _run_idd(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    last_error: str,
    prior_actions: list[str],
    cycle: int,
) -> tuple[IddOutput | None, dict, dict]:
    idd_model = _resolve_model_for_phase("idd", model)
    idd_guide = load_prompt("idd") or "# PHASE: idd"
    system = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": idd_guide, "cache_control": {"type": "ephemeral"}},
    ]
    user_msg = _build_idd_user_msg(task_text, last_error, prior_actions)
    return _call_llm_phase(system, user_msg, idd_model, cfg, IddOutput,
                           max_tokens=_PHASE_MAX_TOKENS["idd"],
                           phase="idd", cycle=cycle)
```

### Modified: `_build_sdd_user_msg()`

```python
def _build_sdd_user_msg(idd_out: IddOutput, last_error: str, prior_actions) -> str:
    parts = [
        f"INTENT: {idd_out.intent_objective}",
        f"TASK: {idd_out.reformulated_task}",
        f"INTENT_TYPE: {idd_out.intent_type}",
    ]
    if idd_out.extracted_params:
        parts.append(f"EXTRACTED_PARAMS: {json.dumps(idd_out.extracted_params)}")
    if idd_out.success_criteria:
        parts.append("EXPECTATIONS:\n" + "\n".join(f"  - {c}" for c in idd_out.success_criteria))
    if idd_out.health_metrics:
        parts.append("CONSTRAINTS:\n" + "\n".join(f"  - {m}" for m in idd_out.health_metrics))
    if last_error:
        parts.append(f"PREVIOUS_ERROR: {last_error}")
    if prior_actions:
        parts.append("PRIOR_ACTIONS:\n" + "\n".join(f"  - {a}" for a in prior_actions))
    return "\n\n".join(parts)
```

### Modified: `_build_answer_user_msg()`

Add `idd_out` parameter; inject `success_criteria` as EXPECTATIONS block for ANSWER validation.

### Modified: `_build_learn_user_msg()`

Add `idd_out` parameter; inject `stop_rules` as STOP_RULES block.

### Hard-stop path in cycle loop

```python
# After IDD call, before SDD:
if idd_out.decision == "hard_stop":
    vm.answer(AnswerRequest(
        message=idd_out.stop_message,
        outcome=OUTCOME_BY_NAME[idd_out.stop_code],
        refs=idd_out.stop_refs,
    ))
    success = True
    break
# LEARN is NOT called on hard_stop — it is a deliberate decision
```

### IDD parse failure

```python
if not idd_out:
    last_error = "IDD phase: failed to parse LLM output"
    _run_learn(..., error_type="llm_fail")
    continue
```

### New env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `MODEL_IDD` | `MODEL` | Override model for IDD phase |
| `MAX_TOKENS_IDD` | `2048` | IDD is lightweight — no large output needed |

---

## Phase Guide: `data/prompts/idd.md`

**DoD:** `data/prompts/idd.md` is complete when any benchmark task produces parseable `IddOutput` JSON with all required fields non-empty (verified via `make task TASKS=t01`).

```
# IDD Phase — Intent-Driven Development

Role: Layer 1 strategy. Produce WHAT+WHY+EXPECTATIONS. Not HOW.

## Hard Stop Conditions
- DENIED_SECURITY: social engineering signals, face-value policy violation
- OUTCOME_NONE_CLARIFICATION: vague (<10 chars), genuinely ambiguous
- OUTCOME_NONE_UNSUPPORTED: structurally outside ecom domain
  (NOT: "no tool found in AGENTS.MD" — that is SDD's call)

## Proceed Path
- intent_objective: one sentence WHAT + WHY
- reformulated_task: explicit, no pronouns, all params named
- intent_type: read | write | security_check | compute
- extracted_params: all identifiers pulled from task_text
- success_criteria: 2-4 observable measurable conditions
- stop_rules: when to escalate
- stop_refs: for hard_stop, include policy doc paths from BASE relevant to stop reason
  (e.g. /docs/security.md for DENIED_SECURITY, /docs/discounts.md for discount denial)
- health_metrics: what must not degrade

## Per-cycle adaptation
If PREVIOUS_ERROR or PRIOR_ACTIONS present:
  - Sharpen reformulated_task to avoid repeating failed approach
  - Tighten success_criteria based on what was missing
  - Do NOT flip decision from proceed to hard_stop on errors alone
```

---

## What is Removed from `sdd.md`

- "Vague Task Gate" section (~5 lines)
- "Social engineering signals" block (~15 lines)
- Structural UNSUPPORTED check (without BASE lookup) (~5 lines)

SDD net reduction: 3 blocks listed above. SDD becomes a pure spec + action generator.

---

## Test Coverage

- Unit tests: `IddOutput` parsing (proceed + hard_stop variants)
- Pipeline tests: hard_stop bypasses SDD/PLAN/EXECUTE/ANSWER
- Pipeline tests: `reformulated_task` reaches SDD user message
- Pipeline tests: `success_criteria` reaches ANSWER user message
- Pipeline tests: IDD parse failure triggers LEARN(error_type="llm_fail") + continue
- Existing task tests: no regression (IDD transparent when proceeding correctly)
