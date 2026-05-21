# Agent Refactor Design

**Date:** 2026-05-21  
**Scope:** `agent/` directory — dead code removal + phase module split  
**Goal:** Eliminate ~600 lines of legacy code and redistribute pipeline responsibilities into isolated, testable phase modules.

---

## Problem

1. **`pipeline.py` is a God Module** — 710 lines handling ASSEMBLE, SDD, PLAN, LEARN, ANSWER, retry logic, state, and error routing all in one file.
2. **~600 lines of dead code** — from removed pipeline phases (RESOLVE, DISCOVERY, TDD, contract evaluator), never cleaned up.
3. **`schema_gate.py` implemented but not connected** — validated, tested, but not invoked in the pipeline.
4. **Tests cover dead code** — `test_runner.py`, `test_sql_security.py` test modules no longer in the pipeline.

---

## Phase 1: Dead Code Removal

### Files to delete entirely

| File | Reason |
|------|--------|
| `agent/contract_models.py` | Orphaned — from removed contract-based pipeline design; not imported anywhere |
| `agent/test_runner.py` | TDD phase removed from pipeline; only test files use it |
| `agent/sql_security.py` | 9/10 functions unused; `check_retry_loop` migrates to `agent/pipeline.py` |
| `tests/test_runner.py` | Tests dead `test_runner.py` |
| `tests/test_sql_security.py` | Tests dead security functions (keep only if `check_retry_loop` test is valuable) |

### Functions/classes to delete from existing files

| Location | Item | Reason |
|----------|------|--------|
| `pipeline.py:44-56` | `run_resolve`, `_extract_discovery_results`, `_format_confirmed_values` | Compat stubs for removed RESOLVE/DISCOVERY phases |
| `pipeline.py:137` | `_format_schema_digest` alias | Unused alias |
| `models.py` | `ResolveOutput`, `ResolveCandidate` | RESOLVE phase removed |
| `models.py` | `TestOutput` | Marked deprecated; never used |
| `prompt.py` | `load_task_blocks()` | Defined, tested, never called in pipeline |
| `cc_client.py:291-293` | broken `from .task_types import ...` try/except block | `task_types.py` does not exist; feature is broken |

---

## Phase 2: Architectural Split — `phases/` Package

### New file structure

```
agent/
├── __init__.py             # exports run_agent (unchanged)
├── orchestrator.py         # entry point: prephase → pipeline (unchanged)
├── prephase.py             # schema discovery, AGENTS.MD parsing (unchanged)
├── pipeline.py             # thin: PipelineState, cycle loop, phase dispatch (~150 lines)
├── phases/
│   ├── __init__.py
│   ├── assemble.py         # ASSEMBLE phase: assemble_prompt → unified_context
│   ├── sdd.py              # SDD + schema_gate + VALIDATE (EXPLAIN check)
│   ├── plan.py             # PLAN phase; check_retry_loop guard lives here
│   ├── learn.py            # LEARN phase + _apply_learn_diff
│   └── answer.py           # ANSWER phase: LLM → AnswerOutput → vm.answer()
├── prompt_assembler.py     # unchanged; imported by phases/assemble.py
├── schema_gate.py          # unchanged; imported by phases/sdd.py
├── llm.py                  # unchanged
├── models.py               # cleaned (dead models removed)
├── json_extract.py         # unchanged
├── prompt.py               # load_task_blocks removed
├── cc_client.py            # task_types import removed
├── agents_md_parser.py     # unchanged
└── trace.py                # unchanged
```

### `PipelineState` dataclass

Defined in `pipeline.py`. Passed into every phase function and mutated in-place.

```python
@dataclass
class PipelineState:
    task: Task
    pre: PrephaseResult
    cfg: dict
    vm: Any
    learn_ctx: list[dict]
    prior_actions: list[str]
    step: int = 0
    unified_context: str = ""
    sdd_output: SddOutput | None = None
    plan_output: PlanOutput | None = None
```

### Phase contracts

Each phase module exposes a single `run_*(state: PipelineState) -> None` function (or raises on failure). Pipeline dispatches:

```
for step in range(max_steps):
    run_assemble(state)
    run_sdd(state)          # includes schema_gate + EXPLAIN
    run_plan(state)         # includes check_retry_loop
    run_answer(state)
    break                   # success
except PhaseError as e:
    run_learn(state, error=e)
    continue
```

### Phase responsibilities

| Phase | Module | Input | Output |
|-------|--------|-------|--------|
| ASSEMBLE | `phases/assemble.py` | state | `state.unified_context` |
| SDD | `phases/sdd.py` | state | `state.sdd_output` |
| SCHEMA CHECK | inside `sdd.py` | `state.sdd_output.sql` | raises or passes |
| VALIDATE (EXPLAIN) | inside `sdd.py` | `state.sdd_output.sql` | raises or passes |
| PLAN | `phases/plan.py` | state | `state.plan_output` |
| LEARN | `phases/learn.py` | state + error | updates `state.learn_ctx` |
| ANSWER | `phases/answer.py` | state | sends answer via vm |

---

## Phase 3: Test Cleanup

| File | Action |
|------|--------|
| `tests/test_runner.py` | Delete |
| `tests/test_sql_security.py` | Delete (or reduce to check_retry_loop test only) |
| `tests/test_schema_gate.py` | Keep — schema_gate is now active |
| `tests/test_pipeline.py` | Update import paths after split |
| `tests/phases/` | Create — unit tests per phase module |

---

## What Does NOT Change

- `prephase.py` — no changes
- `prompt_assembler.py` — no changes (imported from `phases/assemble.py`)
- `schema_gate.py` — no changes (imported from `phases/sdd.py`)
- `llm.py`, `json_extract.py`, `trace.py`, `cc_client.py` (after cleanup), `agents_md_parser.py`
- Public API: `run_agent()` signature unchanged
- Data files: `data/prompts/`, `data/learned/`, `models.json`
- Environment variables: all unchanged

---

## Success Criteria

- All existing tests pass after refactor
- `pipeline.py` ≤ 200 lines
- Each `phases/*.py` file ≤ 150 lines
- `schema_gate` invoked in SDD phase (verifiable via test)
- Zero imports of deleted modules anywhere in `agent/`
- `check_retry_loop` accessible from `phases/plan.py`
