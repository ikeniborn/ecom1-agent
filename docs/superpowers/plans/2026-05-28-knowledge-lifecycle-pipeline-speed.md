---
chain:
  intent: docs/superpowers/intents/2026-05-28-knowledge-lifecycle-pipeline-speed-intent.md
  spec: docs/superpowers/specs/2026-05-28-knowledge-lifecycle-pipeline-speed-design.md
review:
  plan_hash: "4a578a51c046a832"
  spec_hash: "e8dd2408d0014152"
  last_run: "2026-05-28"
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings: []
---
# Knowledge Lifecycle & Pipeline Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent stale heuristics from failing repeat runs by enforcing generalized scripts and detecting schema changes.

**Architecture:** Three-layer defense: (1) codegen.md mandatory param-extraction rule → LLM writes general scripts; (2) AST hardcode detector + dual-run MockVM validation → rejects hardcoded scripts at generation time; (3) schema hash guard → skips fast path on schema change, then injects HEURISTIC_HINT so CODEGEN adapts the existing script. LEARN gets `error_type="hardcoded_params"` to generate regex-parsing rules rather than domain logic.

**Tech Stack:** Python stdlib (`ast`, `re`, `hashlib`), existing MockVM, PyYAML, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `data/prompts/codegen.md` | Modify | Add mandatory param extraction block |
| `agent/pipeline.py` | Modify | `_STOP_WORDS`, `_detect_hardcoded_params`, dual-run in `_run_codegen`, HARDCODED_PARAMS handling, schema hash + fast path guard, HEURISTIC_HINT, ERROR_CATEGORY in `_build_learn_user_msg` |
| `agent/prompt_assembler.py` | Modify | Add `schema_hash` param to `save_last_run` |
| `tests/test_codegen.py` | Modify | Tests for hardcode detection, dual-run, HARDCODED_PARAMS error |
| `tests/test_prompt_assembler.py` | Modify | Test for `schema_hash` in `save_last_run` |

---

## Task 1: Add mandatory param extraction block to `codegen.md`

**Files:**
- Modify: `data/prompts/codegen.md`
- Test: `tests/test_prompt_loader.py` (extend existing)

- [ ] **Step 1: Write failing test**

```python
# In tests/test_prompt_loader.py — add at bottom:
def test_codegen_prompt_has_mandatory_param_extraction():
    from agent.prompt import load_prompt
    content = load_prompt("codegen")
    assert "MANDATORY" in content, "codegen.md must contain MANDATORY param extraction rule"
    assert "task_text" in content, "codegen.md must reference task_text variable"
    assert "re.search" in content, "codegen.md must show regex extraction pattern"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_prompt_loader.py::test_codegen_prompt_has_mandatory_param_extraction -v
```

Expected: FAIL — prompt lacks MANDATORY block

- [ ] **Step 3: Add mandatory param extraction block to `data/prompts/codegen.md`**

Insert after the line `## Script requirements` (after "The script MUST:"), add the following block before item 1:

```markdown
## Param extraction — MANDATORY

NEVER hardcode values from the task. ALL task-specific tokens
(brand, model, SKU, name, category, amount, date, order ID, etc.)
MUST be extracted from `task_text` at runtime.

Required pattern:
```python
import re
brand = re.search(r'brand[=:\s]+(["\']?)(\S+)\1', task_text, re.I)
brand = brand.group(2) if brand else ""
```

Scripts that hardcode task values will be rejected.
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_prompt_loader.py::test_codegen_prompt_has_mandatory_param_extraction -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/prompts/codegen.md tests/test_prompt_loader.py
git commit -m "feat(prompts): add mandatory param extraction block to codegen.md"
```

---

## Task 2: Add `_STOP_WORDS` + `_detect_hardcoded_params` to `pipeline.py`

**Files:**
- Modify: `agent/pipeline.py` — add constant + function before `_run_codegen`
- Test: `tests/test_codegen.py` — add detector unit tests

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_codegen.py — add after imports, before existing tests:
from agent.pipeline import _detect_hardcoded_params


def test_detect_hardcoded_params_catches_task_token():
    """Token from task_text that appears as a string literal in script → detected."""
    script = '''
_result = {"message": "found Heco brand", "outcome": "OUTCOME_OK", "refs": []}
sql = "SELECT * FROM products WHERE brand = 'Heco'"
'''
    reason = _detect_hardcoded_params(script, "Find products for brand Heco")
    assert reason is not None, "Should detect 'Heco' hardcoded from task_text"
    assert "Heco" in reason


def test_detect_hardcoded_params_ignores_stopwords():
    """SQL keywords and short words not in task_text are not flagged."""
    script = '''
import csv, io
from bitgn.vm.ecom.ecom_pb2 import ExecRequest
result = vm.exec(ExecRequest(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM orders"]))
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
count = int(rows[0]["cnt"]) if rows else 0
_result = {"message": f"{count} orders", "outcome": "OUTCOME_OK", "refs": []}
'''
    reason = _detect_hardcoded_params(script, "How many orders?")
    assert reason is None, f"Should not detect false positives, but got: {reason}"


def test_detect_hardcoded_params_ignores_short_tokens():
    """Tokens shorter than 4 chars are not checked."""
    script = '_result = {"message": "ok", "outcome": "OUTCOME_OK", "refs": []}'
    reason = _detect_hardcoded_params(script, "ok id")
    assert reason is None


def test_detect_hardcoded_params_returns_none_on_syntax_error():
    """Broken script (SyntaxError) → returns None, not raises."""
    reason = _detect_hardcoded_params("def broken(", "find brand Sony")
    assert reason is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_codegen.py::test_detect_hardcoded_params_catches_task_token tests/test_codegen.py::test_detect_hardcoded_params_ignores_stopwords tests/test_codegen.py::test_detect_hardcoded_params_ignores_short_tokens tests/test_codegen.py::test_detect_hardcoded_params_returns_none_on_syntax_error -v
```

Expected: FAIL — `ImportError: cannot import name '_detect_hardcoded_params'`

- [ ] **Step 3: Add `_STOP_WORDS` and `_detect_hardcoded_params` to `agent/pipeline.py`**

Add after `_CODEGEN_LINT_RETRIES` line (after line ~44) and before the compat stubs:

```python
_STOP_WORDS = frozenset({
    "from", "where", "select", "count", "inner", "join", "lower",
    "like", "true", "false", "none", "outcome", "message", "result",
    "python", "import", "return", "stdout", "strip", "items",
})


def _detect_hardcoded_params(script_code: str, task_text: str) -> str | None:
    """Return a reason string if script_code contains a string literal copied from task_text.

    Returns None if no hardcoded params detected or if script_code has a SyntaxError.
    """
    task_tokens = {
        t.lower() for t in re.findall(r"[A-Za-z0-9_-]{4,}", task_text)
        if t.lower() not in _STOP_WORDS
    }
    try:
        tree = ast.parse(script_code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.s, str):
            if node.s.lower() in task_tokens:
                return f"hardcoded value {node.s!r} from task_text"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_codegen.py::test_detect_hardcoded_params_catches_task_token tests/test_codegen.py::test_detect_hardcoded_params_ignores_stopwords tests/test_codegen.py::test_detect_hardcoded_params_ignores_short_tokens tests/test_codegen.py::test_detect_hardcoded_params_returns_none_on_syntax_error -v
```

Expected: all 4 PASS

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all previously passing tests still pass

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_codegen.py
git commit -m "feat(pipeline): add _STOP_WORDS + _detect_hardcoded_params AST detector"
```

---

## Task 3: Dual-run MockVM validation inside `_run_codegen` loop

**Files:**
- Modify: `agent/pipeline.py` — restructure `_run_codegen` to add hardcode detection + dual-run inside loop
- Modify: `tests/test_codegen.py` — update `test_run_codegen_success`, add dual-run tests

The restructured `_run_codegen` moves:
1. AST hardcode detection inside the retry loop (after lint)
2. Script execution on original `task_text` (dual-run step 1) inside the loop
3. Script execution on mutated `task_text` (dual-run step 2) inside the loop
4. `test_code` execution moved outside loop (only runs once after loop succeeds)

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_codegen.py — add after detector tests:

_HARDCODED_SCRIPT = '''
import csv, io
from bitgn.vm.ecom.ecom_pb2 import ExecRequest
result = vm.exec(ExecRequest(path="/bin/sql", args=["SELECT * FROM products WHERE brand = 'Heco'"]))
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
_result = {"message": f"{len(rows)} Heco products", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
'''

_HARDCODED_LLM_RESPONSE = f'{{"script": {repr(_HARDCODED_SCRIPT)}, "test": {repr(_GOOD_TEST)}}}'


def test_run_codegen_detects_hardcoded_params_returns_prefixed_error():
    """Script hardcodes brand from task_text → all retries fail → HARDCODED_PARAMS: prefix in error."""
    import agent.pipeline as pipeline_mod
    with patch("agent.pipeline.call_llm_raw", return_value=_HARDCODED_LLM_RESPONSE), \
         patch.object(pipeline_mod, "_CODEGEN_LINT_RETRIES", 2):
        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="Find products for brand Heco",
            task_id="t01",
            idd_out=_make_idd(extracted_params={"brand": "Heco"}),
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
        )
    assert err.startswith("HARDCODED_PARAMS:"), f"Expected HARDCODED_PARAMS: prefix, got: {err!r}"
    assert result is not None, "Should return partial CodegenOutput for LEARN to inspect"
    assert result.script_code == _HARDCODED_SCRIPT


_CRASH_ON_MUTATED_SCRIPT = '''
import re, csv, io
from bitgn.vm.ecom.ecom_pb2 import ExecRequest

# This script uses a hardcoded dict lookup that crashes on SYNTHTOK input
_prices = {"Heco": 100, "Sony": 200}
brand_m = re.search(r"brand\s+(\S+)", task_text, re.I)
brand = brand_m.group(1) if brand_m else "Heco"
price = _prices[brand]  # KeyError when brand = "SYNTHTOK"

result = vm.exec(ExecRequest(path="/bin/sql", args=[f"SELECT * FROM products WHERE brand = '{brand}'"]))
rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
_result = {"message": f"Price: {price}", "outcome": "OUTCOME_OK", "refs": []}
if __name__ == "__main__":
    pass
'''

_CRASH_LLM_RESPONSE = f'{{"script": {repr(_CRASH_ON_MUTATED_SCRIPT)}, "test": {repr(_GOOD_TEST)}}}'


def test_run_codegen_dual_run_crash_returns_hardcoded_prefix():
    """Script passes AST hardcode check but crashes on mutated task_text → HARDCODED_PARAMS:."""
    import agent.pipeline as pipeline_mod
    with patch("agent.pipeline.call_llm_raw", return_value=_CRASH_LLM_RESPONSE), \
         patch.object(pipeline_mod, "_CODEGEN_LINT_RETRIES", 2):
        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="Get price for brand Heco",
            task_id="t01",
            idd_out=_make_idd(extracted_params={"brand": "Heco"}),
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
        )
    assert err.startswith("HARDCODED_PARAMS:"), f"Expected HARDCODED_PARAMS: prefix, got: {err!r}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_codegen.py::test_run_codegen_detects_hardcoded_params_returns_prefixed_error tests/test_codegen.py::test_run_codegen_dual_run_crash_returns_hardcoded_prefix -v
```

Expected: FAIL (no hardcode detection or prefix logic yet)

- [ ] **Step 3: Restructure `_run_codegen` in `agent/pipeline.py`**

Replace the entire `_run_codegen` function body (from the `lint_error: str | None = None` line through the `return CodegenOutput(...)` at the end):

```python
def _run_codegen(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    task_id: str,
    idd_out: "IddOutput",
    sdd_out: "SddOutput",
    plan_out: "PlanOutput",
    pre: "PrephaseResult",
    cycle: int,
    heuristic_hint: str = "",
) -> "tuple[CodegenOutput | None, str]":
    """CODEGEN phase: LLM generates heuristic script + mock test. Returns (CodegenOutput, error)."""
    codegen_model = _resolve_model_for_phase("codegen", model)
    codegen_guide = load_prompt("codegen") or "# PHASE: codegen"

    import json as _json

    user_parts = [
        f"TASK: {task_text}",
        f"TASK_ID: {task_id}",
        f"REFORMULATED_TASK: {idd_out.reformulated_task}",
        f"INTENT_TYPE: {idd_out.intent_type}",
    ]
    if idd_out.extracted_params:
        user_parts.append(f"EXTRACTED_PARAMS: {_json.dumps(idd_out.extracted_params)}")
    if idd_out.success_criteria:
        user_parts.append("SUCCESS_CRITERIA:\n" + "\n".join(f"  - {c}" for c in idd_out.success_criteria))
    user_parts.append(f"SDD_GOAL: {sdd_out.spec_goal}")
    user_parts.append(f"PLAN_ACTION: {plan_out.action}")
    if heuristic_hint:
        user_parts.append(heuristic_hint)
    user_msg = "\n\n".join(user_parts)

    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": codegen_guide, "cache_control": {"type": "ephemeral"}},
    ]

    lint_error: str | None = None
    script_code = ""
    test_code = ""
    _last_was_hardcoded = False
    _schema_str = pre.schema_digest if isinstance(pre.schema_digest, str) else str(pre.schema_digest)
    exec_globals_for_test: dict = {}

    for attempt in range(_CODEGEN_LINT_RETRIES):
        _last_was_hardcoded = False
        retry_msg = f"{user_msg}\n\nPREVIOUS_LINT_ERROR: {lint_error}\nFix and regenerate." if lint_error else user_msg

        tok_info: dict = {}
        raw = call_llm_raw(system, retry_msg, codegen_model, cfg,
                           max_tokens=_CODEGEN_MAX_TOKENS, token_out=tok_info)
        if not raw:
            lint_error = "LLM returned empty response"
            continue

        extracted = _extract_json_from_text(raw)
        if not isinstance(extracted, dict):
            lint_error = f"Could not parse JSON from LLM response: {raw[:200]}"
            continue

        script_code = extracted.get("script", "")
        test_code = extracted.get("test", "")

        # AST lint check
        lint_error = None
        for label, code in [("script", script_code), ("test", test_code)]:
            try:
                ast.parse(code)
            except SyntaxError as e:
                lint_error = f"{label} syntax error: {e}"
                break
        if lint_error:
            continue

        # AST hardcode detection
        hc_reason = _detect_hardcoded_params(script_code, task_text)
        if hc_reason:
            lint_error = (
                f"Hardcoded param detected: {hc_reason}. "
                f"Extract all task-specific values from the task_text variable using regex."
            )
            _last_was_hardcoded = True
            continue

        # Dual-run step 1: original task_text
        mock_vm_orig = MockVM(extracted_params=idd_out.extracted_params, schema_digest=_schema_str)
        _eg_orig: dict = {"vm": mock_vm_orig, "task_text": task_text, "_result": None}
        try:
            exec(compile(script_code, f"{task_id}.py", "exec"), _eg_orig)
        except Exception as e:
            lint_error = f"Script runtime error on original task_text: {e}"
            continue
        _raw_result = _eg_orig.get("_result")
        if not _raw_result or not isinstance(_raw_result, dict) \
                or "outcome" not in _raw_result or "message" not in _raw_result:
            lint_error = "Script did not set valid _result (needs outcome + message) on original task_text"
            continue

        # Dual-run step 2: mutated task_text (replaces 4+ char non-stopword tokens with SYNTHTOK)
        _mutated = re.sub(
            r"[A-Za-z0-9_-]{4,}",
            lambda m: "SYNTHTOK" if m.group(0).lower() not in _STOP_WORDS else m.group(0),
            task_text,
        )
        mock_vm_mut = MockVM(extracted_params={}, schema_digest=_schema_str)
        _eg_mut: dict = {"vm": mock_vm_mut, "task_text": _mutated, "_result": None}
        try:
            exec(compile(script_code, f"{task_id}_mut.py", "exec"), _eg_mut)
        except (KeyError, IndexError, AttributeError) as e:
            lint_error = (
                f"Script crashed on mutated task_text ({type(e).__name__}: {e}). "
                f"Script must not rely on hardcoded values from task_text."
            )
            _last_was_hardcoded = True
            continue
        except Exception:
            pass  # Non-hardcode crash — not a generality failure

        exec_globals_for_test = _eg_orig
        break  # All checks passed

    if lint_error:
        partial = CodegenOutput(script_path="", script_code=script_code, test_code=test_code) if script_code else None
        prefix = "HARDCODED_PARAMS:" if _last_was_hardcoded else ""
        return partial, f"{prefix}CODEGEN lint failed after {_CODEGEN_LINT_RETRIES} attempts: {lint_error}"

    # Mock test — run test_code using exec_globals with _result from original run
    try:
        exec(compile(test_code, f"{task_id}_test.py", "exec"), exec_globals_for_test)
    except Exception as e:
        return None, f"CODEGEN mock test failed: {e}"

    # Persist script
    heuristics_dir = Path("data/heuristics")
    heuristics_dir.mkdir(exist_ok=True)
    script_path = f"data/heuristics/{task_id}.py"
    (heuristics_dir / f"{task_id}.py").write_text(script_code, encoding="utf-8")
    (heuristics_dir / f"{task_id}_test.py").write_text(test_code, encoding="utf-8")

    return CodegenOutput(script_path=script_path, script_code=script_code, test_code=test_code), ""
```

- [ ] **Step 4: Run new tests to verify they pass**

```bash
uv run pytest tests/test_codegen.py::test_run_codegen_detects_hardcoded_params_returns_prefixed_error tests/test_codegen.py::test_run_codegen_dual_run_crash_returns_hardcoded_prefix -v
```

Expected: PASS

- [ ] **Step 5: Run all codegen tests to verify no regressions**

```bash
uv run pytest tests/test_codegen.py -v
```

Expected: all PASS. If `test_run_codegen_success` fails because Path is patched and the dual-run exec fails, update the test to use `tmp_path` for heuristics dir:

```python
def test_run_codegen_success(tmp_path):
    """LLM returns valid script+test → CodegenOutput written to data/heuristics/"""
    import agent.pipeline as pipeline_mod
    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)

    with patch("agent.pipeline.call_llm_raw", return_value=_GOOD_LLM_RESPONSE), \
         patch.object(pipeline_mod, "Path") as mock_path_cls:
        mock_path_cls.return_value = heur_dir
        mock_path_cls.side_effect = lambda p: tmp_path / p if "heuristics" in str(p) else Path(p)

        result, err = _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="How many orders?",
            task_id="t01",
            idd_out=_make_idd(),
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
        )

    assert err == "", f"Unexpected error: {err}"
    assert result is not None
    assert isinstance(result, CodegenOutput)
    assert result.script_path == "data/heuristics/t01.py"
    assert "OUTCOME_OK" in result.script_code
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline.py tests/test_codegen.py
git commit -m "feat(pipeline): add hardcode detection + dual-run MockVM validation to _run_codegen"
```

---

## Task 4: Handle `HARDCODED_PARAMS:` in `run_pipeline` + `ERROR_CATEGORY` in `_build_learn_user_msg`

**Files:**
- Modify: `agent/pipeline.py` — CODEGEN failure path + `_build_learn_user_msg`
- Modify: `tests/test_codegen.py` — add LEARN routing test
- Test: `tests/test_pipeline.py` — add ERROR_CATEGORY test

- [ ] **Step 1: Write failing tests**

```python
# In tests/test_pipeline.py — add at bottom:
def test_build_learn_user_msg_hardcoded_params_inserts_error_category():
    from agent.pipeline import _build_learn_user_msg
    msg = _build_learn_user_msg(
        task_text="Find products for brand Heco",
        error="HARDCODED_PARAMS:CODEGEN lint failed...",
        error_type="hardcoded_params",
        existing_entries=[],
    )
    assert "ERROR_CATEGORY" in msg
    assert "parsing" in msg.lower() or "parse" in msg.lower() or "PARSING" in msg


def test_build_learn_user_msg_semantic_no_error_category():
    from agent.pipeline import _build_learn_user_msg
    msg = _build_learn_user_msg(
        task_text="How many orders?",
        error="some semantic error",
        error_type="semantic",
        existing_entries=[],
    )
    assert "ERROR_CATEGORY" not in msg
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_pipeline.py::test_build_learn_user_msg_hardcoded_params_inserts_error_category tests/test_pipeline.py::test_build_learn_user_msg_semantic_no_error_category -v
```

Expected: FAIL — `ERROR_CATEGORY` not in msg

- [ ] **Step 3: Update `_build_learn_user_msg` in `agent/pipeline.py`**

In `_build_learn_user_msg`, add after the `parts = [...]` initial list (after `f"ERROR_TYPE: {error_type}"`):

```python
    if error_type == "hardcoded_params":
        parts.insert(1, "ERROR_CATEGORY: script hardcodes task-specific values instead of parsing from task_text — write a rule describing the PARSING PATTERN, not the SQL logic")
```

- [ ] **Step 4: Update CODEGEN failure path in `run_pipeline` in `agent/pipeline.py`**

Replace the CODEGEN failure block (lines ~858–867):

```python
            if codegen_error or codegen_out is None:
                err = codegen_error or "CODEGEN returned None"
                print(f"{CLI_YELLOW}[pipeline] CODEGEN failed: {err}{CLI_CLR}")
                last_error = err
                _learn_error_type = "hardcoded_params" if err.startswith("HARDCODED_PARAMS:") else "semantic"
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type=_learn_error_type, cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out,
                           heuristic_code=codegen_out.script_code if codegen_out else None)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_pipeline.py::test_build_learn_user_msg_hardcoded_params_inserts_error_category tests/test_pipeline.py::test_build_learn_user_msg_semantic_no_error_category -v
```

Expected: PASS

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): route HARDCODED_PARAMS: to error_type=hardcoded_params LEARN; add ERROR_CATEGORY to learn msg"
```

---

## Task 5: Add `schema_hash` to `save_last_run`

**Files:**
- Modify: `agent/prompt_assembler.py` — add `schema_hash` param
- Modify: `tests/test_prompt_assembler.py` — add schema_hash test

- [ ] **Step 1: Write failing test**

```python
# In tests/test_prompt_assembler.py — add at bottom:
def test_save_last_run_stores_schema_hash(tmp_path, monkeypatch):
    from agent import prompt_assembler
    monkeypatch.setattr(prompt_assembler, "_LEARNED_DIR", tmp_path)
    prompt_assembler.save_last_run(
        task_id="t99",
        status="success",
        outcome="OUTCOME_OK",
        cycles_used=1,
        heuristic_valid=True,
        schema_hash="abc12345",
    )
    import yaml
    data = yaml.safe_load((tmp_path / "t99.yaml").read_text())
    assert data["last_run"]["schema_hash"] == "abc12345"


def test_save_last_run_schema_hash_default_empty(tmp_path, monkeypatch):
    from agent import prompt_assembler
    monkeypatch.setattr(prompt_assembler, "_LEARNED_DIR", tmp_path)
    prompt_assembler.save_last_run("t99", "success", "OUTCOME_OK", 1)
    import yaml
    data = yaml.safe_load((tmp_path / "t99.yaml").read_text())
    assert data["last_run"]["schema_hash"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_prompt_assembler.py::test_save_last_run_stores_schema_hash tests/test_prompt_assembler.py::test_save_last_run_schema_hash_default_empty -v
```

Expected: FAIL — `TypeError: unexpected keyword argument 'schema_hash'`

- [ ] **Step 3: Add `schema_hash` param to `save_last_run` in `agent/prompt_assembler.py`**

Replace the function signature (line ~59) and add `schema_hash` to `data["last_run"]`:

```python
def save_last_run(
    task_id: str,
    status: str,
    outcome: str,
    cycles_used: int,
    grounding_refs_count: int = 0,
    heuristic_valid: bool = False,
    schema_hash: str = "",
) -> None:
    """Write last_run metadata to data/learned/{task_id}.yaml."""
    if not task_id:
        return
    from datetime import date
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    else:
        data = {}
    data["task_id"] = task_id
    data["last_run"] = {
        "status": status,
        "outcome": outcome,
        "cycles_used": cycles_used,
        "grounding_refs_count": grounding_refs_count,
        "heuristic_valid": heuristic_valid,
        "schema_hash": schema_hash,
        "date": str(date.today()),
    }
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_prompt_assembler.py::test_save_last_run_stores_schema_hash tests/test_prompt_assembler.py::test_save_last_run_schema_hash_default_empty -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add agent/prompt_assembler.py tests/test_prompt_assembler.py
git commit -m "feat(assembler): add schema_hash field to save_last_run"
```

---

## Task 6: Schema hash computation + fast path guard in `run_pipeline`

**Files:**
- Modify: `agent/pipeline.py` — schema hash in `run_pipeline`, extend fast path guard, update `save_last_run` calls
- Test: `tests/test_pipeline.py` — add schema hash mismatch test

- [ ] **Step 1: Write failing test**

```python
# In tests/test_pipeline.py — add at bottom:
import json as _json
import yaml as _yaml


def test_fast_path_skips_when_schema_hash_mismatch(tmp_path):
    """last_run.schema_hash differs from current schema_hash → fast path skipped, full path runs."""
    from unittest.mock import patch, MagicMock
    from agent.pipeline import run_pipeline
    from agent.prephase import PrephaseResult

    vm = MagicMock()
    pre = PrephaseResult(
        agents_md_content="AGENTS", agents_md_path="/AGENTS.MD",
        db_schema="CREATE TABLE orders(id INT)", task_type="sql",
        schema_digest={"orders": ["id INT", "status TEXT"]},
    )
    task_id = "t_schema_test"
    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)
    _script = '_result = {"message": "3", "outcome": "OUTCOME_OK", "refs": []}\nif __name__ == "__main__": pass\n'
    (heur_dir / f"{task_id}.py").write_text(_script)

    # Store a DIFFERENT schema_hash in last_run
    learned_dir = tmp_path / "data" / "learned"
    learned_dir.mkdir(parents=True)
    last_run_record = {
        "task_id": task_id,
        "last_run": {
            "status": "success", "outcome": "OUTCOME_OK", "cycles_used": 1,
            "grounding_refs_count": 0, "heuristic_valid": True, "schema_hash": "deadbeef",
            "date": "2026-05-28",
        },
        "entries": [],
    }
    (learned_dir / f"{task_id}.yaml").write_text(
        _yaml.dump(last_run_record, allow_unicode=True)
    )

    llm_calls: list[str] = []
    def _idd_resp(*a, **kw):
        llm_calls.append("called")
        return _json.dumps({
            "intent_objective": "x", "reformulated_task": "y", "intent_type": "read",
            "extracted_params": {}, "success_criteria": [], "stop_rules": [],
            "health_metrics": [], "decision": "hard_stop",
            "stop_code": "OUTCOME_NONE_CLARIFICATION",
            "stop_message": "schema changed, test", "stop_refs": [], "reasoning": "",
        })

    with patch("agent.pipeline.call_llm_raw", side_effect=_idd_resp), \
         patch("agent.pipeline.assemble_prompt") as mock_assemble, \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir), \
         patch("agent.pipeline.Path", side_effect=lambda p: heur_dir / Path(p).name if "heuristics" in str(p) else Path(p)):
        mock_assemble.return_value = type("AP", (), {"unified_context": "ctx"})()
        run_pipeline(
            vm=vm, model="anthropic/claude-sonnet-4-6",
            task_text="How many orders?", pre=pre, cfg={}, task_id=task_id,
        )

    # Full path ran (LLM called), fast path was skipped
    assert len(llm_calls) > 0, "Fast path should be skipped, full path should call LLM"
    vm.answer.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_pipeline.py::test_fast_path_skips_when_schema_hash_mismatch -v
```

Expected: FAIL — fast path still runs (LLM not called)

- [ ] **Step 3: Add schema hash computation and extended fast path guard to `run_pipeline`**

In `run_pipeline`, add schema hash computation before the fast path block (after `final_grounding_refs_count = 0`):

```python
    # ── SCHEMA HASH ───────────────────────────────────────────────────────────
    import hashlib as _hashlib
    _schema_src = str(pre.schema_digest) if pre.schema_digest else ""
    _current_schema_hash = _hashlib.md5(_schema_src.encode()).hexdigest()[:8]
```

Replace the fast path eligibility block (the `_fast_eligible = (...)` check):

```python
    if task_id:
        last_run_record = load_last_run(task_id)
        _heuristic_script = Path("data") / "heuristics" / f"{task_id}.py"
        _stored_schema_hash = (last_run_record or {}).get("schema_hash", "")
        _schema_hash_ok = (
            _stored_schema_hash == ""
            or _stored_schema_hash == _current_schema_hash
        )
        _fast_eligible = (
            last_run_record is not None
            and last_run_record.get("heuristic_valid") is True
            and _heuristic_script.exists()
            and _schema_hash_ok
        )
        if not _fast_eligible and last_run_record is not None \
                and last_run_record.get("heuristic_valid") is True \
                and _heuristic_script.exists() \
                and not _schema_hash_ok:
            last_error = f"schema changed since last heuristic ({_stored_schema_hash} → {_current_schema_hash})"
            print(f"{CLI_YELLOW}[pipeline] fast path skipped: schema changed{CLI_CLR}")
        if _fast_eligible:
            print(f"{CLI_BLUE}[pipeline] fast path: {task_id}{CLI_CLR}")
            _fp_ok, _fp_err, _fp_outcome = _run_fast_path(vm, task_id, task_text, schema_hash=_current_schema_hash)
            if _fp_ok:
                return {
                    "outcome": _fp_outcome,
                    "cycles_used": 0,
                    "grounding_refs_count": 0,
                    "step_facts": ["fast path: 0 LLM calls"],
                    "done_ops": [],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_elapsed_ms": 0,
                }, None
            last_error = _fp_err
            print(f"{CLI_YELLOW}[pipeline] fast path failed: {_fp_err} — falling through to full path{CLI_CLR}")
```

- [ ] **Step 4: Update `_run_fast_path` to accept and pass `schema_hash`**

Replace `_run_fast_path` signature and its success `save_last_run` call:

```python
def _run_fast_path(
    vm,
    task_id: str,
    task_text: str,
    schema_hash: str = "",
) -> "tuple[bool, str, str]":
    """Execute existing heuristic script. Returns (ok, error_string, outcome_str)."""
```

And replace the success `save_last_run` call (the one with `heuristic_valid=True`):

```python
    save_last_run(task_id, status="success", outcome=script_outcome,
                  cycles_used=0, heuristic_valid=True, schema_hash=schema_hash)
    return True, "", script_outcome
```

- [ ] **Step 5: Update `save_last_run` call at end of `run_pipeline` to pass `schema_hash`**

Replace the final `save_last_run` call (lines ~927–934):

```python
        save_last_run(
            task_id=task_id,
            status=last_run_status,
            outcome=outcome,
            cycles_used=cycles_used,
            grounding_refs_count=final_grounding_refs_count,
            heuristic_valid=success and outcome in _SUCCESSFUL_OUTCOMES,
            schema_hash=_current_schema_hash if (success and outcome in _SUCCESSFUL_OUTCOMES) else "",
        )
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_pipeline.py::test_fast_path_skips_when_schema_hash_mismatch -v
```

Expected: PASS

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass. Note: existing fast path tests in `tests/test_fast_path.py` that don't pass `schema_hash` in `last_run` YAML will have `_stored_schema_hash = ""`, which makes `_schema_hash_ok = True` (empty stored hash = always eligible). Those tests still pass.

- [ ] **Step 8: Commit**

```bash
git add agent/pipeline.py agent/prompt_assembler.py tests/test_pipeline.py
git commit -m "feat(pipeline): add schema_hash computation, fast path guard, and schema_hash persistence"
```

---

## Task 7: HEURISTIC_HINT injection in CODEGEN on schema change

**Files:**
- Modify: `agent/pipeline.py` — inject hint before calling `_run_codegen` when schema changed
- Test: `tests/test_codegen.py` — verify hint appears in LLM call

- [ ] **Step 1: Write failing test**

```python
# In tests/test_codegen.py — add at bottom:

def test_run_codegen_includes_heuristic_hint_when_provided():
    """When heuristic_hint is passed, it appears in the user message sent to LLM."""
    captured_user_msgs: list[str] = []

    def _capture_llm(system, user_msg, *a, **kw):
        captured_user_msgs.append(user_msg)
        return _GOOD_LLM_RESPONSE

    with patch("agent.pipeline.call_llm_raw", side_effect=_capture_llm), \
         patch("agent.pipeline.Path") as mock_path_cls:
        mock_dir = MagicMock()
        mock_path_cls.return_value = mock_dir
        mock_dir.__truediv__ = MagicMock(return_value=MagicMock())

        _run_codegen(
            unified_context="context",
            model="anthropic/claude-sonnet-4-6",
            cfg={},
            task_text="How many orders?",
            task_id="t01",
            idd_out=_make_idd(),
            sdd_out=_make_sdd(),
            plan_out=_make_plan(),
            pre=_make_pre(),
            cycle=1,
            heuristic_hint="HEURISTIC_HINT: data/heuristics/t01.py may be reusable.",
        )

    assert captured_user_msgs, "LLM should have been called"
    assert "HEURISTIC_HINT" in captured_user_msgs[0], "Hint must appear in first LLM call user message"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_codegen.py::test_run_codegen_includes_heuristic_hint_when_provided -v
```

Expected: FAIL — `_run_codegen` has no `heuristic_hint` parameter yet (Task 3 added it but this is testing the behavior end-to-end)

Note: if Task 3 was completed, the parameter already exists. Just verify the test passes.

- [ ] **Step 3: Wire `HEURISTIC_HINT` injection in `run_pipeline` before CODEGEN call**

In `run_pipeline`, in the cycle loop just before the `# ── CODEGEN` comment (before `_t0 = time.monotonic()`), add:

```python
            # Build HEURISTIC_HINT when schema changed (first cycle only)
            _heuristic_hint = ""
            if last_error.startswith("schema changed") and task_id:
                _h_path = Path("data") / "heuristics" / f"{task_id}.py"
                if _h_path.exists():
                    _heuristic_hint = (
                        f"HEURISTIC_HINT: data/heuristics/{task_id}.py may be reusable with updated schema.\n"
                        f"{last_error}. Review SQL/read calls for schema compatibility."
                    )
```

Then update the `_run_codegen(...)` call to include `heuristic_hint=_heuristic_hint`:

```python
            codegen_out, codegen_error = _run_codegen(
                unified_context=unified_context,
                model=model,
                cfg=cfg,
                task_text=task_text,
                task_id=task_id,
                idd_out=idd_out,
                sdd_out=sdd_out,
                plan_out=plan_out,
                pre=pre,
                cycle=cycle + 1,
                heuristic_hint=_heuristic_hint,
            )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_codegen.py::test_run_codegen_includes_heuristic_hint_when_provided -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_codegen.py
git commit -m "feat(pipeline): inject HEURISTIC_HINT into CODEGEN when schema changed"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered in task |
|---|---|
| §1.1 codegen.md mandatory block | Task 1 |
| §1.2 `_STOP_WORDS` + `_detect_hardcoded_params` + wire into retry | Task 2, Task 3 |
| §1.3 dual-run MockVM validation | Task 3 |
| §1.3 HARDCODED_PARAMS: prefix on all retries exhausted | Task 3 |
| §1.3 `run_pipeline` routes to `error_type="hardcoded_params"` | Task 4 |
| §2.1 schema hash computation | Task 6 |
| §2.2 `save_last_run` schema_hash param | Task 5 |
| §2.3 fast path guard with schema hash | Task 6 |
| §2.4 HEURISTIC_HINT injection | Task 7 |
| §3.1 `error_type="hardcoded_params"` in LEARN call | Task 4 |
| §3.2 ERROR_CATEGORY in `_build_learn_user_msg` | Task 4 |

**Placeholder scan:** None found — all steps contain concrete code.

**Type consistency:**
- `_run_codegen` return type: `tuple[CodegenOutput | None, str]` — on HARDCODED_PARAMS returns `(partial_CodegenOutput, "HARDCODED_PARAMS:...")` — callers already do `codegen_out.script_code if codegen_out else None`, consistent.
- `_run_fast_path` gets new `schema_hash: str = ""` param — existing callers that don't pass it use the default, backward-compatible.
- `save_last_run` gets new `schema_hash: str = ""` param — all existing callers (main.py, fast path failure calls) use the default `""`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-28-knowledge-lifecycle-pipeline-speed.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
