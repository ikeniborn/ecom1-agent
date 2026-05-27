---
chain:
  intent: docs/superpowers/intents/2026-05-27-heuristic-pipeline-intent.md
review:
  spec_hash: "e236ecc26672c483"
  last_run: "2026-05-27"
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: CRITICAL
      section: "8. Error Handling Summary"
      section_hash: "71270233a068ae75"
      text: "§8 table row 'LLM validation fails (ANSWER)' contradicted §3 which explicitly removes LLM from ANSWER. Stale row from old design."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "3. ANSWER Phase (modified)"
      section_hash: "190f25162bdcb95c"
      text: "Spec removes LLM from ANSWER, contradicting intent hard constraint 'vm.answer() always through LLM validation layer'. Design decision needs explicit acknowledgment."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-003
      phase: coverage
      severity: WARNING
      section: "4. LEARN Phase (minimal changes)"
      section_hash: "41cb831699a81dd2"
      text: "Intent: 'LEARN refines the heuristic script (not YAML rules)'. Spec uses indirect path: LEARN→YAML→CODEGEN. Not documented as intentional design."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-004
      phase: coverage
      severity: WARNING
      section: "8. Error Handling Summary"
      section_hash: "71270233a068ae75"
      text: "Intent stop rule: 'preserve last heuristic version' on MAX_STEPS exhaustion. Not explicit in spec."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-005
      phase: coverage
      severity: WARNING
      section: "8. Error Handling Summary"
      section_hash: "71270233a068ae75"
      text: "Intent: FS access outside data/ → hard error, no LEARN. Spec routed all script exceptions to LEARN generically."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-006
      phase: clarity
      severity: WARNING
      section: "6. MockVM"
      section_hash: "964d3b09c75ea62f"
      text: "§6 said 'empty-ish response', contradicting §2 'data synthesized from extracted_params and schema_digest'. Inconsistent description of same behavior."
      verdict: fixed
      verdict_at: "2026-05-27"
    - id: F-007
      phase: clarity
      severity: WARNING
      section: "7. Files Changed"
      section_hash: "8b9b9911fdd07c03"
      text: "§7 listed 'data/prompts/answer.md | Extend to accept SCRIPT_RESULT block' but §3 removed LLM from ANSWER entirely — that prompt file is no longer used. Stale entry."
      verdict: fixed
      verdict_at: "2026-05-27"
---
# Design: Heuristic-Driven Pipeline

**Date:** 2026-05-27
**Status:** approved
**Intent doc:** `docs/superpowers/intents/2026-05-27-heuristic-pipeline-intent.md`

## Overview

Replace the current LLM-as-executor model with an LLM-as-heuristic-generator model. The pipeline generates a self-contained Python script (`data/heuristics/{task_id}.py`) that encodes all task logic (SQL, regex, loops, aggregation, etc.). On repeat runs the script executes directly with zero LLM calls. The LLM focuses on generating and refining quality heuristics; code handles execution.

---

## 1. Execution Flow

### Two paths, decided at the start of `run_pipeline()`

```
run_pipeline():
  fast_path_eligible = (
      data/heuristics/{task_id}.py exists
      AND last_run[task_id].heuristic_valid == True
  )

  if fast_path_eligible:
      ok, fast_error = _run_fast_path()
      if ok:
          return                        # done, 0 LLM calls
      # fast path failed → fall through to full path immediately
      last_error = fast_error           # error context passed to first LEARN cycle
      save_last_run(task_id, heuristic_valid=False)

  # full pipeline cycle loop (runs on first encounter OR after fast path failure)
  for cycle in range(MAX_STEPS):
    ASSEMBLE → IDD → SDD → PLAN → CODEGEN → ANSWER → LEARN/CONSOLIDATE
```

LLM вызывается **только если fast path упал или скрипт ещё не существует**.

### Fast path

Fast path runs **0 LLM calls**. Skips ASSEMBLE, IDD, SDD, PLAN, CODEGEN, ANSWER-LLM.

The script was generated with full schema + success_criteria context, so `_result` already contains a complete, correctly formatted answer.

```
_run_fast_path(vm, task_id, task_text):
  script_code = read(data/heuristics/{task_id}.py)
  exec_globals = {"vm": vm, "task_text": task_text, "_result": None}
  exec(compile(script_code, f"{task_id}.py", "exec"), exec_globals)
  raw_result = exec_globals["_result"]   # {"message": ..., "outcome": ..., "refs": [...]}

  if raw_result is None or "outcome" not in raw_result:
    save_last_run(task_id, status="failure", heuristic_valid=False)
    return  # script broken → full path next run

  vm.answer(AnswerRequest(
      message=raw_result["message"],
      outcome=OUTCOME_BY_NAME[raw_result["outcome"]],
      refs=raw_result.get("refs", []),
  ))                                     # may raise APIError

  on APIError or script exception:
    save_last_run(task_id, status="failure", heuristic_valid=False)
    return False, f"fast path error: {error}"   # → caller runs full path immediately

  save_last_run(task_id, status="success", heuristic_valid=True)
  return True, ""
```

Fast path failure triggers full path **in the same run**. The `fast_error` is passed as `last_error` into the first LEARN cycle so the script is regenerated with error context.

### Full path (existing cycle loop, phases modified)

```
for cycle in range(MAX_STEPS):
  ASSEMBLE   → unified_context
  IDD        → IddOutput
  SDD        → SddOutput
  PLAN       → PlanOutput
  CODEGEN    → data/heuristics/{task_id}.py  ← NEW (replaces EXECUTE)
  ANSWER     → exec script → validate → vm.answer()
  (on fail)  → LEARN → CONSOLIDATE → next cycle
```

---

## 2. CODEGEN Phase

Replaces `_run_execute()`. Called after PLAN produces a `PlanOutput`.

### Inputs

- `unified_context` — assembled context (schema + learned rules)
- `IddOutput` — `reformulated_task`, `extracted_params`, `success_criteria`
- `SddOutput` — `spec_goal`, `actions` (SQL/read candidates as hints)
- `PlanOutput` — `action` (primary anchor action)
- `task_id` — for output path

### LLM call

```python
MODEL_CODEGEN     = env.get("MODEL_CODEGEN", MODEL)
MAX_TOKENS_CODEGEN = int(env.get("MAX_TOKENS_CODEGEN", "8192"))
```

Single LLM call using `data/prompts/codegen.md` as guide. Produces JSON:
```json
{
  "script": "# full python script...",
  "test":   "# mock test script..."
}
```

The script must:
- Import and use injected `vm` variable for all VM calls (`vm.exec`, `vm.read`, `vm.search`, etc.)
- Use injected `task_text: str` to extract task-specific parameters using its own regex/parsing logic — script is self-contained, no external `task_params` dict
- Write a **complete answer** to `_result`:
  ```python
  _result = {
      "message": "...",        # formatted human-readable answer
      "outcome": "OUTCOME_OK", # valid outcome code (OUTCOME_OK | OUTCOME_DENIED_SECURITY | OUTCOME_NONE_UNSUPPORTED | OUTCOME_NONE_CLARIFICATION)
      "refs": ["/proc/..."]    # grounding refs
  }
  ```
  The script is generated by LLM with full schema + success_criteria context, so it knows exactly how to format the final answer.
- Have `if __name__ == "__main__":` guard (never called in exec mode, but required for lint)
- Never call `vm.answer()`
- Never access filesystem outside `data/`
- Never make network calls

**BATCH EXECUTE is removed.** The script handles multi-action logic internally (loops over multiple SQL queries, reads multiple files, etc.).

Allowed techniques: SQL queries, regex, string matching, loops, aggregation, sorting, filtering, statistical calculations, fuzzy matching, memoization, any Python stdlib or project-installed packages.

### Internal lint-fix loop

```
CODEGEN_LINT_RETRIES = int(env.get("CODEGEN_LINT_RETRIES", "3"))

for attempt in range(CODEGEN_LINT_RETRIES):
    raw = call_llm_codegen(...)           # generates script + test JSON
    script, test = parse_codegen_output(raw)

    lint_error = None
    try:
        ast.parse(script)
        ast.parse(test)
    except SyntaxError as e:
        lint_error = str(e)

    if lint_error is None:
        break  # lint passed
    # else: feed lint_error back to LLM → retry

if lint_error:
    return None, f"CODEGEN lint failed after {CODEGEN_LINT_RETRIES} attempts: {lint_error}"
```

### Mock test execution

After lint passes:

```python
mock_vm = MockVM(extracted_params=idd_out.extracted_params, schema_digest=pre.schema_digest)
exec_globals = {"vm": mock_vm, "task_text": task_text, "_result": None}
exec(compile(test_code, f"{task_id}_test.py", "exec"), exec_globals)
# any Exception → return error to pipeline LEARN
```

`MockVM` is a stub with the same interface as `EcomRuntimeClientSync`. Its methods return data synthesized from `IddOutput.extracted_params` and `schema_digest` (columns, table names, sample values). LLM generates the test knowing what mock data will be available.

If mock test raises → CODEGEN returns error → pipeline routes to LEARN → next cycle regenerates script with the lesson.

### On success

```python
heuristics_dir = Path("data/heuristics")
heuristics_dir.mkdir(exist_ok=True)
(heuristics_dir / f"{task_id}.py").write_text(script_code)
(heuristics_dir / f"{task_id}_test.py").write_text(test_code)  # kept for debugging
```

Returns `CodegenOutput(script_path=..., script_code=...)`.

---

## 3. ANSWER Phase (modified)

ANSWER receives `CodegenOutput`, runs the script, and calls `vm.answer()` directly — **no LLM call**. The script is responsible for producing a correctly formatted answer (it was generated by LLM with full schema + success_criteria context).

```python
_run_answer(vm, codegen_out, task_text):
    exec_globals = {
        "vm": vm,
        "task_text": task_text,
        "_result": None,
    }
    try:
        exec(compile(codegen_out.script_code, codegen_out.script_path, "exec"), exec_globals)
    except Exception as e:
        return None, f"Script runtime error: {e}"

    raw_result = exec_globals.get("_result")
    if not raw_result or "outcome" not in raw_result or "message" not in raw_result:
        return None, "Script did not produce valid _result"

    # Structural validation only — no LLM needed
    if raw_result["outcome"] not in OUTCOME_BY_NAME:
        return None, f"Unknown outcome code: {raw_result['outcome']}"

    vm.answer(AnswerRequest(
        message=raw_result["message"],
        outcome=OUTCOME_BY_NAME[raw_result["outcome"]],
        refs=raw_result.get("refs", []),
    ))
    return AnswerOutput(
        message=raw_result["message"],
        outcome=raw_result["outcome"],
        grounding_refs=raw_result.get("refs", []),
    ), ""
```

**No ANSWER LLM call in either full path or fast path.** The script contains the complete answer logic. If the answer is wrong, LEARN captures the error and next CODEGEN regenerates a better script.

> **Design note (intent divergence):** The intent specified "vm.answer() call path: always through LLM validation layer". This design supersedes that constraint: the script is generated by LLM with full schema + success_criteria context baked in, so a separate LLM validation call is redundant. Structural validation (`outcome` code check + `_result` field presence) is sufficient. Correctness is enforced at generation time, not at answer time.

---

## 4. LEARN Phase (minimal changes)

LEARN still generates YAML rules written to `data/learned/{task_id}.yaml`. These rules are loaded by ASSEMBLE in the next cycle and flow into `unified_context`, which informs CODEGEN to regenerate a better script.

This is the heuristic refinement mechanism: LEARN writes the lesson as a YAML rule → ASSEMBLE surfaces it → CODEGEN regenerates the script incorporating the fix. The net effect is equivalent to "LEARN refines the heuristic script" per intent — the path is indirect (YAML → next-cycle CODEGEN) rather than direct script patching.

Single addition: `_build_learn_user_msg()` receives `heuristic_code` — the script that failed. This gives LEARN precise context to write a targeted fix rule.

```python
if heuristic_code:
    parts.append(f"HEURISTIC_CODE:\n```python\n{heuristic_code[:3000]}\n```")
```

CONSOLIDATE is unchanged.

---

## 5. Data Model Changes

### `save_last_run` extended

```python
save_last_run(
    task_id: str,
    status: str,           # "success" | "failure"
    outcome: str,
    cycles_used: int,
    grounding_refs_count: int,
    heuristic_valid: bool = False,   # NEW: True only on successful ANSWER + vm.answer()
)
```

`heuristic_valid=True` set only when: fast path OR full path completes with `vm.answer()` succeeding (no APIError).

### New Pydantic model

```python
class CodegenOutput(BaseModel):
    script_path: str
    script_code: str
    test_code: str
```

### New files

```
data/heuristics/{task_id}.py        # generated heuristic script
data/heuristics/{task_id}_test.py   # mock test (generation-time only)
data/prompts/codegen.md             # CODEGEN phase guide
```

### New env vars (add to `.env.example` and `CLAUDE.md`)

```
MODEL_CODEGEN=               # default: MODEL value
MAX_TOKENS_CODEGEN=8192
CODEGEN_LINT_RETRIES=3
```

---

## 6. MockVM

New class in `agent/mock_vm.py`:

```python
class MockVM:
    """Stub for EcomRuntimeClientSync. Returns synthesized data for mock tests."""
    def __init__(self, extracted_params: dict, schema_digest: str): ...
    def exec(self, req) -> Any: ...     # returns mock SQL rows from params
    def read(self, req) -> Any: ...     # returns mock file content
    def search(self, req) -> Any: ...
    def find(self, req) -> Any: ...
    def list(self, req) -> Any: ...
    def tree(self, req) -> Any: ...
    def answer(self, req) -> None:
        raise RuntimeError("vm.answer() must not be called from heuristic script")
```

MockVM never raises on `exec/read/search/etc.` — always returns structurally valid responses with data synthesized from `extracted_params` and `schema_digest` (column names, table names, sample values). This ensures mock tests validate logic, not connectivity.

---

## 7. Files Changed

| File | Change |
|------|--------|
| `agent/pipeline.py` | Add fast path check; replace `_run_execute` with `_run_codegen`; modify `_run_answer`; extend `_build_learn_user_msg` |
| `agent/models.py` | Add `CodegenOutput`; extend `LastRunRecord` with `heuristic_valid` |
| `agent/prompt_assembler.py` | Extend `save_last_run` signature |
| `agent/mock_vm.py` | New file — `MockVM` class |
| `data/prompts/codegen.md` | New file — CODEGEN phase guide |
| `.env.example` | Add `MODEL_CODEGEN`, `MAX_TOKENS_CODEGEN`, `CODEGEN_LINT_RETRIES` |
| `CLAUDE.md` | Document new env vars and heuristics directory |

---

## 8. Error Handling Summary

| Error | Handler |
|-------|---------|
| Lint fails after N retries | CODEGEN returns error → pipeline LEARN |
| Mock test exception | CODEGEN returns error → pipeline LEARN |
| Script runtime exception in ANSWER | ANSWER returns error → pipeline LEARN |
| `_result` not set by script | ANSWER returns error → pipeline LEARN |
| Script FS access outside `data/` (OSError/PermissionError) | Hard error — not routed to LEARN; pipeline aborts task |
| `vm.answer()` APIError (fast path) | save_last_run(heuristic_valid=False) → return |
| `vm.answer()` APIError (full path) | existing error handler unchanged |
| All cycles exhausted | existing fallback unchanged; last written `data/heuristics/{task_id}.py` preserved |