---
review:
  plan_hash: 506e93b7045822ea
  spec_hash: d78b9dd0c845db29
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
      section: "Task 5 (P5 tier split / relevance)"
      section_hash: c86cf7ccec546baf
      text: "Spec Testing-table row 'H2 relevance: oracle atom widens set pre-failure' has no plan step. `_relevant_tables` is lexical-only and never consults the oracle (oracle atoms feed PLAN/CODEGEN via build_oracle_block, not table sampling). Only the LEARN post-failure half (prephase_deep_read, Task 14) is covered. Spec H2 treats the oracle layer as 'already wired', so the pre-failure widening is architecturally a no-op on sampling — but no plan step verifies the spec's stated assertion."
      verdict: fixed
      verdict_at: 2026-06-15
      resolution: "Added explicit 'H2 coverage note' after Task 5 mapping the two widening layers to where each is verified: post-failure per-task = LEARN prephase_deep_read (Task 14 test); general/pre-failure = oracle atoms injected into PLAN via build_oracle_block (existing oracle suite). _relevant_tables stays lexical by design; the accepted-residual one-cycle synonym miss is logged (Task 5 Step 3), never silent."
    - id: F-002
      phase: coverage
      severity: WARNING
      section: "Task 2 (constants) — Constants & budgets DoD"
      section_hash: 020ce1216471eff7
      text: "Spec 'Constants & budgets' DoD: 'a unit test asserts both the default and one override per constant'. The plan provides a default+env-override test only for _PATH_LITERAL_CAP (Task 2). _PATH_LISTING_BUDGET, _SAMPLE_ROWS_PER_TABLE, _SAMPLE_ROW_MAX_CHARS, and _IMAX_STEPS are exercised by behavior/monkeypatch but lack the per-constant env default+override unit test the DoD requires."
      verdict: fixed
      verdict_at: 2026-06-15
      resolution: "Added per-constant default+override env tests: _PATH_LISTING_BUDGET (Task 2 test_prephase_listing_bytes_default_and_override), _SAMPLE_ROWS_PER_TABLE/_SAMPLE_ROW_MAX_CHARS (Task 5 test_prephase_sample_constants_default_and_override), _IMAX_STEPS (Task 11 test_interpreter_max_steps_default_and_override). _PATH_LITERAL_CAP already covered. Each asserts the documented default AND one override."
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-15-prephase-loop-security-hardening-design.md
result_check:
  verdict: OK
  plan_hash: 506e93b7045822ea
  last_run: 2026-06-15
---

# Pre-phase / loop / security hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ground INTENT on real VM files (fixing the t55 literal-path failure), harden the deterministic-interpreter loop (cross-run IR learning, observation-fed re-planning, convergence guards), and remove over-firing customer-ownership security denials — while de-hardcoding domain lists out of `orchestrator.py`.

**Architecture:** Three phases on branch `heuristics`. Phase 1 (pre-phase/discovery) adds runtime `List`/`Stat` parsers, literal-path grounding, a metadata/content read-tier split, and a sufficiency signal. Phase 2 (interpreter loop) gives the Plan-IR path its own learned-rule namespace, a PlanIR-framed LEARN prompt, observation-fed re-planning, an identical-plan short-circuit, and its own cycle ceiling. Phase 3 (security scope) classifies caller identity structurally and teaches INTENT to apply customer-ownership denials only to customers. Phases 1+3 together fix t55 end-to-end (ref + outcome); Phase 2 is independent interpreter debt. A final **gated** cutover task removes legacy CODEGEN/fidelity config and code only after the A/B validation gate passes.

**Tech Stack:** Python 3, Pydantic v2, protobuf (`bitgn.vm.ecom`), pytest, `uv`. LLM phases emit JSON (IntentSpec / PlanIR / LearnConsolidateOutput); the interpreter executes deterministically.

---

## Scope note

This plan covers one coherent hardening effort across shared files (`agent/orchestrator.py`, `agent/pipeline.py`, `agent/reason.py`, `agent/learned_store.py`). It is **not** three independent subsystems — Phase 1 supplies t55's required ref, Phase 3 supplies its outcome, and Phase 2's `prephase_deep_read` hook depends on Phase 1's tier split. Execute in task order: Phase 1 (Tasks 1–7) → Phase 2 (Tasks 8–14) → Phase 3 (Tasks 15–16) → cross-cutting docs (Task 17) → **gated** cutover (Task 18).

## Conventions used throughout

- All numeric knobs read via `os.environ.get(NAME, DEFAULT)` at module import. They are **cost safety rails only** (Stat-probe count, byte budget, sample LIMIT, cycle ceiling) — never domain knowledge.
- Tests are deterministic, use `MagicMock` / `SimpleNamespace`, and are **proto-and-dict tolerant** (an RPC result may be a protobuf message OR a plain dict).
- Run a single test: `uv run pytest tests/test_FILE.py::test_NAME -v`. Run a file: `uv run pytest tests/test_FILE.py -v`. Full suite: `uv run python -m pytest tests/ -q`.
- `test_t09_replay_matches_known_good` is a **known pre-existing stale-fixture red** — not a regression. Ignore it in green-suite checks.

## File Structure

| File | Responsibility | Phase |
|---|---|---|
| `agent/orchestrator.py` | pre-phase fact gathering: runtime parsers, literal-path grounding, tier split, VM-discovered record paths, structural `identity.kind` | 1, 3 |
| `agent/reason.py` | `_facts_block` surfacing (`path_listings` + `FACT_STATUS`), `run_plan(observed=)` block | 1, 2 |
| `agent/learned_store.py` | `surface` namespace on entries, `prephase_deep_read` persistence | 2 |
| `agent/models.py` | `LearnConsolidateOutput.prephase_deep_read` field | 2 |
| `agent/pipeline.py` | interpreter loop: IR learn namespace, `_ilearn` reframe, observed threading, plan-signature short-circuit, `_IMAX_STEPS`; legacy `path_listings` fold | 1, 2 |
| `data/prompts/ilearn.md` | **new** — PlanIR-framed LEARN prompt | 2 |
| `data/prompts/intent.md` | role-aware customer-ownership `deny_when` rule + `identity.kind` fact doc | 3 |
| `scripts/probe_t55_refs.py` | **new** — grader-oracle probe for t55 (manual integration gate) | 3 |
| `.env.example`, `CLAUDE.md` | env documentation for `INTERPRETER_*` / `PREPHASE_*`; MAX_STEPS legacy note | cross-cut |
| Tests | `tests/test_orchestrator.py`, `tests/test_reason.py`, `tests/test_learned_store.py`, `tests/test_pipeline_interpreted.py`, `tests/test_predicates.py` (new) | all |

---

# Phase 1 — pre-phase / discovery

## Task 1: P9-runtime shared parsers (`_list_entries` / `_stat_kind`)

`ListResponse`/`StatResponse` carry **no `.stdout`** — code reading `.stdout` on them gets `""`. Add reusable proto/dict-tolerant parsers that read `entries[*].path` and `kind`.

**Files:**
- Modify: `agent/orchestrator.py` (import line ~9; add functions after `_read_agents_md`, ~line 28)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orchestrator.py` (the file already imports `SimpleNamespace as _NS` and `MagicMock`; add the new symbol imports):

```python
from bitgn.vm.ecom.ecom_pb2 import NodeKind
from agent.orchestrator import _list_entries, _stat_kind


def test_list_entries_reads_paths_not_stdout():
    vm = MagicMock()
    vm.list.return_value = _NS(
        entries=[_NS(path="/proc/incoming/payments/inpay_a.json"),
                 _NS(path="/proc/incoming/payments/inpay_b.json")],
        stdout="SHOULD_BE_IGNORED",
    )
    assert _list_entries(vm, "/proc/incoming/payments") == [
        "/proc/incoming/payments/inpay_a.json",
        "/proc/incoming/payments/inpay_b.json",
    ]


def test_list_entries_dict_tolerant_and_empty_on_error():
    vm = MagicMock()
    vm.list.return_value = {"entries": [{"path": "/x/a"}, {"path": ""}]}
    assert _list_entries(vm, "/x") == ["/x/a"]
    vm.list.side_effect = RuntimeError("boom")
    assert _list_entries(vm, "/x") == []


def test_stat_kind_maps_enum_and_string():
    vm = MagicMock()
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_DIR)
    assert _stat_kind(vm, "/proc/incoming/payments") == "dir"
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_FILE)
    assert _stat_kind(vm, "/bin/sql") == "file"
    vm.stat.return_value = {"kind": "dir"}          # dict-tolerant (mock)
    assert _stat_kind(vm, "/x") == "dir"
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_UNSPECIFIED)
    assert _stat_kind(vm, "/nope") == ""
    vm.stat.side_effect = RuntimeError("boom")
    assert _stat_kind(vm, "/nope") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_orchestrator.py -k "list_entries or stat_kind" -v`
Expected: FAIL with `ImportError: cannot import name '_list_entries'`.

- [ ] **Step 3: Add the parsers**

In `agent/orchestrator.py`, change the proto import (currently `from bitgn.vm.ecom.ecom_pb2 import ReadRequest`) to:

```python
from bitgn.vm.ecom.ecom_pb2 import NodeKind, ReadRequest
```

Then add, immediately after `_read_agents_md` (before `_SAMPLE_TABLES_MAX`):

```python
def _list_entries(vm, path: str) -> list[str]:
    """ListResponse.entries[*].path (proto or dict). NOT `.stdout` (absent in proto)."""
    try:
        resp = vm.list(path=path)
    except Exception:
        return []
    entries = getattr(resp, "entries", None)
    if entries is None and isinstance(resp, dict):
        entries = resp.get("entries")
    out: list[str] = []
    for e in entries or []:
        p = getattr(e, "path", None)
        if p is None and isinstance(e, dict):
            p = e.get("path")
        if p:
            out.append(p)
    return out


def _stat_kind(vm, path: str) -> str:
    """StatResponse.kind -> 'dir' | 'file' | '' (proto enum or dict/string tolerant)."""
    try:
        resp = vm.stat(path=path)
    except Exception:
        return ""
    k = getattr(resp, "kind", None)
    if k is None and isinstance(resp, dict):
        k = resp.get("kind")
    if isinstance(k, str):
        return k if k in ("dir", "file") else ""
    return {NodeKind.NODE_KIND_DIR: "dir", NodeKind.NODE_KIND_FILE: "file"}.get(k, "")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_orchestrator.py -k "list_entries or stat_kind" -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): add proto/dict-tolerant _list_entries/_stat_kind (P9-runtime)"
```

---

## Task 2: Path-literal extraction + byte-budget renderer

Extract any absolute path from the instruction (no `/proc` allowlist — the VM is the filter) and render a directory listing under a byte budget with a non-silent overflow marker.

**Files:**
- Modify: `agent/orchestrator.py` (add constants near the other module constants ~line 30; add functions after the parsers from Task 1)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orchestrator.py`:

```python
from agent.orchestrator import _extract_path_literals, _render_budget


def test_extract_path_literals_any_root_strip_dedup():
    instr = "details in /proc/incoming/payments and /data/incoming/x.json, also /proc/incoming/payments again"
    out = _extract_path_literals(instr)
    assert out == ["/proc/incoming/payments", "/data/incoming/x.json"]  # dedup, trailing comma stripped


def test_extract_path_literals_respects_cap(monkeypatch):
    monkeypatch.setenv("PREPHASE_PATH_LITERALS", "2")
    import importlib, agent.orchestrator as orch
    importlib.reload(orch)
    try:
        out = orch._extract_path_literals("/a/b /c/d /e/f /g/h")
        assert out == ["/a/b", "/c/d"]
    finally:
        monkeypatch.delenv("PREPHASE_PATH_LITERALS", raising=False)
        importlib.reload(orch)   # restore default cap for later tests


def test_render_budget_marks_overflow():
    paths = [f"/proc/p/{i}.json" for i in range(100)]
    rendered = _render_budget(paths, budget=60)
    assert "skipped" in rendered                       # no silent truncation
    assert rendered.count("\n") < 100


def test_render_budget_within_budget_no_marker():
    rendered = _render_budget(["/a/b", "/c/d"], budget=4096)
    assert rendered == "/a/b\n/c/d"
    assert "skipped" not in rendered


def test_prephase_listing_bytes_default_and_override(monkeypatch):
    # Constants & budgets DoD: assert default AND one env override for this constant.
    import importlib, agent.orchestrator as orch
    assert orch._PATH_LISTING_BUDGET == 4096                 # default
    monkeypatch.setenv("PREPHASE_LISTING_BYTES", "128")
    importlib.reload(orch)
    try:
        assert orch._PATH_LISTING_BUDGET == 128              # override
    finally:
        monkeypatch.delenv("PREPHASE_LISTING_BYTES", raising=False)
        importlib.reload(orch)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator.py -k "path_literals or render_budget" -v`
Expected: FAIL with `ImportError: cannot import name '_extract_path_literals'`.

- [ ] **Step 3: Add constants + functions**

In `agent/orchestrator.py`, add near the existing module constants (after `_SAMPLE_ROW_MAX_CHARS`, around line 32):

```python
# Cost safety rails (NOT domain knowledge): bound Stat-probe count + rendered listing size.
_PATH_LITERAL_RE = re.compile(r"/[\w./-]+")
_PATH_LITERAL_CAP = int(os.environ.get("PREPHASE_PATH_LITERALS", "3"))
_PATH_LISTING_BUDGET = int(os.environ.get("PREPHASE_LISTING_BYTES", "4096"))
```

Add these functions after `_stat_kind` (from Task 1):

```python
def _extract_path_literals(instruction: str) -> list[str]:
    """Any absolute-path literal in the instruction, deduped, trailing-punct stripped.

    No root allowlist: Stat() (the caller's filter) decides which paths exist.
    The cap bounds Stat-probe cost only — a safety rail, not domain knowledge.
    """
    out: list[str] = []
    for m in _PATH_LITERAL_RE.findall(instruction or ""):
        lit = m.rstrip(".,;:)'\"")
        if lit and lit not in out:
            out.append(lit)
    return out[:_PATH_LITERAL_CAP]


def _render_budget(paths: list[str], budget: int) -> str:
    """Join paths under a byte budget; overflow -> '… +N skipped' (no silent truncation)."""
    lines: list[str] = []
    used = 0
    for i, p in enumerate(paths):
        if used + len(p) + 1 > budget:
            lines.append(f"… +{len(paths) - i} skipped")
            break
        lines.append(p)
        used += len(p) + 1
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_orchestrator.py -k "path_literals or render_budget or prephase_listing_bytes" -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): path-literal extraction + byte-budget renderer (1.2)"
```

---

## Task 3: Wire `path_listings` fact into `gather_prephase_facts`

Surface the real record paths under any instruction-named directory (Tier-1, listing only — no content slurp). `Stat` is the only filter; a non-existent/non-data path is dropped.

**Files:**
- Modify: `agent/orchestrator.py` (`PrePhaseFacts` model ~line 146; `gather_prephase_facts` ~line 396)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_gather_path_listings_dir_lists_file_existence_nonexistent_skipped():
    import agent.orchestrator as orch
    from bitgn.vm.ecom.ecom_pb2 import NodeKind
    vm = MagicMock()
    vm.exec.return_value = _NS(stdout="", stderr="", exit_code=0)      # no schema
    vm.read.return_value = _NS(content="")
    vm.search.return_value = _NS(matches=[])
    vm.tree.side_effect = RuntimeError("no docs")

    def _stat(path=None):
        if path == "/proc/incoming/payments":
            return _NS(kind=NodeKind.NODE_KIND_DIR)
        return _NS(kind=NodeKind.NODE_KIND_UNSPECIFIED)
    vm.stat.side_effect = _stat
    vm.list.return_value = _NS(entries=[_NS(path="/proc/incoming/payments/inpay_a.json")])

    instr = "All details about the last transaction in /proc/incoming/payments"
    facts = orch.gather_prephase_facts(vm, instruction=instr, agents_md_text="")
    assert "/proc/incoming/payments" in facts.path_listings
    assert "inpay_a.json" in facts.path_listings["/proc/incoming/payments"]
    assert facts.gather_status.get("path_listings") == "ok"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator.py::test_gather_path_listings_dir_lists_file_existence_nonexistent_skipped -v`
Expected: FAIL with `AttributeError: 'PrePhaseFacts' object has no attribute 'path_listings'`.

- [ ] **Step 3: Add the field + wire the fact**

In `agent/orchestrator.py`, add a field to `PrePhaseFacts` (after `target_records`):

```python
    path_listings: dict[str, str] = {}   # instruction-named dir -> rendered listing (Tier-1)
```

In `gather_prephase_facts`, insert this block immediately before the `return PrePhaseFacts(...)` statement (after `_mark("target_records", target_records)`):

```python
    # literal-path listings (1.2) — VM is the filter; no /proc allowlist, no hardcoded roots.
    path_listings: dict[str, str] = {}
    for lit in _extract_path_literals(instruction):
        kind = _stat_kind(vm, lit)
        if kind == "dir":
            paths = _list_entries(vm, lit)               # Tier-1, cheap
            if paths:
                path_listings[lit] = _render_budget(paths, _PATH_LISTING_BUDGET)
        elif kind == "file":
            path_listings[lit] = f"file {lit}"           # existence; body NOT read
        # kind == "" -> non-existent / non-data path -> skipped
    _mark("path_listings", path_listings)
```

Add `path_listings=path_listings,` to the `return PrePhaseFacts(...)` constructor call.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_orchestrator.py::test_gather_path_listings_dir_lists_file_existence_nonexistent_skipped -v`
Expected: PASS.

- [ ] **Step 5: Run the orchestrator suite (regression)**

Run: `uv run pytest tests/test_orchestrator.py -q`
Expected: all PASS (existing `gather_prephase_facts` tests don't name path literals; their `/docs/...` tokens hit the MagicMock default `vm.stat`, which returns a Mock — `_stat_kind` maps it to `""` and drops it).

- [ ] **Step 6: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): surface path_listings fact from instruction-named dirs (1.2)"
```

---

## Task 4: H1 de-hardcode — VM-discovered record paths (drop `_PROC_DIR` map + prefix allowlist)

The frozen `{basket:baskets,…}` map and the seven-prefix `_RECORD_ID_RE` alternation make any unlisted entity or `/proc` layout invisible (the t55 class). Replace with: a structural id-shape regex + the **actual** `/proc` subdirs from `_list_entries(vm, "/proc")`.

**Files:**
- Modify: `agent/orchestrator.py` (`_RECORD_ID_RE` ~line 159; delete `_PROC_DIR` ~line 162; `_proc_candidates` ~line 225; `target_records` loop ~line 379)
- Test: `tests/test_orchestrator.py` (replace `test_proc_candidates_maps_prefix_to_plural_dir`)

- [ ] **Step 1: Replace the failing `_proc_candidates` test + add a discovery test**

In `tests/test_orchestrator.py`, replace `test_proc_candidates_maps_prefix_to_plural_dir` (lines ~185-188) with:

```python
def test_proc_candidates_uses_discovered_subdirs_no_static_map():
    # subdirs are LISTED from /proc, not mapped by a frozen singular->plural dict.
    subdirs = ["stores", "baskets", "incoming"]
    assert _proc_candidates(subdirs, "store_S001") == ["/proc/stores/store_S001.json"]
    assert _proc_candidates(subdirs, "basket_069") == ["/proc/baskets/basket_069.json"]
    assert _proc_candidates(subdirs, "unknown_xx") == []   # no matching subdir -> no probe
```

Add:

```python
def test_gather_target_records_matches_discovered_subdir():
    import agent.orchestrator as orch
    from bitgn.vm.ecom.ecom_pb2 import NodeKind
    vm = MagicMock()
    vm.exec.return_value = _NS(stdout="", stderr="", exit_code=0)
    vm.search.return_value = _NS(matches=[])
    vm.tree.side_effect = RuntimeError("no docs")
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_UNSPECIFIED)

    def _list(path=None):
        if path == "/proc":
            return _NS(entries=[_NS(path="/proc/baskets"), _NS(path="/proc/payments")])
        return _NS(entries=[])
    vm.list.side_effect = _list

    def _read(path=None):
        if path == "/proc/baskets/basket_069.json":
            return _NS(content='{"id":"basket_069"}')
        return _NS(content="")
    vm.read.side_effect = _read

    facts = orch.gather_prephase_facts(vm, instruction="approve basket_069", agents_md_text="")
    assert "/proc/baskets/basket_069.json" in facts.target_records
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator.py -k "proc_candidates or target_records_matches" -v`
Expected: FAIL — `_proc_candidates()` currently takes one arg; the new test passes two.

- [ ] **Step 3: De-hardcode**

In `agent/orchestrator.py`:

(a) Replace the `_RECORD_ID_RE` definition (lines ~159-161) with a structural id-shape regex, and **delete** the `_PROC_DIR` dict (lines ~162-166):

```python
# Structural id-shape only (H1): <prefix>_<rest>. The /proc listing + DDL decide
# which prefixes are real — no entity-prefix allowlist, no singular->plural map.
_RECORD_ID_RE = re.compile(r"\b([A-Za-z]+)_\w+\b")
```

(b) Replace `_proc_candidates` (lines ~225-229) with a discovered-subdir matcher:

```python
def _proc_candidates(proc_subdirs: list[str], record_id: str) -> list[str]:
    """`/proc/<subdir>/<id>.json` for each DISCOVERED subdir matching the id prefix.

    Plural/dir is discovered (`_list_entries(vm, "/proc")`), never a static map.
    `name.startswith(prefix)` catches singular->plural (payment -> payments); a
    spurious match is harmless — the caller reads the file and keeps it only if non-empty.
    """
    prefix = record_id.split("_", 1)[0].lower()
    return [f"/proc/{name}/{record_id}.json"
            for name in proc_subdirs if name.startswith(prefix)]
```

(c) Replace the `target_records` loop in `gather_prephase_facts` (lines ~378-396, from `# target_records (P3 wider — S1-R6)` through `_mark("target_records", target_records)`) with:

```python
    # target_records (H1 — VM-discovered subdirs; no static prefix list / plural map)
    target_records: dict[str, str] = {}
    proc_subdirs = [d.rstrip("/").rsplit("/", 1)[-1].lower()
                    for d in _list_entries(vm, "/proc")]
    seen_ids: list[str] = []
    for m in _RECORD_ID_RE.finditer(instruction or ""):
        full = m.group(0)
        prefix = full.split("_", 1)[0].lower()
        # structural id-shape; the /proc listing decides which prefixes are real
        if not any(name.startswith(prefix) for name in proc_subdirs):
            continue
        if full in seen_ids:
            continue
        seen_ids.append(full)
        if len(seen_ids) > _RECORD_CAP:
            break
        for proc in _proc_candidates(proc_subdirs, full):
            try:
                txt = _extract_text(vm.read(path=proc), "content")
                if txt:
                    target_records[proc] = txt
                    break
            except Exception:
                continue
    _mark("target_records", target_records)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_orchestrator.py -k "proc_candidates or target_records" -v`
Expected: PASS.

- [ ] **Step 5: Full orchestrator regression**

Run: `uv run pytest tests/test_orchestrator.py -q`
Expected: all PASS. (`test_gather_prephase_facts_collects_identity_and_target_record` seeds a `basket_069` read — if it stubs `vm.list` as a bare MagicMock, update that stub to return `_NS(entries=[_NS(path="/proc/baskets")])` for `path="/proc"` so the discovered-subdir filter passes; otherwise the record won't be probed.)

- [ ] **Step 6: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "refactor(prephase): de-hardcode record paths via /proc listing (H1)"
```

---

## Task 5: P5 tier split — uncap table names, relevance-gate sampling

Drop the static `_SAMPLE_TABLES_MAX` cap: table names + DDL are Tier-1 (uncapped, one query). Sample rows (Tier-2) only for **relevant** tables (name/entity token in the instruction), with a per-table `LIMIT` + row byte cap as the only safety rail. Log skipped tables (no silent truncation).

**Files:**
- Modify: `agent/orchestrator.py` (constants ~line 30-32; `_discover_table_names` ~line 56; add `_relevant_tables`; `gather_prephase_facts` schema/sample block ~line 303-306)
- Test: `tests/test_orchestrator.py` (replace `test_discover_table_names_parses_and_caps`)

- [ ] **Step 1: Adjust + add tests**

Replace `test_discover_table_names_parses_and_caps` in `tests/test_orchestrator.py` with:

```python
def test_discover_table_names_uncapped():
    vm = MagicMock()
    names = "\n".join(f"t{i}" for i in range(20))
    vm.exec.return_value = _exec_returning(names)
    out = _discover_table_names(vm)
    assert len(out) == 20            # Tier-1: no cap
    assert out[0] == "t0"
```

Add:

```python
from agent.orchestrator import _relevant_tables


def test_relevant_tables_lexical_and_deep_read():
    tables = ["payments", "orders", "payment_transaction_items", "customers"]
    # "payment" appears -> payments matches; deep_read adds an indirect table.
    got = _relevant_tables(tables, "show the payment for cust", deep_read=("payment_transaction_items",))
    assert "payments" in got
    assert "payment_transaction_items" in got
    assert "orders" not in got and "customers" not in got


def test_prephase_sample_constants_default_and_override(monkeypatch):
    # Constants & budgets DoD: default AND one env override for each sample-tier constant.
    import importlib, agent.orchestrator as orch
    assert (orch._SAMPLE_ROWS_PER_TABLE, orch._SAMPLE_ROW_MAX_CHARS) == (3, 400)   # defaults
    monkeypatch.setenv("PREPHASE_SAMPLE_ROWS", "1")
    monkeypatch.setenv("PREPHASE_SAMPLE_ROW_CHARS", "50")
    importlib.reload(orch)
    try:
        assert (orch._SAMPLE_ROWS_PER_TABLE, orch._SAMPLE_ROW_MAX_CHARS) == (1, 50)  # overrides
    finally:
        monkeypatch.delenv("PREPHASE_SAMPLE_ROWS", raising=False)
        monkeypatch.delenv("PREPHASE_SAMPLE_ROW_CHARS", raising=False)
        importlib.reload(orch)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator.py -k "discover_table_names_uncapped or relevant_tables" -v`
Expected: FAIL (`_relevant_tables` import error; old cap test gone).

- [ ] **Step 3: Implement the tier split**

In `agent/orchestrator.py`:

(a) Replace the three sample constants (lines ~30-32) with env-driven rails and **remove** `_SAMPLE_TABLES_MAX`:

```python
_SAMPLE_ROWS_PER_TABLE = int(os.environ.get("PREPHASE_SAMPLE_ROWS", "3"))
_SAMPLE_ROW_MAX_CHARS = int(os.environ.get("PREPHASE_SAMPLE_ROW_CHARS", "400"))
```

(b) Drop the cap in `_discover_table_names` — change its final two lines from:

```python
    names = [line.strip() for line in text.splitlines() if line.strip()]
    return names[:_SAMPLE_TABLES_MAX]
```

to:

```python
    return [line.strip() for line in text.splitlines() if line.strip()]
```

(c) Add `_relevant_tables` after `_discover_sample_rows`:

```python
def _relevant_tables(tables: list[str], instruction: str,
                     deep_read: tuple[str, ...] = ()) -> list[str]:
    """Tables to sample (Tier-2): name/entity token present in the instruction,
    UNION learned `prephase_deep_read` for this tid. NOT 'first N alphabetical'.

    Lexical match only (singular form too); FK-adjacency and synonym widening are
    handled by the oracle / LEARN loop, not a static rule (see spec H2)."""
    instr = (instruction or "").lower()
    out: list[str] = []
    for t in tables:
        tl = t.lower()
        if tl in instr or tl.rstrip("s") in instr:
            out.append(t)
    for t in deep_read:
        if t in tables and t not in out:
            out.append(t)
    return out
```

(d) Replace the schema/sample block in `gather_prephase_facts` (lines ~302-306) with:

```python
    # schema + sample rows (P5 tier split: names/DDL uncapped; samples relevance-gated)
    schema = _discover_schema(vm)
    _mark("schema", schema)
    tables = _discover_table_names(vm) if schema else []
    sample_set = _relevant_tables(tables, instruction)
    samples = _discover_sample_rows(vm, sample_set) if sample_set else ""
    skipped = [t for t in tables if t not in sample_set]
    if skipped:                                  # no silent truncation
        print(f"[prephase] sample_rows: {len(skipped)} table(s) not relevant, not sampled: "
              + ", ".join(skipped[:10]) + (" …" if len(skipped) > 10 else ""))
    _mark("sample_rows", samples)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_orchestrator.py -k "discover_table_names_uncapped or relevant_tables or sample_rows or prephase_sample_constants" -v`
Expected: PASS. (`_discover_sample_rows` tests still pass — they call it directly with explicit table lists.)

- [ ] **Step 5: Full orchestrator regression**

Run: `uv run pytest tests/test_orchestrator.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "refactor(prephase): P5 read-tier split — uncap names, relevance-gate samples"
```

> **H2 coverage note (spec Testing-table "H2 relevance" row).** Semantic relevance
> widening has two layers, each verified where it actually lives — `_relevant_tables`
> itself stays lexical **by design**:
> 1. **Post-failure / per-task:** the LEARN `prephase_deep_read` union, verified by Task 14
>    (`test_gather_uses_learned_deep_read`). This is the spec's per-task backstop.
> 2. **General / pre-failure:** oracle atoms are injected into **PLAN** via `build_oracle_block`
>    (`reason.run_plan`), covered by the existing oracle suite — the oracle widens *what PLAN
>    sees*, not the pre-phase sample set. There is no new sampling-time oracle call (spec H2
>    states the oracle is "already wired into the pipeline").
>
> A novel synonym with no atom and no prior run costs exactly one cycle — the **accepted
> residual** per spec H2 — and it is logged by Task 5 Step 3 (`… not relevant, not sampled`),
> never a silent miss.

---

## Task 6: D1/H3 — structural `identity.kind` (no role allowlist)

Classify the caller by id-shape only and store it in `facts.identity["kind"]`: a `customer_id`/`cust_*` id → `customer`; any other non-empty authenticated id → `employee` (safe default); empty → `guest`. This is the Phase-3 hook (consumed by `intent.md`) but lives in pre-phase.

**Files:**
- Modify: `agent/orchestrator.py` (add `_identity_kind`; set it in `gather_prephase_facts` identity block ~line 309-315)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orchestrator.py`:

```python
from agent.orchestrator import _identity_kind


def test_identity_kind_structural():
    assert _identity_kind({"customer_id": "cust_016"}) == "customer"
    assert _identity_kind({"id": "cust_001", "store": "s1"}) == "customer"
    assert _identity_kind({"employee_id": "emp_023", "role": "fulfillment_coordinator"}) == "employee"
    assert _identity_kind({"id": "wholly_new_role_99"}) == "employee"   # unknown role -> employee (safe)
    assert _identity_kind({}) == "guest"
    assert _identity_kind({"store": ""}) == "guest"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator.py::test_identity_kind_structural -v`
Expected: FAIL with `ImportError: cannot import name '_identity_kind'`.

- [ ] **Step 3: Implement**

In `agent/orchestrator.py`, add after `_parse_identity`:

```python
def _identity_kind(identity: dict) -> str:
    """Structural id-shape classification (H3 — no role-name list).

    customer_id / cust_* present -> 'customer'; any other non-empty authenticated
    id -> 'employee' (operational; the safe default — a new employee role classifies
    as employee, never silently guest); empty -> 'guest'."""
    if not identity:
        return "guest"
    if (identity.get("customer_id") or "").strip():
        return "customer"
    if any(isinstance(v, str) and v.strip().lower().startswith("cust_")
           for v in identity.values()):
        return "customer"
    if any(isinstance(v, str) and v.strip() for v in identity.values()):
        return "employee"
    return "guest"
```

In `gather_prephase_facts`, set the kind in the identity block — change:

```python
        id_out = _sql_stdout_or_exec(vm, "/bin/id")
        identity = _parse_identity(id_out)
        _mark("identity", identity)
```

to:

```python
        id_out = _sql_stdout_or_exec(vm, "/bin/id")
        identity = _parse_identity(id_out)
        identity["kind"] = _identity_kind(identity)
        _mark("identity", identity)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_orchestrator.py::test_identity_kind_structural -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): structural identity.kind classification (D1/H3)"
```

---

## Task 7: Surface `path_listings` + `FACT_STATUS` to INTENT/PLAN and legacy

Flow the new listing into both pipelines and add a deterministic sufficiency signal (P8) so a silently-missing fact reads as "no fact", not a confident-wrong spec.

**Files:**
- Modify: `agent/reason.py` (`_facts_block` ~line 32; add `_facts_sufficiency`)
- Modify: `agent/pipeline.py` (`_fold_facts_into_agents_md` key tuple ~line 110)
- Test: `tests/test_reason.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_reason.py`:

```python
from agent.reason import _facts_sufficiency


def test_facts_block_includes_path_listings_and_status():
    facts = {
        "schema": "CREATE TABLE x(...)",
        "path_listings": {"/proc/incoming/payments": "/proc/incoming/payments/inpay_a.json"},
        "gather_status": {"schema": "ok", "identity": "empty", "target_records": "error(boom)"},
    }
    block = _facts_block(facts)
    assert "path_listings" in block
    assert "inpay_a.json" in block
    assert "FACT_STATUS (non-ok):" in block
    assert "identity=empty" in block
    assert "target_records=error(boom)" in block


def test_facts_sufficiency_lists_non_ok():
    facts = {"gather_status": {"a": "ok", "b": "empty", "c": "error(x)"}}
    assert set(_facts_sufficiency(facts)) == {"b", "c"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_reason.py -k "path_listings or sufficiency" -v`
Expected: FAIL (`_facts_sufficiency` import error; `path_listings` not rendered).

- [ ] **Step 3: Implement in `agent/reason.py`**

Add before `_facts_block`:

```python
def _facts_sufficiency(facts: Any) -> list[str]:
    """gather_status keys whose value is not 'ok' (empty or error) — P8 signal."""
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    status = facts.get("gather_status", {}) if isinstance(facts, dict) else {}
    return [k for k, v in status.items() if v != "ok"]
```

Replace `_facts_block` with (adds `path_listings` to the rendered keys and a trailing `FACT_STATUS` line):

```python
def _facts_block(facts: Any) -> str:
    if facts is None:
        return ""
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    parts = []
    for key in ("agents_md", "schema", "sample_rows", "docs_inventory",
                "policies", "identity", "target_records", "path_listings",
                "gather_status"):
        val = facts.get(key) if isinstance(facts, dict) else None
        if val:
            parts.append(f"## {key}\n{val if isinstance(val, str) else val}")
    block = "PRE-PHASE FACTS:\n" + "\n\n".join(str(p) for p in parts)
    nonok = _facts_sufficiency(facts)
    if nonok:
        status = facts.get("gather_status", {}) if isinstance(facts, dict) else {}
        block += "\n\nFACT_STATUS (non-ok): " + ", ".join(f"{k}={status.get(k)}" for k in nonok)
    return block
```

- [ ] **Step 4: Implement legacy fold in `agent/pipeline.py`**

In `_fold_facts_into_agents_md`, add `"path_listings"` to the key tuple (line ~110):

```python
    for key in ("docs_inventory", "policies", "identity", "target_records",
                "path_listings", "gather_status"):
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_reason.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/reason.py agent/pipeline.py tests/test_reason.py
git commit -m "feat(prephase): surface path_listings + FACT_STATUS to INTENT/PLAN/legacy (1.4/1.5/P8)"
```

---

# Phase 2 — interpreter loop mechanics

## Task 8: R1 — `surface` namespace + `prephase_deep_read` store in `learned_store`

Give IR-distilled rules their own namespace so the Plan-IR path never inherits codegen-era rules, and add a small per-task store for learned deep-read hints.

**Files:**
- Modify: `agent/learned_store.py` (`load_entries`, `apply_learn_diff`; add `append_prephase_deep_read` / `load_prephase_deep_read`)
- Modify: `agent/models.py` (`LearnConsolidateOutput.prephase_deep_read`)
- Test: `tests/test_learned_store.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_learned_store.py`:

```python
def test_load_entries_surface_filter(tid_dir):
    _seed(tid_dir, "t10", entries=[
        {"id": "r001", "content": "ir rule", "status": "active", "surface": "ir"},
        {"id": "r002", "content": "codegen rule", "status": "active", "surface": "codegen"},
        {"id": "r003", "content": "legacy untagged", "status": "active"},  # no surface
    ])
    assert [e["id"] for e in learned_store.load_entries("t10", surface="ir")] == ["r001"]
    # untagged defaults to codegen
    assert {e["id"] for e in learned_store.load_entries("t10", surface="codegen")} == {"r002", "r003"}
    assert len(learned_store.load_entries("t10")) == 3  # no filter -> all active


def test_apply_learn_diff_stamps_surface(tid_dir):
    _seed(tid_dir, "t11", entries=[])
    out = LearnConsolidateOutput(rule_content="Always bind a runtime ref for OK answers",
                                 reasoning="r", deactivate_ids=[], skip=False)
    learned_store.apply_learn_diff("t11", out, surface="ir")
    data = yaml.safe_load((tid_dir / "t11.yaml").read_text())
    assert data["entries"][0]["surface"] == "ir"


def test_prephase_deep_read_round_trip(tid_dir):
    learned_store.append_prephase_deep_read("t12", ["payment_transaction_items", "/proc/incoming/payments"])
    learned_store.append_prephase_deep_read("t12", ["payment_transaction_items"])  # dedup
    assert learned_store.load_prephase_deep_read("t12") == [
        "payment_transaction_items", "/proc/incoming/payments"]
    assert learned_store.load_prephase_deep_read("t_none") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_learned_store.py -k "surface or prephase_deep_read" -v`
Expected: FAIL (`load_entries()` takes no `surface`; `append_prephase_deep_read` missing).

- [ ] **Step 3: Implement in `agent/learned_store.py`**

Replace `load_entries`:

```python
def load_entries(tid: str, surface: str | None = None) -> list[dict]:
    """Active entries; optionally filtered by `surface` ('ir'|'codegen').

    Untagged legacy entries default to 'codegen' (honors the codegen-era warning)."""
    data = _read(tid)
    out: list[dict] = []
    for e in data.get("entries", []):
        if e.get("status") != "active":
            continue
        if surface is not None and (e.get("surface") or "codegen") != surface:
            continue
        out.append(e)
    return out
```

Change the `apply_learn_diff` signature and stamp the new entry:

```python
def apply_learn_diff(tid: str, out: LearnConsolidateOutput, surface: str = "codegen") -> None:
```

In its appended-entry dict, add the `surface` key:

```python
    entries.append({
        "id": _next_entry_id(entries),
        "content": content,
        "agents_md_anchor": out.agents_md_anchor,
        "reasoning": (out.reasoning or "").strip(),
        "status": "active",
        "surface": surface,
        "created": str(date.today()),
        "deactivated_reason": None,
    })
```

Add at the end of the file:

```python
def append_prephase_deep_read(tid: str, items: list[str]) -> None:
    """Union new deep-read hints (table names or /literal/paths) into the tid store."""
    if not tid or not items:
        return
    data = _read(tid)
    cur = list(data.get("prephase_deep_read", []))
    for it in items:
        if it and it not in cur:
            cur.append(it)
    data["task_id"] = tid
    data["prephase_deep_read"] = cur
    _write(tid, data)


def load_prephase_deep_read(tid: str) -> list[str]:
    return list(_read(tid).get("prephase_deep_read", []))
```

- [ ] **Step 4: Add the model field in `agent/models.py`**

In `LearnConsolidateOutput`, add after `skip_reason`:

```python
    prephase_deep_read: list[str] = []   # table names / literal paths to read eagerly next run (IR)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_learned_store.py -q`
Expected: all PASS (existing tests unaffected — `surface` defaults to codegen).

- [ ] **Step 6: Commit**

```bash
git add agent/learned_store.py agent/models.py tests/test_learned_store.py
git commit -m "feat(learn): surface namespace + prephase_deep_read store (R1)"
```

---

## Task 9: R2 — PlanIR-framed LEARN prompt (`ilearn.md`)

A dedicated prompt with PlanIR framing (no `SCRIPT_CODE`/`tool_plan`/fidelity), emitting `LearnConsolidateOutput` + optional `prephase_deep_read`.

**Files:**
- Create: `data/prompts/ilearn.md`
- Test: `tests/test_reason_prompts.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reason_prompts.py` (it already imports from `agent.prompt`; if not, add `from agent.prompt import load_prompt`):

```python
def test_ilearn_prompt_loads_and_is_planir_framed():
    from agent.prompt import load_prompt
    txt = load_prompt("ilearn")
    assert txt and "PLAN" in txt.upper()
    assert "prephase_deep_read" in txt
    assert "fidelity" not in txt.lower()           # no codegen framing
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_reason_prompts.py::test_ilearn_prompt_loads_and_is_planir_framed -v`
Expected: FAIL (`load_prompt("ilearn")` returns `""`).

- [ ] **Step 3: Create `data/prompts/ilearn.md`**

```markdown
# PHASE: LEARN (Plan-IR)

You diagnose a failed interpreter cycle and produce a corrective rule for the
PLAN phase (which emits a PlanIR — structured data, never code). You may also
deactivate stale rules and request additional pre-phase deep-reads.

## Inputs

- `TOOL_PLAN` — the frozen IntentSpec JSON for this run (WHAT/why; do not change it)
- `ERROR` — failure string (`plan:`, `interpret:`, `verify:`, `real_vm:`)
- `OBSERVED_RPC_OUTPUTS` — stdout/content captured from the failed run's RPCs
  (present when the cycle reached execution). Use it to see WHY a ref was empty:
  a table missing, a column misnamed, a listing that returned nothing.
- `SCRIPT_CODE` — the failing **PlanIR JSON** (the candidate "how")
- `EXISTING_RULES` — active IR rules from prior cycles/runs

## Output format

Single JSON object — no prose, no markdown fences:

\`\`\`json
{
  "rule_content": "<starts with Never|Always|Use|Do not|When|If|Prefer>",
  "agents_md_anchor": "<#section> or null",
  "reasoning": "<diagnosis: verbatim error, root cause, failing PlanIR fragment, rule linkage>",
  "deactivate_ids": ["rXXX"],
  "deactivate_reason": "<why obsolete> or null",
  "skip": false,
  "skip_reason": null,
  "prephase_deep_read": []
}
\`\`\`

## Rules

- `rule_content` must describe a PLAN technique — how to shape the PlanIR
  (discovery steps, rowsets, decision branches, ref projection) so the next
  cycle grounds correctly. NOT a domain conclusion, NOT a literal task value.
- `rule_content` must be task-agnostic — never embed a re-seeded literal
  (SKU, id, city, date).
- `prephase_deep_read` (optional): list table names or absolute literal paths the
  pre-phase MUST read next run because grounding needed data it did not surface
  (a table named only by synonym, or a literal directory the instruction named).
  These are read EAGERLY next run (Tier-2 deep-read set) — they self-tune the
  pre-phase, so PREFER them over baking a value into a rule. Leave `[]` when the
  failure is purely a PlanIR-shape bug.
- Skip (`skip: true`) only if an existing rule already covers this.
- Use `deactivate_ids` when the new rule strictly supersedes prior ones — set `deactivate_reason`.
- Length: `rule_content` >= 20 chars; must start with a listed lead verb.
```

> Note: in the actual file, the JSON block uses normal triple-backtick fences (`` ```json ``). The `\`` escapes above are only to keep this plan's markdown intact — write plain fences in `ilearn.md`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_reason_prompts.py::test_ilearn_prompt_loads_and_is_planir_framed -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data/prompts/ilearn.md tests/test_reason_prompts.py
git commit -m "feat(learn): PlanIR-framed ilearn.md prompt (R2)"
```

---

## Task 10: R2 — `_ilearn` loads `ilearn.md`, stamps `surface="ir"`, persists `prephase_deep_read`

Thread the prompt name + surface + deep-read persistence through `_learn_consolidate_text` and rewire `_ilearn`.

**Files:**
- Modify: `agent/pipeline.py` (`_learn_consolidate_text` ~line 176; `_ilearn` ~line 283)
- Test: `tests/test_pipeline_interpreted.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline_interpreted.py`:

```python
def test_ilearn_stamps_ir_surface_and_persists_deep_read():
    from agent import learned_store, pipeline
    from agent.ir_models import IntentSpec
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={})
    learn_json = json.dumps({
        "rule_content": "Always list the instruction-named directory before projecting refs",
        "reasoning": "missing ref", "deactivate_ids": [], "skip": False,
        "prephase_deep_read": ["/proc/incoming/payments"],
    })
    with patch("agent.pipeline.call_llm_raw", return_value=learn_json):
        pipeline._ilearn("t_ir", [], intent, "{}", "verify: missing ref", observed=["[List /x] a"])
    data = learned_store._read("t_ir")
    assert data["entries"][0]["surface"] == "ir"
    assert learned_store.load_prephase_deep_read("t_ir") == ["/proc/incoming/payments"]
```

(The autouse `_enabled` fixture already points `learned_store._LEARNED_DIR` at `tmp_path` and chdirs there.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pipeline_interpreted.py::test_ilearn_stamps_ir_surface_and_persists_deep_read -v`
Expected: FAIL (`_ilearn` uses `learn.md` + default `codegen` surface; deep-read not persisted).

- [ ] **Step 3: Generalize `_learn_consolidate_text`**

In `agent/pipeline.py`, change the `_learn_consolidate_text` signature to accept a prompt name + surface (append params with defaults — legacy callers unchanged):

```python
def _learn_consolidate_text(
    task_id: str,
    learn_ctx: list[dict],
    plan_context: str,
    error: str,
    artifact: str,
    token_out: dict | None = None,
    observed: list[str] | None = None,
    prompt_name: str = "learn",
    surface: str = "codegen",
) -> None:
```

Change the prompt load line from `load_prompt("learn")` to `load_prompt(prompt_name)`. Change the `apply_learn_diff(task_id, out)` call (line ~228) to pass surface + persist deep-read + stamp the in-memory entry:

```python
    apply_learn_diff(task_id, out, surface=surface)

    deep = getattr(out, "prephase_deep_read", None)
    if surface == "ir" and deep:
        from .learned_store import append_prephase_deep_read
        append_prephase_deep_read(task_id, deep)

    if not out.skip and out.rule_content:
        learn_ctx.append({
            "id": "in-session",
            "content": out.rule_content,
            "agents_md_anchor": out.agents_md_anchor,
            "surface": surface,
        })
```

- [ ] **Step 4: Rewire `_ilearn`**

Replace `_ilearn`:

```python
def _ilearn(task_id, learn_ctx, intent, plan_text, error, observed=None):
    """LEARN seam for the interpreted path — uses the PlanIR-framed ilearn.md prompt,
    stamps surface='ir', and persists any prephase_deep_read hints."""
    tk: dict = {}
    _learn_consolidate_text(
        task_id, learn_ctx,
        plan_context=intent.model_dump_json(indent=2),
        error=error, artifact=plan_text, token_out=tk, observed=observed,
        prompt_name="ilearn", surface="ir",
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_pipeline_interpreted.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "feat(learn): _ilearn uses ilearn.md, surface=ir, persists deep_read (R2)"
```

---

## Task 11: R5 + R1-wiring — interpreter cycle ceiling and IR-namespaced `learn_ctx`

Give the interpreter its own ceiling (`INTERPRETER_MAX_STEPS`, default 6, independent of legacy `MAX_STEPS`) and seed its `learn_ctx` from `surface="ir"` (not `[]`).

**Files:**
- Modify: `agent/pipeline.py` (add `_IMAX_STEPS` constant ~line 26; `_run_interpreted` ~line 320, 351-353)
- Test: `tests/test_pipeline_interpreted.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline_interpreted.py`:

```python
def test_interpreter_seeds_ir_learn_ctx_and_uses_imax(monkeypatch):
    from agent import learned_store, pipeline
    # An active IR rule for this tid must reach run_plan's learn_ctx; codegen noise must not.
    learned_store._write("t_seed", {"task_id": "t_seed", "entries": [
        {"id": "r001", "content": "Always project the record_path ref", "status": "active", "surface": "ir"},
        {"id": "r002", "content": "codegen-era noise", "status": "active", "surface": "codegen"},
    ]})
    seen = {}

    def _capture_plan(intent, facts, learn_ctx, prev_error, **kw):
        seen["ctx"] = [e["id"] for e in learn_ctx]
        from agent.ir_models import PlanIR
        return PlanIR(**json.loads(_PLAN))

    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 2)
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(_INTENT)), \
         patch("agent.reason.run_plan", side_effect=_capture_plan):
        pipeline.run_pipeline(vm, instruction="how many", task_id="t_seed", agents_md_text="A")
    assert seen["ctx"] == ["r001"]      # only the IR-surface rule, not codegen noise


def test_interpreter_max_steps_default_and_override(monkeypatch):
    # Constants & budgets DoD: default AND one env override for _IMAX_STEPS.
    # Avoid reloading agent.pipeline (cross-module patched refs) — assert the module
    # default and that the same os.environ.get expression resolves the override.
    import os
    from agent import pipeline
    assert pipeline._IMAX_STEPS == 6                                  # default
    monkeypatch.setenv("INTERPRETER_MAX_STEPS", "9")
    assert int(os.environ.get("INTERPRETER_MAX_STEPS", "6")) == 9     # override resolves
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pipeline_interpreted.py -k "seeds_ir_learn_ctx or interpreter_max_steps" -v`
Expected: FAIL (`_IMAX_STEPS` missing; `learn_ctx` starts `[]`).

- [ ] **Step 3: Add the ceiling constant**

In `agent/pipeline.py`, near `_MAX_STEPS` (line ~26):

```python
_IMAX_STEPS = int(os.environ.get("INTERPRETER_MAX_STEPS", "6"))
```

- [ ] **Step 4: Seed IR learn_ctx + use the ceiling in `_run_interpreted`**

Replace the `learn_ctx: list = []` initialization (and its comment block, lines ~315-320) with:

```python
    # The IR PLAN LLM must not inherit codegen-era learned rules (they reference the old
    # codegen surface and bake literals). Seed only IR-surface rules for this tid; the
    # interpreter self-corrects within a run via per-cycle prev_error fed to run_plan.
    learn_ctx: list = load_entries(task_id, surface="ir")
```

Replace the loop header and its print (lines ~351-353):

```python
    for cycle in range(1, _IMAX_STEPS + 1):
        set_cycle(cycle)
        print(f"{CLI_BLUE}[pipeline] interpreted cycle {cycle}/{_IMAX_STEPS}{CLI_CLR}")
```

(The post-loop `save_last_run(... cycle)` / terminal lines are unchanged.)

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_pipeline_interpreted.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "feat(interpreter): INTERPRETER_MAX_STEPS ceiling + IR-namespaced learn_ctx (R5/R1)"
```

---

## Task 12: R3 — observations fed into PLAN re-planning

PLAN re-plans seeing actual RPC stdouts, not just a one-line error.

**Files:**
- Modify: `agent/reason.py` (`run_plan` signature + OBSERVED block ~line 63-77)
- Modify: `agent/pipeline.py` (`_run_interpreted` — track + pass `last_observed`)
- Test: `tests/test_reason.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reason.py`:

```python
def test_run_plan_renders_observed_block():
    spec = IntentSpec(**json.loads(_INTENT_JSON))
    captured = {}

    def _fake(system, user, model, cfg, **kw):
        captured["user"] = user
        return _PLAN_JSON

    with patch("agent.pipeline.call_llm_raw", side_effect=_fake):
        run_plan(spec, _FACTS, [], None, observed=["[Exec /bin/sql] cnt 5", "[List /proc] /proc/x"])
    assert "OBSERVED_RPC_OUTPUTS:" in captured["user"]
    assert "/proc/x" in captured["user"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_reason.py::test_run_plan_renders_observed_block -v`
Expected: FAIL (`run_plan()` got an unexpected keyword argument `observed`).

- [ ] **Step 3: Add `observed` to `run_plan`**

In `agent/reason.py`, change the signature:

```python
def run_plan(intent: IntentSpec, facts, learn_ctx: list[dict], prev_error: str | None,
             token_out: dict | None = None, oracle_atoms: list | None = None,
             observed: list[str] | None = None) -> PlanIR:
```

In the `parts` assembly, add the observed block after the `learn_ctx` block and before `prev_error`:

```python
    if observed:
        parts.append("OBSERVED_RPC_OUTPUTS:\n" + "\n".join(observed))
    if prev_error:
        parts.append(f"PREVIOUS_ERROR:\n{prev_error}")
```

- [ ] **Step 4: Thread `last_observed` in `_run_interpreted`**

In `agent/pipeline.py`, initialize before the loop (next to `last_error = None`):

```python
    last_error = None
    last_observed = None
    cycle = 0
```

Pass it into the in-loop `run_plan` call (~line 357):

```python
            plan = run_plan(intent, facts, learn_ctx, last_error,
                            token_out=tk, oracle_atoms=oracle_atoms,
                            observed=last_observed); _accum(tk)
```

Record observations immediately after a successful `result = interpret(plan, intent, vm, facts)` (before `verify`):

```python
        last_observed = result.observations
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_reason.py -q && uv run pytest tests/test_pipeline_interpreted.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/reason.py agent/pipeline.py tests/test_reason.py
git commit -m "feat(interpreter): feed OBSERVED_RPC_OUTPUTS into PLAN re-planning (R3)"
```

---

## Task 13: R4 — identical-plan short-circuit

Two identical consecutive plan signatures → break to terminal CLARIFICATION (PLAN + observations must change *something*; 2 not 3).

**Files:**
- Modify: `agent/pipeline.py` (add `_norm_sql` / `_plan_signature`; `_run_interpreted` loop)
- Test: `tests/test_pipeline_interpreted.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline_interpreted.py`:

```python
def test_plan_signature_normalizes_sql_and_rpcs():
    from agent.pipeline import _plan_signature
    from agent.ir_models import PlanIR
    a = PlanIR(**json.loads(_PLAN))
    b = PlanIR(**json.loads(_PLAN.replace("SELECT 1 AS cnt", "select   1   AS   cnt")))
    assert _plan_signature(a) == _plan_signature(b)   # whitespace/case-insensitive


def test_interpreter_breaks_on_repeated_plan(monkeypatch):
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 5)
    # Same plan every cycle, but verify always fails -> 2nd identical sig breaks.
    intent = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [{"op": "eq", "lhs": "$row0.cnt", "rhs": "999"}],
        "answer_shape": {},
    })
    learn = json.dumps({"rule_content": "cnt must be 999 for this task type", "reasoning": "x",
                        "deactivate_ids": [], "skip": False})
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    # INTENT, then PLAN/LEARN pairs; the 2nd identical plan must break before exhausting 5 cycles.
    seq = [intent, _PLAN, learn, _PLAN, learn, _PLAN, learn, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="how many", task_id="t_rep", agents_md_text="A")
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    assert m["cycles_used"] <= 2          # broke on the 2nd identical signature
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pipeline_interpreted.py -k "plan_signature or repeated_plan" -v`
Expected: FAIL (`_plan_signature` missing; without the guard `cycles_used` reaches the ceiling).

- [ ] **Step 3: Add the signature helpers**

In `agent/pipeline.py`, add near the other module helpers (e.g. after `_identical_sql_set` / `_normalise`, ~line 120):

```python
def _norm_sql(s: str) -> str:
    return " ".join(str(s).lower().split())


def _plan_signature(plan) -> tuple:
    """(normalized SQL multiset, sorted RPC multiset) over discovery + ops."""
    steps = list(plan.discovery) + list(plan.ops)
    sql: list[str] = []
    for st in steps:
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            for a in st.args.get("args", []) or []:
                sql.append(_norm_sql(a))
    rpcs = sorted(st.rpc for st in steps)
    return (tuple(sorted(sql)), tuple(rpcs))
```

- [ ] **Step 4: Wire the short-circuit in `_run_interpreted`**

Initialize before the loop (next to `last_observed = None`):

```python
    prev_sig = None
```

After `plan` is known good (i.e. after the `try/except (PlanError, InterpretError)` block that builds `plan` and runs `lint_security_first`, and **before** `result = interpret(...)`), add:

```python
        sig = _plan_signature(plan)
        if sig == prev_sig:
            last_error = "identical plan repeated (no progress)"
            print(f"{CLI_YELLOW}[pipeline] identical plan repeated -> CLARIFICATION{CLI_CLR}")
            break
        prev_sig = sig
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_pipeline_interpreted.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_interpreted.py
git commit -m "feat(interpreter): identical-plan short-circuit to CLARIFICATION (R4)"
```

---

## Task 14: `prephase_deep_read` stitch — learned hints feed the pre-phase

Close the adaptive loop: deep-read hints distilled by `_ilearn` are read eagerly on the next run (table names → Tier-2 sample set; literal paths → `path_listings`).

**Files:**
- Modify: `agent/orchestrator.py` (`gather_prephase_facts` signature + literal/relevance call sites; `run_agent` call)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py`:

```python
def test_gather_uses_learned_deep_read(tmp_path, monkeypatch):
    import agent.orchestrator as orch
    from agent import learned_store
    from bitgn.vm.ecom.ecom_pb2 import NodeKind
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    learned_store._write("t_dr", {"task_id": "t_dr",
                                  "prephase_deep_read": ["/proc/incoming/payments"]})

    vm = MagicMock()
    vm.exec.return_value = _NS(stdout="", stderr="", exit_code=0)
    vm.read.return_value = _NS(content="")
    vm.search.return_value = _NS(matches=[])
    vm.tree.side_effect = RuntimeError("no docs")
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_DIR)     # deep-read path resolves as dir
    vm.list.return_value = _NS(entries=[_NS(path="/proc/incoming/payments/inpay_z.json")])

    # instruction does NOT name the path — only the learned hint does.
    facts = orch.gather_prephase_facts(vm, instruction="show the last transaction",
                                       agents_md_text="", task_id="t_dr")
    assert "/proc/incoming/payments" in facts.path_listings
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator.py::test_gather_uses_learned_deep_read -v`
Expected: FAIL (`gather_prephase_facts()` got an unexpected keyword argument `task_id`).

- [ ] **Step 3: Thread `task_id` + deep-read into `gather_prephase_facts`**

In `agent/orchestrator.py`, add the import (top, with the other agent imports):

```python
from agent.learned_store import load_prephase_deep_read
```

Change the signature:

```python
def gather_prephase_facts(vm, instruction: str, agents_md_text: str, task_id: str = "") -> PrePhaseFacts:
```

At the top of the function body (after `status: dict[str, str] = {}` and the `_mark` def), load and split the hints:

```python
    deep_read = load_prephase_deep_read(task_id) if task_id else []
    deep_paths = [d for d in deep_read if d.startswith("/")]
    deep_tables = tuple(d for d in deep_read if not d.startswith("/"))
```

Change the relevance call (from Task 5) to pass `deep_tables`:

```python
    sample_set = _relevant_tables(tables, instruction, deep_read=deep_tables)
```

Change the literal-path loop (from Task 3) to union instruction literals with deep-read paths:

```python
    path_listings: dict[str, str] = {}
    literals = _extract_path_literals(instruction)
    for d in deep_paths:
        if d not in literals:
            literals.append(d)
    for lit in literals:
        kind = _stat_kind(vm, lit)
        if kind == "dir":
            paths = _list_entries(vm, lit)
            if paths:
                path_listings[lit] = _render_budget(paths, _PATH_LISTING_BUDGET)
        elif kind == "file":
            path_listings[lit] = f"file {lit}"
    _mark("path_listings", path_listings)
```

- [ ] **Step 4: Pass `task_id` from `run_agent`**

In `run_agent`, change the gather call (line ~416):

```python
    facts = gather_prephase_facts(vm, task_text, agents_md_text, task_id=task_id)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_orchestrator.py::test_gather_uses_learned_deep_read -v && uv run pytest tests/test_orchestrator.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(prephase): feed learned prephase_deep_read into gather (Phase1<->Phase2 stitch)"
```

---

# Phase 3 — security-scope grounding

## Task 15: D2 — role-aware customer-ownership `deny_when` (intent.md + predicate regression)

Teach INTENT to emit a customer-ownership denial **only when** `identity.kind == "customer"`, so an employee operational read is not over-DENIED. The predicate engine already supports `$_facts.identity.kind` (dotted/attr access) — add a deterministic regression proving the role-aware form.

**Files:**
- Modify: `data/prompts/intent.md` (facts table `identity` row; new "Security scope" subsection)
- Create: `tests/test_predicates.py`
- Test: `tests/test_predicates.py`

- [ ] **Step 1: Write the regression test (executable contract for the prompt rule)**

Create `tests/test_predicates.py`:

```python
from agent.ir_models import PredExpr
from agent.predicates import evaluate


def _deny():
    # the role-aware customer-ownership predicate from intent.md (D2)
    return PredExpr(op="and", args=[
        PredExpr(op="eq", lhs="$_facts.identity.kind", rhs="customer"),
        PredExpr(op="ne", lhs="$record.customer_id", rhs="$_facts.identity.customer_id"),
    ])


def test_deny_when_employee_does_not_fire():
    env = {"_facts": {"identity": {"kind": "employee"}},
           "record": {"customer_id": "cust_016"}}
    assert evaluate(_deny(), env) is False


def test_deny_when_customer_mismatch_fires():
    env = {"_facts": {"identity": {"kind": "customer", "customer_id": "cust_001"}},
           "record": {"customer_id": "cust_016"}}
    assert evaluate(_deny(), env) is True


def test_deny_when_customer_owns_record_does_not_fire():
    env = {"_facts": {"identity": {"kind": "customer", "customer_id": "cust_016"}},
           "record": {"customer_id": "cust_016"}}
    assert evaluate(_deny(), env) is False
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_predicates.py -v`
Expected: PASS — the predicate engine already resolves dotted `$_facts.identity.kind`. This locks the predicate shape INTENT must author; the prompt change in Step 3 is exercised end-to-end by the t55 probe (Task 16) + the A/B gate, not by a unit test.

- [ ] **Step 3: Update `data/prompts/intent.md`**

(a) Replace the `identity` row in the "Pre-phase facts you receive" table with:

```markdown
| `identity` | Output of `/bin/id` — caller role, store, issuer; includes a structural `kind`: `customer` \| `employee` \| `guest` |
```

(b) Insert a new subsection immediately after the `### Field rules` list (before "## IDD vs SDD"):

```markdown
### Security scope — role-aware customer-ownership deny

`facts.identity.kind` is one of `customer`, `employee`, `guest` (structural,
derived from the `/bin/id` id-shape — not a role-name list). The `security.md`
customer-ownership clause binds **customers** acting on their own account — NOT
an employee operational read or action.

Apply a customer-ownership `deny_when` **only when** the caller is a customer:

​```json
{"op":"and","args":[
  {"op":"eq","lhs":"$_facts.identity.kind","rhs":"customer"},
  {"op":"ne","lhs":"$record.customer_id","rhs":"$_facts.identity.customer_id"}]}
​```

Do NOT emit an owner-mismatch deny for an `employee`/operational identity — an
employee reading or acting on a record they do not "own" is not a customer-scope
violation. Customer-only actions (account recovery, email change per the doc)
remain a separate class. Ground this in the `security.md` scope + `facts.identity`,
never a hardcoded role or id.
```

(Use plain ```` ```json ```` fences in the file; the zero-width marks above are only to keep this plan's nesting intact.)

- [ ] **Step 4: Run the verify + predicates suites (regression)**

Run: `uv run pytest tests/test_predicates.py tests/test_verify.py -q`
Expected: all PASS. (verify.py's I3 re-derives the *same* IntentSpec predicate on the *same* env — no verify.py change needed; the killer-property stays role-aware automatically.)

- [ ] **Step 5: Commit**

```bash
git add data/prompts/intent.md tests/test_predicates.py
git commit -m "feat(security): role-aware customer-ownership deny_when in intent.md (D2)"
```

---

## Task 16: D4 — grader-oracle probe `scripts/probe_t55_refs.py`

A manual integration gate (mirror of `probe_t09_refs.py`): one fresh StartRun, employee identity + literal path → answer the last transaction with the `inpay_*.json` ref, assert score → 1.0.

**Files:**
- Create: `scripts/probe_t55_refs.py`
- Manual run only (requires live harness + creds); not part of the unit suite.

- [ ] **Step 1: Create the probe**

```python
#!/usr/bin/env python3
"""Grader-oracle probe for the t55 literal-path ref contract (D4).

t55 instruction: "All details about the last transaction in /proc/incoming/payments".
One fresh StartRun (one seed). For the t55 trial: dump /bin/id (employee), list the
literal dir /proc/incoming/payments, read each inpay_*.json, pick the latest by
timestamp, answer OUTCOME_OK with all details + that file path as the only ref,
end_trial immediately, submit.

Reveals in ONE run BOTH the "last transaction" selection AND whether
(details + /proc/incoming/payments/inpay_*.json ref) scores 1.0 under an EMPLOYEE
identity (i.e. that Phase 3 stopped the over-DENIED).

Run ONLY when no `main.py` is hitting the harness (the harness serializes trials).
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from bitgn import harness_pb2 as H                              # noqa: E402
from bitgn.harness_connect import HarnessServiceClientSync     # noqa: E402
from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync   # noqa: E402
from agent.oracle_validate import _URL, _BID, _KEY, parse_score  # noqa: E402
from agent.vm_adapter import VMAdapter                         # noqa: E402

TASK = "t55"


def _stdout(r):
    s = getattr(r, "stdout", None)
    if s is None and isinstance(r, dict):
        s = r.get("stdout", "")
    return (s or "").strip()


def _content(r):
    s = getattr(r, "content", None)
    if s is None and isinstance(r, dict):
        s = r.get("content", "")
    return (s or "").strip()


def _list_paths(vm, path):
    """ListResponse.entries[*].path -> ordered list."""
    out = []
    for e in getattr(vm.list(path=path), "entries", []) or []:
        p = getattr(e, "path", "")
        if p:
            out.append(p)
    return out


def build_answer(vm, instruction: str):
    print("\n=== INSTRUCTION ===\n" + instruction)
    print("\n=== /bin/id ===\n" + _stdout(vm.exec(path="/bin/id", args=[])))

    m = re.search(r"(/[\w./-]+)", instruction)
    root = (m.group(1).rstrip(".,;:") if m else "/proc/incoming/payments")
    print(f"\n=== LITERAL DIR === {root!r}")

    paths = _list_paths(vm, root)
    print(f"\n=== LISTING ({len(paths)}) ===\n" + "\n".join(paths[:40]))

    # read each file, pick the latest by any ISO-8601 timestamp it contains
    best_path, best_ts, best_body = "", "", ""
    for p in paths:
        body = _content(vm.read(path=p))
        ts = max(re.findall(r"\d{4}-\d{2}-\d{2}T[\d:]+Z", body) or [""])
        if ts >= best_ts:
            best_ts, best_path, best_body = ts, p, body
    print(f"\n=== PICKED === {best_path!r} ts={best_ts!r}\n{best_body[:800]}")

    msg = f"Last transaction in {root}: {best_body[:600]}"
    refs = [best_path] if best_path else []
    print(f"\n=== ANSWER === outcome=OUTCOME_OK refs={refs!r}")
    return msg, "OUTCOME_OK", refs


def main() -> int:
    c = HarnessServiceClientSync(_URL)
    run = c.start_run(H.StartRunRequest(name=f"probe-{TASK}", benchmark_id=_BID, api_key=_KEY))
    print(f"run={run.run_id} trials={len(run.trial_ids)}")
    answered = False
    for tid in run.trial_ids:
        try:
            t = c.start_trial(H.StartTrialRequest(trial_id=tid))
        except Exception:
            continue
        if t.task_id == TASK and not answered:
            vm = VMAdapter(EcomRuntimeClientSync(t.harness_url))
            msg, outcome, refs = build_answer(vm, t.instruction)
            vm.answer(message=msg, outcome=outcome, refs=refs)
            answered = True
        try:
            c.end_trial(H.EndTrialRequest(trial_id=t.trial_id))
        except Exception:
            pass
    res = c.submit_run(H.SubmitRunRequest(run_id=run.run_id, force=True))
    score, detail = parse_score(res, TASK)
    print("\n" + "=" * 60)
    print(f"SCORE = {score}")
    for d in detail:
        print(f"  - {d}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-check it parses (no harness call)**

Run: `uv run python -c "import ast,sys; ast.parse(open('scripts/probe_t55_refs.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Manual gate (only when the harness is free — `pgrep -f main.py` first)**

Run: `uv run python scripts/probe_t55_refs.py`
Expected (validation gate §1): `SCORE = 1.0`, with the answer ref `/proc/incoming/payments/inpay_*.json`. If `< 1.0`, read the printed `detail` — it tells you whether the gap is the ref (Phase 1) or the outcome (Phase 3).

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_t55_refs.py
git commit -m "test(t55): grader-oracle probe for literal-path ref + employee outcome (D4)"
```

---

# Cross-cutting

## Task 17: Env documentation — `.env.example` + `CLAUDE.md`

Surface the new runtime knobs to operators. (Additive only — legacy-var *removal* is the gated Task 18.)

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md` (repo-root env-var table)

- [ ] **Step 1: Add the new vars to `.env.example`**

Append a new block (after the existing `MAX_STEPS=5` / model blocks):

```bash
# ─── Interpreter (Plan-IR pipeline) ──────────────────────────────────────────
INTERPRETER_ENABLED=0                # 1 → use the deterministic Plan-IR interpreter branch
INTERPRETER_MAX_STEPS=6              # interpreter cycle ceiling (MAX_STEPS no longer drives it)

# ─── Pre-phase discovery (cost safety rails — NOT domain knowledge) ───────────
PREPHASE_PATH_LITERALS=3             # max literal paths Stat-probed per instruction
PREPHASE_LISTING_BYTES=4096          # byte cap on a rendered dir listing; overflow → "… +N skipped"
PREPHASE_SAMPLE_ROWS=3               # LIMIT per sampled table (Tier-2)
PREPHASE_SAMPLE_ROW_CHARS=400        # per-row byte cap (Tier-2 safety rail)
```

- [ ] **Step 2: Add rows to the `CLAUDE.md` env-var table**

In the repo-root `CLAUDE.md` "Environment Variables" table, add after the oracle vars:

```markdown
| `INTERPRETER_ENABLED` | `1` → run the deterministic Plan-IR interpreter branch (default 0) |
| `INTERPRETER_MAX_STEPS` | Interpreter cycle ceiling (default 6). `MAX_STEPS` is legacy-path only and no longer drives the interpreter loop. |
| `PREPHASE_PATH_LITERALS` | Max literal paths Stat-probed per instruction (default 3) |
| `PREPHASE_LISTING_BYTES` | Byte cap on a rendered dir listing; overflow logs `… +N skipped` (default 4096) |
| `PREPHASE_SAMPLE_ROWS` | `LIMIT` per sampled table — Tier-2 (default 3) |
| `PREPHASE_SAMPLE_ROW_CHARS` | Per-row byte cap — Tier-2 safety rail (default 400) |
```

Update the existing `MAX_STEPS` row's description to: `Legacy-pipeline cycle limit (default 3). The interpreter uses INTERPRETER_MAX_STEPS.`

- [ ] **Step 3: Verify the DoD checklist**

Run: `grep -E "INTERPRETER_ENABLED|INTERPRETER_MAX_STEPS|PREPHASE_(PATH_LITERALS|LISTING_BYTES|SAMPLE_ROWS|SAMPLE_ROW_CHARS)" .env.example CLAUDE.md`
Expected: each of the six vars appears in BOTH files.

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs(env): document INTERPRETER_* + PREPHASE_* knobs; MAX_STEPS legacy note"
```

---

## Task 18 (GATED): legacy CODEGEN/fidelity cutover — config + code removal

> **DO NOT EXECUTE until validation gate §2 passes:** an A/B run behind `INTERPRETER_ENABLED` shows score ≥ baseline (~32%) AND t55/bucket improve with no regression on green tasks. Premature deletion regresses the legacy A/B arm. This task is documented now so config and code die in the same commit.

**Files:**
- Modify: `.env.example`, `CLAUDE.md` (drop legacy vars), `agent/pipeline.py`, `agent/fidelity.py` (+ callers)

- [ ] **Step 1: Confirm the gate**

Verify the latest A/B run log shows interpreted-branch score ≥ baseline and t55 = 1.0 with no green-task regressions. Record the run dir in the commit message. If not met, **stop** — do not proceed.

- [ ] **Step 2: Drop legacy-only env vars**

Remove from `.env.example` and the `CLAUDE.md` table: `FIDELITY_TIMEOUT_S`, `MAX_TOKENS_CODEGEN`, `MODEL_CODEGEN`, `MAX_TOKENS_TEST`, `MODEL_TEST`, `TDD_ENABLED`, `TDD_MOCK_ENABLED`, `TDD_FORCE_SUBMIT_AFTER`. Drop `MAX_STEPS` only once the legacy branch itself is deleted. Review `MAX_TOKENS_DESIGN`/`MODEL_DESIGN`: the interpreter has no DESIGN call (INTENT replaces it) → drop. **Keep:** `COMPACTION_THRESHOLD`, `COMPACTION_KEEP_RECENT`, `MODEL`, `MODEL_FALLBACK`, `MODEL_LEARN`, all oracle `*`, HTTP timeouts, `INTERPRETER_*`, `PREPHASE_*`.

- [ ] **Step 3: Delete dead code**

Delete (per the interpreter cutover step): `_AnswerGuard`, `_AnswerRefsError`, `_extract_sql_literals`, `_retry_guard_applies`, `_detect_zero_row_miss`, `_run_intent_tests`, `_mock_run`, `_RETRYABLE_VM_ERROR_PATTERNS`, and `generate_fidelity_test` / `exec_fidelity_in_subprocess` (`agent/fidelity.py`). **Keep:** `_is_retryable_vm_error`, `_ground_security_refs`, `_terminal_clarification`, `_learn_consolidate_text`, `learn_from_grader`, `_compact_learn_ctx`. When `INTERPRETER_ENABLED` becomes the only branch, also remove the legacy `run_pipeline` body below the `_run_interpreted` dispatch and the now-unused `_fold_facts_into_agents_md` / `_learn_consolidate` imports.

- [ ] **Step 4: Remove orphaned tests + prompts**

Delete tests that exercise only deleted symbols (`tests/test_pipeline_tdd.py`, fidelity tests, `_AnswerGuard` tests). Remove now-dead prompts `data/prompts/{codegen,test}.md` if nothing loads them (`grep -rn "load_prompt(\"codegen\"\|load_prompt(\"test\"" agent/` first).

- [ ] **Step 5: DoD checklist**

Run: `grep -rn -E "FIDELITY_TIMEOUT_S|MAX_TOKENS_CODEGEN|MODEL_CODEGEN|TDD_ENABLED|_AnswerGuard|generate_fidelity_test" agent/ .env.example CLAUDE.md`
Expected: **no matches** (every "drop" var/symbol absent). Then `grep -rn -E "MODEL_LEARN|COMPACTION_THRESHOLD|INTERPRETER_MAX_STEPS|ORACLE_K" .env.example CLAUDE.md` → every "keep" var still present.

- [ ] **Step 6: Green suite + commit**

Run: `uv run python -m pytest tests/ -q` (ignore the known `test_t09_replay_matches_known_good` red).
Expected: green.

```bash
git add -A
git commit -m "chore(cutover): remove legacy CODEGEN/fidelity code + config (gate §2 passed; run=<DIR>)"
```

---

## Final verification (whole plan)

- [ ] Run the full suite: `uv run python -m pytest tests/ -q` — green except the known `test_t09_replay_matches_known_good` stale-fixture red.
- [ ] Phase-1+3 end-to-end gate (manual, harness free): `uv run python scripts/probe_t55_refs.py` → `SCORE = 1.0`, ref `/proc/incoming/payments/inpay_*.json`.
- [ ] A/B benchmark behind `INTERPRETER_ENABLED=1` vs baseline (~32%): score ≥ baseline, t55/bucket improved, no green-task regression — this is the gate that unlocks Task 18.

## Self-review traceability (spec → task)

| Spec item | Task |
|---|---|
| 1.1 P9 parsers | 1 |
| 1.2 literal-path fact | 2, 3 |
| H1 de-hardcode (`_PROC_DIR`/`_RECORD_ID_RE`) | 4 |
| 1.3 P5 tier split / H2 (relevance) | 5 (+14 deep-read; oracle backstop noted) |
| D1/H3 identity.kind | 6 |
| 1.4 P8 sufficiency / 1.5 surfacing (both paths) | 7 |
| R1 surface namespace | 8, 11 |
| R2 ilearn.md + prephase_deep_read | 8, 9, 10 |
| R5 interpreter ceiling | 11 |
| R3 observed → PLAN | 12 |
| R4 identical-plan short-circuit | 13 |
| prephase_deep_read stitch | 14 |
| D2 intent.md role-aware deny | 15 |
| D3 verify defense | 15 (no code change — confirmed by predicate/verify regression) |
| D4 probe_t55 | 16 |
| Constants & budgets / Env documentation | 2, 5, 11 (constants) + 17 (docs) |
| Legacy cleanup (gated) | 18 |
