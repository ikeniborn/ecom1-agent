---
review:
  plan_hash: 0d255368dbfceb20
  spec_hash: 9526087f3a09f16c
  last_run: 2026-06-22
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      severity: WARNING
      phase: coverage
      section: "Task 2 — generic SQL record fallback"
      section_hash: 7135d595f01b33fc
      verdict: fixed
      text: "FIXED: generic SQL fallback added as resolve_record_path stage 3 (_sql_record_paths + _schema_tables_from); table names parsed from facts.schema, record_path LIKE token, SQL-safe-token guard — no per-task values. Spec §Design 'Record refs' now covered."
    - id: F-002
      severity: WARNING
      phase: coverage
      section: "Task 4 — relies-on doc filter"
      section_hash: 2901c7375ace3d57
      verdict: fixed
      text: "FIXED: canonical_doc_refs regains intent/answer params with a recall-preserving relies-on filter (narrow to signalled docs only when a signal exists, else keep all). Matches spec signature; no recall regression."
    - id: F-003
      severity: WARNING
      phase: verifiability
      section: "Task 5 Step 1"
      section_hash: ee6def555c485e40
      verdict: fixed
      text: "FIXED: test rewritten to throw via answer.message (consumed by ungated _proc_paths_in) so it really exercises the outer try/except; a second test covers the inner-guard vm-explosion path."
    - id: F-004
      severity: WARNING
      phase: verifiability
      section: "Task 10 Step 2"
      section_hash: e0c42b5930891138
      verdict: fixed
      text: "FIXED: wiki-ingest step gains a measurable DoD (test -f docs/wiki/grounding.md + git status diff on the four pages)."
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-22-phase1-deterministic-ref-grounding-design.md
---
# Phase 1 — Deterministic Ref-Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move grounding-ref production out of the LLM into a deterministic stage (`agent/grounding.py`) that re-derives every required `/proc/...` and `/docs/...` reference from the VM + task text + computed answer, then harden `verify.py` to enforce ref *presence* on all outcomes.

**Architecture:** A new best-effort `ground_refs(...)` runs in `pipeline.py` after `interpret` and before `verify`; it overwrites `answer.refs` with a VM-derived authoritative set (record refs via entity-token → `find`/evidence-scan → `stat`-validate; doc refs via investigator `docs_read` → canonical-case). `verify.py` I1 switches from OK-only count to presence-based on every outcome. The model's declared refs become hints; code produces the enforced set.

**Tech Stack:** Python 3, Pydantic v2 (`agent/ir_models.py`), pytest, `MockVMSpy` (`agent/mock_vm_spy.py`) for VM doubles, the kwargs VM surface (`agent/vm_adapter.py`).

**Branch:** Builds on `determinism` (Phase 0 already merged). Implement on a `dev/*` branch cut from `determinism`; PR back into `determinism` (NOT `master`).

---

## Background the executor MUST read first

You know nothing about this codebase. Read these before Task 1:

- `docs/superpowers/specs/2026-06-22-phase1-deterministic-ref-grounding-design.md` — the spec this plan implements.
- `agent/interpreter.py` lines 39–53 (`CapturedAnswer`, `InterpretResult`), 126–162 (`_project_required_refs`, `_resolve_authored_refs`), 360–390 (answer assembly + the OK-unresolved `_refuse`).
- `agent/verify.py` (whole file, 48 lines) — the gate you will harden.
- `agent/investigate.py` lines 175–195 (`_ground_doc_refs`, `_forced_doc_read`) and 287–365 (the `investigate` loop; note the two `_ground_doc_refs(...)` call sites).
- `agent/pipeline.py` lines 399–445 — the interpret→verify→answer block you will wire into.
- `agent/mock_vm_spy.py` (whole file) + `agent/vm_adapter.py` (whole file) — VM call surface. **All VM calls are kwargs-style**: `vm.find(root=..., name=..., limit=...)`, `vm.stat(path=...)`, `vm.read(path=...)`, `vm.exec(path=..., args=[...], stdin=...)`.

### Key facts that shape the design

1. **VM result shapes** (`proto/bitgn/vm/ecom/ecom.proto`): `FindResult.paths` = `repeated string` (a list of path strings, NOT `nodes`). `StatResult.path` = string (set on success; the real client raises on a missing path). `ReadResult.content` = string. `ExecResult.stdout` = string. `MockVMSpy._lookup` returns `_DEFAULT_STUB = {"stdout","stderr","content","entries","nodes","matches"}` (note: **no `path`, no `paths` key**) when no fixture matches — so an absent `Find` fixture yields `[]` paths and an absent `Stat` fixture yields a falsy `path` (treated as "does not exist"). Tests assert existence by registering `{"path": "..."}` / `{"paths": [...]}` fixtures.

2. **Record-path convention**: records live at `/proc/<table>/<ID>.json`, e.g. `/proc/catalog/STO-2R84BSHQ.json`, `/proc/catalog/SKU-FK.json` (see `tests/replay/fixtures_t47.py`).

3. **Entity-token shapes**: SKU/ID tokens like `STO-2R84BSHQ` (`[A-Z]{3}-[A-Z0-9]{8}`), `SKU-FK`; prefixed IDs like `basket_12`, `ord_45`, `cust_016`.

4. **`result.env["_facts"]`** holds the `PrePhaseFacts` object; `facts.identity` is a `dict` that may carry `customer_id` (see `agent/orchestrator.py:521-534`). The interpreter seeds `env["_facts"] = facts` (`interpreter.py:289-290`).

5. **`brief.env["docs_read"]`** does NOT exist yet — Task 6 creates it. It is separate from `result.env`, so Task 8 threads it into `ground_refs` as an explicit `docs_read=` argument (the spec's `env["docs_read"]` lives on the investigator brief, not the interpreter env).

6. **Interpreter is NOT touched** (confirmed by the spec's "Components touched" list). Its existing OK-unresolved `_refuse` (`interpreter.py:381`) coexists with grounding: the 11 target tasks have `required_refs=[]` for the chosen outcome (under-declared), so that refuse does not fire and `ground_refs` is free to add the missing refs.

### Design decisions (read before coding)

- **Record resolution = three generic stages, no per-task values:** (1) a free "evidence-scan" fast-path — regex `/proc/...json` over `result.sql_results` + `answer.message` + stringified `result.env` — catches the common case where the PLAN's SQL already returned `record_path` but the model failed to cite it; (2) `find`-by-id over `/proc`; (3) the spec's `/bin/sql select record_path` fallback, made generic — table names come from `facts.schema` (parsed by `_schema_tables_from`, not hard-coded) and the query is `record_path LIKE '%<token>%'`, gated by an SQL-safe-token guard. Each candidate is `stat`-validated. No per-task table/key map — table discovery is mechanism (`CLAUDE.md` "Prompt Engineering Rules" satisfied).
- **`canonical_doc_refs` is recall-preserving with a relies-on narrowing:** it derives doc refs from the `/docs/*.md` paths the investigator actually read (`docs_read`), `stat`-validated and case-corrected. When `intent`/`answer` are supplied it narrows to docs the answer relies on (basename stem in the message, or a declared `policy_doc`) — but ONLY if at least one read doc carries such a signal; with no signal it keeps every read doc (so a single relevant doc like `/docs/payments/3ds.md` is never dropped). The full outcome-policy-area mapping still lands in Phase 2; this is the Phase-1 approximation. Over-citation is further mitigated by `align_count` for count tasks.
- **Trace observability** is via `print(...)` (matching `pipeline.py`'s existing `CLI_YELLOW` prints), NOT a new structured trace event — avoids churning the versioned trace schema (`tests/test_trace_v2_schema.py`).
- **`verify.py` test rewrites**: the hardening changes I1 from OK-only-count to presence-based-all-outcomes. Two existing tests in `tests/test_verify.py` encode the old count semantics and are rewritten in Task 7 (spelled out in full).

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `agent/grounding.py` (new) | All deterministic ref re-derivation: `extract_entity_tokens`, `resolve_record_path`, `ownership_safe`, `canonical_doc_refs`, `align_count`, `ground_refs` + small VM-field helpers. Best-effort, never raises. | 1–5 |
| `agent/investigate.py` (modify) | Accumulate `/docs/*.md` reads into `brief.env["docs_read"]` via a new `_note_doc_read` helper at the two existing `_ground_doc_refs` call sites. | 6 |
| `agent/verify.py` (modify) | I1 hardening: presence-based required-ref check on all outcomes + `$`-ref guard on all outcomes. | 7 |
| `agent/pipeline.py` (modify) | Invoke `ground_refs` between `interpret` and `verify`, overwriting `result.captured.refs`; thread `brief.env["docs_read"]`. | 8 |
| `tests/test_grounding.py` (new) | Unit tests for every grounding helper. | 1–5 |
| `tests/test_investigate_doc_grounding.py` (modify) | Add `_note_doc_read` cases. | 6 |
| `tests/test_verify.py` (modify) | Rewrite I1 tests for presence-based semantics. | 7 |
| `tests/test_pipeline_grounding.py` (new) | Integration: a record/doc ref absent from the model's plan is grounded before verify. | 9 |

---

## Task 1: grounding module + `extract_entity_tokens`

**Files:**
- Create: `agent/grounding.py`
- Test: `tests/test_grounding.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_grounding.py`:

```python
from agent.grounding import extract_entity_tokens


def test_extracts_sku_dash_id_token():
    toks = extract_entity_tokens("Does STO-2R84BSHQ exist in the catalog?", "")
    assert "STO-2R84BSHQ" in toks


def test_extracts_short_sku_token():
    toks = extract_entity_tokens("check SKU-FK availability", "")
    assert "SKU-FK" in toks


def test_extracts_prefixed_entity_id():
    toks = extract_entity_tokens("refund basket_12 for cust_016", "")
    assert "basket_12" in toks
    assert "cust_016" in toks


def test_scans_both_task_text_and_message():
    toks = extract_entity_tokens("task mentions STO-2R84BSHQ", "answer cites SKU-FK")
    assert "STO-2R84BSHQ" in toks and "SKU-FK" in toks


def test_dedupes_and_preserves_order():
    toks = extract_entity_tokens("SKU-FK then SKU-FK again", "SKU-FK")
    assert toks.count("SKU-FK") == 1


def test_ignores_lowercase_schema_words():
    # 'record_path' / 'product_sku' are schema words, not entity ids — must NOT match.
    toks = extract_entity_tokens("select record_path, product_sku from product_variants", "")
    assert toks == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grounding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.grounding'`

- [ ] **Step 3: Write minimal implementation**

Create `agent/grounding.py`:

```python
"""Deterministic ref-grounding (0 LLM): re-derive required /proc and /docs refs from
the VM + task text + computed answer. Best-effort — ground_refs never raises; any single
resolution failure drops that one ref. The model's declared refs are hints; this module
produces the authoritative set that replaces answer.refs (the muxx exoskeleton pattern).
"""
from __future__ import annotations

import os
import re

# Entity-id / SKU shapes (STO-2R84BSHQ, SKU-FK). Mechanism, not per-task values.
_ID_RE = re.compile(r"\b[A-Z]{2,4}-[A-Z0-9]{2,12}\b")
# Prefixed ids (basket_12, ord_45, cust_016): an allowlist of entity prefixes keeps
# schema words (record_path, product_sku) out without per-task knowledge.
_PREFIXED_ID_RE = re.compile(
    r"\b(?:basket|order|ord|return|ret|payment|pay|invoice|inv|customer|cust|shipment|ship)"
    r"_[A-Za-z0-9]+\b",
    re.IGNORECASE,
)


def extract_entity_tokens(*texts: str) -> list[str]:
    """Entity IDs/SKUs found across the given texts (task text, answer message).
    Deterministic, order-preserving, deduped."""
    toks: list[str] = []
    for t in texts:
        for rx in (_ID_RE, _PREFIXED_ID_RE):
            for m in rx.findall(t or ""):
                if m not in toks:
                    toks.append(m)
    return toks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_grounding.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/grounding.py tests/test_grounding.py
git commit -m "feat(grounding): extract_entity_tokens for ref re-derivation"
```

---

## Task 2: VM-field helpers + `resolve_record_path`

**Files:**
- Modify: `agent/grounding.py`
- Test: `tests/test_grounding.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grounding.py`:

```python
from agent.grounding import resolve_record_path, _proc_paths_in
from agent.mock_vm_spy import MockVMSpy, fixture_key
from agent.interpreter import InterpretResult, CapturedAnswer


def _result(env=None, sql_results=None, message=""):
    return InterpretResult(
        captured=CapturedAnswer(message=message, outcome="OUTCOME_OK", refs=[]),
        env=env or {}, observations=[], sql_results=sql_results or [],
        mutation_landed=False, label="ok")


def test_resolve_via_find_then_stat():
    path = "/proc/catalog/STO-2R84BSHQ.json"
    vm = MockVMSpy(fixtures={
        fixture_key("Find", "/proc"): {"paths": [path]},
        fixture_key("Stat", path): {"path": path},
    })
    assert resolve_record_path(vm, "STO-2R84BSHQ", evidence_paths=[]) == path


def test_resolve_drops_token_with_no_stat_match():
    # find returns nothing, no evidence -> token does not resolve to a real path.
    vm = MockVMSpy(fixtures={})
    assert resolve_record_path(vm, "STO-NOPE", evidence_paths=[]) is None


def test_resolve_evidence_fastpath_when_stat_ok():
    path = "/proc/catalog/SKU-FK.json"
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})
    # path already present in evidence (SQL returned it) -> no find needed.
    assert resolve_record_path(vm, "SKU-FK", evidence_paths=[path]) == path


def test_resolve_evidence_path_dropped_when_stat_fails():
    path = "/proc/catalog/SKU-STALE.json"
    vm = MockVMSpy(fixtures={})   # no Stat fixture -> stub has no "path" -> not ok
    assert resolve_record_path(vm, "SKU-STALE", evidence_paths=[path]) is None


def test_proc_paths_scans_sql_results_and_env_and_message():
    res = _result(
        env={"rows": [{"record_path": "/proc/catalog/SKU-A.json"}]},
        sql_results=["product_sku,record_path\nSKU-B,/proc/catalog/SKU-B.json"],
        message="see /proc/catalog/SKU-C.json")
    found = _proc_paths_in(res, res.captured)
    assert set(found) == {
        "/proc/catalog/SKU-A.json",
        "/proc/catalog/SKU-B.json",
        "/proc/catalog/SKU-C.json",
    }


def test_resolve_via_sql_fallback_when_find_empty():
    # evidence + find both empty -> generic SQL fallback selects record_path from a
    # schema table by LIKE-token, then stat-validates.
    path = "/proc/catalog/STO-2R84BSHQ.json"
    sql = "SELECT record_path FROM catalog WHERE record_path LIKE '%STO-2R84BSHQ%' LIMIT 5"
    vm = MockVMSpy(fixtures={
        fixture_key("Exec", "/bin/sql", [sql]): {"stdout": f"record_path\n{path}"},
        fixture_key("Stat", path): {"path": path},
    })
    assert resolve_record_path(vm, "STO-2R84BSHQ", evidence_paths=[],
                               schema_tables=["catalog"]) == path


def test_resolve_sql_fallback_skips_unsafe_token():
    # a token with a space is not SQL-safe -> fallback is skipped (no injection), None.
    vm = MockVMSpy(fixtures={})
    assert resolve_record_path(vm, "bad token", evidence_paths=[],
                               schema_tables=["catalog"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grounding.py -k "resolve or proc_paths" -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_record_path'`

- [ ] **Step 3: Write minimal implementation**

Append to `agent/grounding.py`:

```python
_PROC_PATH_RE = re.compile(r"/proc/[A-Za-z0-9_./-]+?\.json")

_FIND_LIMIT = int(os.environ.get("ECOM_GROUND_FIND_LIMIT", "10"))


def _get(res, key, default=None):
    """Read a field from a proto message OR a dict RPC result."""
    if res is None:
        return default
    if isinstance(res, dict):
        return res.get(key, default)
    return getattr(res, key, default)


def _stat_ok(vm, path: str) -> bool:
    """True iff `path` resolves to a real node. The real client raises on a missing
    path; MockVMSpy's stub carries no `path` key. Both map to False."""
    try:
        res = vm.stat(path=path)
    except Exception:
        return False
    return bool(_get(res, "path", ""))


def _find_paths(vm, root: str, name: str) -> list[str]:
    """Find paths by name glob under `root` (FindResult.paths). Empty on any failure."""
    try:
        res = vm.find(root=root, name=name, limit=_FIND_LIMIT)
    except Exception:
        return []
    paths = _get(res, "paths", []) or []
    return [p for p in paths if isinstance(p, str)]


def _proc_paths_in(result, answer) -> list[str]:
    """Every distinct /proc/...json literal already present in the run's evidence:
    SQL stdouts, the answer message, and stringified env values (rowsets)."""
    blobs: list[str] = list(getattr(result, "sql_results", None) or [])
    blobs.append(getattr(answer, "message", "") or "")
    for v in (getattr(result, "env", None) or {}).values():
        blobs.append(v if isinstance(v, str) else str(v))
    out: list[str] = []
    for b in blobs:
        for m in _PROC_PATH_RE.findall(b or ""):
            if m not in out:
                out.append(m)
    return out


_SQL_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{2,40}$")
_SQL_TABLE_CAP = int(os.environ.get("ECOM_GROUND_SQL_TABLES", "12"))
# Table names from facts.schema — matches DDL ('CREATE TABLE name (') and digest
# ('name(col, ...)') shapes. Generic mechanism, no per-task table values.
_TABLE_NAME_RE = re.compile(
    r"(?im)(?:create\s+table\s+(?:if\s+not\s+exists\s+)?|^\s*)([a-z][a-z0-9_]+)\s*\(")


def _schema_tables_from(result) -> list[str]:
    """Table names parsed from facts.schema (result.env['_facts'].schema), deduped/capped.
    Empty when no schema is available — the SQL fallback then simply does nothing."""
    facts = (getattr(result, "env", None) or {}).get("_facts")
    schema = getattr(facts, "schema", "") if facts is not None else ""
    if not isinstance(schema, str) or not schema:
        return []
    out: list[str] = []
    for m in _TABLE_NAME_RE.findall(schema):
        if m not in out:
            out.append(m)
    return out[:_SQL_TABLE_CAP]


def _sql_record_paths(vm, token: str, tables: list[str]) -> list[str]:
    """Generic SQL fallback (spec §Design 'Record refs'): SELECT record_path from each
    schema table where the path carries the token. Mechanism only — no per-task table/key
    values. Skipped for a non-SQL-safe token (injection guard; entity tokens are
    alnum/-/_). Returns the /proc paths found (caller stat-validates)."""
    if not _SQL_SAFE_TOKEN_RE.match(token or ""):
        return []
    out: list[str] = []
    for t in tables or []:
        if not _SQL_SAFE_TOKEN_RE.match(t):
            continue
        sql = f"SELECT record_path FROM {t} WHERE record_path LIKE '%{token}%' LIMIT 5"
        try:
            res = vm.exec(path="/bin/sql", args=[], stdin=sql)
        except Exception:
            continue
        for m in _PROC_PATH_RE.findall(_get(res, "stdout", "") or ""):
            if m not in out:
                out.append(m)
    return out


def resolve_record_path(vm, token: str, evidence_paths: list[str],
                        schema_tables: "list[str] | None" = None) -> "str | None":
    """Resolve an entity token to a real /proc record path, else None.

    1. Evidence fast-path: a /proc path already returned by the run that names the
       token (0 new RPC), stat-validated.
    2. find-by-id over /proc, stat-validated.
    3. Generic SQL fallback over schema tables (record_path LIKE token), stat-validated.
    A candidate that does not stat to a real node is dropped (conservative)."""
    for p in evidence_paths:
        if token in p and _stat_ok(vm, p):
            return p
    for p in _find_paths(vm, "/proc", f"*{token}*"):
        if _stat_ok(vm, p):
            return p
    for p in _sql_record_paths(vm, token, schema_tables or []):
        if _stat_ok(vm, p):
            return p
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_grounding.py -v`
Expected: PASS (all Task 1 + Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/grounding.py tests/test_grounding.py
git commit -m "feat(grounding): resolve_record_path via evidence-scan + find + stat-validate"
```

---

## Task 3: `ownership_safe` guard

**Files:**
- Modify: `agent/grounding.py`
- Test: `tests/test_grounding.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grounding.py`:

```python
import json as _json
from agent.grounding import ownership_safe
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _vm_with_record(path, record):
    return MockVMSpy(fixtures={fixture_key("Read", path): {"content": _json.dumps(record)}})


def test_public_record_is_safe_for_customer():
    path = "/proc/catalog/SKU-FK.json"
    vm = _vm_with_record(path, {"sku": "SKU-FK"})   # no customer_id -> public
    assert ownership_safe(vm, path, {"customer_id": "cust_016"}) is True


def test_owned_record_is_safe():
    path = "/proc/baskets/basket_12.json"
    vm = _vm_with_record(path, {"customer_id": "cust_016"})
    assert ownership_safe(vm, path, {"customer_id": "cust_016"}) is True


def test_cross_customer_record_is_unsafe():
    path = "/proc/baskets/basket_99.json"
    vm = _vm_with_record(path, {"customer_id": "cust_777"})
    assert ownership_safe(vm, path, {"customer_id": "cust_016"}) is False


def test_non_customer_caller_never_blocked():
    # employee/admin identity (no customer_id) -> no cross-customer leak possible.
    path = "/proc/baskets/basket_99.json"
    vm = _vm_with_record(path, {"customer_id": "cust_777"})
    assert ownership_safe(vm, path, {"user": "emp_3"}) is True


def test_unreadable_record_dropped_for_customer():
    # customer caller, record cannot be read -> err toward dropping (conservative).
    vm = MockVMSpy(fixtures={})   # Read stub -> empty content -> unparseable
    assert ownership_safe(vm, "/proc/baskets/basket_x.json", {"customer_id": "cust_016"}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grounding.py -k ownership -v`
Expected: FAIL with `ImportError: cannot import name 'ownership_safe'`

- [ ] **Step 3: Write minimal implementation**

Append to `agent/grounding.py` (add `import json` to the top-of-file imports block, next to `import os`):

```python
def ownership_safe(vm, record_path: str, identity: dict) -> bool:
    """Phase-1 conservative ownership guard: never auto-cite a record owned by another
    customer. Cite only public (no owner) or owned records.

    - Non-customer caller (no customer_id): no cross-customer leak risk -> safe.
    - Customer caller: read the record; public or self-owned -> safe; another owner OR
      unreadable/unparseable -> drop (errs toward dropping a doubtful record ref).
    The full identity gate lands in Phase 2."""
    cust = ((identity or {}).get("customer_id") or "").strip()
    if not cust:
        return True
    try:
        content = _get(vm.read(path=record_path), "content", "") or ""
        record = json.loads(content)
    except Exception:
        return False
    owner = str((record or {}).get("customer_id", "")).strip()
    return owner == "" or owner == cust
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_grounding.py -k ownership -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add agent/grounding.py tests/test_grounding.py
git commit -m "feat(grounding): conservative cross-customer ownership guard"
```

---

## Task 4: `canonical_doc_refs`

**Files:**
- Modify: `agent/grounding.py`
- Test: `tests/test_grounding.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grounding.py`:

```python
from agent.grounding import canonical_doc_refs
from agent.mock_vm_spy import MockVMSpy, fixture_key


def test_keeps_existing_doc_path_as_is():
    path = "/docs/payments/3ds.md"
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})
    assert canonical_doc_refs([path], vm) == [path]


def test_case_corrects_via_find_basename():
    real = "/docs/Checkout.md"
    asked = "/docs/checkout.md"
    vm = MockVMSpy(fixtures={
        # asked path does not stat; find by basename returns the real-cased path.
        fixture_key("Find", "/docs"): {"paths": [real]},
    })
    assert canonical_doc_refs([asked], vm) == [real]


def test_drops_unresolvable_doc():
    vm = MockVMSpy(fixtures={})   # neither stat nor find resolves
    assert canonical_doc_refs(["/docs/ghost.md"], vm) == []


def test_dedupes_doc_refs():
    path = "/docs/security.md"
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})
    assert canonical_doc_refs([path, path], vm) == [path]


class _Ans:
    def __init__(self, message):
        self.message = message


def test_relies_on_filter_keeps_only_signalled_doc():
    a, b = "/docs/checkout.md", "/docs/returns.md"
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", a): {"path": a},
        fixture_key("Stat", b): {"path": b},
    })
    # 'checkout' stem appears in the message -> only that doc is relied on.
    out = canonical_doc_refs([a, b], vm, intent=None, answer=_Ans("the checkout policy blocks this"))
    assert out == [a]


def test_relies_on_keeps_all_when_no_signal():
    a, b = "/docs/checkout.md", "/docs/returns.md"
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", a): {"path": a},
        fixture_key("Stat", b): {"path": b},
    })
    # no doc stem in the message and no declared policy_doc -> recall-preserving: keep all.
    out = canonical_doc_refs([a, b], vm, intent=None, answer=_Ans("request cannot proceed"))
    assert out == [a, b]


def test_relies_on_policy_doc_signal_from_intent():
    from agent.ir_models import IntentSpec
    a, b = "/docs/checkout.md", "/docs/returns.md"
    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_NONE_UNSUPPORTED",
                        outcome_space=["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
                        constraints=[], success_criteria={}, answer_shape={},
                        required_refs={"OUTCOME_NONE_UNSUPPORTED": [
                            {"kind": "policy_doc", "path": a}]})
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", a): {"path": a},
        fixture_key("Stat", b): {"path": b},
    })
    out = canonical_doc_refs([a, b], vm, intent=intent, answer=_Ans("denied"))
    assert out == [a]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grounding.py -k canonical -v`
Expected: FAIL with `ImportError: cannot import name 'canonical_doc_refs'`

- [ ] **Step 3: Write minimal implementation**

Append to `agent/grounding.py`:

```python
def _canonical_doc_path(vm, path: str) -> "str | None":
    """The real-cased path for a /docs doc the investigator read, or None if it no
    longer resolves. Exact path that stats -> keep; else case-correct via find-by-basename."""
    if _stat_ok(vm, path):
        return path
    base = path.rsplit("/", 1)[-1]
    for cand in _find_paths(vm, "/docs", base):
        if cand.lower() == path.lower():
            return cand
    return None


def _doc_relied_on_signal(path: str, intent, answer) -> bool:
    """A positive 'the answer relies on this doc' signal: its basename stem appears in the
    answer message, OR it is a declared policy_doc in intent.required_refs (any outcome)."""
    stem = path.rsplit("/", 1)[-1]
    if stem.endswith(".md"):
        stem = stem[:-3]
    msg = (getattr(answer, "message", "") or "").lower()
    if stem and stem.lower() in msg:
        return True
    refs = getattr(intent, "required_refs", None) or {}
    for specs in refs.values():
        for r in specs:
            if getattr(r, "kind", "") == "policy_doc" and getattr(r, "path", None) == path:
                return True
    return False


def canonical_doc_refs(docs_read: list[str], vm, intent=None, answer=None) -> list[str]:
    """Doc refs derived from the /docs paths the investigator actually read. When an
    intent/answer is supplied, narrow to the docs the answer relies on (basename stem in
    the message, or a declared policy_doc) — but ONLY if at least one read doc carries such
    a signal; with no signal at all, keep every read doc (recall-preserving, since the
    investigator only reads docs it routed to as relevant for the objective). Each kept doc
    is stat-validated and case-corrected; unresolvable docs dropped. Deduped, ordered.
    intent/answer omitted -> no relies-on filter (keep all read docs)."""
    cands = [p for p in (docs_read or [])
             if isinstance(p, str) and p.startswith("/docs/") and p.endswith(".md")]
    if intent is not None or answer is not None:
        relied = [p for p in cands if _doc_relied_on_signal(p, intent, answer)]
        if relied:                       # narrow only when a signal exists; else keep all
            cands = relied
    out: list[str] = []
    for p in cands:
        c = _canonical_doc_path(vm, p)
        if c and c not in out:
            out.append(c)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_grounding.py -k "canonical or relies_on or doc_refs" -v`
Expected: PASS (4 canonical + 3 relies-on tests)

- [ ] **Step 5: Commit**

```bash
git add agent/grounding.py tests/test_grounding.py
git commit -m "feat(grounding): canonical_doc_refs from investigator docs_read"
```

---

## Task 5: `align_count` + `ground_refs` orchestration

**Files:**
- Modify: `agent/grounding.py`
- Test: `tests/test_grounding.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grounding.py`:

```python
from agent.grounding import align_count, ground_refs
from agent.ir_models import IntentSpec
from agent.mock_vm_spy import MockVMSpy, fixture_key
from agent.interpreter import InterpretResult, CapturedAnswer


def test_align_count_truncates_catalog_refs_to_leading_number():
    refs = ["/proc/catalog/A.json", "/proc/catalog/B.json", "/proc/catalog/C.json"]
    assert align_count(refs, "2 products are in stock") == refs[:2]


def test_align_count_noop_without_leading_number():
    refs = ["/proc/catalog/A.json", "/proc/catalog/B.json"]
    assert align_count(refs, "these products are in stock") == refs


def test_align_count_noop_when_not_all_catalog():
    refs = ["/proc/baskets/b.json", "/proc/catalog/A.json"]
    assert align_count(refs, "1 found") == refs


def _intent():
    return IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                      outcome_space=["OUTCOME_OK"], constraints=[],
                      success_criteria={}, answer_shape={}, required_refs={})


def _result(message, env=None, sql_results=None, refs=None):
    return InterpretResult(
        captured=CapturedAnswer(message=message, outcome="OUTCOME_OK", refs=refs or []),
        env=env or {}, observations=[], sql_results=sql_results or [],
        mutation_landed=False, label="ok")


def test_ground_refs_adds_record_ref_from_evidence():
    path = "/proc/catalog/STO-2R84BSHQ.json"
    res = _result(message="STO-2R84BSHQ exists",
                  sql_results=[f"sku,record_path\nSTO-2R84BSHQ,{path}"])
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})
    out = ground_refs(_intent(), res.captured, res, vm,
                      task_text="does STO-2R84BSHQ exist?", docs_read=[])
    assert path in out


def test_ground_refs_adds_doc_ref_from_docs_read():
    doc = "/docs/payments/3ds.md"
    res = _result(message="3DS required")
    vm = MockVMSpy(fixtures={fixture_key("Stat", doc): {"path": doc}})
    out = ground_refs(_intent(), res.captured, res, vm,
                      task_text="payment", docs_read=[doc])
    assert doc in out


def test_ground_refs_preserves_existing_enforced_refs_first():
    res = _result(message="ok", refs=["/docs/counting.md"])
    vm = MockVMSpy(fixtures={})
    out = ground_refs(_intent(), res.captured, res, vm, task_text="x", docs_read=[])
    assert out[0] == "/docs/counting.md"


def test_ground_refs_never_raises_returns_base_on_error():
    # Force a throw INSIDE ground_refs's try but OUTSIDE the inner per-RPC guards:
    # answer.message is consumed by _proc_paths_in / extract_entity_tokens (which are
    # NOT individually guarded), so a raising message exercises the OUTER try/except and
    # ground_refs returns the interpreter refs unchanged.
    res = _result(message="ok")

    class _BoomAnswer:
        refs = ["/docs/a.md"]

        @property
        def message(self):
            raise RuntimeError("message exploded")

    vm = MockVMSpy(fixtures={})
    out = ground_refs(_intent(), _BoomAnswer(), res, vm,
                      task_text="STO-ABCDEFGH", docs_read=[])
    assert out == ["/docs/a.md"]


def test_ground_refs_survives_vm_explosion_via_inner_guards():
    # Complementary path: a VM that raises on every call is swallowed by the inner
    # _find_paths/_stat_ok/ownership_safe guards (record + doc refs resolve to nothing),
    # so base is preserved without reaching the outer except.
    res = _result(message="ok", refs=["/docs/a.md"])

    class Boom:
        def __getattr__(self, _):
            raise RuntimeError("vm exploded")

    out = ground_refs(_intent(), res.captured, res, Boom(),
                      task_text="STO-ABCDEFGH", docs_read=["/docs/x.md"])
    assert out == ["/docs/a.md"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grounding.py -k "align_count or ground_refs" -v`
Expected: FAIL with `ImportError: cannot import name 'align_count'`

- [ ] **Step 3: Write minimal implementation**

Append to `agent/grounding.py`:

```python
_LEAD_NUM_RE = re.compile(r"\b(\d{1,4})\b")
_TOKEN_CAP = int(os.environ.get("ECOM_GROUND_TOKEN_CAP", "12"))
_RECORD_CAP = int(os.environ.get("ECOM_GROUND_RECORD_CAP", "10"))


def align_count(record_refs: list[str], message: str) -> list[str]:
    """Count-task mitigation: when every cited record is a /proc/catalog ref and the
    message leads with a count N < len(refs), cite exactly N (avoids the grader's
    over-citation penalty). Conservative — only truncates, never pads."""
    refs = list(record_refs)
    if not refs or any("/proc/catalog/" not in r for r in refs):
        return refs
    m = _LEAD_NUM_RE.search(message or "")
    if not m:
        return refs
    n = int(m.group(1))
    return refs[:n] if 1 <= n < len(refs) else refs


def _dedup(items: list[str]) -> list[str]:
    out: list[str] = []
    for x in items:
        if x and x not in out:
            out.append(x)
    return out


def _identity_from(result) -> dict:
    facts = (getattr(result, "env", None) or {}).get("_facts")
    if facts is None:
        return {}
    ident = getattr(facts, "identity", None)
    if ident is None and isinstance(facts, dict):
        ident = facts.get("identity")
    return ident or {}


def ground_refs(intent, answer, result, vm, task_text: str,
                docs_read: "list[str] | None" = None) -> list[str]:
    """Authoritative, VM-derived ref set that replaces answer.refs. Best-effort: any
    failure drops that one ref; a catastrophic failure returns the interpreter's refs
    unchanged. Merge order keeps enforced projections (already in answer.refs) first."""
    base = list(getattr(answer, "refs", None) or [])
    try:
        identity = _identity_from(result)
        schema_tables = _schema_tables_from(result)
        evidence = _proc_paths_in(result, answer)
        record_refs: list[str] = []
        for tok in extract_entity_tokens(task_text, getattr(answer, "message", ""))[:_TOKEN_CAP]:
            p = resolve_record_path(vm, tok, evidence, schema_tables)
            if p and p not in record_refs and ownership_safe(vm, p, identity):
                record_refs.append(p)
            if len(record_refs) >= _RECORD_CAP:
                break
        record_refs = align_count(record_refs, getattr(answer, "message", ""))
        doc_refs = canonical_doc_refs(docs_read or [], vm, intent=intent, answer=answer)
        merged = _dedup([*base, *record_refs, *doc_refs])
        if merged != base:
            print(f"[grounding] refs {base} -> {merged}")
        return merged
    except Exception as e:
        print(f"[grounding] skipped ({e}); keeping interpreter refs")
        return base
```

- [ ] **Step 4: Run the full grounding suite**

Run: `uv run pytest tests/test_grounding.py -v`
Expected: PASS (all Task 1–5 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/grounding.py tests/test_grounding.py
git commit -m "feat(grounding): ground_refs orchestration + align_count merge"
```

---

## Task 6: investigator accumulates `docs_read`

**Files:**
- Modify: `agent/investigate.py` (add `_note_doc_read`; call at the two `_ground_doc_refs` sites near lines 344 and 355)
- Test: `tests/test_investigate_doc_grounding.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_investigate_doc_grounding.py`:

```python
from agent.investigate import _note_doc_read


def test_note_doc_read_appends_md_path():
    env = {}
    _note_doc_read(env, "read", {"path": "/docs/payments/3ds.md"})
    assert env["docs_read"] == ["/docs/payments/3ds.md"]


def test_note_doc_read_dedupes():
    env = {"docs_read": ["/docs/a.md"]}
    _note_doc_read(env, "read", {"path": "/docs/a.md"})
    assert env["docs_read"] == ["/docs/a.md"]


def test_note_doc_read_ignores_non_docs_path():
    env = {}
    _note_doc_read(env, "read", {"path": "/proc/catalog/x.json"})
    assert "docs_read" not in env


def test_note_doc_read_ignores_non_read_tool():
    env = {}
    _note_doc_read(env, "list", {"path": "/docs/a.md"})
    assert "docs_read" not in env
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_investigate_doc_grounding.py -k note_doc_read -v`
Expected: FAIL with `ImportError: cannot import name '_note_doc_read'`

- [ ] **Step 3: Write minimal implementation**

In `agent/investigate.py`, add this function immediately after `_ground_doc_refs` (it ends at line ~185, just before `def _forced_doc_read`):

```python
def _note_doc_read(env: dict, tool: str, args: dict) -> None:
    """Record a /docs/*.md path the investigator actually read into env['docs_read']
    (deduped). Phase-1 grounding consumes this to auto-cite docs the answer relied on."""
    if (tool or "").lower() != "read":
        return
    path = args.get("path", "")
    if isinstance(path, str) and path.startswith("/docs/") and path.endswith(".md"):
        lst = env.setdefault("docs_read", [])
        if path not in lst:
            lst.append(path)
```

Then wire it at the two existing `_ground_doc_refs(...)` call sites in `investigate(...)`. The first is in the stalled-after-escalation branch:

```python
                        note, env_updates = digest(goal, tool, args, observation, escalate=True)
                        brief.notes.append(note); brief.env.update(env_updates)
                        _ground_doc_refs(brief.env, tool, args, req_refs)
                        _note_doc_read(brief.env, tool, args)
                        stop_reason = "budget"   # stalled even after escalation — gave up, not satisfied
                        break
```

The second is in the normal digest path:

```python
                brief.notes.append(note)
                brief.env.update(env_updates)
                _ground_doc_refs(brief.env, tool, args, req_refs)
                _note_doc_read(brief.env, tool, args)
                if sufficient(intent, brief.env):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_investigate_doc_grounding.py -v`
Expected: PASS (existing + 4 new)

- [ ] **Step 5: Run the investigate suite (regression)**

Run: `uv run pytest tests/test_investigate.py tests/test_investigate_merge.py tests/test_pipeline_investigate.py -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add agent/investigate.py tests/test_investigate_doc_grounding.py
git commit -m "feat(investigate): accumulate docs_read for Phase-1 grounding"
```

---

## Task 7: `verify.py` I1 hardening (presence-based, all outcomes)

**Files:**
- Modify: `agent/verify.py`
- Test: `tests/test_verify.py`

> **Why the existing tests change:** I1 moves from *OK-only, count-based* (`len(refs) < n_required`) to *presence-based on every outcome* (each **resolved** `required_refs[outcome]` value must be in `answer.refs`) + a `$`-ref guard on every outcome. The scenario "OK + a required record_path whose `$source` doesn't resolve" is already refused upstream by the interpreter (`interpreter.py:381`), so verify no longer needs to fail it — and must not (grounding may have supplied a concrete path). Two tests encoding the old semantics are rewritten below.

- [ ] **Step 1: Write the new/updated tests**

Edit `tests/test_verify.py`. Replace the body of `test_i1_ok_missing_a_required_ref_fails` (lines ~28–34) with a presence-based version, and append three new tests. The final state of these tests:

```python
def test_i1_ok_missing_a_required_policy_doc_fails():
    # required policy_doc resolves to a literal path; absent from refs -> fail.
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "policy_doc", "path": "/docs/counting.md"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]))
    ok, err = verify(res, intent)
    assert not ok and "/docs/counting.md" in err


def test_i1_required_ref_enforced_on_non_ok_outcome():
    # the t26 class: a denial must still cite its required policy doc.
    intent = _intent(required_refs={"OUTCOME_NONE_UNSUPPORTED": [
        {"kind": "policy_doc", "path": "/docs/checkout.md"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_NONE_UNSUPPORTED",
                                 refs=["/docs/security.md"]))
    ok, err = verify(res, intent)
    assert not ok and "/docs/checkout.md" in err


def test_i1_required_ref_present_on_non_ok_passes():
    intent = _intent(required_refs={"OUTCOME_NONE_UNSUPPORTED": [
        {"kind": "policy_doc", "path": "/docs/checkout.md"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_NONE_UNSUPPORTED",
                                 refs=["/docs/checkout.md"]))
    ok, err = verify(res, intent)
    assert ok, err


def test_i1_dollar_ref_guard_fires_on_non_ok():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_NONE_UNSUPPORTED",
                                 refs=["$unresolved"]))
    ok, err = verify(res, _intent())
    assert not ok and "ref" in err.lower()


def test_i1_unresolved_record_path_source_skipped_when_path_present():
    # required record_path whose $source isn't in env, but grounding put the literal
    # path in refs -> presence-based check skips the unresolved source and passes.
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$row.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK",
                                 refs=["/proc/catalog/A.json"]))
    ok, err = verify(res, intent)
    assert ok, err
```

Keep `test_i1_ok_with_unresolved_dollar_ref_fails`, `test_i1_ok_with_all_required_refs_passes`, and `test_i1_static_only_docs_ref_no_longer_auto_fails` as-is (they still pass under the new logic).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_verify.py -v`
Expected: FAIL — the new non-OK enforcement tests fail because current I1 only checks `OUTCOME_OK`.

- [ ] **Step 3: Write the implementation**

In `agent/verify.py`, add the import and replace the I1 block. New top of file:

```python
from .interpreter import InterpretResult, _project_required_refs
from .ir_models import IntentSpec
from .predicates import evaluate
```

Replace the current I1 block (lines 21–31, the `if ans.outcome == "OUTCOME_OK":` stanza) with:

```python
    # I1: ref-grounding — enforced on EVERY outcome (not just OK), presence-based
    # (not count). grounding.ground_refs has already overwritten ans.refs with the
    # authoritative VM-derived set before verify runs.
    unresolved = [r for r in ans.refs if isinstance(r, str) and r.startswith("$")]
    if unresolved:
        return False, f"I1: unresolved refs {unresolved!r} on {ans.outcome} answer"
    required_vals, _missing_src = _project_required_refs(intent, ans.outcome, env)
    absent = [v for v in required_vals if v not in ans.refs]
    if absent:
        return False, (f"I1: required ref(s) {absent!r} absent from "
                       f"{ans.outcome} answer")
```

Leave I2, I3, and the `success_criteria` block unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_verify.py -v`
Expected: PASS (all, including the 4 new tests)

- [ ] **Step 5: Commit**

```bash
git add agent/verify.py tests/test_verify.py
git commit -m "feat(verify): I1 presence-based ref enforcement on all outcomes"
```

---

## Task 8: wire `ground_refs` into the pipeline

**Files:**
- Modify: `agent/pipeline.py` (the interpret→verify block, lines ~431–433)
- Test: covered by Task 9 integration; this task adds the wiring only.

- [ ] **Step 1: Add the call between interpret and verify**

In `agent/pipeline.py`, locate this block (currently lines ~431–433):

```python
        log_gate_auto("INTERPRET", True, "")
        last_observed = result.observations
        ok, verr = verify(result, intent)
```

Replace it with:

```python
        log_gate_auto("INTERPRET", True, "")
        last_observed = result.observations
        # Phase 1: deterministic ref-grounding overwrites answer.refs with the
        # authoritative VM-derived set before VERIFY (best-effort, never raises).
        _docs_read = (brief.env.get("docs_read") if brief is not None else None) or []
        result.captured.refs = ground_refs(intent, result.captured, result, vm,
                                            instruction, docs_read=_docs_read)
        ok, verr = verify(result, intent)
```

- [ ] **Step 2: Add the import**

In `agent/pipeline.py`, the local-import block at the top of `run_pipeline` (lines ~283–285) currently reads:

```python
    from .interpreter import InterpretError, interpret, lint, repair_sql_stdin
    from .reason import IntentError, PlanEmptyError, PlanError, run_intent, run_plan
    from .verify import verify
```

Add `ground_refs`:

```python
    from .interpreter import InterpretError, interpret, lint, repair_sql_stdin
    from .reason import IntentError, PlanEmptyError, PlanError, run_intent, run_plan
    from .verify import verify
    from .grounding import ground_refs
```

- [ ] **Step 3: Run the pipeline regression suite**

Run: `uv run pytest tests/test_pipeline_interpreted.py tests/test_pipeline_investigate.py tests/test_pipeline_v2.py -v`
Expected: PASS (no regressions; `brief` is in scope at the call site — it is set to `None` or a `Brief` earlier in `run_pipeline`).

- [ ] **Step 4: Commit**

```bash
git add agent/pipeline.py
git commit -m "feat(pipeline): invoke ground_refs between interpret and verify"
```

---

## Task 9: integration test — absent ref gets grounded before verify

**Files:**
- Create: `tests/test_pipeline_grounding.py`

This test drives `ground_refs` + hardened `verify` together against a `MockVMSpy`, proving the unit pieces compose: an answer the interpreter produced with no record ref ends up citing the VM-resolved record path, and a non-OK answer missing a required doc fails verify until the doc is present.

- [ ] **Step 1: Write the test**

Create `tests/test_pipeline_grounding.py`:

```python
"""Phase 1 integration: ground_refs + hardened verify compose so a missing required
reference is re-derived from the VM before the answer is accepted."""
from agent.grounding import ground_refs
from agent.verify import verify
from agent.ir_models import IntentSpec
from agent.interpreter import InterpretResult, CapturedAnswer
from agent.mock_vm_spy import MockVMSpy, fixture_key


def _intent(required_refs=None, outcome_space=None):
    return IntentSpec(
        objective="o", desired_outcome="OUTCOME_OK",
        outcome_space=outcome_space or ["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
        constraints=[], success_criteria={}, answer_shape={},
        required_refs=required_refs or {})


def _result(captured, env=None, sql_results=None):
    return InterpretResult(captured=captured, env=env or {}, observations=[],
                           sql_results=sql_results or [], mutation_landed=False, label="ok")


def test_record_ref_grounded_from_evidence_then_verify_passes():
    path = "/proc/catalog/STO-2R84BSHQ.json"
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$missing"}]})  # source never binds
    cap = CapturedAnswer(message="STO-2R84BSHQ exists", outcome="OUTCOME_OK", refs=[])
    res = _result(cap, sql_results=[f"sku,record_path\nSTO-2R84BSHQ,{path}"])
    vm = MockVMSpy(fixtures={fixture_key("Stat", path): {"path": path}})

    res.captured.refs = ground_refs(intent, res.captured, res, vm,
                                    task_text="does STO-2R84BSHQ exist?", docs_read=[])
    assert path in res.captured.refs
    ok, err = verify(res, intent)
    assert ok, err


def test_doc_ref_grounded_from_docs_read_satisfies_non_ok_requirement():
    doc = "/docs/checkout.md"
    intent = _intent(required_refs={"OUTCOME_NONE_UNSUPPORTED": [
        {"kind": "policy_doc", "path": doc}]})
    cap = CapturedAnswer(message="cannot proceed", outcome="OUTCOME_NONE_UNSUPPORTED",
                         refs=[])
    res = _result(cap)
    vm = MockVMSpy(fixtures={fixture_key("Stat", doc): {"path": doc}})

    # before grounding: verify fails (required doc absent on a non-OK outcome)
    ok_before, _ = verify(res, intent)
    assert not ok_before

    res.captured.refs = ground_refs(intent, res.captured, res, vm,
                                    task_text="checkout", docs_read=[doc])
    assert doc in res.captured.refs
    ok_after, err = verify(res, intent)
    assert ok_after, err


def test_cross_customer_record_not_auto_cited():
    import json
    path = "/proc/baskets/basket_99.json"
    intent = _intent()
    cap = CapturedAnswer(message="basket_99 belongs to someone else",
                         outcome="OUTCOME_OK", refs=[])

    class _Facts:
        identity = {"customer_id": "cust_016"}

    res = _result(cap, env={"_facts": _Facts()})
    vm = MockVMSpy(fixtures={
        fixture_key("Stat", path): {"path": path},
        fixture_key("Read", path): {"content": json.dumps({"customer_id": "cust_777"})},
    })
    out = ground_refs(intent, res.captured, res, vm,
                      task_text="show basket_99", docs_read=[])
    assert path not in out
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_pipeline_grounding.py -v`
Expected: PASS (3 passed)

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_grounding.py
git commit -m "test(grounding): integration — grounded refs satisfy hardened verify"
```

---

## Task 10: full regression, docs, and lint

**Files:**
- Docs: `docs/wiki/` pages for `agent/grounding.py`, `agent/verify.py`, `agent/investigate.py`, `agent/pipeline.py`

- [ ] **Step 1: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS. Known pre-existing red: `test_t09_replay_matches_known_good` (stale parity fixture, per project memory) — confirm it is the ONLY failure and unrelated to this change. Any other new failure is a regression to fix before proceeding.

- [ ] **Step 2: Regenerate wiki pages for changed sources**

Run (one per changed source — these alter behavior, so `CLAUDE.md` mandates the doc update):

```bash
# via the iwiki skill, not a guessed CLI subcommand:
#   iwiki:iwiki-ingest agent/grounding.py
#   iwiki:iwiki-ingest agent/verify.py
#   iwiki:iwiki-ingest agent/investigate.py
#   iwiki:iwiki-ingest agent/pipeline.py
```

Invoke the `iwiki:iwiki-ingest` skill for each path above (the new `grounding.py` page documents the deterministic ref-grounding stage; the others get the Phase-1 deltas).

Verify each ingest produced/updated its page (measurable DoD):

```bash
test -f docs/wiki/grounding.md && echo "grounding page OK" || echo "MISSING"
git status --porcelain docs/wiki/ | grep -E 'grounding|verify|investigate|pipeline'
```
Expected: `docs/wiki/grounding.md` exists, and `git status` lists the four pages as added/modified (a non-empty diff confirms the ingest ran). An empty diff for a changed source means the ingest did not run — re-invoke before continuing.

- [ ] **Step 3: Lint the wiki**

Invoke the `/iwiki-lint` skill.
Expected: no broken `[[refs]]`, no orphan/stale pages introduced by the new `grounding` page.

- [ ] **Step 4: Update the architecture sections**

Edit `CLAUDE.md` (repo root) and `agent/CLAUDE.md`: in the per-task execution flow, note the new stage — "interpret → **ground_refs (deterministic, agent/grounding.py)** → verify". One sentence each; match surrounding style.

- [ ] **Step 5: Commit**

```bash
git add docs/wiki/ CLAUDE.md agent/CLAUDE.md
git commit -m "docs: Phase 1 deterministic ref-grounding (wiki + architecture)"
```

---

## Manual validation (after the suite is green)

The unit + integration tests prove the mechanism. Behavioral confirmation against the 11 motivating tasks requires a benchmark run (out of band, ~costly) — per the spec's "settle by subset measurement":

- Run the subset `{t13,t14,t15,t16,t26,t28,t41,t42,t45,t47,t50}` and confirm `missing required reference` disappears from `score_detail` (success criterion #1).
- Confirm currently-passing tasks do not regress, especially security denials (I1 now enforces required refs on non-OK outcomes) and count-type catalog tasks (`align_count` over-citation guard).

This is a measurement step, not a code step — record results in a run report; do not gate the merge on a full benchmark inside the plan.

---

## Self-Review

**Spec coverage:**
- `agent/grounding.py` with `ground_refs`, `extract_entity_tokens`, `resolve_record_path`, `canonical_doc_refs`, `ownership_safe` → Tasks 1–5. ✓ (`align_count` → Task 5.)
- Record refs: entity-token extraction + resolve (evidence + `find` + generic SQL fallback) + `stat`-validate + ownership guard → Tasks 1–3, 5. ✓ (SQL fallback per spec §Design "Record refs" → Task 2, `_sql_record_paths`/`_schema_tables_from`.)
- Doc refs from evidence: `env["docs_read"]` accumulation + `canonical_doc_refs` with recall-preserving relies-on filter → Tasks 4, 6. ✓
- Merge (union enforced projections, dedup, stable order) → Task 5 `ground_refs` (base refs first). ✓
- `verify.py` I1 hardening (all outcomes, presence-based, keep `$`-ref guard) → Task 7. ✓
- `pipeline.py` invoke between interpret and verify → Task 8. ✓
- Error handling (never raises; dropped/added refs logged) → Task 5 (`try/except` returns base; `print` logging). ✓
- Testing (unit, integration, regression) → Tasks 1–7 unit, Task 9 integration, Task 10 regression. ✓

**Placeholder scan:** every code step contains complete code; no TBD/TODO/"handle edge cases". ✓

**Type consistency:** `ground_refs(intent, answer, result, vm, task_text, docs_read=None)` used identically in Tasks 5, 8, 9. `resolve_record_path(vm, token, evidence_paths, schema_tables=None)` (Task 2 defines the optional `schema_tables`; Task 5 passes it; Tasks 2/9 omit it → default `None`), `ownership_safe(vm, record_path, identity)`, `canonical_doc_refs(docs_read, vm, intent=None, answer=None)` (Tasks 1–4 unit tests use the 2-arg form → keep-all; Task 5 passes `intent=`/`answer=`), `align_count(record_refs, message)`, `_sql_record_paths(vm, token, tables)`, `_schema_tables_from(result)`, `_get/_stat_ok/_find_paths/_proc_paths_in` signatures match across tasks. `_project_required_refs(intent, outcome, env) -> (vals, unresolved)` matches `interpreter.py`. `InterpretResult`/`CapturedAnswer` fields (`captured`, `env`, `sql_results`, `message`, `outcome`, `refs`) match `interpreter.py:39-53`. ✓
</content>
</invoke>
