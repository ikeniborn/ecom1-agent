---
review:
  spec_hash: "e8dd2408d0014152"
  last_run: "2026-05-28"
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "§1.3"
      section_hash: "7bbd78725b03440a"
      text: "Mutation algorithm now explicitly references _STOP_WORDS and regex from §1.2"
      verdict: fixed
      verdict_at: "2026-05-28"
chain:
  intent: docs/superpowers/intents/2026-05-28-knowledge-lifecycle-pipeline-speed-intent.md
---

# Design: Knowledge Lifecycle & Pipeline Speed

**Date:** 2026-05-28
**Status:** approved
**Intent:** docs/superpowers/intents/2026-05-28-knowledge-lifecycle-pipeline-speed-intent.md

## Problem

Two failures observed in testing:

1. **Stale heuristics**: A heuristic script solves the task on first run but fails on subsequent runs when task inputs or DB data change. Root cause: CODEGEN generates scripts that hardcode task-specific values (brand, model, SKU, etc.) directly into SQL instead of parsing them from `task_text` at runtime.

2. **Pipeline speed**: Full path (ASSEMBLE → IDD → SDD → PLAN → CODEGEN → ANSWER) runs 5 LLM calls/cycle. With 3 max cycles and LEARN retries, worst case exceeds 600s.

The fast path (0 LLM calls) is the solution to both problems: if heuristics are reliably generalized, fast path handles repeat runs. Full path is only needed for new tasks or schema changes.

## Approach: Generality Enforcement + Staleness Detection

### What changes

| Component | Change |
|-----------|--------|
| `data/prompts/codegen.md` | Add mandatory param-extraction rules + example pattern |
| `agent/pipeline.py` | AST hardcode detector; dual-run MockVM validation; schema_hash fast path guard; `error_type="hardcoded_params"` for LEARN |
| `agent/prompt_assembler.py` | Add `schema_hash` parameter to `save_last_run()`; include in `last_run` dict |

### What stays the same

- MockVM API, Protobuf/harness (`bitgn/`)
- Phase order: ASSEMBLE → IDD → SDD → PLAN → CODEGEN → ANSWER
- `data/learned/*.yaml` schema (only new fields added to `last_run`)
- `LearnOutput` model, `data/prompts/learn.md`

---

## Section 1: CODEGEN Generality

### 1.1 Prompt rule (`data/prompts/codegen.md`)

Add a mandatory block:

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

### 1.2 AST hardcode detector (`pipeline.py`)

After lint check in `_run_codegen`, before MockVM exec:

```python
_STOP_WORDS = frozenset({
    "from", "where", "select", "count", "inner", "join", "lower",
    "like", "true", "false", "none", "outcome", "message", "result",
    "python", "import", "return", "stdout", "strip", "items",
})

def _detect_hardcoded_params(script_code: str, task_text: str) -> str | None:
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

If triggered, append to `lint_error`:
```
Hardcoded param detected: {reason}. Extract all task-specific values from the task_text variable using regex.
```
This feeds into the existing retry loop (up to `CODEGEN_LINT_RETRIES`).

### 1.3 Dual-run MockVM validation

After AST check passes, run the script twice:

1. **Original** `task_text` — existing behavior
2. **Mutated** `task_text` — apply `re.sub(r"[A-Za-z0-9_-]{4,}", lambda m: "SYNTHTOK" if m.group(0).lower() not in _STOP_WORDS else m.group(0), task_text)` (same regex and `_STOP_WORDS` as §1.2)

Both runs use MockVM. Both must complete without exception — `_result` must be non-None with `outcome` and `message` fields. Any outcome code (including `OUTCOME_NONE_CLARIFICATION`) is acceptable; the check is for crashes, not for data presence. If the mutated run raises `KeyError`/`IndexError`/`AttributeError`, that indicates the script relied on hardcoded values and couldn't handle the synthetic input — add to `lint_error` and retry.

If all retries exhausted with dual-run failures: `_run_codegen` returns error string prefixed with `"HARDCODED_PARAMS:"`. In `run_pipeline`, when handling CODEGEN failure, check `codegen_error.startswith("HARDCODED_PARAMS:")` → call `_run_learn` with `error_type="hardcoded_params"` and `heuristic_code=script_code`, then continue to next cycle.

---

## Section 2: Staleness Detection

### 2.1 Schema hash computation

In `run_pipeline()`, before fast path check:

```python
import hashlib
_schema_src = str(pre.schema_digest) if pre.schema_digest else ""
_current_schema_hash = hashlib.md5(_schema_src.encode()).hexdigest()[:8]
```

### 2.2 `save_last_run` update (`prompt_assembler.py`)

Add `schema_hash: str = ""` parameter. Include in `last_run` dict:
```python
"schema_hash": schema_hash,
```

Call sites in `pipeline.py` pass `_current_schema_hash`.

### 2.3 Fast path guard

Extend eligibility check:

```python
_stored_schema_hash = last_run_record.get("schema_hash", "")
_fast_eligible = (
    last_run_record is not None
    and last_run_record.get("heuristic_valid") is True
    and _heuristic_script.exists()
    and (_stored_schema_hash == "" or _stored_schema_hash == _current_schema_hash)
)
```

If schema hash mismatches:
- Skip fast path without attempting execution
- Set `last_error = f"schema changed since last heuristic ({_stored_schema_hash} → {_current_schema_hash})"`
- Log: `[pipeline] fast path skipped: schema changed`
- Existing `heuristic_valid=False` write happens when full path completes

### 2.4 Heuristic hint on schema change

When full path runs after schema change, inject into CODEGEN `user_msg`:

```
HEURISTIC_HINT: data/heuristics/{task_id}.py may be reusable with updated schema.
Schema changed: {stored_hash} → {current_hash}. Review SQL/read calls for schema compatibility.
```

This lets CODEGEN adapt the existing script rather than regenerate from scratch. Only injected when `last_error` starts with `"schema changed"` and the heuristic file exists.

---

## Section 3: LEARN Improvement

### 3.1 New `error_type="hardcoded_params"`

Triggered from `_run_codegen` when all lint retries fail due to detected hardcoding.

### 3.2 `_build_learn_user_msg` addition

When `error_type == "hardcoded_params"`, insert before the ERROR field:

```python
parts.insert(1, "ERROR_CATEGORY: script hardcodes task-specific values instead of parsing from task_text — write a rule describing the PARSING PATTERN, not the SQL logic")
```

This signals LEARN to produce a regex/parsing rule rather than a domain logic rule.

### 3.3 Expected output

LEARN should emit rules like:
- `"always extract brand from task_text using re.search(r'brand[=:\\s]+(\\S+)', task_text, re.I)"`
- `"when task asks about product attributes, parse each attribute name and value from task_text before building SQL"`

These rules persist to `data/learned/{task_id}.yaml` and flow into `unified_context` for CODEGEN on the next cycle.

---

## Expected Outcomes

### Repeat run with changed task params (same schema)

```
fast path: schema_hash match → exec script
script parses task_text dynamically → correct SQL → success
LLM calls: 0
```

### Repeat run with schema change

```
fast path: schema_hash mismatch → skip
full path cycle 1: CODEGEN receives HEURISTIC_HINT → adapts existing script
  AST check: clean → dual-run: pass → save with new schema_hash → heuristic_valid=True
LLM calls: ~5 (1 cycle)
Estimated time: 150–250s
```

### New task, first run, script hardcodes values

```
Cycle 1: CODEGEN → AST detects hardcoded 'Heco' → retry
  All retries fail → LEARN(error_type="hardcoded_params") → rule: "parse brand via regex"
Cycle 2: unified_context has parsing rule → CODEGEN generates clean script
  AST: clean → dual-run: pass → heuristic_valid=True
LLM calls: ~11 (2 cycles + LEARN)
Estimated time: 250–400s
```

### New task, first run, CODEGEN gets it right (post-prompt fix)

```
Cycle 1: CODEGEN → prompt enforces parsing → AST clean → dual-run pass
  ANSWER: success → heuristic_valid=True + schema_hash stored
LLM calls: ~5
Estimated time: 150–250s
```

---

## Health Metrics (from intent)

- LEARN rule quality: rules now describe parsing patterns (verifiable by content inspection)
- CODEGEN quality: AST check + dual-run are objective gates
- MockVM compatibility: MockVM interface unchanged; dual-run uses same MockVM

## Constraints Met

- MockVM API: unchanged
- `bitgn/` / harness: untouched
- LEARN rules: readable (regex patterns are human-readable)
- Phase order: unchanged
- `data/learned/` format: backward-compatible (new `schema_hash` field in `last_run` only)
