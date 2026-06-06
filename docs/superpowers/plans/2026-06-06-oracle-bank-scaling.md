---
review:
  plan_hash: b78332350d6f53c1
  spec_hash: b4e02fe299932549
  last_run: 2026-06-06
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings: []
chain:
  intent: docs/superpowers/intents/2026-06-06-oracle-bank-scaling-intent.md
  spec: docs/superpowers/specs/2026-06-06-oracle-bank-scaling-design.md
---
# Knowledge-Oracle Bank Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the knowledge-oracle vector retrieval genuinely functional — persistent embed cache, nomic task prefixes, cosine floor, DESIGN-phase injection — and add an offline distill→candidate→promote pipeline gated by a green-suite regression check, with no already-green task regressing.

**Architecture:** `agent/oracle.py` holds the atom bank + two-stage retrieval (cosine top-N → LLM re-rank). This plan: (1) persists atom vectors to `data/oracle/embeddings.json` keyed by content hash; (2) applies nomic `search_document:`/`search_query:` prefixes in `agent/llm.py:embed_texts`; (3) adds an `ORACLE_FLOOR` cosine cutoff; (4) renders retrieved atoms into the DESIGN prompt (read-only, F-001 signature preserved); (5) adds an offline `make promote` pass that activates each candidate atom, runs `source ∪ green-suite`, and promotes only when green held and source improved.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `httpx` (Ollama embeddings), `pyyaml`, pydantic. LLM routing via `agent/llm.py`. Tests mock the harness/grader — no real benchmark run inside unit tests.

---

## Background — current state (verified)

- `agent/oracle.py:KnowledgeOracle` is constructed **per task** in `pipeline.py:457`; `self._vec_cache` is in-memory and dies with the instance — every task re-embeds all atoms + query (~7 embed calls/task at bank=6).
- `agent/llm.py:embed_texts(texts, model, base_url=None)` posts raw text to Ollama `/v1/embeddings` — no nomic prefixes.
- `oracle.retrieve` reads `ORACLE_TOPN` (default 10) and `ORACLE_K` (default 4); at bank=6 top-N ≥ bank so cosine filters nothing. There is **no** cosine floor.
- `oracle._cosine_topn` returns atoms only (scores discarded after sort).
- `agent/codegen_v2.py:build_oracle_block(oracle_atoms)` renders atoms for CODEGEN; CODEGEN already receives `oracle_atoms`. DESIGN does **not**.
- `agent/design.py:run_design(instruction, agents_md_text, token_out=None)` — F-001 guard tests in `tests/test_design.py` assert `params[:2] == ["instruction","agents_md_text"]` and `"learn_ctx" not in params`.
- Auto-distill (B1) is **already wired**: `pipeline.py:146-157` calls `KnowledgeOracle().distill(...)` when `ORACLE_ENABLED!=0` and `ORACLE_DISTILL==1`. `oracle.distill` writes `status: candidate`; `_active()` already excludes candidates. This plan only adds **source-task threading** to distill (needed by promote) plus a test.
- `oracle.promote(atom_id, validated_by, validated_at)` exists and flips candidate→active in `atoms.yaml`.
- `agent/oracle_atoms.py:Atom` is a dataclass; `load_atoms`/`save_atoms` round-trip a fixed key set (`save_atoms` drops `extra`).
- `main.py:_run_one_pass(client, task_filter, train_cycle)` runs one StartRun → trials → SubmitRun and returns `(scores, result)` where each score row is `(task_id, score, detail, elapsed, token_stats)`.
- `pipeline.py:run_pipeline` constructs a fresh `KnowledgeOracle` per task that **reads `atoms.yaml` from disk** — so to make a candidate visible to a pass, its `active` status must be written to disk for the duration of that pass, then reverted.

## File Structure

| File | Change |
|------|--------|
| `agent/llm.py` | `embed_texts` gains `prefix` param; nomic-only prefix logic |
| `agent/oracle.py` | pass prefixes; persistent embed cache load/save; `ORACLE_FLOOR` cutoff |
| `agent/oracle_atoms.py` | `Atom.source_task` field; load/save round-trip |
| `agent/design.py` | accept + render `oracle_atoms` (F-001 signature preserved) |
| `agent/pipeline.py` | pass `oracle_atoms` to `run_design`; pass `source_task=task_id` to `distill` |
| `agent/promote.py` | **new** — green-suite loader, promote decision, offline promote pass |
| `main.py` | `--promote` entry wiring the harness into the promote pass |
| `Makefile` | `promote` target |
| `data/oracle/green_suite.yaml` | **new** — curated green-task manifest |
| `data/oracle/embeddings.json` | **new (generated)** — persisted vector cache |
| `tests/test_oracle_embed.py` | extend — nomic prefix applied; non-nomic raw |
| `tests/test_oracle_retrieve.py` | extend — cosine floor discards; fakes accept `prefix` |
| `tests/test_oracle_cache.py` | **new** — embed-once, persist+reload, corrupt rebuild |
| `tests/test_oracle_distill.py` | extend — `source_task` recorded |
| `tests/test_oracle_promote.py` | **new** — decision + loader + pass (harness mocked) |
| `tests/test_design.py` | extend — `oracle_atoms` does not break signature; `learn_ctx` still forbidden |

---

## Task 1: nomic task prefixes in `embed_texts`

**Files:**
- Modify: `agent/llm.py:603-616`
- Test: `tests/test_oracle_embed.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_oracle_embed.py`:

```python
def test_nomic_prefix_applied_to_inputs():
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"data": [{"embedding": [0.0]}]}
        def raise_for_status(self):
            pass

    def _fake_post(url, json, headers, timeout):
        captured["input"] = json["input"]
        return _Resp()

    with patch("agent.llm.httpx.post", side_effect=_fake_post):
        llm.embed_texts(["hello"], model="nomic-embed-text", prefix="search_query")
    assert captured["input"] == ["search_query: hello"]


def test_non_nomic_model_gets_raw_text():
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"data": [{"embedding": [0.0]}]}
        def raise_for_status(self):
            pass

    def _fake_post(url, json, headers, timeout):
        captured["input"] = json["input"]
        return _Resp()

    with patch("agent.llm.httpx.post", side_effect=_fake_post):
        llm.embed_texts(["hello"], model="mxbai-embed-large", prefix="search_query")
    assert captured["input"] == ["hello"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_oracle_embed.py -v`
Expected: FAIL — `embed_texts() got an unexpected keyword argument 'prefix'`

- [ ] **Step 3: Add the `prefix` parameter and nomic logic**

Replace `agent/llm.py:603-616` (the whole `embed_texts` function) with:

```python
def embed_texts(texts, model, base_url=None, prefix=None):
    """Return a list of embedding vectors (one per input) via the Ollama OpenAI-compat
    /v1/embeddings endpoint. Raises on HTTP error; callers handle fallback.

    `prefix` applies the nomic task-prefix convention ("search_document"/"search_query")
    only for nomic-* model ids; other models receive raw text unchanged.
    """
    import os
    base = (base_url or os.environ.get("EMBED_BASE_URL")
            or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1")
    url = base.rstrip("/") + "/embeddings"
    key = os.environ.get("OLLAMA_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    inputs = list(texts)
    if prefix and model and model.lower().startswith("nomic"):
        inputs = [f"{prefix}: {t}" for t in inputs]
    resp = httpx.post(url, json={"model": model, "input": inputs},
                      headers=headers, timeout=60.0)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [row["embedding"] for row in data]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_oracle_embed.py -v`
Expected: PASS (3 tests: existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add agent/llm.py tests/test_oracle_embed.py
git commit -m "feat(oracle): nomic task prefixes in embed_texts"
```

---

## Task 2: oracle passes nomic prefixes through retrieval

**Files:**
- Modify: `agent/oracle.py:35-50`
- Test: `tests/test_oracle_retrieve.py` (update fakes to accept `prefix`)

- [ ] **Step 1: Update existing test fakes to accept `prefix`**

In `tests/test_oracle_retrieve.py`, the fakes must accept the new kwarg. Replace the three fake signatures:

- Line 16: `def fake_embed(texts, model, base_url=None):` → `def fake_embed(texts, model, base_url=None, prefix=None):`
- Line 29: `embed_fn=lambda t, model, base_url=None: [[1.0]] * len(t)` → `embed_fn=lambda t, model, base_url=None, prefix=None: [[1.0]] * len(t)`
- Line 37: `def boom(texts, model, base_url=None):` → `def boom(texts, model, base_url=None, prefix=None):`

- [ ] **Step 2: Add a test asserting prefixes are passed**

Append to `tests/test_oracle_retrieve.py`:

```python
def test_oracle_passes_nomic_prefixes():
    calls = []

    def fake_embed(texts, model, base_url=None, prefix=None):
        calls.append((texts[0], prefix))
        return [[1.0, 0.0]] * len(texts)

    atoms = [_atom("sql", "sql binds", ["sql"])]
    o = KnowledgeOracle(atoms=atoms, embed_fn=fake_embed)
    o._cosine_topn("query text", n=1)
    prefixes = {p for _, p in calls}
    assert "search_query" in prefixes
    assert "search_document" in prefixes
```

- [ ] **Step 3: Run to verify the new test fails**

Run: `uv run pytest tests/test_oracle_retrieve.py::test_oracle_passes_nomic_prefixes -v`
Expected: FAIL — `search_query`/`search_document` not in prefixes (oracle passes no prefix)

- [ ] **Step 4: Pass prefixes from oracle**

In `agent/oracle.py`, replace `_embed_atom` (lines 35-41) and the query-embed line in `_cosine_topn` (line 44).

`_embed_atom`:

```python
    def _embed_atom(self, a: Atom):
        h = content_hash(a.content)
        if h in self._vec_cache:
            return self._vec_cache[h]
        vec = self._embed([a.content], model=self._model, prefix="search_document")[0]
        self._vec_cache[h] = vec
        return vec
```

`_cosine_topn` first line (was `qv = self._embed([query], model=self._model)[0]`):

```python
        qv = self._embed([query], model=self._model, prefix="search_query")[0]
```

- [ ] **Step 5: Run the full oracle retrieve suite**

Run: `uv run pytest tests/test_oracle_retrieve.py -v`
Expected: PASS (all, including updated fakes)

- [ ] **Step 6: Commit**

```bash
git add agent/oracle.py tests/test_oracle_retrieve.py
git commit -m "feat(oracle): pass nomic prefixes through retrieval"
```

---

## Task 3: persistent embed cache (`embeddings.json`)

**Files:**
- Modify: `agent/oracle.py:24-41` (`__init__`, `_embed_atom`)
- Test: `tests/test_oracle_cache.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_oracle_cache.py`:

```python
import json
from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom


def _atom(i, content):
    return Atom(id=i, description=content, domain=["sql"], content=content,
                source="investigation", validated_by="manual",
                validated_at="2026-06-05", status="active", embedding_hash="")


def _counting_embed(calls):
    def fn(texts, model, base_url=None, prefix=None):
        for t in texts:
            calls.append(t)
        return [[1.0, 0.0]] * len(texts)
    return fn


def test_atom_embedded_once_across_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_FLOOR", "-1")  # disable floor for this test
    emb = tmp_path / "embeddings.json"
    atoms = [_atom("a", "C:alpha")]
    calls = []

    o1 = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed(calls),
                         embeddings_path=emb)
    o1.retrieve("alpha query", k=1, rank_fn=None)

    o2 = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed(calls),
                         embeddings_path=emb)
    o2.retrieve("alpha query", k=1, rank_fn=None)

    assert calls.count("C:alpha") == 1  # cached after first instance


def test_cache_persisted_to_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_FLOOR", "-1")
    emb = tmp_path / "embeddings.json"
    atoms = [_atom("a", "C:alpha")]
    o = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed([]),
                        embeddings_path=emb)
    o.retrieve("alpha query", k=1, rank_fn=None)
    data = json.loads(emb.read_text())
    from agent.oracle_atoms import content_hash
    assert content_hash("C:alpha") in data


def test_corrupt_cache_file_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setenv("ORACLE_FLOOR", "-1")
    emb = tmp_path / "embeddings.json"
    emb.write_text("{ this is not json")
    atoms = [_atom("a", "C:alpha")]
    o = KnowledgeOracle(atoms=atoms, embed_fn=_counting_embed([]),
                        embeddings_path=emb)
    assert o._vec_cache == {}          # graceful rebuild, no crash
    out = o.retrieve("alpha query", k=1, rank_fn=None)
    assert out and out[0].id == "a"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_oracle_cache.py -v`
Expected: FAIL — `__init__() got an unexpected keyword argument 'embeddings_path'`

- [ ] **Step 3: Add persistent cache to `KnowledgeOracle`**

In `agent/oracle.py`, add the JSON import at the top (after `import os`):

```python
import json
```

Add the default path constant after `_DEFAULT_ATOMS` (line 12):

```python
_DEFAULT_EMBEDDINGS = Path(__file__).resolve().parent.parent / "data" / "oracle" / "embeddings.json"
```

Replace `__init__` (lines 25-30) with:

```python
    def __init__(self, atoms=None, atoms_path=None, embed_fn=None, embeddings_path=None):
        self._path = Path(atoms_path or _DEFAULT_ATOMS)
        self.atoms = atoms if atoms is not None else load_atoms(self._path)
        self._embed = embed_fn or llm.embed_texts
        self._model = os.environ.get("EMBED_MODEL", "nomic-embed-text")
        self._emb_path = Path(embeddings_path or _DEFAULT_EMBEDDINGS)
        self._vec_cache: dict[str, list[float]] = self._load_vec_cache()

    def _load_vec_cache(self) -> dict:
        """Load persisted atom vectors. Corrupt/missing file → empty (rebuild)."""
        try:
            data = json.loads(self._emb_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_vec_cache(self) -> None:
        """Persist atom vectors. Non-critical — failure is silently ignored."""
        try:
            self._emb_path.parent.mkdir(parents=True, exist_ok=True)
            self._emb_path.write_text(json.dumps(self._vec_cache), encoding="utf-8")
        except Exception:
            pass
```

Update `_embed_atom` to write back on miss (replace the body from Task 2):

```python
    def _embed_atom(self, a: Atom):
        h = content_hash(a.content)
        if h in self._vec_cache:
            return self._vec_cache[h]
        vec = self._embed([a.content], model=self._model, prefix="search_document")[0]
        self._vec_cache[h] = vec
        self._save_vec_cache()
        return vec
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_oracle_cache.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/oracle.py tests/test_oracle_cache.py
git commit -m "feat(oracle): persist atom embeddings to embeddings.json"
```

---

## Task 4: cosine floor (`ORACLE_FLOOR`)

**Files:**
- Modify: `agent/oracle.py:_cosine_topn`
- Test: `tests/test_oracle_retrieve.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_oracle_retrieve.py`:

```python
def test_cosine_floor_discards_subthreshold(monkeypatch):
    monkeypatch.setenv("ORACLE_FLOOR", "0.5")
    atoms = [_atom("hi", "high sim", ["sql"]),
             _atom("lo", "low sim", ["pricing"])]
    emap = {"C:high sim": [1.0, 0.0], "C:low sim": [0.0, 1.0]}

    def fake_embed(texts, model, base_url=None, prefix=None):
        return [emap.get(t, [1.0, 0.0]) for t in texts]  # query -> [1,0] (high)

    o = KnowledgeOracle(atoms=atoms, embed_fn=fake_embed)
    out = o._cosine_topn("query", n=2)
    assert [a.id for a in out] == ["hi"]   # "lo" (cosine 0.0) discarded by floor
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_oracle_retrieve.py::test_cosine_floor_discards_subthreshold -v`
Expected: FAIL — both atoms returned (`['hi', 'lo']`), no floor applied

- [ ] **Step 3: Apply the floor in `_cosine_topn`**

Replace `_cosine_topn` (was lines 43-50) with:

```python
    def _cosine_topn(self, query: str, n: int):
        qv = self._embed([query], model=self._model, prefix="search_query")[0]
        scored = []
        for a in self._active():
            sv = self._embed_atom(a)
            scored.append((_cosine(qv, sv), a))
        scored.sort(key=lambda t: t[0], reverse=True)
        floor = float(os.environ.get("ORACLE_FLOOR", "0.5"))
        kept = []
        for score, a in scored[:n]:
            if score < floor:
                print(f"[oracle] discard {a.id} cosine={score:.3f} < floor {floor}")
                continue
            kept.append(a)
        return kept
```

- [ ] **Step 4: Run the full retrieve suite**

Run: `uv run pytest tests/test_oracle_retrieve.py -v`
Expected: PASS — new floor test passes; `test_cosine_orders_by_similarity` still passes (vat cosine=1.0 ≥ 0.5 default, returned first).

- [ ] **Step 5: Commit**

```bash
git add agent/oracle.py tests/test_oracle_retrieve.py
git commit -m "feat(oracle): ORACLE_FLOOR cosine cutoff"
```

---

## Task 5: DESIGN-phase oracle injection (F-001 preserved)

**Files:**
- Modify: `agent/design.py:29-50`
- Modify: `agent/pipeline.py:475` (DESIGN call)
- Test: `tests/test_design.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_design.py`:

```python
def test_oracle_atoms_param_preserves_signature():
    """F-001: oracle_atoms is allowed but must not be positional and must not
    re-introduce learn_ctx."""
    sig = inspect.signature(run_design)
    params = list(sig.parameters.keys())
    assert "learn_ctx" not in params, params
    assert params[:2] == ["instruction", "agents_md_text"], params
    assert "oracle_atoms" in params, params


def test_oracle_block_rendered_into_design_prompt():
    from agent.oracle_atoms import Atom
    atoms = [Atom(id="sql-no-name-binds", description="d", domain=["sql"],
                  content="inline quoted literals in IN()", source="s",
                  validated_by="grader", validated_at="d", status="active",
                  embedding_hash="")]
    captured = {}

    def _fake(system, user_msg, model, cfg, **kw):
        captured["user_msg"] = user_msg
        return _GOOD_DESIGN_JSON

    with patch("agent.pipeline.call_llm_raw", side_effect=_fake):
        run_design("How many baskets?", "AGENTS.MD body", oracle_atoms=atoms)
    assert "VALIDATED KNOWLEDGE" in captured["user_msg"]
    assert "inline quoted literals" in captured["user_msg"]


def test_design_without_oracle_atoms_unchanged():
    captured = {}

    def _fake(system, user_msg, model, cfg, **kw):
        captured["user_msg"] = user_msg
        return _GOOD_DESIGN_JSON

    with patch("agent.pipeline.call_llm_raw", side_effect=_fake):
        run_design("How many baskets?", "AGENTS.MD body")
    assert "VALIDATED KNOWLEDGE" not in captured["user_msg"]
    assert captured["user_msg"].startswith("INSTRUCTION:")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_design.py -v`
Expected: FAIL — `run_design() got an unexpected keyword argument 'oracle_atoms'`

- [ ] **Step 3: Add `oracle_atoms` to `run_design`**

In `agent/design.py`, add the import after line 13 (`from .prompt import load_prompt`):

```python
from .codegen_v2 import build_oracle_block
```

Replace the `run_design` signature and body (lines 29-47, down to the `user_msg = (...)` block) with:

```python
def run_design(
    instruction: str,
    agents_md_text: str,
    token_out: dict | None = None,
    oracle_atoms: list | None = None,
) -> DesignOutput:
    """Run DESIGN phase. Returns DesignOutput or raises DesignError.

    H2/H13/H15: signature MUST NOT accept learn_ctx. `oracle_atoms` is read-only
    validated knowledge — DESIGN stays frozen-for-the-run; this is context, not
    per-cycle state.
    """
    guide = load_prompt("design") or "# PHASE: DESIGN"

    system: list[dict] = [
        {"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}},
    ]

    parts = []
    oracle_block = build_oracle_block(oracle_atoms)
    if oracle_block:
        parts.append(oracle_block)
    parts.append(f"INSTRUCTION:\n{instruction}")
    parts.append(f"AGENTS.MD:\n{agents_md_text}")
    user_msg = "\n\n".join(parts)
```

(Leave the rest of the function — `model = ...`, the `_call_llm_raw` call, parsing — unchanged.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_design.py -v`
Expected: PASS — including existing F-001 guards (`test_signature_accepts_only_two_args`, `test_stray_learn_ctx_kwarg_raises_type_error`).

- [ ] **Step 5: Wire `oracle_atoms` into the pipeline DESIGN call**

In `agent/pipeline.py:475`, replace:

```python
            design = run_design(instruction, agents_md_text, token_out=_tk)
```

with:

```python
            design = run_design(instruction, agents_md_text, token_out=_tk,
                                oracle_atoms=oracle_atoms)
```

(`oracle_atoms` is already retrieved at `pipeline.py:457` before the DESIGN loop — reuse it.)

- [ ] **Step 6: Run design + pipeline regression tests**

Run: `uv run pytest tests/test_design.py tests/test_codegen_oracle.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent/design.py agent/pipeline.py tests/test_design.py
git commit -m "feat(oracle): inject validated atoms into DESIGN prompt (F-001 preserved)"
```

---

## Task 6: `Atom.source_task` field + distill threading

**Files:**
- Modify: `agent/oracle_atoms.py` (`Atom`, `load_atoms`)
- Modify: `agent/oracle.py:distill`
- Modify: `agent/pipeline.py:151` (distill call)
- Test: `tests/test_oracle_distill.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_oracle_distill.py`:

```python
def test_distill_records_source_task(tmp_path):
    o = _o(tmp_path)
    fake = {"id": "m2", "description": "d", "domain": ["sql"],
            "content": "general method text"}
    with patch("agent.oracle.call_llm_json", return_value=fake):
        atom = o.distill(design_intent="x", error="boom", script_code="code",
                         source_task="t42")
    assert atom.source_task == "t42"
    # survives a yaml round-trip
    from agent.oracle_atoms import load_atoms
    reloaded = {a.id: a for a in load_atoms(o._path)}
    assert reloaded["m2"].source_task == "t42"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_oracle_distill.py::test_distill_records_source_task -v`
Expected: FAIL — `distill() got an unexpected keyword argument 'source_task'`

- [ ] **Step 3: Add `source_task` to `Atom` and persistence**

In `agent/oracle_atoms.py`, add the field to the `Atom` dataclass (after `embedding_hash`, line 21):

```python
    source_task: str = ""   # task_id the candidate was distilled from (promote gate)
```

In `load_atoms`, after the `known["embedding_hash"] = ...` line (line 41), add:

```python
        known["source_task"] = d.get("source_task") or ""
```

(`save_atoms` uses `asdict` and only drops `extra`, so `source_task` is written automatically.)

- [ ] **Step 4: Thread `source_task` through `distill`**

In `agent/oracle.py`, replace the `distill` method signature and the `Atom(...)` construction:

```python
    def distill(self, design_intent, error, script_code, source_task=""):
        user = (f"INTENT:\n{design_intent}\n\nERROR:\n{error}\n\n"
                f"SCRIPT:\n{(script_code or '')[:4000]}\n\nReturn the atom JSON.")
        out = call_llm_json(self._DISTILL_SYS, user,
                            os.environ.get("MODEL_LEARN") or os.environ.get("MODEL", ""))
        if not isinstance(out, dict) or not out.get("content"):
            return None
        atom = Atom(id=out["id"], description=out.get("description", ""),
                    domain=list(out.get("domain") or []), content=out["content"],
                    source="distilled", validated_by="", validated_at="",
                    status="candidate", embedding_hash=content_hash(out["content"]),
                    source_task=source_task)
        return self.add_candidate(atom)
```

- [ ] **Step 5: Pass `task_id` from the pipeline**

In `agent/pipeline.py:151-155`, replace the distill call:

```python
            KnowledgeOracle().distill(
                design_intent=getattr(design, "intent", ""),
                error=error or "",
                script_code=script_code or "",
                source_task=task_id,
            )
```

- [ ] **Step 6: Run distill + atoms tests**

Run: `uv run pytest tests/test_oracle_distill.py tests/test_oracle_atoms.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add agent/oracle_atoms.py agent/oracle.py agent/pipeline.py tests/test_oracle_distill.py
git commit -m "feat(oracle): record source_task on distilled candidate atoms"
```

---

## Task 7: green-suite manifest + loader

**Files:**
- Create: `data/oracle/green_suite.yaml`
- Create: `agent/promote.py`
- Test: `tests/test_oracle_promote.py` (new)

- [ ] **Step 1: Create the green-suite manifest**

Create `data/oracle/green_suite.yaml` (seed with current known-green tasks; reference = expected score):

```yaml
# Curated list of tasks that must NOT regress when a candidate atom is promoted.
# Explicit (not auto-derived from data/learned/) for trust control — membership
# is a one-time human decision. Each entry: task_id + reference score.
- task_id: t01
  reference: 1.0
- task_id: t51
  reference: 1.0
```

- [ ] **Step 2: Write the failing loader test**

Create `tests/test_oracle_promote.py`:

```python
import pytest
from agent.promote import load_green_suite, promote_decision


def test_load_green_suite(tmp_path):
    p = tmp_path / "green_suite.yaml"
    p.write_text(
        "- task_id: t01\n  reference: 1.0\n"
        "- task_id: t51\n  reference: 1.0\n"
    )
    suite = load_green_suite(p)
    assert suite == [("t01", 1.0), ("t51", 1.0)]


def test_load_green_suite_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_green_suite(tmp_path / "nope.yaml")
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_oracle_promote.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.promote'`

- [ ] **Step 4: Create `agent/promote.py` with the loader**

Create `agent/promote.py`:

```python
"""Offline distill→candidate→promote gate.

Activates each candidate atom, runs the task set `source ∪ green-suite`, and
promotes only when every green-suite task held its reference score AND the
candidate's source task improved. Promote is a separate offline pass (not run
on production tasks) because score is visible only post-SubmitRun.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_DEFAULT_GREEN = Path(__file__).resolve().parent.parent / "data" / "oracle" / "green_suite.yaml"


def load_green_suite(path: str | Path | None = None) -> list[tuple[str, float]]:
    """Return [(task_id, reference_score), ...]. Missing file → FileNotFoundError
    (promote must never silently proceed without its gate)."""
    p = Path(path or _DEFAULT_GREEN)
    if not p.exists():
        raise FileNotFoundError(f"green_suite manifest not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    return [(str(d["task_id"]), float(d["reference"])) for d in raw]


def promote_decision(
    run_scores: dict[str, float],
    source_task: str,
    source_baseline: float,
    green_suite: list[tuple[str, float]],
    eps: float = 1e-9,
) -> str:
    """Verdict for one candidate, given post-pass scores.

    Returns:
      "halt"       — a green-suite task dropped below its reference (regression).
      "promote"    — green held AND source improved over baseline.
      "no_improve" — green held but source did not improve.
    """
    for tid, ref in green_suite:
        if run_scores.get(tid, 0.0) + eps < ref:
            return "halt"
    if run_scores.get(source_task, 0.0) > source_baseline + eps:
        return "promote"
    return "no_improve"
```

- [ ] **Step 5: Run to verify the loader tests pass**

Run: `uv run pytest tests/test_oracle_promote.py -v`
Expected: PASS (2 loader tests)

- [ ] **Step 6: Commit**

```bash
git add data/oracle/green_suite.yaml agent/promote.py tests/test_oracle_promote.py
git commit -m "feat(promote): green-suite manifest + loader and decision"
```

---

## Task 8: promote decision unit tests

**Files:**
- Test: `tests/test_oracle_promote.py`

- [ ] **Step 1: Write the decision tests**

Append to `tests/test_oracle_promote.py`:

```python
_GREEN = [("t01", 1.0), ("t51", 1.0)]


def test_promote_when_green_held_and_source_improved():
    scores = {"t01": 1.0, "t51": 1.0, "t38": 0.8}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "promote"


def test_halt_when_green_dropped():
    scores = {"t01": 1.0, "t51": 0.6, "t38": 0.9}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "halt"


def test_no_improve_when_source_flat():
    scores = {"t01": 1.0, "t51": 1.0, "t38": 0.5}
    assert promote_decision(scores, "t38", 0.5, _GREEN) == "no_improve"


def test_missing_source_score_is_no_improve():
    scores = {"t01": 1.0, "t51": 1.0}
    assert promote_decision(scores, "t38", 0.0, _GREEN) == "no_improve"
```

- [ ] **Step 2: Run to verify they pass**

Run: `uv run pytest tests/test_oracle_promote.py -v`
Expected: PASS — `promote_decision` already implemented in Task 7.

- [ ] **Step 3: Commit**

```bash
git add tests/test_oracle_promote.py
git commit -m "test(promote): decision coverage for promote/halt/no_improve"
```

---

## Task 9: offline promote pass (`run_promote`)

**Files:**
- Modify: `agent/promote.py`
- Test: `tests/test_oracle_promote.py`

- [ ] **Step 1: Write the failing pass tests**

Append to `tests/test_oracle_promote.py`:

```python
from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom
from agent.promote import run_promote


def _oracle_with_candidate(tmp_path, source_task):
    p = tmp_path / "atoms.yaml"
    p.write_text("[]")
    o = KnowledgeOracle(atoms=[], atoms_path=p,
                        embed_fn=lambda t, model, base_url=None, prefix=None: [[1.0]] * len(t),
                        embeddings_path=tmp_path / "emb.json")
    o.atoms.append(Atom(id="cand", description="d", domain=["sql"], content="x",
                        source="distilled", validated_by="", validated_at="",
                        status="candidate", embedding_hash="", source_task=source_task))
    return o


def test_run_promote_promotes_when_green_held(tmp_path):
    o = _oracle_with_candidate(tmp_path, "t38")
    green = [("t01", 1.0)]

    def run_fn(task_ids, active_atom_id):
        # baseline pass (active=None): source low; candidate pass: source up, green held
        if active_atom_id is None:
            return {"t01": 1.0, "t38": 0.5}
        return {"t01": 1.0, "t38": 0.9}

    results = run_promote(o, green, run_fn, validated_at="2026-06-06")
    assert results == [("cand", "promote")]
    a = next(a for a in o.atoms if a.id == "cand")
    assert a.status == "active" and a.validated_at == "2026-06-06"


def test_run_promote_halts_and_keeps_candidate(tmp_path):
    o = _oracle_with_candidate(tmp_path, "t38")
    green = [("t01", 1.0)]

    def run_fn(task_ids, active_atom_id):
        if active_atom_id is None:
            return {"t01": 1.0, "t38": 0.5}
        return {"t01": 0.7, "t38": 0.9}   # green regressed

    results = run_promote(o, green, run_fn, validated_at="2026-06-06")
    assert results == [("cand", "halt")]
    a = next(a for a in o.atoms if a.id == "cand")
    assert a.status == "candidate"        # unchanged
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_oracle_promote.py -k run_promote -v`
Expected: FAIL — `cannot import name 'run_promote'`

- [ ] **Step 3: Implement `run_promote`**

Append to `agent/promote.py`:

```python
def run_promote(oracle, green_suite, run_fn, validated_at, validated_by="grader"):
    """Iterate candidate atoms; promote those that hold green + improve source.

    `run_fn(task_ids: list[str], active_atom_id: str | None) -> dict[str, float]`
    runs the harness over `task_ids` with the given candidate active (or none for
    the baseline pass) and returns {task_id: score}. Injected so unit tests need
    no real harness.

    Returns [(atom_id, verdict), ...]. On any error the candidate is left
    untouched (fail-safe: zero bank change).
    """
    candidates = [a for a in oracle.atoms if a.status == "candidate"]
    green_ids = [tid for tid, _ in green_suite]

    # A3 DoD gate-warning: promote logs the active count; crossing >10 without a
    # top-N bump is a warning (top-N must drop below bank for cosine to filter).
    active_n = len([a for a in oracle.atoms if a.status == "active"])
    print(f"[promote] active={active_n} candidates={len(candidates)}")
    if active_n > 10:
        import os
        topn = int(os.environ.get("ORACLE_TOPN", "10"))
        if topn >= active_n:
            print(f"[promote] WARNING: active={active_n} but ORACLE_TOPN={topn} — "
                  "lower ORACLE_TOPN (ceil(active*0.5)) so cosine filters.")

    results: list[tuple[str, str]] = []
    for atom in candidates:
        source_task = atom.source_task
        task_ids = sorted(set(green_ids) | ({source_task} if source_task else set()))
        try:
            baseline = run_fn(task_ids, None)
            scores = run_fn(task_ids, atom.id)
        except Exception as e:
            print(f"[promote] {atom.id}: run failed ({e}) — staying candidate")
            results.append((atom.id, "halt"))
            continue
        verdict = promote_decision(
            scores, source_task, baseline.get(source_task, 0.0), green_suite
        )
        if verdict == "promote":
            oracle.promote(atom.id, validated_by=validated_by, validated_at=validated_at)
            print(f"[promote] {atom.id}: PROMOTED (source {source_task} improved, green held)")
        else:
            print(f"[promote] {atom.id}: {verdict} — staying candidate")
        results.append((atom.id, verdict))
    return results
```

- [ ] **Step 4: Run the full promote suite**

Run: `uv run pytest tests/test_oracle_promote.py -v`
Expected: PASS (all loader + decision + run_promote tests)

- [ ] **Step 5: Commit**

```bash
git add agent/promote.py tests/test_oracle_promote.py
git commit -m "feat(promote): offline run_promote pass over source ∪ green-suite"
```

---

## Task 10: `make promote` entry wiring the harness

**Files:**
- Modify: `main.py` (add `_promote_entry`, dispatch on `--promote`)
- Modify: `Makefile` (add `promote` target)

This task is integration glue over the real harness; it is verified by the E2E run in Task 12 (unit tests already cover the pure pieces in Tasks 7–9).

- [ ] **Step 1: Add the promote entry to `main.py`**

In `main.py`, add this function just above `if __name__ == "__main__":` (line 401):

```python
def _promote_entry() -> None:
    """Offline promote gate. Activates each candidate atom on disk for the
    duration of a pass over `source ∪ green-suite`, then promotes or reverts.

    Run via `make promote` (sets argv to ['--promote']).
    """
    import datetime as _dt
    from agent.oracle import KnowledgeOracle
    from agent.oracle_atoms import save_atoms
    from agent.promote import load_green_suite, run_promote

    oracle = KnowledgeOracle()
    try:
        green_suite = load_green_suite()
    except FileNotFoundError as e:
        print(f"{CLI_RED}[promote] {e} — aborting (no silent promote){CLI_CLR}")
        return

    client = HarnessServiceClientSync(BITGN_URL)

    def run_fn(task_ids, active_atom_id):
        # Activation must be visible to the per-task pipeline, which reads
        # atoms.yaml from disk — so toggle on disk, run, then revert.
        original = {a.id: a.status for a in oracle.atoms}
        try:
            for a in oracle.atoms:
                if a.id == active_atom_id and a.status == "candidate":
                    a.status = "active"
            save_atoms(oracle._path, oracle.atoms)
            scores, _ = _run_one_pass(client, list(task_ids), train_cycle=1)
            return {tid: score for tid, score, *_ in scores}
        finally:
            for a in oracle.atoms:
                a.status = original.get(a.id, a.status)
            save_atoms(oracle._path, oracle.atoms)

    results = run_promote(
        oracle, green_suite, run_fn,
        validated_at=_dt.date.today().isoformat(),
    )
    print(f"{CLI_BLUE}[promote] results: {results}{CLI_CLR}")
```

- [ ] **Step 2: Dispatch on `--promote`**

In `main.py`, replace the `if __name__ == "__main__":` block (lines 401-402):

```python
if __name__ == "__main__":
    if "--promote" in sys.argv[1:]:
        _promote_entry()
    else:
        main()
```

- [ ] **Step 3: Add the Makefile target**

In `Makefile`, add `promote` to `.PHONY` (line 4) and append a target:

```makefile
.PHONY: sync run task graph-health promote
```

```makefile
promote:
	uv run python main.py --promote
```

- [ ] **Step 4: Verify the module imports cleanly (no run)**

Run: `uv run python -c "import main; print(hasattr(main, '_promote_entry'))"`
Expected: prints `True` (no import error). Note: importing `main` runs `_setup_logging()` — this only creates a `logs/` dir, no harness call.

- [ ] **Step 5: Commit**

```bash
git add main.py Makefile
git commit -m "feat(promote): make promote entry wiring harness into gate"
```

---

## Task 11: full unit-test regression sweep

**Files:** none (verification only)

- [ ] **Step 1: Run the whole oracle + design + pipeline test surface**

Run:
```bash
uv run pytest tests/test_oracle_embed.py tests/test_oracle_retrieve.py \
  tests/test_oracle_cache.py tests/test_oracle_distill.py \
  tests/test_oracle_promote.py tests/test_oracle_atoms.py \
  tests/test_codegen_oracle.py tests/test_design.py -v
```
Expected: PASS (all)

- [ ] **Step 2: Run the complete suite to catch collateral breakage**

Run: `uv run pytest tests/ -q`
Expected: PASS (no regressions). If anything fails, fix before proceeding — do not mark complete with failing tests.

- [ ] **Step 3: Commit (only if fixes were needed)**

```bash
git add -A
git commit -m "test(oracle): regression sweep for bank-scaling changes"
```

---

## Task 12: E2E verification (intent Done-criteria)

**Files:** none (manual verification, per spec C3)

This task requires a live harness/Ollama embeddings endpoint and is the spec's E2E gate. Do not fabricate results — record actual output.

- [ ] **Step 1: Confirm at least one candidate atom exists**

Run: `uv run python -c "from agent.oracle import KnowledgeOracle as K; print([a.id for a in K().atoms if a.status=='candidate'])"`
Expected: a non-empty list. If empty, enable auto-distill (`ORACLE_DISTILL=1`) and run a failing task once, or hand-add a `status: candidate` atom with a `source_task` to `data/oracle/atoms.yaml`.

- [ ] **Step 2: Run the promote gate**

Run: `make promote`
Expected: logs `[promote] active=N candidates=M`, a baseline + candidate pass per candidate, and a final `[promote] results: [...]`. Green-suite tasks must hold their reference; a held+improved candidate flips to `status: active` in `data/oracle/atoms.yaml`.

- [ ] **Step 3: Confirm no silent promotion on a missing manifest**

Run: `mv data/oracle/green_suite.yaml /tmp/gs.yaml && make promote; mv /tmp/gs.yaml data/oracle/green_suite.yaml`
Expected: prints `[promote] ... green_suite manifest not found ... aborting (no silent promote)` and makes zero changes to `atoms.yaml`.

- [ ] **Step 4: Full benchmark run — no regression**

Run: `uv run python main.py` (≈3h)
Expected: final score ≥ baseline 32.32%, green tasks (t01, t51, …) held. Record the score.

- [ ] **Step 5: Update memory + docs**

Per CLAUDE.md maintenance rule, after this non-trivial change run `graphify` and `update-docs`, and update the project memory (`project_knowledge_oracle.md`) with the bank-scaling outcome and the final score.

---

## Self-Review notes

- **Spec coverage:** A1 (Task 3), A2 (Tasks 1–2), A3 floor (Task 4) + top-N DoD warning (Task 9 `run_promote`), A4 (Task 5). B1 auto-distill already wired — only `source_task` added (Task 6). B2 (Task 7), B3 decision/loader/pass (Tasks 7–9) + harness glue (Task 10), B4 is design rationale (no code). C1 error handling: corrupt cache rebuild (Task 3), nomic prefix preserves fallback (existing `retrieve` catch, unchanged), missing manifest halt (Tasks 7 & 12), DESIGN empty/exception unchanged (Task 5 — empty `oracle_atoms` → no block). C2 tests all present. C3 verification (Task 12).
- **Type consistency:** `run_fn(task_ids, active_atom_id)` signature identical in `run_promote`, its tests, and `main._promote_entry`. `promote_decision(run_scores, source_task, source_baseline, green_suite)` consistent across Tasks 7–9. `embed_fn` fakes carry `prefix=None` everywhere after Task 2.
- **Note (not a code change):** `data/oracle/embeddings.json` is a generated cache. It is written under `data/oracle/`; left untracked-vs-committed to the implementer's discretion — no `.gitignore` edit is in scope.
