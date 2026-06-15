---
review:
  plan_hash: bf3cc1be3f0ddcf8
  spec_hash: ea9e2096f04da0cd
  last_run: 2026-06-15
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: WARNING
      section: "File Structure"
      section_hash: 25be5438e6dde3c9
      text: "spec blast-radius table (S design §Blast radius) lists only production files; plan also modifies 8 test files and adds tests/replay/conftest.py:_required_refs_from_plan parity shim — necessary fallout of S2-R4 but undeclared in spec"
      verdict: fixed
      verdict_at: 2026-06-15
chain:
  intent: docs/superpowers/intents/2026-06-15-approach-a-prephase-grounding-intent.md
  spec: docs/superpowers/specs/2026-06-15-approach-a-prephase-grounding-design.md
---

# Approach A — Pre-phase Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the INTERPRETER pre-phase so it grounds a high-quality frozen INTENT on the first pass (docs discovered + read, policies enriched, every fact status-marked), and project `answer.refs` deterministically from `INTENT.required_refs` per-outcome so the grader never sees a missing/extra ref.

**Architecture:** Two slices. **Slice 1** rewrites the pre-phase fact gather in `orchestrator.py` (doc discovery via `TreeResponse.root` Entry-walk, entity-token Search enrichment of `policies`, `gather_status` signal, wider `target_records`, robust `/bin/id` parse) and folds those facts into the legacy DESIGN path for fair A/B. **Slice 2** replaces the flat `AnswerShape.required_ref_kinds` with `IntentSpec.required_refs: dict[outcome → list[RefSpec]]`; the interpreter projects `answer.refs` from the selected outcome's RefSpecs, and `verify` checks each required ref resolved non-empty.

**Tech Stack:** Python 3, pydantic v2 (`extra="forbid"` models + `model_validator`), pytest, `uv` runner. LLM via `agent/llm.py:call_llm_raw`. Protobuf stubs in `bitgn/` (ecom `TreeResponse.Entry{name,kind,content_type,children}`, `SearchResponse.Match{path,line,line_text}`).

**Autonomy note (from intent):** Every sub-step is **proposal-first**. Tasks that touch `data/prompts/`, the `ir_models` schema, or delete a `verify` heuristic are marked **HUMAN CHECKPOINT** — pause for approval before committing them. The final A/B benchmark cutover is **human-only**.

---

## File Structure

| File | Slice | Responsibility after change |
|------|-------|------------------------------|
| `agent/orchestrator.py` | 1 | `_discover_docs`, `_extract_entity_tokens`, `_parse_identity` (robust), `_search_paths`, `_proc_candidates`, `_doc_select_fallback`; rewritten `gather_prephase_facts`; `PrePhaseFacts.gather_status` |
| `agent/reason.py` | 1 | `_facts_block` surfaces `gather_status` |
| `agent/pipeline.py` | 1 | `_fold_facts_into_agents_md` — facts → legacy DESIGN agents_md (P7) |
| `agent/ir_models.py` | 2 | `RefSpec` model; `IntentSpec.required_refs`; drop `AnswerShape.required_ref_kinds` |
| `agent/interpreter.py` | 2 | `_project_required_refs`; ref-projection in answer assembly; refuse-invariant; remove `_resolve_refs` + old `required_ref_kinds` branch |
| `agent/verify.py` | 2 | I1 rewrite over `required_refs`; delete `/docs`-static heuristic |
| `data/prompts/intent.md` | 2 | declare `required_refs` per-outcome; structural-only `success_criteria`; IDD/SDD section |
| `data/prompts/plan.md` | 2 | drop PLAN-authored refs; read eligibility-rule from `facts.policies` |
| `tests/replay/conftest.py` | 2 | `run_plan` derives `required_refs` from golden plan (parity shim) |

**Test files touched:** `tests/test_orchestrator.py`, `tests/test_reason.py`, `tests/test_pipeline_interpreted.py`, `tests/test_ir_models.py`, `tests/test_interpreter.py`, `tests/test_verify.py`, `tests/test_reason_prompts.py`, `tests/replay/conftest.py`.

**Staging rationale:** `AnswerShape` uses `extra="forbid"`, so the moment `required_ref_kinds` is dropped, every `IntentSpec(..., answer_shape={"required_ref_kinds": ...})` raises `ValidationError`, and `interpreter.py:243` / `verify.py:26` raise `AttributeError`. To keep `uv run pytest` green after **every** commit, Slice 2 is ordered: **(9)** add `required_refs` additively → **(10)** interpreter reads `required_refs`, stops reading `required_ref_kinds` → **(11)** verify reads `required_refs`, stops reading `required_ref_kinds` → **(12)** now nothing reads the old field, drop it and scrub remaining test constructions.

---

## Slice 1 — pre-phase discovery + facts

### Task 1: `_discover_docs` — doc inventory via Entry-walk (S1-R1)

**Files:**
- Modify: `agent/orchestrator.py` (add helper near other `_discover_*`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
from types import SimpleNamespace as _NS

from agent.orchestrator import _discover_docs


def _entry(name, kind="file", children=None):
    # Mirrors ecom TreeResponse.Entry{name, kind, content_type, children}.
    return _NS(name=name, kind=kind, content_type="", children=children or [])


def test_discover_docs_walks_entry_tree_not_stdout():
    root = _entry("docs", kind="dir", children=[
        _entry("security.md"),
        _entry("catalogue", kind="dir", children=[
            _entry("counting.md"),
            _entry("addenda.md"),
        ]),
    ])
    vm = MagicMock()
    # .stdout intentionally set: _discover_docs must IGNORE it (proto has no stdout).
    vm.tree.return_value = _NS(root=root, stdout="SHOULD_BE_IGNORED")
    paths = _discover_docs(vm)
    assert paths == [
        "/docs/security.md",
        "/docs/catalogue/counting.md",
        "/docs/catalogue/addenda.md",
    ]


def test_discover_docs_empty_on_tree_exception():
    vm = MagicMock()
    vm.tree.side_effect = RuntimeError("boom")
    assert _discover_docs(vm) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py::test_discover_docs_walks_entry_tree_not_stdout -v`
Expected: FAIL with `ImportError: cannot import name '_discover_docs'`.

- [ ] **Step 3: Write minimal implementation**

Add to `agent/orchestrator.py` (after `_discover_sample_rows`):

```python
def _entry_children(node) -> list:
    ch = getattr(node, "children", None)
    if ch is None and isinstance(node, dict):
        ch = node.get("children")
    return list(ch or [])


def _entry_name(node) -> str:
    name = getattr(node, "name", None)
    if name is None and isinstance(node, dict):
        name = node.get("name")
    return (name or "").strip("/")


def _discover_docs(vm, root_path: str = "/docs") -> list[str]:
    """Absolute file paths under `root_path`, walked from `TreeResponse.root`.

    Uses the ecom Entry tree (`name`/`kind`/`children`), NOT `tree.stdout`
    (absent in proto) and NOT `Find(kind=...)` (int32 mismatch yields empty).
    A node with no children is a leaf file; a node with children is a dir.
    """
    try:
        resp = vm.tree(root=root_path, level=0)
    except Exception:
        return []
    root = getattr(resp, "root", None)
    if root is None and isinstance(resp, dict):
        root = resp.get("root")
    if root is None:
        return []

    out: list[str] = []

    def _walk(node, prefix: str) -> None:
        children = _entry_children(node)
        if not children:
            out.append(prefix)
            return
        for ch in children:
            _walk(ch, prefix.rstrip("/") + "/" + _entry_name(ch))

    _walk(root, root_path)
    return [p for p in out if p != root_path]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -k discover_docs -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): _discover_docs walks Entry tree, not tree.stdout (S1-R1)"
```

---

### Task 2: `_extract_entity_tokens` — deterministic token extraction (S1-R2)

**Files:**
- Modify: `agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
from agent.orchestrator import _extract_entity_tokens


def test_extract_entity_tokens_quoted_and_capitalized():
    instr = 'How many "Tool Box and Bag" products are Non-Bladed Workshop items?'
    toks = _extract_entity_tokens(instr)
    assert "Tool Box and Bag" in toks          # quoted literal
    assert "Non" not in toks                    # single cap word excluded
    assert any(t.startswith("Non-Bladed") or "Bladed Workshop" in t for t in toks)


def test_extract_entity_tokens_dedupes_and_handles_empty():
    assert _extract_entity_tokens("") == []
    toks = _extract_entity_tokens('"Alpha" then "Alpha" again')
    assert toks.count("Alpha") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -k extract_entity_tokens -v`
Expected: FAIL with `ImportError: cannot import name '_extract_entity_tokens'`.

- [ ] **Step 3: Write minimal implementation**

Add to `agent/orchestrator.py` (near the module-level regexes, after `_RECORD_ID_RE`):

```python
_QUOTED_RE = re.compile(r'"([^"]+)"')
# Two or more Capitalized words in a row (hyphens kept: "Non-Bladed Workshop").
_CAP_SEQ_RE = re.compile(r"\b([A-Z][\w-]*(?:\s+[A-Z][\w-]*)+)\b")


def _extract_entity_tokens(instruction: str) -> list[str]:
    """Quoted strings + Capitalized n-grams (length >= 2) from the instruction.

    Deterministic (0 LLM). Each token becomes one Search pattern in S1-R3.
    """
    text = instruction or ""
    toks: list[str] = []
    for m in _QUOTED_RE.findall(text):
        t = m.strip()
        if t and t not in toks:
            toks.append(t)
    for m in _CAP_SEQ_RE.findall(text):
        t = m.strip()
        if t and t not in toks:
            toks.append(t)
    return toks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -k extract_entity_tokens -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): _extract_entity_tokens (quoted + Capitalized n-grams) (S1-R2)"
```

---

### Task 3: `_parse_identity` — robust `/bin/id` parse (S1-R7, P4)

**Files:**
- Modify: `agent/orchestrator.py` (replace existing `_parse_identity` + `_ID_RE`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
from agent.orchestrator import _parse_identity


def test_parse_identity_tolerant_to_commas_and_whitespace():
    d = _parse_identity("uid=42(emp_42)   role=employee,  store_id=S001")
    assert d["uid"] == "42(emp_42)"
    assert d["role"] == "employee"
    assert d["store_id"] == "S001"


def test_parse_identity_empty_on_blank():
    assert _parse_identity("") == {}
    assert _parse_identity("   ") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -k parse_identity -v`
Expected: FAIL — current parser drops `store_id` when separated by a comma (`[^\s]+` swallows the comma into the prior value, or order/whitespace variants break).

- [ ] **Step 3: Write minimal implementation**

Replace `_ID_RE` and `_parse_identity` in `agent/orchestrator.py`:

```python
_ID_SPLIT_RE = re.compile(r"[\s,]+")


def _parse_identity(stdout: str) -> dict:
    """Parse `/bin/id` into key=value pairs, tolerant to whitespace/commas/order.

    Empty result ONLY when stdout is genuinely blank — recorded as empty/error
    in gather_status by the caller, never a silent {}.
    """
    out: dict = {}
    for tok in _ID_SPLIT_RE.split((stdout or "").strip()):
        if "=" in tok:
            k, _, v = tok.partition("=")
            k, v = k.strip(), v.strip()
            if k:
                out[k] = v
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -k parse_identity -v`
Expected: PASS.

- [ ] **Step 5: Run the existing orchestrator suite (regression)**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS (existing `test_gather_prephase_facts_collects_identity_and_target_record` still green — `emp_42` still parsed).

- [ ] **Step 6: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "fix(prephase): robust /bin/id parse, tolerant to whitespace/commas/order (S1-R7)"
```

---

### Task 4: Search-path + proc-candidate helpers (S1-R3, S1-R6 support)

**Files:**
- Modify: `agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
from agent.orchestrator import _search_paths, _proc_candidates


def test_search_paths_unique_ordered_from_matches():
    resp = _NS(matches=[
        _NS(path="/docs/a.md", line=1, line_text="x"),
        _NS(path="/docs/b.md", line=2, line_text="y"),
        _NS(path="/docs/a.md", line=9, line_text="z"),   # dup path dropped
    ])
    assert _search_paths(resp) == ["/docs/a.md", "/docs/b.md"]


def test_search_paths_empty_on_no_matches():
    assert _search_paths(_NS(matches=[])) == []
    assert _search_paths({"matches": []}) == []


def test_proc_candidates_maps_prefix_to_plural_dir():
    assert _proc_candidates("store_S001") == ["/proc/stores/store_S001.json"]
    assert _proc_candidates("basket_069") == ["/proc/baskets/basket_069.json"]
    assert _proc_candidates("unknown_xx") == []   # unmapped prefix -> no probe
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -k "search_paths or proc_candidates" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write minimal implementation**

In `agent/orchestrator.py`, replace `_RECORD_ID_RE` and add helpers:

```python
# P3 (S1-R6): widen record discovery beyond baskets/payments.
_RECORD_ID_RE = re.compile(
    r"\b(basket|payment|return|order|store|employee|product)_\w+\b", re.IGNORECASE
)
_PROC_DIR = {
    "basket": "baskets", "payment": "payments", "return": "returns",
    "order": "orders", "store": "stores", "employee": "employees",
    "product": "products",
}


def _search_paths(resp) -> list[str]:
    """SearchResponse.matches[*].path -> ordered unique list (proto or dict)."""
    matches = getattr(resp, "matches", None)
    if matches is None and isinstance(resp, dict):
        matches = resp.get("matches")
    out: list[str] = []
    for m in matches or []:
        p = getattr(m, "path", None)
        if p is None and isinstance(m, dict):
            p = m.get("path")
        if p and p not in out:
            out.append(p)
    return out


def _proc_candidates(record_id: str) -> list[str]:
    """Map `<prefix>_<id>` to its `/proc/<plural>/<id>.json` probe path(s)."""
    prefix = record_id.split("_", 1)[0].lower()
    plural = _PROC_DIR.get(prefix)
    return [f"/proc/{plural}/{record_id}.json"] if plural else []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -k "search_paths or proc_candidates" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): _search_paths + _proc_candidates (wider records) (S1-R3/R6)"
```

---

### Task 5: Rewrite `gather_prephase_facts` — wire discovery + policies + gather_status (S1-R3, R5, R6)

**Files:**
- Modify: `agent/orchestrator.py` (`PrePhaseFacts` + `gather_prephase_facts`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_gather_prephase_facts_search_enriches_policies_and_marks_status():
    # docs tree -> inventory; Search by entity token -> doc path -> Read content.
    root = _entry("docs", kind="dir", children=[
        _entry("security.md"),
        _entry("widget-counting.md"),
    ])

    def _tree(**kw):
        return _NS(root=root)

    def _search(**kw):
        if kw.get("pattern") == "Widget Counting":
            return _NS(matches=[_NS(path="/docs/widget-counting.md", line=1, line_text="rule")])
        return _NS(matches=[])

    def _read(**kw):
        return {"content": f"CONTENT OF {kw.get('path')}"}

    def _exec(**kw):
        if kw.get("path") == "/bin/id":
            return {"stdout": "uid=7(emp_7) role=employee"}
        return {"stdout": "name\nstores"}

    vm = MagicMock()
    vm.tree.side_effect = _tree
    vm.search.side_effect = _search
    vm.read.side_effect = _read
    vm.exec.side_effect = _exec

    facts = gather_prephase_facts(
        vm, instruction='count "Widget Counting" items', agents_md_text="RULES"
    )
    assert "/docs/widget-counting.md" in facts.docs_inventory
    assert facts.policies.get("/docs/widget-counting.md", "").startswith("CONTENT OF")
    assert facts.gather_status["docs_inventory"] == "ok"
    assert facts.gather_status["policies"] == "ok"
    assert facts.gather_status["identity"] == "ok"


def test_gather_prephase_facts_caps_doc_content():
    big = "x" * 9000
    root = _entry("docs", kind="dir", children=[_entry("big.md")])
    vm = MagicMock()
    vm.tree.return_value = _NS(root=root)
    vm.search.return_value = _NS(matches=[_NS(path="/docs/big.md", line=1, line_text="m")])
    vm.read.return_value = {"content": big}
    vm.exec.return_value = {"stdout": ""}
    facts = gather_prephase_facts(vm, instruction='see "Big Doc Here"', agents_md_text="")
    assert len(facts.policies["/docs/big.md"]) <= 4096
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -k "search_enriches or caps_doc" -v`
Expected: FAIL — `PrePhaseFacts` has no `gather_status`; policies are not Search-enriched.

- [ ] **Step 3: Write the implementation**

In `agent/orchestrator.py`, add the field to `PrePhaseFacts`:

```python
class PrePhaseFacts(BaseModel):
    agents_md: str = ""
    schema: str = ""
    sample_rows: str = ""
    docs_inventory: str = ""
    policies: dict[str, str] = {}
    identity: dict = {}
    target_records: dict[str, str] = {}
    gather_status: dict[str, str] = {}   # fact -> ok|empty|error(<msg>)
```

Add caps near the other module constants:

```python
_DOC_HITS_PER_TOKEN = 3
_DOC_CONTENT_CAP = 4096
```

Replace the body of `gather_prephase_facts` with:

```python
def gather_prephase_facts(vm, instruction: str, agents_md_text: str) -> PrePhaseFacts:
    status: dict[str, str] = {}

    def _mark(key: str, value, err: str = "") -> None:
        if err:
            status[key] = f"error({err})"
        elif value:
            status[key] = "ok"
        else:
            status[key] = "empty"

    # schema + sample rows (unchanged discovery)
    schema = _discover_schema(vm)
    _mark("schema", schema)
    tables = _discover_table_names(vm) if schema else []
    samples = _discover_sample_rows(vm, tables) if tables else ""
    _mark("sample_rows", samples)

    # identity (P4 robust parse)
    try:
        id_out = _sql_stdout_or_exec(vm, "/bin/id")
        identity = _parse_identity(id_out)
        _mark("identity", identity)
    except Exception as e:                       # pragma: no cover - defensive
        identity, _ = {}, _mark("identity", None, str(e))

    # doc inventory (S1-R1)
    try:
        doc_paths = _discover_docs(vm)
        docs_inventory = "\n".join(doc_paths)
        _mark("docs_inventory", docs_inventory)
    except Exception as e:                       # pragma: no cover - defensive
        doc_paths, docs_inventory = [], ""
        _mark("docs_inventory", None, str(e))

    # policies: security.md + path-named docs (existing behaviour)
    policies: dict[str, str] = {}
    wanted = ["/docs/security.md"]
    for name in re.findall(r"/docs/[\w/.-]+\.md", (instruction or "") + " " + (agents_md_text or "")):
        if name not in wanted:
            wanted.append(name)
    for path in wanted[:_POLICY_CAP]:
        try:
            txt = _extract_text(vm.read(path=path), "content")
            if txt:
                policies[path] = txt[:_DOC_CONTENT_CAP]
        except Exception:
            continue

    # policies enrichment via entity-token Search (S1-R3)
    tokens = _extract_entity_tokens(instruction)
    search_hit = False
    search_err = ""
    for tok in tokens:
        try:
            hits = _search_paths(vm.search(root="/docs", pattern=tok, limit=30))
        except Exception as e:
            search_err = str(e)
            continue
        if hits:
            search_hit = True
        for p in hits[:_DOC_HITS_PER_TOKEN]:
            if p in policies:
                continue
            try:
                txt = _extract_text(vm.read(path=p), "content")
                if txt:
                    policies[p] = txt[:_DOC_CONTENT_CAP]
            except Exception:
                continue
    _mark("policies", policies, search_err if (not policies and search_err) else "")

    # LLM DOC-SELECT fallback (S1-R4) — only when Search found nothing.
    if not search_hit and tokens and doc_paths:
        picked = _doc_select_fallback(doc_paths, instruction, tokens)
        for p in picked:
            if p in policies:
                continue
            try:
                txt = _extract_text(vm.read(path=p), "content")
                if txt:
                    policies[p] = txt[:_DOC_CONTENT_CAP]
            except Exception:
                continue
        if picked:
            status["policies"] = "ok"

    # target_records (P3 wider — S1-R6)
    target_records: dict[str, str] = {}
    seen_ids: list[str] = []
    for m in _RECORD_ID_RE.finditer(instruction or ""):
        full = m.group(0)
        if full in seen_ids:
            continue
        seen_ids.append(full)
        if len(seen_ids) > _RECORD_CAP:
            break
        for proc in _proc_candidates(full):
            try:
                txt = _extract_text(vm.read(path=proc), "content")
                if txt:
                    target_records[proc] = txt
                    break
            except Exception:
                continue
    _mark("target_records", target_records)

    return PrePhaseFacts(
        agents_md=agents_md_text, schema=schema, sample_rows=samples,
        docs_inventory=docs_inventory, policies=policies, identity=identity,
        target_records=target_records, gather_status=status,
    )
```

Note: this references `_doc_select_fallback`, added in Task 6. Until then, define a temporary stub at module scope so this task's tests pass in isolation:

```python
def _doc_select_fallback(doc_paths: list[str], instruction: str, tokens: list[str]) -> list[str]:
    return []   # replaced with a real LLM call in Task 6
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS (new tests + the legacy `test_gather_prephase_facts_collects_identity_and_target_record`).

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): Search-enriched policies + gather_status + wider records (S1-R3/R5/R6)"
```

---

### Task 6: `_doc_select_fallback` — cheap LLM fallback when Search is empty (S1-R4)

**Files:**
- Modify: `agent/orchestrator.py` (imports + replace stub)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
def test_doc_select_fallback_filters_to_existing_paths(monkeypatch):
    import agent.orchestrator as orch

    monkeypatch.setattr(orch, "_resolve_model_for_phase", lambda phase, model: "m")
    monkeypatch.setattr(
        orch, "call_llm_raw",
        lambda *a, **kw: '{"docs": ["/docs/real.md", "/docs/hallucinated.md"]}',
    )
    out = orch._doc_select_fallback(
        ["/docs/real.md", "/docs/other.md"], "find the policy", ["Some Policy"]
    )
    assert out == ["/docs/real.md"]     # hallucinated path filtered out


def test_doc_select_fallback_never_raises(monkeypatch):
    import agent.orchestrator as orch

    monkeypatch.setattr(orch, "_resolve_model_for_phase", lambda phase, model: "m")
    monkeypatch.setattr(orch, "call_llm_raw",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("llm down")))
    assert orch._doc_select_fallback(["/docs/real.md"], "x", ["T"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -k doc_select_fallback -v`
Expected: FAIL — the stub returns `[]` unconditionally, so `test_doc_select_fallback_filters_to_existing_paths` fails on the non-empty expectation.

- [ ] **Step 3: Write the implementation**

Add imports at the top of `agent/orchestrator.py`:

```python
from agent.json_extract import _extract_json_from_text
from agent.llm import _resolve_model_for_phase, call_llm_raw
```

Replace the Task-5 stub with:

```python
_DOC_SELECT_CAP = 4


def _doc_select_fallback(doc_paths: list[str], instruction: str, tokens: list[str]) -> list[str]:
    """One cheap LLM pick over the doc inventory when Search returned 0 hits.

    Returns up to `_DOC_SELECT_CAP` paths, filtered to existing inventory paths.
    Never raises — on any failure returns [] (graceful degrade to path-named
    policies only). Not invoked in the typical case (Search finds the doc).
    """
    inventory = "\n".join(doc_paths)
    system = [{"type": "text", "text":
               "Select the /docs files most relevant to the task. "
               "Respond ONLY with JSON {\"docs\": [\"/docs/....md\", ...]}, "
               "max 4 paths, chosen verbatim from the inventory."}]
    user = (f"INSTRUCTION:\n{instruction}\n\n"
            f"ENTITIES:\n{', '.join(tokens)}\n\n"
            f"DOC_INVENTORY:\n{inventory}")
    model = _resolve_model_for_phase("learn", os.environ.get("MODEL", ""))
    try:
        raw = call_llm_raw(system, user, model, {}, max_tokens=256, phase="DOC_SELECT")
    except Exception:
        return []
    obj = _extract_json_from_text(raw or "")
    if not isinstance(obj, dict):
        return []
    valid = set(doc_paths)
    out: list[str] = []
    for p in obj.get("docs", []) or []:
        if isinstance(p, str) and p in valid and p not in out:
            out.append(p)
        if len(out) >= _DOC_SELECT_CAP:
            break
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -k doc_select_fallback -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): LLM DOC-SELECT fallback when Search empty, filtered to inventory (S1-R4)"
```

---

### Task 7: `_facts_block` surfaces `gather_status` (S1-R5)

**Files:**
- Modify: `agent/reason.py:32-43` (`_facts_block`)
- Test: `tests/test_reason.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reason.py`:

```python
from agent.reason import _facts_block


def test_facts_block_surfaces_gather_status():
    facts = {
        "schema": "CREATE TABLE x(...)",
        "docs_inventory": "/docs/a.md",
        "gather_status": {"docs_inventory": "ok", "policies": "empty"},
    }
    block = _facts_block(facts)
    assert "gather_status" in block
    assert "policies" in block and "empty" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reason.py::test_facts_block_surfaces_gather_status -v`
Expected: FAIL — `gather_status` is not in the surfaced key tuple.

- [ ] **Step 3: Write minimal implementation**

In `agent/reason.py:_facts_block`, add `gather_status` to the key tuple:

```python
    for key in ("agents_md", "schema", "sample_rows", "docs_inventory",
                "policies", "identity", "target_records", "gather_status"):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reason.py -v`
Expected: PASS (all, including the existing `run_intent`/`run_plan` tests).

- [ ] **Step 5: Commit**

```bash
git add agent/reason.py tests/test_reason.py
git commit -m "feat(prephase): surface gather_status in _facts_block (S1-R5)"
```

---

### Task 8: P7 — fold facts into legacy DESIGN (S1-R8)

**Files:**
- Modify: `agent/pipeline.py` (helper + legacy branch in `run_pipeline`)
- Test: `tests/test_pipeline_v2.py`

**Why a fold, not a signature change:** DESIGN's signature is strictly `(instruction, agents_md_text)` — guarded by the F-001 regression tests in `tests/test_design.py`. To give the legacy path the same grounding the interpreter gets, append the new facts (docs/policies/identity/target_records/status — schema+samples are already in `agents_md_text` via `orchestrator._augment_agents_md`) to `agents_md_text` before DESIGN. Do this **only** in the legacy branch (the interpreter branch returns earlier and consumes `facts` directly).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline_v2.py`:

```python
from agent.orchestrator import PrePhaseFacts
from agent.pipeline import _fold_facts_into_agents_md


def test_fold_facts_appends_policies_and_status():
    facts = PrePhaseFacts(
        agents_md="RULES", policies={"/docs/p.md": "POLICY BODY"},
        docs_inventory="/docs/p.md", identity={"role": "employee"},
        gather_status={"policies": "ok"},
    )
    out = _fold_facts_into_agents_md("# AGENTS\n", facts)
    assert out.startswith("# AGENTS")
    assert "POLICY BODY" in out
    assert "/docs/p.md" in out
    assert "gather_status" in out


def test_fold_facts_noop_when_facts_none():
    assert _fold_facts_into_agents_md("# AGENTS\n", None) == "# AGENTS\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_v2.py -k fold_facts -v`
Expected: FAIL with `ImportError: cannot import name '_fold_facts_into_agents_md'`.

- [ ] **Step 3: Write minimal implementation**

Add to `agent/pipeline.py` (near the other module helpers, after `_normalise`):

```python
def _fold_facts_into_agents_md(agents_md_text: str, facts) -> str:
    """Append pre-phase grounding facts to agents_md for the legacy DESIGN path.

    Schema/sample_rows are already folded by orchestrator._augment_agents_md, so
    this adds only docs_inventory/policies/identity/target_records/gather_status.
    Keeps the strict DESIGN signature intact (P7: fair A/B vs the interpreter).
    """
    if facts is None:
        return agents_md_text
    data = facts.model_dump() if hasattr(facts, "model_dump") else dict(facts)
    blocks: list[str] = [agents_md_text or ""]
    for key in ("docs_inventory", "policies", "identity", "target_records", "gather_status"):
        val = data.get(key)
        if val:
            blocks.append(f"\n\n## {key} (pre-phase)\n{val}")
    return "".join(blocks)
```

Wire it into the legacy branch of `run_pipeline`. The interpreter early-return is at the top of `run_pipeline`; immediately after it, add the fold:

```python
    # Deterministic Plan-IR interpreter path (read flag fresh so test setenv works).
    if os.environ.get("INTERPRETER_ENABLED", "0") == "1":
        return _run_interpreted(vm, instruction, task_id, agents_md_text, facts)

    # P7: legacy DESIGN sees the same grounding facts the interpreter does.
    agents_md_text = _fold_facts_into_agents_md(agents_md_text, facts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline_v2.py -k fold_facts -v`
Expected: PASS.

- [ ] **Step 5: Run the design regression guard (F-001 must stay green)**

Run: `uv run pytest tests/test_design.py -v`
Expected: PASS — DESIGN signature unchanged.

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_v2.py
git commit -m "feat(prephase): fold facts into legacy DESIGN agents_md for fair A/B (S1-R8)"
```

---

## Slice 2 — required_refs projection

### Task 9: `RefSpec` model + `IntentSpec.required_refs` (additive) (S2-R1)

**Files:**
- Modify: `agent/ir_models.py` (add `RefSpec`; add `required_refs` to `IntentSpec`; keep `required_ref_kinds` for now)
- Test: `tests/test_ir_models.py`

**HUMAN CHECKPOINT** — schema change. Pause for approval before committing.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ir_models.py`:

```python
from agent.ir_models import RefSpec


def test_refspec_policy_doc_requires_path():
    r = RefSpec(kind="policy_doc", path="/docs/x.md")
    assert r.path == "/docs/x.md" and r.source is None


def test_refspec_record_path_requires_source():
    r = RefSpec(kind="record_path", source="$row0.record_path")
    assert r.source == "$row0.record_path" and r.path is None


def test_refspec_policy_doc_with_source_rejected():
    with pytest.raises(ValidationError):
        RefSpec(kind="policy_doc", path="/docs/x.md", source="$y")


def test_refspec_record_path_without_source_rejected():
    with pytest.raises(ValidationError):
        RefSpec(kind="record_path")


def test_refspec_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        RefSpec(kind="mystery", path="/docs/x.md")


def test_intentspec_required_refs_keyed_by_outcome():
    spec = IntentSpec(
        objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
        answer_shape={"required_ref_kinds": []},   # still accepted in Task 9
        required_refs={"OUTCOME_OK": [
            {"kind": "policy_doc", "path": "/docs/counting.md"},
            {"kind": "record_path", "source": "$row0.record_path"},
        ]},
    )
    assert len(spec.required_refs["OUTCOME_OK"]) == 2
    assert spec.required_refs["OUTCOME_OK"][0].kind == "policy_doc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ir_models.py -k "refspec or required_refs" -v`
Expected: FAIL with `ImportError: cannot import name 'RefSpec'`.

- [ ] **Step 3: Write minimal implementation**

In `agent/ir_models.py`, add `RefSpec` above `IntentSpec` (after `AnswerShape`):

```python
class RefSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str                  # "policy_doc" | "record_path"
    path: str | None = None    # literal /docs/...md, known at INTENT (from discovery)
    source: str | None = None  # $ref binding, resolved at runtime (record_path)

    @model_validator(mode="after")
    def _check(self) -> "RefSpec":
        if self.kind == "policy_doc":
            if not self.path or self.source:
                raise ValueError("policy_doc RefSpec requires `path` and no `source`")
        elif self.kind == "record_path":
            if not self.source or self.path:
                raise ValueError("record_path RefSpec requires `source` and no `path`")
        else:
            raise ValueError(f"unknown RefSpec kind {self.kind!r}")
        return self
```

Add the field to `IntentSpec` (keep `answer_shape`; `required_ref_kinds` stays for now):

```python
class IntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str
    desired_outcome: str
    params: dict[str, Any] = {}
    outcome_space: list[str]
    constraints: list[Constraint] = []
    success_criteria: list[PredExpr] = []
    answer_shape: AnswerShape
    required_refs: dict[str, list[RefSpec]] = {}   # keyed by outcome
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ir_models.py -v`
Expected: PASS (new + existing golden tests; `required_ref_kinds` still present).

- [ ] **Step 5: Full suite (additive change must not regress)**

Run: `uv run pytest tests/ -q`
Expected: PASS — change is purely additive.

- [ ] **Step 6: Commit (HUMAN CHECKPOINT)**

```bash
git add agent/ir_models.py tests/test_ir_models.py
git commit -m "feat(ir): add RefSpec + IntentSpec.required_refs (additive) (S2-R1)"
```

---

### Task 10: Interpreter projects refs from `required_refs` (S2-R4)

**Files:**
- Modify: `agent/interpreter.py` (answer assembly + refuse-invariant; remove `_resolve_refs`)
- Modify: `tests/test_interpreter.py` (migrate ref tests to `required_refs`)
- Modify: `tests/replay/conftest.py` (`run_plan` derives `required_refs` from golden plan — parity shim)
- Modify: `tests/test_pipeline_interpreted.py` (`test_interpreted_verify_fail_then_learn_then_exhaust` mechanism)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_interpreter.py`:

```python
def test_refs_projected_from_required_refs_per_outcome():
    fx = {fixture_key("Exec", "/bin/sql", ["Q"]):
          {"stdout": "sku|record_path\nA|/proc/catalog/A.json"}}
    vm = MockVMSpy(fixtures=fx)
    intent = IntentSpec(
        objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
        answer_shape={"required_ref_kinds": []},
        required_refs={"OUTCOME_OK": [
            {"kind": "policy_doc", "path": "/docs/counting.md"},
            {"kind": "record_path", "source": "$row0.record_path"},
        ]},
    )
    plan = _plan(
        discovery=[{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["Q"]}, "bind": "raw"}],
        rowsets=[{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        compute=[{"prim": "first", "args": ["$rows"], "into": "row0"}],
        answer={"ok": {"message": "Found {row0.sku}", "outcome": "OUTCOME_OK", "refs": []}},
    )
    res = interpret(plan, intent, vm)
    assert res.captured.refs == ["/docs/counting.md", "/proc/catalog/A.json"]


def test_required_record_path_unresolved_refuses_on_ok():
    vm = MockVMSpy(fixtures={})
    intent = IntentSpec(
        objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
        answer_shape={"required_ref_kinds": []},
        required_refs={"OUTCOME_OK": [{"kind": "record_path", "source": "$missing"}]},
    )
    plan = _plan(answer={"ok": {"message": "m", "outcome": "OUTCOME_OK", "refs": []}})
    with pytest.raises(InterpretError):
        interpret(plan, intent, vm)
```

Migrate the four legacy ref tests in `tests/test_interpreter.py` to the new model:

- `test_answer_resolves_slots_and_refs` — change the plan's `answer["ok"]["refs"]` to `[]` and instead pass an `intent` with `required_refs={"OUTCOME_OK":[{"kind":"record_path","source":"$row0.record_path"}]}`; keep the `assert res.captured.refs == ["/proc/catalog/A.json"]`.
- `test_refuse_after_mutation_tags_mutation_landed` — replace `answer_shape={"required_ref_kinds": ["runtime"]}` + `refs=["$w.record_path"]` with `required_refs={"OUTCOME_OK":[{"kind":"record_path","source":"$w.record_path"}]}` and `refs=[]`.
- `test_refuse_when_runtime_ref_required_but_unresolved` — replace with `required_refs={"OUTCOME_OK":[{"kind":"record_path","source":"$row0.record_path"}]}` (which resolves empty → refuse).
- `test_refuse_when_ok_has_only_static_refs_but_runtime_required` — this scenario ("static present, runtime required") now equals "a record_path required ref resolves empty". Rewrite with `required_refs={"OUTCOME_OK":[{"kind":"policy_doc","path":"/docs/security.md"},{"kind":"record_path","source":"$missing"}]}` → refuse.

(The module-level `_INTENT` and other constructions keep `answer_shape={"required_ref_kinds": [...]}` for now — that field is dropped in Task 12.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter.py -k "projected_from_required or required_record_path_unresolved" -v`
Expected: FAIL — interpreter still sources refs from `tmpl.refs`, so `res.captured.refs` is `[]`, not the projected list.

- [ ] **Step 3: Write the implementation**

In `agent/interpreter.py`, **remove** the `_resolve_refs` helper (lines ~95-107) and add the projector near it:

```python
def _project_required_refs(intent: IntentSpec, outcome: str, env: dict) -> tuple[list[str], list[str]]:
    """Build answer.refs from intent.required_refs[outcome]. Return (refs, unresolved).

    policy_doc -> literal `path`; record_path -> resolve(`source`, env).
    A record_path that resolves to None/"" lands in `unresolved`.
    """
    out, unresolved = [], []
    for r in intent.required_refs.get(outcome, []):
        if r.kind == "policy_doc":
            if r.path:
                out.append(r.path)
            else:
                unresolved.append(f"policy_doc:{r.kind}")
        else:  # record_path
            val = resolve(r.source, env)
            if val in (None, ""):
                unresolved.append(r.source)
            else:
                out.append(str(val))
    return out, unresolved
```

Replace the answer-assembly + refuse block (current lines ~231-251) with:

```python
    # 7. answer assembly — refs are PROJECTED from intent.required_refs[outcome],
    #    not authored by PLAN (tmpl.refs is ignored).
    tmpl = plan.answer.get(label) or next(iter(plan.answer.values()))
    outcome = exit_outcome or tmpl.outcome
    message = _fill_slots(tmpl.message, env)
    refs, unresolved = _project_required_refs(intent, outcome, env)

    # 8. refuse invariant: an OK answer whose required record_path ref did not
    #    resolve carries mutation_landed so the pipeline routes to terminal.
    if outcome == "OUTCOME_OK" and unresolved:
        raise _refuse(f"unresolved required ref(s) {unresolved!r} on OK answer", mutation_landed)
    captured = CapturedAnswer(message=message, outcome=outcome, refs=refs)
    return InterpretResult(captured=captured, env=env, observations=observations,
                           sql_results=sql_results, mutation_landed=mutation_landed,
                           label=label)
```

Update the corpus-replay parity shim in `tests/replay/conftest.py`:

```python
def _required_refs_from_plan(plan) -> dict:
    """Transitional parity shim: derive required_refs from a golden plan's
    answer refs so the new projection reproduces the old script's refs."""
    rr: dict = {}
    for tmpl in plan.answer.values():
        bucket = rr.setdefault(tmpl.outcome, [])
        for r in tmpl.refs:
            spec = ({"kind": "record_path", "source": r}
                    if isinstance(r, str) and r.startswith("$")
                    else {"kind": "policy_doc", "path": str(r)})
            if spec not in bucket:
                bucket.append(spec)
    return rr


def run_plan(tid: str, fixtures: dict, params: dict, intent=_MINIMAL_INTENT) -> dict:
    plan = PlanIR(**json.loads((_REPLAY / f"plan_{tid}.json").read_text()))
    spy = MockVMSpy(fixtures=fixtures)
    intent = intent.model_copy(update={"params": params,
                                       "required_refs": _required_refs_from_plan(plan)})
    res = interpret(plan, intent, spy)
    return {"message": res.captured.message, "outcome": res.captured.outcome,
            "refs": sorted(res.captured.refs)}
```

Update `tests/test_pipeline_interpreted.py::test_interpreted_verify_fail_then_learn_then_exhaust` — replace the `intent_runtime` JSON's `"answer_shape": {"required_ref_kinds": ["runtime"]}` with a static answer_shape **plus** a `required_refs` that forces a refuse every cycle:

```python
    intent_runtime = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [],
        "answer_shape": {"required_ref_kinds": []},
        "required_refs": {"OUTCOME_OK": [{"kind": "record_path", "source": "$missing"}]},
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_interpreter.py tests/test_corpus_replay.py tests/test_pipeline_interpreted.py -v`
Expected: PASS — projection works, corpus parity holds via the shim, refuse path still exhausts to CLARIFICATION.

- [ ] **Step 5: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter.py tests/replay/conftest.py tests/test_pipeline_interpreted.py
git commit -m "feat(interpreter): project answer.refs from required_refs per-outcome (S2-R4)"
```

---

### Task 11: `verify` I1 over `required_refs`; delete `/docs` heuristic (S2-R5)

**Files:**
- Modify: `agent/verify.py` (I1 block, lines ~22-29)
- Modify: `tests/test_verify.py`

**HUMAN CHECKPOINT** — deletes a verify heuristic. Pause for approval before committing.

- [ ] **Step 1: Write the failing test**

Rewrite the `_intent` helper and I1 tests in `tests/test_verify.py`:

```python
def _intent(**over):
    base = dict(objective="o", desired_outcome="d",
                outcome_space=["OUTCOME_OK", "OUTCOME_DENIED_SECURITY",
                               "OUTCOME_NONE_UNSUPPORTED"],
                constraints=[], success_criteria=[],
                answer_shape={"required_ref_kinds": []},   # dropped in Task 12
                required_refs={})
    base.update(over)
    return IntentSpec(**base)


def test_i1_ok_with_unresolved_dollar_ref_fails():
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["$still_a_ref"]))
    ok, err = verify(res, _intent())
    assert not ok and "ref" in err.lower()


def test_i1_ok_missing_a_required_ref_fails():
    # one record_path required, but the answer carries no refs -> fail
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "record_path", "source": "$row.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[]))
    ok, err = verify(res, intent)
    assert not ok


def test_i1_ok_with_all_required_refs_passes():
    intent = _intent(required_refs={"OUTCOME_OK": [
        {"kind": "policy_doc", "path": "/docs/counting.md"},
        {"kind": "record_path", "source": "$row.record_path"}]})
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK",
                                 refs=["/docs/counting.md", "/proc/catalog/A.json"]))
    ok, err = verify(res, intent)
    assert ok, err


def test_i1_static_only_docs_ref_no_longer_auto_fails():
    # regression guard: the deleted /docs-static heuristic must NOT fire.
    # With required_refs empty, a /docs-only OK answer is acceptable to verify.
    res = _result(CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=["/docs/security.md"]))
    ok, err = verify(res, _intent())
    assert ok, err
```

Also update the remaining `_intent(answer_shape={"required_ref_kinds": []}, ...)` calls in `test_i2_*` / `test_i3_*` / `test_success_criteria_must_hold` — they already pass `[]`, so they work unchanged through Task 11 (the field still exists; it is removed in Task 12).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_verify.py -k "i1_ok_missing or i1_ok_with_all or static_only_docs" -v`
Expected: FAIL — `verify` still keys I1 on `answer_shape.required_ref_kinds` and the `/docs/`-static heuristic still fires.

- [ ] **Step 3: Write minimal implementation**

Replace the I1 block in `agent/verify.py` (lines ~22-29) with:

```python
    # I1: ref-grounding on OK answers — every required ref for the selected
    # outcome must be present and non-empty. refs are projected by the
    # interpreter from intent.required_refs, so this is defense-in-depth.
    if ans.outcome == "OUTCOME_OK":
        unresolved = [r for r in ans.refs if isinstance(r, str) and r.startswith("$")]
        if unresolved:
            return False, f"I1: unresolved refs {unresolved!r} on OK answer"
        n_required = len(intent.required_refs.get(ans.outcome, []))
        if n_required and len(ans.refs) < n_required:
            return False, (f"I1: OK answer carries {len(ans.refs)} ref(s) "
                           f"but {n_required} required")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_verify.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (HUMAN CHECKPOINT)**

```bash
git add agent/verify.py tests/test_verify.py
git commit -m "feat(verify): I1 over required_refs; delete /docs-static heuristic (S2-R5)"
```

---

### Task 12: Drop `AnswerShape.required_ref_kinds`; scrub remaining constructions (S2-R1)

**Files:**
- Modify: `agent/ir_models.py` (`AnswerShape`)
- Modify: `tests/test_ir_models.py`, `tests/test_reason.py`, `tests/test_pipeline_interpreted.py`, `tests/test_interpreter.py`, `tests/test_verify.py`, `tests/replay/conftest.py`

**HUMAN CHECKPOINT** — schema change. Pause for approval before committing. By this point **no production code reads `required_ref_kinds`** (interpreter → Task 10, verify → Task 11); this task removes the now-dead field and the test literals still passing it.

- [ ] **Step 1: Confirm no production reader remains**

Run: `grep -rn "required_ref_kinds" agent/`
Expected: NO matches (only `data/prompts/intent.md` remains, handled in Task 13).

- [ ] **Step 2: Write/adjust the failing test**

In `tests/test_ir_models.py`:
- Update `_GOLDEN_INTENT["answer_shape"]` from `{"msg_skeleton": "{cnt}", "required_ref_kinds": ["static"]}` to `{"msg_skeleton": "{cnt}"}`.
- Replace the assertion `assert spec.answer_shape.required_ref_kinds == ["static"]` with `assert spec.answer_shape.msg_skeleton == "{cnt}"`.
- Add a rejection test:

```python
def test_answer_shape_rejects_dropped_field():
    from agent.ir_models import AnswerShape
    with pytest.raises(ValidationError):
        AnswerShape(required_ref_kinds=["static"])
```

- [ ] **Step 3: Drop the field**

In `agent/ir_models.py`, `AnswerShape` becomes:

```python
class AnswerShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    msg_skeleton: str = ""
```

- [ ] **Step 4: Scrub the remaining test literals**

Remove `"required_ref_kinds": ...` from every remaining construction (each becomes `answer_shape={}` or `answer_shape={"msg_skeleton": "..."}`):
- `tests/test_reason.py:14` — `_INTENT_JSON` `"answer_shape": {}`.
- `tests/test_pipeline_interpreted.py:21,64,85` — `_INTENT`, `intent_no_runtime_req`, `intent_runtime` → `"answer_shape": {}`.
- `tests/test_interpreter.py:8,176,193,205` — module `_INTENT` and the three local intents → `answer_shape={}`.
- `tests/test_verify.py` — `_intent` helper default → `answer_shape={}` (drop the `required_ref_kinds` key; keep `required_refs={}`).
- `tests/replay/conftest.py:14` — `_MINIMAL_INTENT` → `answer_shape={}`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: PASS — no construction passes the dropped field; `extra="forbid"` rejection test green.

- [ ] **Step 6: Commit (HUMAN CHECKPOINT)**

```bash
git add agent/ir_models.py tests/
git commit -m "feat(ir): drop AnswerShape.required_ref_kinds, scrub callers (S2-R1)"
```

---

### Task 13: `intent.md` — declare `required_refs`, structural success_criteria (S2-R2)

**Files:**
- Modify: `data/prompts/intent.md`
- Test: `tests/test_reason_prompts.py`

**HUMAN CHECKPOINT** — `data/prompts/` edit. Pause for approval. Note the project rule: prompts hold only **general structural** rules; no task-specific knowledge.

- [ ] **Step 1: Write the failing test**

In `tests/test_reason_prompts.py`, extend `test_intent_prompt_loads_and_is_general`:

```python
def test_intent_prompt_loads_and_is_general():
    g = load_prompt("intent")
    assert g and "IntentSpec" in g
    assert "required_refs" in g            # new per-outcome ref contract
    assert "required_ref_kinds" not in g   # old flat field removed
    for banned in ("basket_069", "Non-Bladed", "service_recovery"):
        assert banned not in g
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reason_prompts.py::test_intent_prompt_loads_and_is_general -v`
Expected: FAIL — `required_refs` absent, `required_ref_kinds` still present.

- [ ] **Step 3: Edit `data/prompts/intent.md`**

In the `## Output format — IntentSpec` JSON block, replace the `answer_shape` object and add `required_refs`:

```json
  "answer_shape": {
    "msg_skeleton": "<human-readable template, e.g. 'Processed {count} items'>"
  },
  "required_refs": {
    "OUTCOME_OK": [
      {"kind": "policy_doc", "path": "/docs/<governing-doc>.md"},
      {"kind": "record_path", "source": "$<row>.record_path"}
    ]
  }
```

Replace the `answer_shape.required_ref_kinds` bullet under **Field rules** with:

```markdown
- `required_refs` — keyed by outcome. For each outcome the answer can take, list the
  evidence the grader requires: a `policy_doc` (literal `/docs/...md` `path` taken from
  THIS run's `docs_inventory`/`policies` — the governing rule/count/procedure the
  decision rests on) and/or a `record_path` (a `$ref` `source` bound at runtime to the
  reported row's path). Declare ONLY load-bearing refs (reading a doc ≠ obligation to
  cite it). Exactly one of `path`/`source` per RefSpec, matching its `kind`.
- `success_criteria` — STRUCTURAL / grounding checks only (e.g. `count ge 0`, a
  nonempty bound id). Do NOT bake a SQL recipe, join, `kind_id`, or `city` here — that
  is PLAN's job (HOW). INTENT states WHAT/why.
```

Add an **IDD/SDD** note after the field rules:

```markdown
## IDD vs SDD (what belongs here)

INTENT is the IDD layer: WHAT must hold and WHY — `objective`, `outcome_space`,
`constraints`, `required_refs` (cite the governing doc + the reported record),
`success_criteria` (structural/grounding). INTENT NEVER specifies HOW: no SQL, joins,
column names, `kind_id`, or `city`. PLAN (the SDD layer) reads the eligibility rule
from `facts.policies` and builds the rule-correct SQL.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reason_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (HUMAN CHECKPOINT)**

```bash
git add data/prompts/intent.md tests/test_reason_prompts.py
git commit -m "docs(intent.md): required_refs per-outcome; structural success_criteria; IDD/SDD (S2-R2)"
```

---

### Task 14: `plan.md` — drop PLAN-authored refs; read rule from policies (S2-R3)

**Files:**
- Modify: `data/prompts/plan.md`
- Test: `tests/test_reason_prompts.py`

**HUMAN CHECKPOINT** — `data/prompts/` edit. Pause for approval.

- [ ] **Step 1: Write the failing test**

Extend `test_plan_prompt_loads_and_documents_ir`:

```python
def test_plan_prompt_loads_and_documents_ir():
    g = load_prompt("plan")
    assert g and "PlanIR" in g and "decision" in g and "discovery" in g
    assert "ALWAYS cite both" not in g          # PLAN no longer authors refs
    assert "facts.policies" in g                # PLAN reads the eligibility rule
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reason_prompts.py::test_plan_prompt_loads_and_documents_ir -v`
Expected: FAIL — "ALWAYS cite both" still present; "facts.policies" absent.

- [ ] **Step 3: Edit `data/prompts/plan.md`**

Replace the entire **`answer`** bullet block (current lines ~99-115, the `message`/`outcome`/`refs` "ALWAYS cite both ..." paragraph) with:

```markdown
**`answer`** — keyed by decision label. Each `AnswerTemplateIR`:
- `message` — f-string-style template; `{slot}` resolves from env (same as `$slot`).
- `outcome` — one of the `Outcome` enum values.
- `refs` — **leave empty (`[]`)**. The interpreter projects `answer.refs` from
  `INTENT.required_refs[selected_outcome]`. PLAN supplies only the runtime *bindings*
  those refs resolve against: ensure your discovery/rowset/compute steps bind the env
  key the INTENT's `record_path` `source` points at (e.g. a `$row.record_path` column
  selected from `/bin/sql`). Do NOT author or cite refs here.
```

Add a sentence to the **`discovery`** bullet:

```markdown
Read the eligibility rule for the computation from `facts.policies` (the governing
`/docs` content surfaced in pre-phase) and encode the rule-correct SQL — the
documented count/filter, not a naive one.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reason_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit (HUMAN CHECKPOINT)**

```bash
git add data/prompts/plan.md tests/test_reason_prompts.py
git commit -m "docs(plan.md): drop PLAN-authored refs; read eligibility rule from facts.policies (S2-R3)"
```

---

## Integration & Outcome Verification

### Task 15: Full unit suite green + t09 probe on live grader

**Files:** none (verification only)

**HUMAN CHECKPOINT** — the probe hits the live grader. Per project memory: run ONLY when no `main.py` is hitting the harness (`pgrep -af main.py` first); the harness serializes trials.

- [ ] **Step 1: Run the entire unit suite**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS (all non-gated tests). `tests/test_integration_interpreter.py` stays skipped unless `RUN_BENCHMARK=1`.

- [ ] **Step 2: Confirm no concurrent harness run**

Run: `pgrep -af "main.py" || echo "clear"`
Expected: `clear` (no other run). If a run is active, STOP — do not contend.

- [ ] **Step 3: Probe t09 end-to-end on the live grader**

Run: `uv run python scripts/probe_t09_refs.py`
Expected: `SCORE = 1.0` with no ref complaint in the printed grader detail. This validates the doc-discover → read-rule → cite contract on a single seed. If `< 1.0`, read the grader detail lines and feed them back into the failing slice (do not patch `data/prompts/` for a task failure — fix the LEARN trigger / pre-phase gather).

- [ ] **Step 4: Commit (if any harness shim changed; otherwise skip)**

No commit expected — verification only.

---

### Task 16: A/B benchmark — `heuristics` vs `master` (outcome gate)

**Files:** none (measurement only)

**HUMAN CHECKPOINT / no-autonomy** — this is the merge-to-`master` cutover decision. Green unit tests are NOT proof of outcome; the live grader is truth (intent Stop Rules). The default benchmark run is ~3h over 54 tasks.

- [ ] **Step 1: Run the interpreter benchmark on `heuristics`**

Ensure `.env` sets `INTERPRETER_ENABLED=1`. Confirm no concurrent run (`pgrep -af main.py`), then:

Run: `INTERPRETER_ENABLED=1 uv run python main.py`
Capture the per-task scores and overall % from the run's `logs/` output.

- [ ] **Step 2: Compare against the `master` baseline**

Compare to the recorded baseline (~32%, per `project_benchmark_baseline` memory; 2026-06-06 = 32.32%). Verify the **Done-when** gate from the intent:
- **t09 = 1.0** in the real run (not just the probe).
- Bucket-B (policy/counting/grounding) tasks rise.
- Overall score ≥ baseline ~32%.
- Previously-green tasks did NOT regress.

- [ ] **Step 3: Decide cutover (human)**

If all four hold → propose merging `heuristics` → `master`. If a green task regressed OR score < ~32% → **Halt** (intent Stop Rule); open the regressed task's trace, attribute to a slice, and iterate. Do NOT merge on red.

---

## Self-Review

**Spec coverage** (each S-requirement → task):

| Req | Task |
|-----|------|
| S1-R1 `_discover_docs` | 1 |
| S1-R2 `_extract_entity_tokens` | 2 |
| S1-R3 policies Search enrichment | 4, 5 |
| S1-R4 LLM DOC-SELECT fallback | 6 |
| S1-R5 `gather_status` | 5, 7 |
| S1-R6 wider `target_records` | 4, 5 |
| S1-R7 robust identity parse | 3 |
| S1-R8 P7 facts → legacy DESIGN | 8 |
| S2-R1 `RefSpec` + `required_refs`, drop `required_ref_kinds` | 9, 12 |
| S2-R2 `intent.md` | 13 |
| S2-R3 `plan.md` | 14 |
| S2-R4 interpreter ref-projection | 10 |
| S2-R5 `verify` I1 rewrite | 11 |
| Outcome verification (t09=1.0, A/B) | 15, 16 |

**Type consistency:** `RefSpec{kind, path?, source?}` defined in Task 9 is consumed identically in Task 10 (`_project_required_refs`: `r.kind`/`r.path`/`r.source`), Task 11 (`intent.required_refs.get(outcome, [])` length), Task 13 (`intent.md` JSON shape), Task 14 (`plan.md` references `source`). `IntentSpec.required_refs: dict[str, list[RefSpec]]` keyed by outcome string throughout. `PrePhaseFacts.gather_status: dict[str, str]` added in Task 5, surfaced in Task 7, folded in Task 8 — same field name.

**Staging invariant:** suite is green after every commit. `required_ref_kinds` is read by production code only until Task 10 (interpreter) and Task 11 (verify) stop reading it; Task 12 drops the field only after Step 1 confirms `grep -rn required_ref_kinds agent/` is empty. The corpus-replay parity shim (Task 10) keeps `test_corpus_replay` green without re-authoring golden plan fixtures.

**Known transitional artifact:** `tests/replay/conftest.py:_required_refs_from_plan` derives `required_refs` from each golden plan's `answer.refs`. This is a parity shim for legacy fixtures, not production behavior — production INTENT authors `required_refs` directly (Task 13). Left in place intentionally; documented in the task.
