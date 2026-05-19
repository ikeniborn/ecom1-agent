# SDD+PLAN Pipeline Redesign

## Goal

Embed superpowers spec→plan patterns into the agent pipeline. SDD becomes a structured spec phase; PLAN decomposes it into executable steps. LEARN updates from both to improve future cycles.

## Pipeline

```
ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER
                            ↑
                LEARN → learn_ctx → next cycle
```

## Phase IO

| Phase | Input | Output |
|-------|-------|--------|
| ASSEMBLE | `task_text` + `learn_ctx` | `unified_context` |
| SDD | `unified_context` | `SddOutput` |
| PLAN | `SddOutput` | `PlanOutput` |
| EXECUTE | `PlanOutput.action` | results |
| ANSWER | `unified_context` + results | `AnswerOutput` |
| LEARN | `unified_context` + error + `SddOutput` + `PlanOutput` | updated `learn_ctx` |

## Data Models

### SddOutput (extended)

```python
class SddOutput(BaseModel):
    spec_goal: str            # one-sentence goal
    success_criteria: list[str]  # 2-4 correctness conditions
    plan: list[str]           # reasoning steps (existing)
    sql_queries: list[str]    # candidate SQL (existing)
    error_code: str = ""      # existing
```

### PlanOutput (new)

```python
class PlanOutput(BaseModel):
    approach: str             # decomposition strategy
    steps: list[str]          # ordered execution steps
    action: str               # final SQL query or expression to execute (plain string)
```

## Components

### models.py
- Add `spec_goal: str` and `success_criteria: list[str]` to `SddOutput`
- Add new `PlanOutput` class

### data/prompts/plan.md
- New PLAN phase prompt
- Input context: full `SddOutput` (spec_goal, success_criteria, plan, sql_queries)
- Output: approach, steps, final action

### pipeline.py
- Remove TDD phase entirely
- Add PLAN phase after SDD, before EXECUTE
- PLAN call: `_call_llm_phase(PlanOutput, system=[plan_guide], user_msg=sdd_out_serialized, phase="plan")`
- EXECUTE receives `PlanOutput.action`
- LEARN receives `unified_context` + error + `SddOutput` + `PlanOutput`

### llm.py
- Add `"plan"` to `_resolve_model_for_phase`
- Env var: `MODEL_PLAN` (defaults to `MODEL`)

### data/prompts/learn.md
- Update to reflect LEARN now receives SddOutput + PlanOutput
- Lessons must target spec quality and plan decomposition, not just SQL

## Learning Loop

LEARN sees: what was intended (spec_goal, success_criteria), how it was decomposed (steps, action), what failed (error). Produces a rule targeting the gap between spec intent and plan execution. Rule enters `learn_ctx` → ASSEMBLE includes it in `unified_context` → SDD and PLAN improve in next cycle.

## Out of Scope

- eval_log.jsonl — no changes
- rules/*.yaml, security/*.yaml — removed from ASSEMBLE
- TDD phase — removed
