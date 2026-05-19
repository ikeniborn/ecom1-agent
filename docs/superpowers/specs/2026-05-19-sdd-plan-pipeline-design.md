# SDD+PLAN Pipeline Redesign

## Goal

Embed superpowers spec→plan patterns into the agent pipeline. SDD becomes a structured spec phase; PLAN decomposes it into executable steps. LEARN updates from both to improve future cycles.

The pipeline is **task-type agnostic** — tasks may involve SQL queries, document traversal, tool calls, verification checks, or any combination. ASSEMBLE studies the available tools and doc structure before SDD forms a spec; the spec and plan must reflect the actual task type, not assume SQL.

## Pipeline

```
ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER
                            ↑
                LEARN → learn_ctx → next cycle
```

## Phase IO

| Phase | Input | Output |
|-------|-------|--------|
| ASSEMBLE | `AGENTS.md` + `task_text` + `tree /docs` + `learn_ctx` | `unified_context` |
| SDD | `unified_context` | `SddOutput` |
| PLAN | `SddOutput` | `PlanOutput` |
| EXECUTE | `PlanOutput` | `ExecuteOutput` (results) |
| ANSWER | `ExecuteOutput` | `AnswerOutput` |
| LEARN | `unified_context` + `SddOutput` + `PlanOutput` + `AnswerOutput` | updated `learn_ctx` |

## Data Models

### SddOutput (redesigned)

```python
class SddOutput(BaseModel):
    spec_goal: str              # one-sentence goal
    success_criteria: list[str] # 2-4 correctness conditions
    plan: list[str]             # reasoning steps toward the goal
    actions: list[str]          # candidate actions (SQL, tool calls, doc reads — type depends on task)
    error_code: str = ""        # existing
```

`actions` replaces `sql_queries` — not all tasks involve SQL. Each action is a plain string; its interpretation depends on task type (SQL query, `/bin` command, path read, etc.).

### PlanOutput (new)

```python
class PlanOutput(BaseModel):
    approach: str             # decomposition strategy
    steps: list[str]          # ordered execution steps
    action: str               # final action to execute (SQL, tool call, path read — plain string; type inferred from task)
```

### ExecuteOutput (new)

```python
class ExecuteOutput(BaseModel):
    results: list[dict]       # raw rows from execution
    action: str               # echo of executed action
```

## Components

### models.py
- Replace `sql_queries: list[str]` with `actions: list[str]` in `SddOutput`
- Add `spec_goal: str` and `success_criteria: list[str]` to `SddOutput`
- Add new `PlanOutput` class
- Add new `ExecuteOutput` class

### data/prompts/plan.md
- New PLAN phase prompt
- Input context: full `SddOutput` (spec_goal, success_criteria, plan, actions)
- Output: approach, steps, final action (task-type agnostic)

### pipeline.py
- Remove TDD phase entirely
- Add PLAN phase after SDD, before EXECUTE
- PLAN call: `_call_llm_phase(PlanOutput, system=[plan_guide], user_msg=sdd_out_serialized, phase="plan")`
- EXECUTE receives full `PlanOutput` (approach, steps, action) — understands decomposition context
- ANSWER receives `ExecuteOutput` only — no `unified_context`
- LEARN receives `unified_context` + `SddOutput` + `PlanOutput` + `AnswerOutput` — full picture: task intent, spec, plan, execution, wrong answer → lesson targets spec/plan quality

### llm.py
- Add `"plan"` to `_resolve_model_for_phase`
- Env var: `MODEL_PLAN` (defaults to `MODEL`)

### data/prompts/learn.md
- Update to reflect LEARN now receives SddOutput + PlanOutput
- Lessons must target spec quality and plan decomposition, not just SQL

## ASSEMBLE Sources

- `AGENTS.md` — base agent instructions from harness (read via `vm.read("/AGENTS.MD")`). Structured as `##` sections parsed into `agents_md_index`. **Section names and content are dynamic** — they vary per deployment and must not be hardcoded. ASSEMBLE reads the index at runtime and passes all sections as-is into `unified_context`. Agent treats whatever is present as authoritative.
- `/bin` utilities — executable tools provided by harness; AGENTS.md describes what each does and when to use them. **ASSEMBLE enumerates available tools** before passing to SDD so the spec can reference concrete capabilities.
- `tree /docs` — executed at ASSEMBLE start; agent studies document structure to understand what knowledge is available before forming spec.
- `task_text` — specific task provided by harness.
- `learn_ctx` — lessons from previous failed cycles; highest priority in `unified_context` assembly.

ASSEMBLE order: read AGENTS.md → enumerate /bin tools → run tree /docs → merge with learn_ctx → produce unified_context. SDD receives a complete picture of the environment before forming any spec.

## Learning Loop

LEARN sees: task intent (unified_context), spec (SddOutput), decomposition (PlanOutput), wrong answer (AnswerOutput). Produces a rule targeting the gap between spec intent and plan execution. Rule enters `learn_ctx` → ASSEMBLE includes it in `unified_context` → SDD and PLAN improve in next cycle.

## Out of Scope

- eval_log.jsonl — no changes
- rules/*.yaml, security/*.yaml — removed from ASSEMBLE
- TDD phase — removed
