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
# Prefixed ids (basket_12, ord_45, cust_016): an allowlist of entity prefixes trims most
# schema words. It is NOT exhaustive — allowlisted prefixes still match SQL columns like
# 'order_id'/'return_reason'; such false positives are harmless because callers
# stat-validate every resolved record path against the live /proc tree (Task 2+), dropping
# tokens that do not resolve. Broad extraction + strict validation is the chosen tradeoff.
_PREFIXED_ID_RE = re.compile(
    r"\b(?:basket|order|ord|return|ret|payment|pay|invoice|inv|customer|cust|shipment|ship)"
    r"_[A-Za-z0-9]+\b",
    re.IGNORECASE,
)


# Note: agent/orchestrator.py:_extract_entity_tokens is a SEPARATE pre-phase extractor
# (quoted strings + capitalized n-grams); this one targets dash/prefixed entity IDs. Distinct roles.
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
