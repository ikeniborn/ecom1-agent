# Knowledge-Oracle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a general, validated knowledge-atom bank with two-stage semantic retrieval that augments CODEGEN, so agent knowledge generalizes across re-seeded runs instead of overfitting per-task LEARN rules.

**Architecture:** Sidecar module `agent/oracle.py` owns atoms (`data/oracle/atoms.yaml`), an in-memory numpy cosine index over Ollama embeddings (cached on disk), and a two-stage `retrieve` (cosine recall → LLM re-rank). A grader-oracle harness (`agent/oracle_validate.py`) confirms atoms before they go `active`. The pipeline retrieves atoms before CODEGEN and distills new candidate atoms after LEARN. The per-task LEARN store is untouched (augmentation).

**Tech Stack:** Python 3.12, `uv`, `numpy`, Ollama embeddings API, existing `agent/llm.py` LLM routing, `pytest`.

**Spec:** [2026-06-05-knowledge-oracle-design.md](../specs/2026-06-05-knowledge-oracle-design.md)

---

## File Structure

- Create `agent/oracle.py` — `KnowledgeOracle`: load/embed/cache atoms, `retrieve`, `distill`, `validate`, `promote`.
- Create `agent/oracle_atoms.py` — `Atom` dataclass + YAML load/save + content hashing (kept separate so oracle.py stays focused).
- Create `agent/oracle_validate.py` — grader-oracle harness (StartRun→answer→SubmitRun→score).
- Create `data/oracle/atoms.yaml` — seeded atom bank.
- Create `scripts/migrate_rules_to_atoms.py` — one-off distill of existing per-task rules.
- Modify `agent/llm.py` — add `embed_texts(texts, model, base_url)`.
- Modify `agent/codegen_v2.py` — `run_codegen(..., oracle_atoms=None)`, inject `VALIDATED KNOWLEDGE` block.
- Modify `agent/pipeline.py` — retrieve atoms before CODEGEN loop; call `oracle.distill` after LEARN.
- Modify `pyproject.toml` — add `numpy` dependency.
- Modify `models.json.example`, `.env.example`, `CLAUDE.md` — config docs.
- Tests: `tests/test_oracle_atoms.py`, `tests/test_oracle_embed.py`, `tests/test_oracle_retrieve.py`, `tests/test_oracle_distill.py`, `tests/test_codegen_oracle.py`.

---

## Task 1: Dependency + package scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `data/oracle/.gitkeep`

- [ ] **Step 1: Add numpy to dependencies**

In `pyproject.toml`, under `[project] dependencies`, add `"numpy>=1.26"` to the list.

- [ ] **Step 2: Sync**

Run: `uv sync`
Expected: resolves and installs numpy, exit 0.

- [ ] **Step 3: Create oracle data dir**

Run: `mkdir -p data/oracle && touch data/oracle/.gitkeep`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock data/oracle/.gitkeep
git commit -m "build: add numpy dep and data/oracle scaffold for knowledge-oracle"
```

---

## Task 2: Atom model + YAML store

**Files:**
- Create: `agent/oracle_atoms.py`
- Test: `tests/test_oracle_atoms.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_atoms.py
import textwrap
from agent.oracle_atoms import Atom, load_atoms, save_atoms, content_hash


def test_load_parses_atoms(tmp_path):
    p = tmp_path / "atoms.yaml"
    p.write_text(textwrap.dedent("""
        - id: sql-no-name-binds
          description: "no :name binds"
          domain: [sql, vm-io]
          content: "inline literals"
          source: investigation
          validated_by: manual
          validated_at: '2026-06-05'
          status: active
          embedding_hash: deadbeef
    """))
    atoms = load_atoms(p)
    assert len(atoms) == 1
    a = atoms[0]
    assert a.id == "sql-no-name-binds"
    assert a.domain == ["sql", "vm-io"]
    assert a.status == "active"


def test_content_hash_changes_with_content():
    assert content_hash("a") != content_hash("b")
    assert content_hash("a") == content_hash("a")


def test_active_filter():
    atoms = [
        Atom(id="x", description="d", domain=[], content="c", source="s",
             validated_by="manual", validated_at="2026-06-05", status="active",
             embedding_hash=""),
        Atom(id="y", description="d", domain=[], content="c", source="s",
             validated_by="manual", validated_at="2026-06-05", status="candidate",
             embedding_hash=""),
    ]
    assert [a.id for a in atoms if a.status == "active"] == ["x"]


def test_save_roundtrip(tmp_path):
    p = tmp_path / "atoms.yaml"
    atoms = [Atom(id="x", description="d", domain=["sql"], content="c", source="s",
                  validated_by="manual", validated_at="2026-06-05", status="active",
                  embedding_hash="h")]
    save_atoms(p, atoms)
    again = load_atoms(p)
    assert again[0].id == "x" and again[0].domain == ["sql"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_atoms.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.oracle_atoms'`.

- [ ] **Step 3: Write the implementation**

```python
# agent/oracle_atoms.py
"""Atom model + YAML persistence for the knowledge oracle."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml


@dataclass
class Atom:
    id: str
    description: str
    domain: list[str]
    content: str
    source: str            # investigation | distilled | verdict
    validated_by: str      # manual | grader | fidelity
    validated_at: str
    status: str            # active | candidate
    embedding_hash: str = ""
    extra: dict = field(default_factory=dict)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_atoms(path: str | Path) -> list[Atom]:
    p = Path(path)
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    atoms: list[Atom] = []
    for d in raw:
        known = {k: d.get(k) for k in (
            "id", "description", "content", "source", "validated_by",
            "validated_at", "status", "embedding_hash")}
        known["domain"] = list(d.get("domain") or [])
        known["embedding_hash"] = d.get("embedding_hash") or ""
        atoms.append(Atom(**known))
    return atoms


def save_atoms(path: str | Path, atoms: list[Atom]) -> None:
    out = []
    for a in atoms:
        d = asdict(a)
        d.pop("extra", None)
        out.append(d)
    Path(path).write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oracle_atoms.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/oracle_atoms.py tests/test_oracle_atoms.py
git commit -m "feat(oracle): Atom model + YAML store"
```

---

## Task 3: Embedding client in llm.py

**Files:**
- Modify: `agent/llm.py`
- Test: `tests/test_oracle_embed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_embed.py
from unittest.mock import patch
import agent.llm as llm


def test_embed_texts_calls_ollama_and_returns_vectors():
    fake = {"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]}

    class _Resp:
        status_code = 200
        def json(self):
            return fake
        def raise_for_status(self):
            pass

    with patch("agent.llm.httpx.post", return_value=_Resp()) as post:
        vecs = llm.embed_texts(["a", "b"], model="nomic-embed-text",
                               base_url="http://localhost:11434/v1")
    assert vecs == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert post.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_embed.py -v`
Expected: FAIL with `AttributeError: module 'agent.llm' has no attribute 'embed_texts'`.

- [ ] **Step 3: Write the implementation**

Add to `agent/llm.py` (ensure `import httpx` exists at top; if not, add it):

```python
def embed_texts(texts, model, base_url=None):
    """Return a list of embedding vectors (one per input) via the Ollama OpenAI-compat
    /v1/embeddings endpoint. Raises on HTTP error; callers handle fallback."""
    import os
    base = (base_url or os.environ.get("EMBED_BASE_URL")
            or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1")
    url = base.rstrip("/") + "/embeddings"
    key = os.environ.get("OLLAMA_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    resp = httpx.post(url, json={"model": model, "input": list(texts)},
                      headers=headers, timeout=60.0)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [row["embedding"] for row in data]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oracle_embed.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/llm.py tests/test_oracle_embed.py
git commit -m "feat(oracle): embed_texts via Ollama embeddings endpoint"
```

---

## Task 4: Cosine retrieval + embedding cache

**Files:**
- Create: `agent/oracle.py` (partial — retrieval core)
- Test: `tests/test_oracle_retrieve.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_retrieve.py
from unittest.mock import patch
from agent.oracle_atoms import Atom
from agent.oracle import KnowledgeOracle


def _atom(i, desc, dom):
    return Atom(id=i, description=desc, domain=dom, content="C:" + desc,
                source="investigation", validated_by="manual",
                validated_at="2026-06-05", status="active", embedding_hash="")


def test_cosine_orders_by_similarity():
    atoms = [_atom("sql", "sql binds", ["sql"]),
             _atom("vat", "vat ex-vat pricing", ["pricing"])]
    # query vector closest to atom 'vat'
    emap = {"sql binds": [1.0, 0.0], "vat ex-vat pricing": [0.0, 1.0]}

    def fake_embed(texts, model, base_url=None):
        return [emap.get(t, [0.0, 1.0]) for t in texts]  # query -> [0,1] (vat)

    o = KnowledgeOracle(atoms=atoms, embed_fn=fake_embed)
    out = o._cosine_topn("how to compute ex-VAT total", n=2)
    assert out[0].id == "vat"


def test_candidate_atoms_excluded():
    atoms = [_atom("a", "x", []),
             Atom(id="b", description="y", domain=[], content="c",
                  source="s", validated_by="manual", validated_at="d",
                  status="candidate", embedding_hash="")]
    o = KnowledgeOracle(atoms=atoms, embed_fn=lambda t, model, base_url=None: [[1.0]] * len(t))
    assert all(a.status == "active" for a in o._active())
    assert [a.id for a in o._active()] == ["a"]


def test_retrieve_falls_back_to_tags_when_embed_down():
    atoms = [_atom("sql", "sql binds", ["sql"]), _atom("vat", "vat", ["pricing"])]

    def boom(texts, model, base_url=None):
        raise RuntimeError("ollama down")

    o = KnowledgeOracle(atoms=atoms, embed_fn=boom)
    out = o.retrieve("sql query help", k=1, rank_fn=None)
    # tag/keyword fallback should still surface the sql atom
    assert out and out[0].id == "sql"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_retrieve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.oracle'`.

- [ ] **Step 3: Write the implementation**

```python
# agent/oracle.py
"""Knowledge oracle: validated atom bank + two-stage semantic retrieval."""
from __future__ import annotations

import math
import os
from pathlib import Path

from .oracle_atoms import Atom, load_atoms, content_hash
from . import llm

_DEFAULT_ATOMS = Path(__file__).resolve().parent.parent / "data" / "oracle" / "atoms.yaml"


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class KnowledgeOracle:
    def __init__(self, atoms=None, atoms_path=None, embed_fn=None):
        self._path = Path(atoms_path or _DEFAULT_ATOMS)
        self.atoms = atoms if atoms is not None else load_atoms(self._path)
        self._embed = embed_fn or llm.embed_texts
        self._model = os.environ.get("EMBED_MODEL", "nomic-embed-text")
        self._vec_cache: dict[str, list[float]] = {}

    def _active(self):
        return [a for a in self.atoms if a.status == "active"]

    def _embed_atom(self, a: Atom):
        h = content_hash(a.content)
        if h in self._vec_cache:
            return self._vec_cache[h]
        vec = self._embed([a.content], model=self._model)[0]
        self._vec_cache[h] = vec
        return vec

    def _cosine_topn(self, query: str, n: int):
        qv = self._embed([query], model=self._model)[0]
        scored = []
        for a in self._active():
            sv = self._embed_atom(a)
            scored.append((_cosine(qv, sv), a))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [a for _, a in scored[:n]]

    def _tag_fallback(self, query: str, n: int):
        q = query.lower()
        scored = []
        for a in self._active():
            score = sum(1 for tag in a.domain if tag.lower() in q)
            score += sum(1 for w in a.description.lower().split() if w in q)
            scored.append((score, a))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [a for s, a in scored[:n] if s > 0]

    def retrieve(self, task_text: str, k=None, rank_fn="default"):
        if os.environ.get("ORACLE_ENABLED", "1") == "0":
            return []
        k = k or int(os.environ.get("ORACLE_K", "4"))
        topn = int(os.environ.get("ORACLE_TOPN", "10"))
        try:
            cands = self._cosine_topn(task_text, topn)
        except Exception:
            return self._tag_fallback(task_text, k)
        if not cands:
            return []
        if rank_fn is None or os.environ.get("ORACLE_RANK_ENABLED", "1") == "0":
            return cands[:k]
        if rank_fn == "default":
            from .oracle_rank import llm_rerank
            rank_fn = llm_rerank
        try:
            return rank_fn(task_text, cands, k)[:k]
        except Exception:
            return cands[:k]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oracle_retrieve.py -v`
Expected: PASS (3 tests). `rank_fn=None` path used so `oracle_rank` import is skipped.

- [ ] **Step 5: Commit**

```bash
git add agent/oracle.py tests/test_oracle_retrieve.py
git commit -m "feat(oracle): cosine recall + tag fallback retrieval"
```

---

## Task 5: LLM re-rank (stage 2)

**Files:**
- Create: `agent/oracle_rank.py`
- Test: `tests/test_oracle_rank.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_rank.py
from unittest.mock import patch
from agent.oracle_atoms import Atom
from agent.oracle_rank import llm_rerank


def _a(i):
    return Atom(id=i, description=i + " desc", domain=[], content="c",
                source="s", validated_by="manual", validated_at="d",
                status="active", embedding_hash="")


def test_rerank_keeps_ids_returned_by_llm():
    cands = [_a("alpha"), _a("beta"), _a("gamma")]
    with patch("agent.oracle_rank.call_llm_json", return_value={"keep": ["gamma", "alpha"]}):
        out = llm_rerank("task", cands, k=2)
    assert [a.id for a in out] == ["gamma", "alpha"]


def test_rerank_ignores_unknown_ids():
    cands = [_a("alpha"), _a("beta")]
    with patch("agent.oracle_rank.call_llm_json", return_value={"keep": ["zzz", "beta"]}):
        out = llm_rerank("task", cands, k=2)
    assert [a.id for a in out] == ["beta"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_rank.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.oracle_rank'`.

- [ ] **Step 3: Add a JSON-LLM helper to `agent/llm.py`**

`agent/llm.py` has no JSON helper — the codebase pattern is `call_llm_raw(...)` → text →
`_extract_json_from_text(...)` (see `agent/design.py`). Add a thin wrapper so oracle modules
have one stable call. Append to `agent/llm.py`:

```python
def call_llm_json(system, user_msg, model, max_tokens=1024, token_out=None):
    """Call the LLM and parse a JSON object from the reply. Returns {} on failure."""
    from .json_extract import _extract_json_from_text
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=max_tokens, token_out=token_out)
    if not raw:
        return {}
    obj = _extract_json_from_text(raw)
    return obj if isinstance(obj, dict) else {}
```

- [ ] **Step 4: Write the re-rank implementation**

```python
# agent/oracle_rank.py
"""Stage-2 LLM re-rank of cosine candidate atoms."""
from __future__ import annotations

import os

from .llm import call_llm_json

_SYS = (
    "You select which knowledge snippets are RELEVANT to a coding task. "
    "Return JSON {\"keep\": [ids]} listing only the ids whose content would help "
    "write the task's script, most relevant first."
)


def llm_rerank(task_text, candidates, k):
    catalog = "\n".join(f"- {a.id}: {a.description}" for a in candidates)
    user = (f"TASK:\n{task_text}\n\nCANDIDATE KNOWLEDGE:\n{catalog}\n\n"
            f"Return at most {k} ids in JSON {{\"keep\": [...]}}.")
    model = os.environ.get("MODEL_RANK") or os.environ.get("MODEL", "")
    out = call_llm_json(_SYS, user, model)
    keep = list(out.get("keep", [])) if isinstance(out, dict) else []
    by_id = {a.id: a for a in candidates}
    return [by_id[i] for i in keep if i in by_id]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_oracle_rank.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add agent/llm.py agent/oracle_rank.py tests/test_oracle_rank.py
git commit -m "feat(oracle): call_llm_json helper + stage-2 LLM re-rank"
```

---

## Task 6: Seed the atom bank

**Files:**
- Create: `data/oracle/atoms.yaml`
- Test: `tests/test_oracle_seed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_seed.py
from agent.oracle_atoms import load_atoms

PATH = "data/oracle/atoms.yaml"


def test_seed_atoms_present_and_valid():
    atoms = load_atoms(PATH)
    ids = {a.id for a in atoms}
    for required in {"fraud-impossible-travel", "sql-no-name-binds",
                     "catalog-price-ex-vat", "never-read-directory"}:
        assert required in ids, f"missing seed atom {required}"
    for a in atoms:
        assert a.content.strip()
        assert a.status in {"active", "candidate"}
        # no hardcoded seed values
        assert "dev_" not in a.content and "cust_" not in a.content


def test_no_task_ids_in_atoms():
    for a in load_atoms(PATH):
        assert "t38" not in a.id and "t51" not in a.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_seed.py -v`
Expected: FAIL (atoms.yaml missing → empty list → assertion error).

- [ ] **Step 3: Write the seed file**

```yaml
# data/oracle/atoms.yaml
- id: fraud-impossible-travel
  description: "Archived-payment fraud = single-device impossible travel; flag the account's far-from-home payments"
  domain: [payments, fraud, sql]
  content: >
    Archived-payment fraud review has no /docs fraud policy and no fraud flag on payment
    records — it is geographic-anomaly detection over payment_transactions JOIN
    customer_accounts (which has home_latitude/home_longitude). Step 1: identify the single
    compromised account = the customer owning ONE device_fingerprint that shows impossible
    travel: per device, order archived rows (is_archived_basket_reference=1) by
    payment_created_at and compute consecutive-leg
    (ABS(observed_latitude-LAG(observed_latitude))+ABS(observed_longitude-LAG(observed_longitude)))
    / NULLIF((julianday(payment_created_at)-julianday(LAG(payment_created_at)))*24.0,0) deg/hr;
    the fraud device has MAX abs deg/hr impossibly high (>5). Customers with multi-DEVICE
    spread are red herrings. Step 2: flag that customer's archived payments far from the
    registered home (ABS(obs_lat-home_lat)+ABS(obs_lon-home_lon) > 0.5); the at-home payments
    are the genuine cardholder. Cite record_path of the flagged rows; cite /docs/security.md.
  source: investigation
  validated_by: manual
  validated_at: '2026-06-05'
  status: active
  embedding_hash: ''
- id: sql-no-name-binds
  description: "/bin/sql rejects :name binds; inline single-quoted literals in IN()"
  domain: [sql, vm-io]
  content: >
    The /bin/sql tool does not accept :name bind parameters passed as
    args=[sql, 'name=value'] — it returns exit_code 1 'missing named argument' and zero rows.
    Always inline values as single-quoted SQL string literals, e.g.
    WHERE product_sku IN ('AAA-111','BBB-222').
  source: investigation
  validated_by: manual
  validated_at: '2026-06-05'
  status: active
  embedding_hash: ''
- id: catalog-price-ex-vat
  description: "catalogue price_cents is ex-VAT (net); no VAT division for ex-VAT totals"
  domain: [pricing, sql]
  content: >
    Per /docs/discounts.md the basket subtotal is computed directly from catalogue
    product_variants.price_cents, so price_cents is ex-VAT (net). For ex-VAT comparisons,
    today_ex = SUM(qty*price_cents)/100 with NO division by (1+vat). The receipt SUBTOTAL is
    already the ex-VAT total and the VAT rate is printed on the receipt, not in /docs — do not
    search /docs for VAT.
  source: investigation
  validated_by: manual
  validated_at: '2026-06-05'
  status: active
  embedding_hash: ''
- id: never-read-directory
  description: "Never vm.read a directory path; list then read the file entry"
  domain: [vm-io]
  content: >
    vm.read on a directory path (e.g. '/uploads/') raises 'read failed: is a directory' and
    aborts the script. Always vm.list the directory, pick the FILE entry (kind FILE or a name
    with an extension), and vm.read that exact file path. When a planned read path is resolved
    from an empty Search/List, fall back to a known regular file rather than a directory root.
  source: investigation
  validated_by: manual
  validated_at: '2026-06-05'
  status: active
  embedding_hash: ''
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oracle_seed.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add data/oracle/atoms.yaml tests/test_oracle_seed.py
git commit -m "feat(oracle): seed atom bank from session investigation"
```

---

## Task 7: CODEGEN integration

**Files:**
- Modify: `agent/codegen_v2.py`
- Test: `tests/test_codegen_oracle.py`

- [ ] **Step 1: Inspect current signature**

Run: `grep -n "def run_codegen" agent/codegen_v2.py`
Note the exact existing parameters so the new `oracle_atoms` param is appended last with a default, preserving all current callers.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_codegen_oracle.py
from agent.codegen_v2 import build_oracle_block
from agent.oracle_atoms import Atom


def test_block_lists_atom_content():
    atoms = [Atom(id="sql-no-name-binds", description="d", domain=["sql"],
                  content="inline quoted literals in IN()", source="s",
                  validated_by="grader", validated_at="d", status="active",
                  embedding_hash="")]
    block = build_oracle_block(atoms)
    assert "VALIDATED KNOWLEDGE" in block
    assert "inline quoted literals" in block


def test_empty_atoms_yields_empty_block():
    assert build_oracle_block([]) == ""
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_codegen_oracle.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_oracle_block'`.

- [ ] **Step 4: Write the implementation**

Add to `agent/codegen_v2.py`:

```python
def build_oracle_block(oracle_atoms):
    """Render retrieved knowledge atoms as a context block for CODEGEN."""
    if not oracle_atoms:
        return ""
    lines = ["## VALIDATED KNOWLEDGE (apply when relevant; verified methods)"]
    for a in oracle_atoms:
        lines.append(f"- ({', '.join(a.domain)}) {a.content.strip()}")
    return "\n".join(lines)
```

Then update `run_codegen` to accept and use it. Add `oracle_atoms=None` as the final parameter, and where the learn-context / prompt is assembled, prepend the block:

```python
def run_codegen(design, learn_ctx, prev_error=None, token_out=None, oracle_atoms=None):
    oracle_block = build_oracle_block(oracle_atoms)
    # ... existing assembly; include `oracle_block` at the top of the user/context
    # message that already carries learn_ctx, e.g.:
    #   context = "\n\n".join(filter(None, [oracle_block, learn_block, prev_error_block]))
```

Locate the existing context assembly (the variable that concatenates `learn_ctx`/`prev_error`) and add `oracle_block` as the first non-empty element via `filter(None, [...])`. Do not remove existing elements.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_codegen_oracle.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run full suite (no regressions)**

Run: `uv run pytest tests/ -q`
Expected: all pass (esp. `tests/test_design.py`).

- [ ] **Step 7: Commit**

```bash
git add agent/codegen_v2.py tests/test_codegen_oracle.py
git commit -m "feat(oracle): inject VALIDATED KNOWLEDGE block into CODEGEN"
```

---

## Task 8: Pipeline wiring (retrieve)

**Files:**
- Modify: `agent/pipeline.py`

- [ ] **Step 1: Inspect the CODEGEN call site**

Run: `grep -n "run_codegen\|load_entries\|def run_pipeline" agent/pipeline.py`
Note where `run_codegen(design, learn_ctx, ...)` is called and where `task_id`/`instruction` are in scope.

- [ ] **Step 2: Add retrieval before the cycle loop**

Near the top of `run_pipeline`, after `learn_ctx = load_entries(task_id)` and compaction, add:

```python
    oracle_atoms = []
    try:
        from .oracle import KnowledgeOracle
        oracle_atoms = KnowledgeOracle().retrieve(instruction)
        if oracle_atoms:
            print(f"{CLI_BLUE}[pipeline] oracle retrieved {len(oracle_atoms)} atom(s): "
                  f"{[a.id for a in oracle_atoms]}{CLI_CLR}")
    except Exception as e:  # oracle must never break the pipeline
        print(f"{CLI_YELLOW}[pipeline] oracle retrieve skipped: {e}{CLI_CLR}")
```

- [ ] **Step 3: Pass atoms into CODEGEN**

At the `run_codegen(...)` call inside the loop, append `oracle_atoms=oracle_atoms`.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Smoke-run one task**

Run: `uv run python main.py t51`
Expected: log shows `[pipeline] oracle retrieved N atom(s)`; task completes (score read at end). This is a smoke check, not the acceptance gate.

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline.py
git commit -m "feat(oracle): retrieve atoms and feed CODEGEN in run_pipeline"
```

---

## Task 9: Grader-oracle validation harness

**Files:**
- Create: `agent/oracle_validate.py`
- Test: `tests/test_oracle_validate.py` (unit-level, network mocked)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_validate.py
from agent.oracle_validate import parse_score


def test_parse_score_reads_t38_trial():
    class _Tr:
        task_id = "t38"; score = 1.0; score_available = True; score_detail = []

    class _Res:
        trials = [_Tr()]

    assert parse_score(_Res(), "t38") == (1.0, [])


def test_parse_score_missing_task_returns_none():
    class _Res:
        trials = []
    assert parse_score(_Res(), "t38") == (None, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.oracle_validate'`.

- [ ] **Step 3: Write the implementation**

```python
# agent/oracle_validate.py
"""Grader-oracle harness: run a candidate answer on a fresh StartRun, read the real score.

Used to promote a candidate atom to `active` only when a script built from it scores 1.0.
The answer-builder is supplied by the caller (a function(vm) -> (message, outcome, refs)).
"""
from __future__ import annotations

import os

from bitgn import harness_pb2 as H
from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from agent.vm_adapter import VMAdapter

_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
_BID = os.getenv("BENCHMARK_ID") or "bitgn/ecom1-dev"
_KEY = os.getenv("BITGN_API_KEY") or ""


def parse_score(submit_result, task_id):
    for t in submit_result.trials:
        if t.task_id == task_id:
            return (float(t.score) if t.score_available else None, list(t.score_detail))
    return (None, [])


def grade_candidate(task_id, answer_builder):
    """Start a run, answer `task_id` via answer_builder(vm)->(msg, outcome, refs),
    end other trials, submit, return (score, detail)."""
    c = HarnessServiceClientSync(_URL)
    run = c.start_run(H.StartRunRequest(name=f"oracle-validate-{task_id}",
                                        benchmark_id=_BID, api_key=_KEY))
    answered = False
    for tid in run.trial_ids:
        try:
            t = c.start_trial(H.StartTrialRequest(trial_id=tid))
        except Exception:
            continue
        if t.task_id == task_id and not answered:
            vm = VMAdapter(EcomRuntimeClientSync(t.harness_url))
            msg, outcome, refs = answer_builder(vm)
            vm.answer(message=msg, outcome=outcome, refs=refs)
            answered = True
            break
        try:
            c.end_trial(H.EndTrialRequest(trial_id=t.trial_id))
        except Exception:
            pass
    res = c.submit_run(H.SubmitRunRequest(run_id=run.run_id, force=True))
    return parse_score(res, task_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oracle_validate.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/oracle_validate.py tests/test_oracle_validate.py
git commit -m "feat(oracle): grader-oracle validation harness"
```

---

## Task 10: distill + promote lifecycle

**Files:**
- Modify: `agent/oracle.py` (add `distill`, `promote`, `add_candidate`)
- Test: `tests/test_oracle_distill.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oracle_distill.py
from unittest.mock import patch
from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom


def _o(tmp_path):
    p = tmp_path / "atoms.yaml"
    p.write_text("[]")
    return KnowledgeOracle(atoms=[], atoms_path=p,
                           embed_fn=lambda t, model, base_url=None: [[1.0]] * len(t))


def test_distill_adds_candidate_without_seed_values(tmp_path):
    o = _o(tmp_path)
    fake = {"id": "new-method", "description": "d", "domain": ["sql"],
            "content": "general method text"}
    with patch("agent.oracle.call_llm_json", return_value=fake):
        atom = o.distill(design_intent="x", error="boom", script_code="code")
    assert atom.status == "candidate"
    assert any(a.id == "new-method" and a.status == "candidate" for a in o.atoms)


def test_promote_sets_active(tmp_path):
    o = _o(tmp_path)
    o.atoms.append(Atom(id="c", description="d", domain=[], content="x",
                        source="distilled", validated_by="", validated_at="",
                        status="candidate", embedding_hash=""))
    o.promote("c", validated_by="grader", validated_at="2026-06-05")
    a = next(a for a in o.atoms if a.id == "c")
    assert a.status == "active" and a.validated_by == "grader"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_oracle_distill.py -v`
Expected: FAIL with `AttributeError: 'KnowledgeOracle' object has no attribute 'distill'`.

- [ ] **Step 3: Write the implementation**

Add to `agent/oracle.py` (add `from .llm import call_llm_json` — created in Task 5 Step 3 — near the top imports; add `save_atoms` to the existing `from .oracle_atoms import ...` line):

```python
    _DISTILL_SYS = (
        "Distill a single REUSABLE coding-knowledge atom from a learned rule. "
        "Strip all run-specific values (ids, paths, skus, amounts). Return JSON "
        "{id, description, domain:[..], content}. content is a general method or fact."
    )

    def add_candidate(self, atom):
        self.atoms.append(atom)
        save_atoms(self._path, self.atoms)
        return atom

    def distill(self, design_intent, error, script_code):
        user = (f"INTENT:\n{design_intent}\n\nERROR:\n{error}\n\n"
                f"SCRIPT:\n{script_code[:4000]}\n\nReturn the atom JSON.")
        out = call_llm_json(self._DISTILL_SYS, user,
                            os.environ.get("MODEL_LEARN") or os.environ.get("MODEL", ""))
        if not isinstance(out, dict) or not out.get("content"):
            return None
        atom = Atom(id=out["id"], description=out.get("description", ""),
                    domain=list(out.get("domain") or []), content=out["content"],
                    source="distilled", validated_by="", validated_at="",
                    status="candidate", embedding_hash=content_hash(out["content"]))
        return self.add_candidate(atom)

    def promote(self, atom_id, validated_by, validated_at):
        for a in self.atoms:
            if a.id == atom_id:
                a.status = "active"
                a.validated_by = validated_by
                a.validated_at = validated_at
        save_atoms(self._path, self.atoms)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_oracle_distill.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/oracle.py tests/test_oracle_distill.py
git commit -m "feat(oracle): distill candidates + promote lifecycle"
```

---

## Task 11: Pipeline distill hook

**Files:**
- Modify: `agent/pipeline.py`

- [ ] **Step 1: Locate the LEARN consolidation call**

Run: `grep -n "_learn_consolidate\|def _learn_consolidate" agent/pipeline.py`
Note the call sites (in-loop on fidelity/AST failure and in the answer-failure path).

- [ ] **Step 2: Add a guarded distill after consolidation**

Inside `_learn_consolidate`, after `apply_learn_diff(...)` succeeds, add (best-effort, never raising):

```python
    if os.environ.get("ORACLE_ENABLED", "1") != "0" and os.environ.get("ORACLE_DISTILL", "0") == "1":
        try:
            from .oracle import KnowledgeOracle
            KnowledgeOracle().distill(
                design_intent=getattr(design, "intent", ""),
                error=error or "",
                script_code=script_code or "",
            )
        except Exception as e:
            print(f"{CLI_YELLOW}[pipeline] oracle distill skipped: {e}{CLI_CLR}")
```

`ORACLE_DISTILL` defaults off so auto-distillation is opt-in until candidates are reviewed; promotion still requires the grader-oracle.

- [ ] **Step 3: Run the suite**

Run: `uv run pytest tests/ -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add agent/pipeline.py
git commit -m "feat(oracle): opt-in distill hook after LEARN consolidation"
```

---

## Task 12: Migration script (existing rules → atoms)

**Files:**
- Create: `scripts/migrate_rules_to_atoms.py`
- Test: `tests/test_migrate_rules.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_rules.py
from scripts.migrate_rules_to_atoms import dedup_by_cosine
from agent.oracle_atoms import Atom


def _a(i, vec):
    a = Atom(id=i, description=i, domain=[], content=i, source="distilled",
             validated_by="", validated_at="", status="candidate", embedding_hash="")
    a.extra["vec"] = vec
    return a


def test_dedup_merges_near_duplicates():
    atoms = [_a("a", [1.0, 0.0]), _a("b", [0.99, 0.01]), _a("c", [0.0, 1.0])]
    kept = dedup_by_cosine(atoms, threshold=0.95, vec_of=lambda a: a.extra["vec"])
    ids = {a.id for a in kept}
    assert "c" in ids
    assert len(kept) == 2  # a and b merged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrate_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.migrate_rules_to_atoms'`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/migrate_rules_to_atoms.py
"""One-off: distill existing per-task learned rules into general atoms (candidates).

Run manually: uv run python -m scripts.migrate_rules_to_atoms
Writes candidate atoms to data/oracle/atoms.yaml; nothing is promoted automatically.
"""
from __future__ import annotations

import math
from pathlib import Path

from agent.oracle import _cosine
from agent.oracle_atoms import load_atoms, save_atoms


def dedup_by_cosine(atoms, threshold, vec_of):
    kept = []
    for a in atoms:
        va = vec_of(a)
        if any(_cosine(va, vec_of(b)) >= threshold for b in kept):
            continue
        kept.append(a)
    return kept


def main():
    # Walk data/learned/*.yaml, distill each active rule into a candidate atom via
    # KnowledgeOracle.distill, then dedup. Left as an operator-run step; see module docstring.
    learned = sorted(Path("data/learned").glob("*.yaml"))
    print(f"{len(learned)} per-task rule files found. "
          f"Run KnowledgeOracle().distill per active rule, then dedup_by_cosine.")


if __name__ == "__main__":
    main()
```

(The `main()` body is intentionally a thin operator entry; the reusable, tested logic is `dedup_by_cosine`. Distillation reuses `KnowledgeOracle.distill` from Task 10.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migrate_rules.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_rules_to_atoms.py tests/test_migrate_rules.py
git commit -m "feat(oracle): rule->atom migration helper with cosine dedup"
```

---

## Task 13: Configuration & docs

**Files:**
- Modify: `models.json.example`, `.env.example`, `CLAUDE.md`

- [ ] **Step 1: Add embedding model to models.json.example**

Add to the `_fields` block: `"kind": "Model role: omit for chat/completion; 'embedding' for vector-embedding models used by the knowledge-oracle"`. Add a top-level entry:

```json
"nomic-embed-text": {
  "provider": "ollama",
  "kind": "embedding",
  "_doc": "Embedding model for the knowledge-oracle. Called via Ollama /v1/embeddings; returns a dense vector, not chat completions. Used only by agent/oracle.py.",
  "ollama_options": { "num_ctx": 8192 }
}
```

- [ ] **Step 2: Validate JSON**

Run: `uv run python -c "import json; json.load(open('models.json.example'))"`
Expected: exit 0 (valid JSON).

- [ ] **Step 3: Add env vars to .env.example**

Append:

```
# --- knowledge-oracle ---
ORACLE_ENABLED=1            # 0 disables retrieval; pipeline behaves as before
EMBED_MODEL=nomic-embed-text
# EMBED_BASE_URL=           # defaults to OLLAMA_BASE_URL
ORACLE_TOPN=10             # stage-1 cosine candidates
ORACLE_K=4                # final atoms injected into CODEGEN
# MODEL_RANK=              # stage-2 re-rank model; defaults to MODEL
ORACLE_RANK_ENABLED=1      # 0 = cosine top-k, skip LLM re-rank
ORACLE_DISTILL=0           # 1 = auto-distill candidate atoms after LEARN
```

- [ ] **Step 4: Document in CLAUDE.md**

Add the seven oracle vars to the Environment Variables table in `CLAUDE.md` with one-line purposes (mirror `.env.example`). Add one line under Architecture/Key Data Files: `data/oracle/atoms.yaml | Validated general knowledge atoms retrieved into CODEGEN`.

- [ ] **Step 5: Commit**

```bash
git add models.json.example .env.example CLAUDE.md
git commit -m "docs(oracle): config vars + models.json embedding entry"
```

---

## Task 14: Acceptance — re-seeded runs

**Files:** none (verification only)

- [ ] **Step 1: Confirm Ollama embedding model is pullable**

Run: `curl -s $OLLAMA_BASE_URL/../api/tags | grep -o nomic-embed-text || echo "pull: ollama pull nomic-embed-text"`
If absent, pull it (operator step) before proceeding.

- [ ] **Step 2: Run the three tasks, twice (independent seeds)**

Run: `uv run python main.py t01 t38 t51`
Then again: `uv run python main.py t01 t38 t51`
Expected (Done-when): in BOTH runs `t01=1.00`, `t38=1.00`, `t51=1.00`.

- [ ] **Step 3: If a task < 1.0 — diagnose, do not hardcode**

Use the grader-oracle harness (`agent/oracle_validate.py`) to test the atom's method on the failing task's current seed, refine the atom `content` (still general, no seed values), re-run. The fix path is the atom, never `data/prompts/`.

- [ ] **Step 4: Full regression**

Run: `uv run pytest tests/ -q`
Expected: all pass, including `tests/test_design.py` F-001 guards.

- [ ] **Step 5: Commit any atom refinements**

```bash
git add data/oracle/atoms.yaml
git commit -m "test(oracle): refine atoms to pass t01/t38/t51 across re-seeds"
```

---

## Self-Review notes

- **Spec coverage:** components (T2,T4,T9), atom schema (T2,T6), two-stage retrieval (T4 cosine, T5 re-rank), lifecycle seed/distill/validate/promote/migrate (T6,T9,T10,T12), integration CODEGEN+pipeline (T7,T8,T11), config env+models.json (T13), error handling (T4 fallbacks, T8/T11 guards), testing+acceptance (every task + T14). DESIGN left unchanged per spec (out of scope).
- **Coupling note:** `call_llm_json` does not exist in the codebase — Task 5 Step 3 creates it in `agent/llm.py` as a thin wrapper over the existing `call_llm_raw` + `_extract_json_from_text` pattern (per `agent/design.py`). T5 and T10 both import that one helper.
- **No hardcoded seed values** anywhere in atoms (enforced by `tests/test_oracle_seed.py`).
