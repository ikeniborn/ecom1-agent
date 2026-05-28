# Pipeline Redesign — Design Spec

**Date:** 2026-05-28
**Intent source:** `docs/superpowers/intents/2026-05-28-pipeline-redesign-intent.md`
**Approach:** Big-bang single-PR rewrite with separate DESIGN + CODEGEN LLM calls.

## Goal

Collapse `PREPHASE + ASSEMBLE + IDD + SDD + PLAN` into a single deterministic `DESIGN` phase grounded in `docs/proto-api-reference.md` + `/AGENTS.MD`. Iterate only on `CODEGEN`. Replace LLM-generated mock test with a deterministic tool-plan fidelity gate. Remove the fast path. `ANSWER` becomes a terminal one-shot outside the retry loop. `LEARN` feedback only influences `CODEGEN` (`DESIGN` is frozen per task run).

Hard targets:
- ≤2 LLM calls best case, ≤7 worst case (with `MAX_STEPS=3`)
- All benchmark tasks pass in a single run, under 1 h wall-clock via `ThreadPoolExecutor`

## Architecture

Per-task flow:

```
ENTRY
  └─ vm.read("/AGENTS.MD")                        [deterministic, 0 LLM]
  └─ DESIGN                                       [LLM #1, cached proto-ref block]
       └─ DesignOutput { tool_plan, outcome_override? }
       └─ if outcome_override: vm.answer(...) → END (terminal one-shot)
  └─ LOOP (cycle = 1..MAX_STEPS=3):
       ├─ CODEGEN                                 [LLM #2..N, cached proto-ref + tool_plan]
       │    └─ ast.parse lint (inline retries: CODEGEN_LINT_RETRIES=3)
       │    └─ generate fidelity test (deterministic, from tool_plan)
       │    └─ exec test on MockVM-spy in subprocess
       │         └─ pass → break loop
       │         └─ fail → LEARN+CONSOLIDATE (merged, single LLM call) → next cycle
  └─ ANSWER terminal (exactly one vm.answer call):
       ├─ loop broke successfully → exec script on real VM → script calls vm.answer
       └─ loop exhausted → vm.answer(OUTCOME_NONE_CLARIFICATION)
```

### LLM call budget

| Path | Calls | Composition |
|------|-------|-------------|
| Hard-stop (outcome_override) | 1 | DESIGN |
| Best happy path | 2 | DESIGN + CODEGEN |
| Worst (3 cycles) | 7 | DESIGN + 3 × (CODEGEN + LearnConsolidate) |

`LEARN` and `CONSOLIDATE` are merged into a single LLM call (`LearnConsolidateOutput`) to satisfy the ≤7 budget while preserving `MAX_STEPS=3` and the CONSOLIDATE-style health metric (HM3).

## Data shapes

### `agent/models.py` — final set

```python
class DesignOutput(BaseModel):
    intent: str                                    # 1-line summary
    params: dict[str, str]                         # extracted values (literal or placeholder)
    discovery: list[ToolOp]                        # runtime context ops
    ops: list[ToolOp]                              # main answer ops
    agents_md_constraints: list[AgentsMdRef]
    answer_template: AnswerTemplate
    outcome_override: str | None                   # OUTCOME_DENIED_SECURITY|OUTCOME_NONE_UNSUPPORTED|None

class ToolOp(BaseModel):
    rpc: str                                       # Read|List|Tree|Find|Search|Exec|Write|Delete|Stat
    args: dict[str, Any]                           # path, args, query, etc.
    bind: str | None                               # variable name for result chaining

class AgentsMdRef(BaseModel):
    anchor: str                                    # e.g. "#baskets > store_scope"
    rule: str                                      # verbatim rule text

class AnswerTemplate(BaseModel):
    message: str                                   # "{rows[0].cnt} baskets"
    outcome: str                                   # OUTCOME_OK by default
    refs: list[str]

class CodegenOutput(BaseModel):
    script_code: str                               # standalone Python; takes vm + params

class LearnConsolidateOutput(BaseModel):           # merged per LLM budget
    rule_content: str
    agents_md_anchor: str | None
    reasoning: str
    deactivate_ids: list[str]                      # consolidation: dedupe/replace
    deactivate_reason: str | None
    skip: bool
    skip_reason: str | None

class AnswerOutput(BaseModel):                     # produced by the script, not by an LLM
    message: str
    outcome: str
    grounding_refs: list[str]
```

**Deleted models:** `IddOutput`, `SddOutput`, `PlanOutput`, `ConsolidateOutput` (merged), `ExecuteOutput`, `ResolveOutput`, `ResolveCandidate`, `TestOutput`.

### Example `tool_plan`

```json
{
  "intent": "count baskets by store",
  "params": {"store_id": "$agent_store_id"},
  "discovery": [
    {"rpc": "Exec", "args": {"path": "/bin/sql", "args": [".schema baskets"]}, "bind": "schema"}
  ],
  "ops": [
    {"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, "bind": "rows"}
  ],
  "agents_md_constraints": [
    {"anchor": "#baskets > store_scope", "rule": "filter store_id=$agent_store_id"}
  ],
  "answer_template": {"message": "{rows[0].cnt} baskets", "outcome": "OUTCOME_OK", "refs": []},
  "outcome_override": null
}
```

### Persisted state — `data/learned/{tid}.yaml`

```yaml
task_id: t01
entries:
  - id: r001
    content: "..."
    agents_md_anchor: "#baskets > store_scope"   # NEW field
    reasoning: "..."
    status: active|inactive
    created: '2026-05-28'
    deactivated_reason: null
last_run:
  date: '2026-05-28'
  cycles_used: 2
  outcome: OUTCOME_OK
  status: success|failure
  # DROPPED: heuristic_valid, schema_hash (fast path removed)
```

## Kill / Create / Keep

### Delete — source

- `agent/prephase.py`
- `agent/prompt_assembler.py` (helpers migrated to `agent/learned_store.py`)
- `agent/evaluator.py`

### Delete — prompts

- `data/prompts/idd.md`
- `data/prompts/sdd.md`
- `data/prompts/plan.md`
- `data/prompts/assembler.md`
- `data/prompts/tdd.md`
- `data/prompts/answer.md` (ANSWER is deterministic)
- `data/prompts/consolidate.md` (merged into `learn.md`)

### Delete — data

- `data/eval_log.jsonl`
- `data/heuristics/t01.py`, `data/heuristics/t99.py` (orphans)
- `data/heuristics/*_test.py` (fidelity test is deterministic, not on disk)

### Reset — data

- `data/learned/t01.yaml` → `{task_id: t01, entries: [], last_run: null}`
- `data/learned/t99.yaml` → same shape

### Create — source

| File | Responsibility |
|------|---------------|
| `agent/learned_store.py` | `load_entries(tid)`, `apply_learn_diff(tid, out)`, `save_last_run(tid, …)` — no `heuristic_valid` / `schema_hash` |
| `agent/design.py` | `run_design(instruction, agents_md_text, learn_ctx) → DesignOutput` |
| `agent/codegen_v2.py` | `run_codegen(tool_plan, learn_ctx, prev_error) → CodegenOutput` |
| `agent/fidelity.py` | `generate_fidelity_test(tool_plan, tid) → str` (deterministic) |
| `agent/mock_vm_spy.py` | Recording MockVM with `EXPECTED_CALLS` assertions and fixture lookup |

### Create — prompts

- `data/prompts/design.md` — DESIGN guide; embeds `proto-api-reference.md` as a cached block
- `data/prompts/codegen.md` — rewritten; input is the tool_plan + AGENTS.MD constraints
- `data/prompts/learn.md` — rewritten; output is `LearnConsolidateOutput`

### Keep — source

- `agent/orchestrator.py` — simplified: `run_agent()` → `vm.read("/AGENTS.MD")` → `run_pipeline(...)`
- `agent/pipeline.py` — rewritten (new loop, no IDD/SDD/PLAN/FAST_PATH)
- `agent/llm.py` — unchanged
- `agent/json_extract.py` — mutation priority preserved (constraint H5)
- `agent/sql_security.py` — `check_retry_loop` preserved; invoked inside the CODEGEN retry loop
- `agent/agents_md_parser.py` — section index used for anchor lookup
- `agent/trace.py`
- `agent/prompt.py` — `load_prompt(name)`

## Fidelity gate (deterministic mock test)

Replaces the LLM-generated mock test, the dual-run mutation check, and the AST hardcode detector with a single deterministic gate. The gate proves the script calls RPCs exactly as listed in `tool_plan`.

### `agent/mock_vm_spy.py`

```python
class MockVMSpy:
    def __init__(self, fixtures: dict[str, Any]):
        self.fixtures = fixtures           # bind_name -> canned response
        self.calls: list[tuple[str, dict]] = []

    def read(self, path):
        self.calls.append(("Read", {"path": path}))
        return self.fixtures.get(_key("Read", path), b"")

    def exec(self, path, args):
        self.calls.append(("Exec", {"path": path, "args": list(args)}))
        return self.fixtures.get(_key("Exec", path, args), _stub_resp())

    # ... List, Tree, Find, Search, Write, Delete, Stat, Answer
```

### `agent/fidelity.py:generate_fidelity_test(tool_plan, tid) → str`

Emits a Python module like:

```python
# auto-generated; do not edit
from agent.mock_vm_spy import MockVMSpy
from data.heuristics.{tid} import run

EXPECTED_CALLS = [
    ("Exec", {"path": "/bin/sql", "args": [".schema baskets"]}),
    ("Exec", {"path": "/bin/sql", "args": ["SELECT COUNT(*) ... :store_id"]}),
    ("Answer", {...}),
]

FIXTURES = {
    "Exec:/bin/sql:.schema baskets": _stub_schema(),
    "Exec:/bin/sql:SELECT COUNT...": _stub_rows([{"cnt": 42}]),
}

def test_fidelity():
    vm = MockVMSpy(FIXTURES)
    run(vm, params={"store_id": "S001"})
    assert vm.calls == EXPECTED_CALLS, f"drift: {vm.calls}"
```

### Pipeline integration

```python
test_src = generate_fidelity_test(design.tool_plan, task_id)
exec_result = run_in_subprocess(test_src, script_code)   # isolated
if exec_result.passed:
    break    # gate passed; proceed to real vm.answer
else:
    learn_consolidate(failure_reason=exec_result.error, ...)
```

### What the gate catches

- Script invoked an extra RPC (hallucinated tool) → fail
- Script skipped a discovery op → fail
- Script altered SQL text relative to tool_plan → fail
- Script hardcoded a param instead of a placeholder → fail (fixture key mismatch)

### What the gate intentionally does not catch

- SQL semantic correctness (validated on the real VM)
- Final `answer_template` formatting (validated on the real VM run)

### Isolation

`subprocess.run([sys.executable, "-c", combined_src], timeout=30)` to isolate global state and to abort infinite loops.

## Pipeline loop + error handling

`agent/pipeline.py:run_pipeline(vm, instruction, task_id, agents_md_text)`:

```python
def run_pipeline(vm, instruction, task_id, agents_md_text):
    learn_ctx = load_entries(task_id)        # active rules only
    trace.header(task_id, instruction)

    # DESIGN — single call, frozen for the run
    try:
        design = run_design(instruction, agents_md_text, learn_ctx)
    except LLMError as e:
        return _terminal_clarification(vm, f"DESIGN failed: {e}")

    # Hard-stop branch
    if design.outcome_override:
        return vm.answer(
            message=design.answer_template.message,
            outcome=design.outcome_override,
            grounding_refs=[],
        )

    # CODEGEN retry loop
    last_error = None
    script_code = None
    for cycle in range(1, MAX_STEPS + 1):
        try:
            cg = run_codegen(
                tool_plan=design,
                learn_ctx=learn_ctx,
                prev_error=last_error,
            )
        except LLMError as e:
            last_error = f"CODEGEN llm_fail: {e}"
            continue

        # Lint gate
        try:
            ast.parse(cg.script_code)
        except SyntaxError as e:
            last_error = f"lint: {e}"
            _learn_consolidate(task_id, learn_ctx, last_error, cg.script_code)
            continue

        # Fidelity gate
        test_src = generate_fidelity_test(design, task_id)
        result = exec_fidelity_in_subprocess(test_src, cg.script_code, timeout_s=30)
        if not result.passed:
            last_error = f"fidelity: {result.error}"
            _learn_consolidate(task_id, learn_ctx, last_error, cg.script_code)
            continue

        # Gate passed
        script_code = cg.script_code
        break

    if script_code is None:
        save_last_run(task_id, cycles_used=MAX_STEPS, outcome="OUTCOME_NONE_CLARIFICATION", status="failure")
        return _terminal_clarification(vm, last_error)

    # Persist + real run
    Path(f"data/heuristics/{task_id}.py").write_text(script_code)
    try:
        run_script_on_vm(script_code, vm, design.params)   # script calls vm.answer
    except Exception as e:
        save_last_run(task_id, cycles_used=cycle, outcome="OUTCOME_NONE_CLARIFICATION", status="failure")
        return _terminal_clarification(vm, f"real-vm exec: {e}")

    save_last_run(task_id, cycles_used=cycle, outcome="OUTCOME_OK", status="success")
```

### Error taxonomy → LEARN trigger

| Error class            | LEARN+CONSOLIDATE called? | Cycle continues? |
|------------------------|---------------------------|------------------|
| DESIGN llm_fail        | no                        | no — terminal CLARIFICATION |
| CODEGEN llm_fail       | no                        | yes (retry; no rule extracted) |
| AST lint fail          | yes                       | yes |
| Fidelity gate fail     | yes                       | yes |
| Real-VM exec fail      | no                        | no — terminal CLARIFICATION |

### `_learn_consolidate(...)`

Single LLM call producing `LearnConsolidateOutput`. Writes a diff to `data/learned/{tid}.yaml` and mutates the in-memory `learn_ctx` for the next cycle.

### `check_retry_loop` integration

Invoked inside the CODEGEN retry loop. Compares the emitted SQL text inside `cg.script_code` against the previous cycle's. If identical SQL appears twice consecutively, the loop forces a terminal CLARIFICATION (anti-infinite-loop guard).

### Terminal one-shot

`vm.answer(...)` is called exactly once, outside the retry loop. All branches converge to a single exit point.

## Test plan

### Unit tests — new, TDD-first

| File | Coverage |
|------|----------|
| `test_design.py` | DesignOutput shape; outcome_override branches (UNSUPPORTED, DENIED_SECURITY); discovery vs ops separation; bind chaining; LLM mocked |
| `test_codegen_v2.py` | tool_plan → script_code; placeholder substitution; AGENTS.MD constraints honored; LLM mocked |
| `test_fidelity.py` | `generate_fidelity_test` determinism (same input → byte-equal output); fixtures cover all bind names; `EXPECTED_CALLS` order matches tool_plan |
| `test_mock_vm_spy.py` | Calls recorded in order; fixture lookup by `(rpc, path, args)`; stub responses match proto types |
| `test_pipeline_v2.py` | Full loop happy path (DESIGN + 1× CODEGEN); retry path (lint fail → LEARN → CODEGEN ok); exhaust path (3× fail → CLARIFICATION); outcome_override terminal; real-VM exec fail terminal |
| `test_learn_consolidate.py` | Merged LearnConsolidateOutput; `deactivate_ids` applied; `rule_content` appended; skip path |
| `test_learned_store.py` | `load_entries` returns active only; `apply_learn_diff` incremental; `save_last_run` without `heuristic_valid` / `schema_hash` |

### Integration tests (env-gated, real LLM)

- `test_benchmark_t01.py` — t01 from empty `learned.yaml` to OUTCOME_OK
- `test_benchmark_t99.py` — t99 from empty `learned.yaml` to OUTCOME_OK

### Keep tests (untouched)

`test_llm_module.py`, `test_sql_security.py`, `test_json_extract_cleanup.py`, `test_agents_md_parser.py`, `test_trace_main.py`.

### Delete tests

`test_pipeline.py`, `test_prephase.py`, `test_prompt_assembler.py`, `test_codegen.py`, `test_fast_path.py`, `test_orchestrator_pipeline.py`, `test_sdd_action_fix.py`, `test_schema_gate.py`, `test_pipeline_models.py`, `test_models_cleanup.py`, `test_models_consolidate.py`, `test_models_json_cleanup.py`, `test_test_runner.py`, `test_trace_pipeline.py`, `test_ref_bugs.py`, `test_answer.py`.

### Review and likely rewrite

`test_consolidate.py`, `test_learned_storage.py`, `test_llm_phases.py`, `test_mock_vm.py`, `test_models.py`, `test_prompt_loader.py`.

## Migration sequence (single PR)

1. Create new source files (`design.py`, `codegen_v2.py`, `fidelity.py`, `mock_vm_spy.py`, `learned_store.py`).
2. Create new prompts (`design.md`, rewritten `codegen.md`, rewritten `learn.md`).
3. Rewrite `models.py` (add `DesignOutput`, merge `ConsolidateOutput` into `LearnConsolidateOutput`, delete `IddOutput` / `SddOutput` / `PlanOutput` / `ExecuteOutput` / `ResolveOutput` / `TestOutput`).
4. Rewrite `pipeline.py` per the loop above.
5. Trim `orchestrator.py` (drop the prephase call, pass instruction + agents_md straight to `run_pipeline`).
6. Delete `prephase.py`, `prompt_assembler.py`, `evaluator.py`.
7. Delete obsolete prompts, `eval_log.jsonl`, orphan heuristic scripts.
8. Reset `data/learned/t01.yaml` and `data/learned/t99.yaml` to `{task_id, entries: [], last_run: null}`.
9. Write new tests (TDD: failing first), implement until green.
10. Delete obsolete tests per the list above.
11. Local run: `make task TASKS='t01,t99'` → both `OUTCOME_OK` from empty learned state.
12. Full benchmark: `uv run python main.py` → all tasks pass, `ThreadPoolExecutor`, under 1 h wall-clock.

## Acceptance gate (health metrics)

| Metric | Check | Result |
|--------|-------|--------|
| HM1 | t01 + t99 pass from empty `learned.yaml` in a single run | satisfied by integration tests |
| HM3 | LEARN+CONSOLIDATE merge persists rule diff to YAML | satisfied by `test_learn_consolidate.py` + `test_learned_store.py` |
| HM4 | ≤7 LLM calls worst case (1 DESIGN + 3 × (CODEGEN + LearnConsolidate)) | satisfied by design |
| HM5 | ≤2 LLM calls best case (1 DESIGN + 1 CODEGEN) | satisfied by design |
| HM6 | Full benchmark under 1 h wall-clock via `ThreadPoolExecutor` | satisfied by harness; verified in step 12 |
| HM7 | 0 LLM calls on repeat run | **deprioritized — fast path removed by H4** |

## Open trade-offs

- **HM7 vs H4:** the intent removes the fast path, so the "0 LLM calls on repeat" metric is intentionally dropped. Re-runs always go through DESIGN + CODEGEN.
- **DESIGN frozen vs LEARN scope:** LEARN feedback only feeds CODEGEN. If a failure root cause is actually a wrong tool_plan, the run will exhaust on CLARIFICATION. The next task run with the new learned rule will then influence the next DESIGN. This is accepted per intent H6 + H8.
- **Subprocess overhead in fidelity gate:** ~30 ms per cycle. Acceptable within the wall-clock budget given `MAX_STEPS=3`.
