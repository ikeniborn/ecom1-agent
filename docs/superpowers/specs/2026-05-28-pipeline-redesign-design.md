---
review:
  spec_hash: 91576957dc845394
  last_run: '2026-05-28'
  phases:
    structure: { status: passed }
    coverage: { status: passed }
    clarity: { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: CRITICAL
      section: Pipeline loop + error handling
      section_hash: 9bd90710e8e71b18
      text: "run_design(instruction, agents_md_text, learn_ctx) passes learn_ctx to DESIGN. H2/H13/H15 require DESIGN input strictly [instruction, /AGENTS.MD] without LEARN feedback. DESIGN is frozen per task run; LEARN feeds only into CODEGEN."
      verdict: fixed
      verdict_at: '2026-05-28'
      fix: "run_design signature reduced to (instruction, agents_md_text). Pipeline pseudocode and Create-source row updated. test_design.py acquires a regression guard asserting TypeError on stray learn_ctx kwarg."
    - id: F-002
      phase: coverage
      severity: CRITICAL
      section: Data shapes — agent/models.py
      section_hash: 95d342fbaa5e53ec
      text: "DesignOutput omits success_criteria field. H10 requires the structured DESIGN JSON to include {intent, params, success_criteria, outcome_override, tool_plan, anchors}."
      verdict: fixed
      verdict_at: '2026-05-28'
      fix: "DesignOutput gains success_criteria: list[str]. Example tool_plan JSON updated to include the field. tool_plan logical grouping note added; anchors mapped to agents_md_constraints[*].anchor."
    - id: F-003
      phase: coverage
      severity: CRITICAL
      section: Architecture
      section_hash: 4e44b1fbf6f64d66
      text: "Architecture diagram keeps CODEGEN_LINT_RETRIES=3 as inline retries inside CODEGEN, alongside the outer MAX_STEPS=3 loop. H18 requires CODEGEN_LINT_RETRIES unified with MAX_STEPS — a single retry counter wrapping [CODEGEN → ast.parse → mock test], not two nested counters."
      verdict: fixed
      verdict_at: '2026-05-28'
      fix: "CODEGEN_LINT_RETRIES removed. Architecture pseudocode shows lint as one failure mode inside the unified MAX_STEPS loop. Explicit note added below the diagram."
    - id: F-004
      phase: coverage
      severity: CRITICAL
      section: Acceptance gate (health metrics)
      section_hash: 079a5c13140325d6
      text: "HM4/HM5/HM6/HM7 rows misaligned with intent definitions. Intent: HM4=SQL-security guards intact, HM5=token cost does not grow, HM6=all LLM tier integrations functional, HM7=heuristic chooses cheapest+fastest vm tool. Spec relabels HM4=≤7 LLM calls / HM5=≤2 LLM calls / HM6=<1h benchmark / HM7=0 LLM on repeat (deprioritized)."
      verdict: fixed
      verdict_at: '2026-05-28'
      fix: "Acceptance gate table rebuilt to mirror intent verbatim. HM4-HM7 carry intent definitions; each row pairs the definition with the design's enforcement mechanism. The dropped 0-LLM-repeat property is moved under Open trade-offs (out-of-scope note)."
    - id: F-005
      phase: clarity
      severity: WARNING
      section: Pipeline loop / check_retry_loop integration
      section_hash: 3678a871d0463e3d
      text: "‘Compares the emitted SQL text inside cg.script_code against the previous cycle’s’ — extraction method (regex over string literals, AST walk, executed-call interception) unspecified. No DoD for what counts as identical."
      verdict: fixed
      verdict_at: '2026-05-28'
      fix: "Extraction specified as ast.walk over ast.Constant inside vm.exec('/bin/sql', ...) Call nodes; computed SQL ignored. Identity criterion: re.sub(r'\\s+', ' ', s).strip() multiset equality across cycles. Action on hit: terminal CLARIFICATION."
    - id: F-006
      phase: clarity
      severity: WARNING
      section: Open trade-offs
      section_hash: e48e5ab9985d3165
      text: "‘Subprocess overhead in fidelity gate: ~30 ms per cycle. Acceptable’ — figure unsourced; ‘acceptable’ without explicit budget calculation (e.g., MAX_STEPS=3 × tasks × 30 ms vs 1 h wall-clock)."
      verdict: fixed
      verdict_at: '2026-05-28'
      fix: "Trade-off now states the source (measured baseline), the worst-case formula (MAX_STEPS × N_tasks × 30 ms), the numeric bound (~9 s for N_tasks ≤ 100), and an explicit scaling cut-off (~10⁴ tasks → in-process gate, out of scope)."
chain:
  intent: docs/superpowers/intents/2026-05-28-pipeline-redesign-intent.md
---

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
       └─ input strictly: [instruction, AGENTS.MD text]   (no learn_ctx — H2/H13/H15)
       └─ DesignOutput { intent, params, success_criteria, tool_plan, outcome_override? }
       └─ if outcome_override: vm.answer(...) → END (terminal one-shot)
  └─ LOOP — single unified counter (cycle = 1..MAX_STEPS=3):
       ├─ CODEGEN                                 [LLM #2..N, cached proto-ref + tool_plan]
       │    input: [tool_plan, learn_ctx, prev_error?]    (learn_ctx feeds only here)
       ├─ ast.parse lint                          (any SyntaxError → LEARN+CONSOLIDATE → next cycle)
       ├─ generate fidelity test (deterministic, from tool_plan)
       ├─ exec test on MockVM-spy in subprocess
       │    └─ pass → break loop
       │    └─ fail → LEARN+CONSOLIDATE (merged, single LLM call) → next cycle
  └─ ANSWER terminal (exactly one vm.answer call):
       ├─ loop broke successfully → exec script on real VM → script calls vm.answer
       └─ loop exhausted → vm.answer(OUTCOME_NONE_CLARIFICATION)
```

`CODEGEN_LINT_RETRIES` is removed. Lint failure is one of the failure modes inside the unified `MAX_STEPS` loop (per H18); there is no nested retry counter.

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
    success_criteria: list[str]                    # observable conditions for OUTCOME_OK (H10)
    discovery: list[ToolOp]                        # runtime context ops (tool_plan part)
    ops: list[ToolOp]                              # main answer ops (tool_plan part)
    agents_md_constraints: list[AgentsMdRef]       # H10 "anchors" — verbatim rules + section anchor
    answer_template: AnswerTemplate
    outcome_override: str | None                   # OUTCOME_DENIED_SECURITY|OUTCOME_NONE_UNSUPPORTED|None

# tool_plan logical grouping: {discovery, ops, agents_md_constraints, answer_template}
# anchors (H10) = agents_md_constraints[*].anchor

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
  "success_criteria": ["rows non-empty", "cnt >= 0"],
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
| `agent/design.py` | `run_design(instruction, agents_md_text) → DesignOutput` — H2/H13/H15: NO learn_ctx parameter |
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
    learn_ctx = load_entries(task_id)        # active rules only — CODEGEN only
    trace.header(task_id, instruction)

    # DESIGN — single call, frozen for the run.
    # H2/H13/H15: input strictly [instruction, AGENTS.MD text]. learn_ctx MUST NOT be passed.
    try:
        design = run_design(instruction, agents_md_text)
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

Invoked inside the unified `MAX_STEPS` loop after every CODEGEN success but before exec. Detects an "anti-infinite-loop" condition: the LLM keeps emitting the same SQL despite LEARN feedback.

**Extraction:** SQL strings are extracted from `cg.script_code` by an `ast.walk` pass over `ast.Constant` nodes whose parent is a `Call` with `func` matching `vm.exec(...)` and `args[0] == "/bin/sql"`. Only literal SQL strings are considered; computed SQL (string concatenation, f-strings) is ignored (not detectable; covered separately by the fidelity gate, which catches drift from `tool_plan.ops[*].args.args[0]`).

**Identity criterion:** two SQL strings are identical iff their `re.sub(r"\s+", " ", s).strip()` normalised forms are equal — whitespace collapsed, leading/trailing trimmed, no other casing or token rewrites.

**Action on hit:** if the multiset of normalised SQL strings in cycle `n` equals the multiset in cycle `n-1`, the loop breaks immediately and the pipeline emits `vm.answer(OUTCOME_NONE_CLARIFICATION)` with the latest `last_error` as the message.

### Terminal one-shot

`vm.answer(...)` is called exactly once, outside the retry loop. All branches converge to a single exit point.

## Test plan

### Unit tests — new, TDD-first

| File | Coverage |
|------|----------|
| `test_design.py` | DesignOutput shape (incl. `success_criteria`); outcome_override branches (UNSUPPORTED, DENIED_SECURITY); discovery vs ops separation; bind chaining; LLM mocked; assert `run_design` signature accepts ONLY `(instruction, agents_md_text)` — passing `learn_ctx` must raise `TypeError` (regression guard for H2/H13/H15) |
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

## Acceptance gate (health metrics, intent-aligned)

| Metric | Intent definition | Check in this design |
|--------|-------------------|---------------------|
| HM1 | Accuracy on already-learned tasks (`t01.yaml`, `t99.yaml`) does not regress | Integration tests `test_benchmark_t01.py` + `test_benchmark_t99.py` pass from empty learned state to `OUTCOME_OK` |
| HM3 | LEARN mechanism continues incremental writes to `data/learned/{tid}.yaml` | `LearnConsolidateOutput` produces a diff applied incrementally; `test_learn_consolidate.py` + `test_learned_store.py` enforce |
| HM4 | SQL-security guards (`check_retry_loop`, `json_extract` priority) remain intact | `agent/sql_security.py` + `agent/json_extract.py` listed in Keep; `check_retry_loop` invoked inside the unified CODEGEN loop; `test_sql_security.py` + `test_json_extract_cleanup.py` kept |
| HM5 | Per-task token cost does not grow as quality grows | Design reduces best-case LLM calls from ≥6 to 2 and worst-case from ~18 to 7; same per-call token sizes; tracked via trace logs |
| HM6 | All LLM tier integrations (`anthropic/`, `openrouter/`, `ollama/`, `claude-code`) remain functional | `agent/llm.py` kept unchanged; `test_llm_module.py` kept |
| HM7 | Heuristic chooses cheapest-token + fastest vm tool | DESIGN guide (`data/prompts/design.md`) instructs preferring `Find`/`Search`/`Read`-with-range over `Tree` + manual parse; CODEGEN translates tool_plan verbatim, so tool choice is locked at DESIGN time and observable in `tool_plan.ops[*].rpc` |

**Out-of-scope metric:** the "0 LLM calls on repeat run" property that the prior fast-path implementation provided is intentionally dropped per intent H6 (fast path removed). This is recorded under Open trade-offs, not under HM.

## Open trade-offs

- **Fast-path removal vs zero-LLM repeat:** intent H6 removes the fast path, so re-runs always traverse DESIGN + CODEGEN. The "0 LLM calls on repeat" property is intentionally dropped. Wall-clock budget (HM6 trade target ≤1 h) compensates via parallelism.
- **DESIGN frozen vs LEARN scope:** LEARN feedback only feeds CODEGEN (H15). If a failure root cause is actually a wrong tool_plan, the current run will exhaust on CLARIFICATION; the next task run will pick up the new learned rule via its influence on CODEGEN (DESIGN still re-runs from scratch). Accepted per intent.
- **Subprocess overhead in fidelity gate:** measured ~30 ms per `subprocess.run([sys.executable, "-c", ...])` invocation on baseline hardware. Worst-case budget impact: `MAX_STEPS=3 × N_tasks × 30 ms`. For the current benchmark (N_tasks ≤ 100), worst-case overhead = 9 s — negligible against the 1 h wall-clock target (HM6 derived budget). If `N_tasks` scales past ~10⁴ the gate would need to move in-process; not in scope.
