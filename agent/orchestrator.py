"""Minimal orchestrator — reads AGENTS.MD then dispatches the pipeline."""
from __future__ import annotations

import os
import re

from pydantic import BaseModel

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import NodeKind, ReadRequest

from agent.agents_md_parser import render_inventory
from agent.json_extract import _extract_json_from_text
from agent.learned_store import load_prephase_deep_read
from agent.llm import _resolve_model_for_phase, call_llm_raw
from agent.pipeline import run_pipeline
from agent.trace import get_trace
from agent.vm_adapter import VMAdapter


def _read_agents_md(vm: EcomRuntimeClientSync) -> str:
    for candidate in ("/AGENTS.MD", "/AGENTS.md"):
        try:
            r = vm.read(ReadRequest(path=candidate))
            if r.content:
                return r.content
        except Exception:
            continue
    return ""


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


# Cost safety rails (NOT domain knowledge): bound Stat-probe count + rendered listing size.
_PATH_LITERAL_RE = re.compile(r"/[\w./-]+")
_PATH_LITERAL_CAP = int(os.environ.get("ECOM_PREPHASE_PATH_LITERALS", "3"))
_PATH_LISTING_BUDGET = int(os.environ.get("ECOM_PREPHASE_LISTING_BYTES", "4096"))


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


_SAMPLE_ROWS_PER_TABLE = int(os.environ.get("ECOM_PREPHASE_SAMPLE_ROWS", "3"))
_SAMPLE_ROW_MAX_CHARS = int(os.environ.get("ECOM_PREPHASE_SAMPLE_ROW_CHARS", "400"))


def _sql_stdout(vm: VMAdapter, sql: str) -> str:
    # Deliver SQL on STDIN — /bin/sql is nondeterministic over args (F3: intermittently
    # returns its usage banner when SQL is not on stdin). stdin is the reliable channel,
    # so pre-phase schema/sample/candidate-probe queries land deterministically.
    try:
        r = vm.exec(path="/bin/sql", args=[], stdin=sql)
    except Exception:
        return ""
    stdout = getattr(r, "stdout", None)
    if stdout is None and isinstance(r, dict):
        stdout = r.get("stdout", "")
    return (stdout or "").strip()


def _discover_schema(vm: VMAdapter) -> str:
    """Best-effort: ask the VM's SQL tool for the catalog schema.

    Returns formatted CREATE statements, or "" if the call fails or yields nothing.
    DESIGN uses this to write column-accurate SQL without an exploratory step.
    """
    sql = "SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type, name;"
    return _sql_stdout(vm, sql)


def _discover_table_names(vm: VMAdapter) -> list[str]:
    sql = "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    text = _sql_stdout(vm, sql)
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _discover_sample_rows(vm: VMAdapter, tables: list[str]) -> str:
    """Per-table top-N rows. Reveals FK link patterns DESIGN can't infer from
    CREATE TABLE alone (column values, foreign-key conventions, status enums).
    """
    parts: list[str] = []
    for name in tables:
        # Identifier injected directly — sqlite_schema names are server-side
        # trusted, but still quote-escape to be safe.
        ident = name.replace('"', '""')
        sql = f'SELECT * FROM "{ident}" LIMIT {_SAMPLE_ROWS_PER_TABLE};'
        text = _sql_stdout(vm, sql)
        if not text:
            continue
        rows = []
        for line in text.splitlines():
            if len(line) > _SAMPLE_ROW_MAX_CHARS:
                line = line[: _SAMPLE_ROW_MAX_CHARS] + "…"
            rows.append(line)
        if rows:
            parts.append(f"-- {name}\n" + "\n".join(rows))
    return "\n\n".join(parts)


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


def _augment_agents_md(agents_md_text: str, schema_text: str, sample_rows: str = "") -> str:
    if not schema_text and not sample_rows:
        return agents_md_text
    blocks: list[str] = [agents_md_text or ""]
    if schema_text:
        blocks.append("\n\n## DB Schema (discovered)\n\n```sql\n" + schema_text + "\n```\n")
    if sample_rows:
        blocks.append("\n## DB Sample Rows (top {n} per table)\n\n```\n{rows}\n```\n".format(
            n=_SAMPLE_ROWS_PER_TABLE, rows=sample_rows
        ))
    return "".join(blocks)


class PrePhaseFacts(BaseModel):
    agents_md: str = ""
    agents_md_inventory: str = ""
    schema: str = ""
    sample_rows: str = ""
    docs_inventory: str = ""
    policies: dict[str, str] = {}
    identity: dict = {}
    target_records: dict[str, str] = {}
    path_listings: dict[str, str] = {}   # instruction-named dir -> rendered listing (Tier-1)
    catalogue_candidates: str = ""       # broad normalized probe over product_variants by entity tokens
    gather_status: dict[str, str] = {}   # fact -> ok|empty|error(<msg>)


_ID_SPLIT_RE = re.compile(r"[\s,]+")
# Structural id-shape only (H1): <prefix>_<rest>. The /proc listing + DDL decide
# which prefixes are real — no entity-prefix allowlist, no singular->plural map.
_RECORD_ID_RE = re.compile(r"\b([A-Za-z]+)_\w+\b")
_QUOTED_RE = re.compile(r'"([^"]+)"')
# Two or more Capitalized words in a row (hyphens kept: "Non-Bladed Workshop").
_CAP_SEQ_RE = re.compile(r"\b([A-Z][\w-]*(?:\s+[A-Z][\w-]*)+)\b")
_POLICY_CAP = 6
_RECORD_CAP = 3
_DOC_HITS_PER_TOKEN = 3
_DOC_CONTENT_CAP = 4096


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


_PROBE_STOP = {
    "the", "from", "you", "can", "do", "does", "have", "has", "had", "in", "into",
    "line", "that", "with", "and", "or", "is", "are", "get", "carry", "stock", "stocks",
    "for", "our", "we", "support", "note", "claims", "claim", "check", "checked", "cite",
    "record", "exact", "base", "extra", "exists", "absent", "answer", "include", "including",
    "sku", "how", "many", "count", "report", "catalogue", "catalog", "product", "products",
    "type", "color", "colour", "family", "size", "please", "actual", "item", "available",
    "availability", "this", "any", "all", "a", "an", "of", "to", "it", "i",
    "pipe", "fitting",
}


def _probe_keywords(instruction: str) -> list[str]:
    """Distinctive single tokens for the catalogue probe: brand/series words and
    alphanumeric model codes (e.g. 'Pipelife', 'Radopress', 'MX2-EGS', '233-MOB').
    Drops generic/stopwords and multi-word phrases (which never match a single column
    via LIKE). Deduped, order-preserving, capped."""
    out: list[str] = []
    seen: set[str] = set()
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", instruction or ""):
        lw = w.lower()
        if lw in _PROBE_STOP or lw in seen:
            continue
        is_code = any(c.isdigit() for c in w) and len(w) >= 2          # model code: MX2-EGS, 233-MOB
        is_name = (w[:1].isupper() and len(w) >= 4)                    # brand/series word: Pipelife, Radopress, KJB-LZD
        if is_code or is_name:
            seen.add(lw)
            out.append(w)
    return out[:8]


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


def _proc_candidates(proc_subdirs: list[str], record_id: str) -> list[str]:
    """`/proc/<subdir>/<id>.json` for each DISCOVERED subdir matching the id prefix.

    Plural/dir is discovered (`_list_entries(vm, "/proc")`), never a static map.
    `name.startswith(prefix)` catches singular->plural (payment -> payments); a
    spurious match is harmless — the caller reads the file and keeps it only if non-empty.
    """
    prefix = record_id.split("_", 1)[0].lower()
    return [f"/proc/{name}/{record_id}.json"
            for name in proc_subdirs if name.startswith(prefix)]


def _extract_text(r, attr: str) -> str:
    """Pull a string field from an RPC result (object with `.attr`, or dict).

    Returns "" for anything non-string (e.g. a bare MagicMock attribute) so
    best-effort gathering degrades cleanly instead of raising downstream.
    """
    val = getattr(r, attr, None)
    if isinstance(val, str):
        return val
    if isinstance(r, dict):
        d = r.get(attr, "")
        return d if isinstance(d, str) else ""
    return ""


def _sql_stdout_or_exec(vm, path: str) -> str:
    try:
        r = vm.exec(path=path, args=[])
    except Exception:
        return ""
    return _extract_text(r, "stdout")


_DOC_SELECT_CAP = 4

_CATALOGUE_HINTS = ("catalog", "catalogue", "product", "sku", "tool bag")


def _is_catalogue_query(instruction: str) -> bool:
    t = (instruction or "").lower()
    return any(h in t for h in _CATALOGUE_HINTS)


_CATALOGUE_PROBE_BYTE_CAP = 2000
_CATALOGUE_PROBE_LIMIT = 15
_CATALOGUE_PROBE_MAX_TOKENS = 5


def _probe_catalogue_candidates(vm: VMAdapter, instruction: str) -> str:
    """Broad normalized probe over product_variants by entity tokens.

    Returns a compact header+rows string (capped to ~2000 bytes), or "" on
    empty result or any error. Deterministic, read-only, no LLM call.
    The probe is intentionally broad (finding candidates); narrowing is PLAN's job.
    """
    tokens = _probe_keywords(instruction)
    if not tokens:
        return ""
    # Use top N tokens; inline token literals (lowercased, single-quotes escaped).
    probe_tokens = tokens[:_CATALOGUE_PROBE_MAX_TOKENS]
    conditions = []
    for tok in probe_tokens:
        safe = tok.lower().replace("'", "''")
        cond = (
            f"(LOWER(TRIM(brand)) LIKE '%{safe}%'"
            f" OR LOWER(TRIM(series)) LIKE '%{safe}%'"
            f" OR LOWER(TRIM(model)) LIKE '%{safe}%'"
            f" OR LOWER(TRIM(product_name)) LIKE '%{safe}%')"
        )
        conditions.append(cond)
    where = " OR ".join(conditions)
    # Relevance-rank: ORDER BY how many distinct tokens a row matches (each condition is
    # 0/1 in SQLite), DESC — so the row matching the most of brand+series+model+code (the
    # exact product) surfaces in the top LIMIT, not 15 brand-only matches.
    score = " + ".join(f"({c})" for c in conditions)
    sql = (
        f"SELECT product_sku, brand, series, model, product_name, record_path"
        f" FROM product_variants"
        f" WHERE {where}"
        f" ORDER BY ({score}) DESC"
        f" LIMIT {_CATALOGUE_PROBE_LIMIT};"
    )
    try:
        text = _sql_stdout(vm, sql)
    except Exception:
        text = ""
    nrows = max(0, text.count("\n")) if text else 0
    print(f"[prephase] catalogue_candidates: {nrows} row(s) (tokens={probe_tokens[:5]})")
    if not text:
        return ""
    # Cap to byte budget; no silent truncation.
    if len(text) > _CATALOGUE_PROBE_BYTE_CAP:
        text = text[:_CATALOGUE_PROBE_BYTE_CAP] + "\n… (truncated)"
    return text


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
    model = _resolve_model_for_phase("docselect", os.environ.get("ECOM_MODEL", ""))
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


def gather_prephase_facts(vm, instruction: str, agents_md_text: str, task_id: str = "") -> PrePhaseFacts:
    status: dict[str, str] = {}

    def _mark(key: str, value, err: str = "") -> None:
        if err:
            status[key] = f"error({err})"
        elif value:
            status[key] = "ok"
        else:
            status[key] = "empty"

    deep_read = load_prephase_deep_read(task_id) if task_id else []
    deep_paths = [d for d in deep_read if d.startswith("/")]
    deep_tables = tuple(d for d in deep_read if not d.startswith("/"))

    # schema + sample rows (P5 tier split: names/DDL uncapped; samples relevance-gated)
    schema = _discover_schema(vm)
    _mark("schema", schema)
    tables = _discover_table_names(vm) if schema else []
    sample_set = _relevant_tables(tables, instruction, deep_read=deep_tables)
    samples = _discover_sample_rows(vm, sample_set) if sample_set else ""
    skipped = [t for t in tables if t not in sample_set]
    if skipped:                                  # no silent truncation
        print(f"[prephase] sample_rows: {len(skipped)} table(s) not relevant, not sampled: "
              + ", ".join(skipped[:10]) + (" …" if len(skipped) > 10 else ""))
    _mark("sample_rows", samples)

    # identity (P4 robust parse)
    try:
        id_out = _sql_stdout_or_exec(vm, "/bin/id")
        identity = _parse_identity(id_out)
        identity["kind"] = _identity_kind(identity)
        # role-aware deny compares $record.customer_id to $_facts.identity.customer_id;
        # if the caller is a customer identified only by a cust_* value under another
        # key (e.g. user=cust_016), surface it as customer_id so the predicate is robust.
        if identity.get("kind") == "customer" and not (identity.get("customer_id") or "").strip():
            for _v in identity.values():
                if isinstance(_v, str) and _v.strip().lower().startswith("cust_"):
                    identity["customer_id"] = _v.strip()
                    break
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
        if picked and policies:
            status["policies"] = "ok"

    # F7: catalogue query but entity-token Search found no /docs match — log the gap
    # (defensive; no break, no prompt change). Many catalogue tasks have no doc.
    if _is_catalogue_query(instruction) and not search_hit:
        print(f"[prephase] DOC_SELECT gap: catalogue query, no /docs matched entity tokens "
              f"(tokens={tokens[:5]})")

    # catalogue candidate probe — broad normalized query by entity tokens (no LLM, read-only).
    # Fire on a catalogue hint OR whenever the instruction carries >=2 distinctive entity
    # tokens (a product reference like "Heco ... Nut Bolt" or "Wiha Screwdriver 13X-B49"
    # that the narrow _is_catalogue_query hint-list misses).
    catalogue_candidates = ""
    if _is_catalogue_query(instruction) or len(_probe_keywords(instruction)) >= 2:
        try:
            catalogue_candidates = _probe_catalogue_candidates(vm, instruction)
        except Exception:
            pass  # best-effort; never break gather
    _mark("catalogue_candidates", catalogue_candidates)

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

    # literal-path listings (1.2) — VM is the filter; no /proc allowlist, no hardcoded roots.
    path_listings: dict[str, str] = {}
    literals = _extract_path_literals(instruction)
    for d in deep_paths:
        if d not in literals:
            literals.append(d)
    for lit in literals:
        kind = _stat_kind(vm, lit)
        if kind == "dir":
            paths = _list_entries(vm, lit)               # Tier-1, cheap
            if paths:
                path_listings[lit] = _render_budget(paths, _PATH_LISTING_BUDGET)
        elif kind == "file":
            path_listings[lit] = f"file {lit}"           # existence; body NOT read
        # kind == "" -> non-existent / non-data path -> skipped
    _mark("path_listings", path_listings)

    return PrePhaseFacts(
        agents_md=agents_md_text, agents_md_inventory=render_inventory(agents_md_text),
        schema=schema, sample_rows=samples,
        docs_inventory=docs_inventory, policies=policies, identity=identity,
        target_records=target_records, path_listings=path_listings,
        catalogue_candidates=catalogue_candidates, gather_status=status,
    )


def run_agent(
    model_configs: dict,
    harness_url: str,
    task_text: str,
    task_id: str = "",
    injected_session_rules: list[str] | None = None,    # accepted for harness compat; unused
    injected_prompt_addendum: str = "",                  # accepted for harness compat; unused
) -> dict:
    raw_vm = EcomRuntimeClientSync(harness_url)
    agents_md_text = _read_agents_md(raw_vm)
    vm = VMAdapter(raw_vm)
    facts = gather_prephase_facts(vm, task_text, agents_md_text, task_id=task_id)
    _t = get_trace()
    if _t is not None:
        try:                                    # observability must never break a run
            _t.log_facts(facts)
        except Exception:
            pass
    agents_md_text = _augment_agents_md(agents_md_text, facts.schema, facts.sample_rows)
    metrics = run_pipeline(vm, instruction=task_text, task_id=task_id,
                           agents_md_text=agents_md_text, facts=facts)
    return {
        "model_used": os.environ.get("ECOM_MODEL", ""),
        "task_type": "lookup",
        "cycles_used": metrics.get("cycles_used", 0),
        "outcome": metrics.get("outcome", ""),
        "input_tokens": metrics.get("input_tokens", 0),
        "output_tokens": metrics.get("output_tokens", 0),
        "answer_message": metrics.get("answer_message", ""),
        "answer_refs": metrics.get("answer_refs", []),
    }
