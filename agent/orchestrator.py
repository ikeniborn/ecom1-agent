"""Minimal orchestrator — reads AGENTS.MD then dispatches the pipeline."""
from __future__ import annotations

import os
import re

from pydantic import BaseModel

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import NodeKind, ReadRequest

from agent.json_extract import _extract_json_from_text
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
_PATH_LITERAL_CAP = int(os.environ.get("PREPHASE_PATH_LITERALS", "3"))
_PATH_LISTING_BUDGET = int(os.environ.get("PREPHASE_LISTING_BYTES", "4096"))


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


_SAMPLE_TABLES_MAX = 12
_SAMPLE_ROWS_PER_TABLE = 3
_SAMPLE_ROW_MAX_CHARS = 400


def _sql_stdout(vm: VMAdapter, sql: str) -> str:
    try:
        r = vm.exec(path="/bin/sql", args=[sql])
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
    names = [line.strip() for line in text.splitlines() if line.strip()]
    return names[:_SAMPLE_TABLES_MAX]


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
    schema: str = ""
    sample_rows: str = ""
    docs_inventory: str = ""
    policies: dict[str, str] = {}
    identity: dict = {}
    target_records: dict[str, str] = {}
    path_listings: dict[str, str] = {}   # instruction-named dir -> rendered listing (Tier-1)
    gather_status: dict[str, str] = {}   # fact -> ok|empty|error(<msg>)


_ID_SPLIT_RE = re.compile(r"[\s,]+")
# P3 (S1-R6): widen record discovery beyond baskets/payments.
_RECORD_ID_RE = re.compile(
    r"\b(basket|payment|return|order|store|employee|product)_\w+\b", re.IGNORECASE
)
_PROC_DIR = {
    "basket": "baskets", "payment": "payments", "return": "returns",
    "order": "orders", "store": "stores", "employee": "employees",
    "product": "products",
}
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
        if picked and policies:
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

    return PrePhaseFacts(
        agents_md=agents_md_text, schema=schema, sample_rows=samples,
        docs_inventory=docs_inventory, policies=policies, identity=identity,
        target_records=target_records, path_listings=path_listings, gather_status=status,
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
    facts = gather_prephase_facts(vm, task_text, agents_md_text)
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
        "model_used": os.environ.get("MODEL", ""),
        "task_type": "lookup",
        "cycles_used": metrics.get("cycles_used", 0),
        "outcome": metrics.get("outcome", ""),
        "input_tokens": metrics.get("input_tokens", 0),
        "output_tokens": metrics.get("output_tokens", 0),
        "answer_message": metrics.get("answer_message", ""),
        "answer_refs": metrics.get("answer_refs", []),
    }
