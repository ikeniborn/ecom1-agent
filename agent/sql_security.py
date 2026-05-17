"""Security gate evaluation — gates loaded from data/security/*.yaml."""
from __future__ import annotations

import hashlib
import json as _json
import re
from pathlib import Path

import yaml

_SECURITY_DIR = Path(__file__).parent.parent / "data" / "security"

_PLACEHOLDER_WORDS = {"foo", "bar", "baz", "x", "y", "z", "test", "xxx", "none", "n/a", "rule", "todo", "tbd", "fixme", "placeholder"}


def load_security_gates(directory: Path = _SECURITY_DIR) -> list[dict]:
    """Load all gate definitions from *.yaml files in directory, sorted by filename."""
    gates = []
    for f in sorted(directory.glob("*.yaml")):
        try:
            gate = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(gate, dict) and gate.get("verified", True):
                gates.append(gate)
        except Exception:
            pass
    return gates


def check_sql_queries(queries: list[str], security_gates: list[dict]) -> str | None:
    """Apply security gates to SQL queries. Returns error message or None if all pass."""
    for query in queries:
        for gate in security_gates:
            if "pattern" in gate:
                if re.search(gate["pattern"], query, re.IGNORECASE):
                    return f"[{gate['id']}] {gate['message']}: {query[:80]}"
            elif gate.get("check") == "no_where_clause":
                if _is_select(query) and not _has_where_clause(query):
                    return f"[{gate['id']}] {gate['message']}: {query[:80]}"
    return None


def check_path_access(path: str, security_gates: list[dict]) -> str | None:
    """Check if a file path access is blocked by path_prefix gates."""
    for gate in security_gates:
        if "path_prefix" in gate and path.startswith(gate["path_prefix"]):
            return f"[{gate['id']}] {gate['message']}: {path}"
    return None


def check_where_literals(queries: list[str], task_text: str, security_gates: list[dict]) -> str | None:
    """Block WHERE clause literals not traceable to task_text (sec-037)."""
    for gate in security_gates:
        if gate.get("check") != "where_literals_must_appear_in_task_text":
            continue
        task_lower = task_text.lower()
        for q in queries:
            m = re.search(
                r"\bWHERE\b(.+?)(?:\bORDER\b|\bGROUP\b|\bHAVING\b|\bLIMIT\b|$)",
                q, re.IGNORECASE | re.DOTALL,
            )
            if not m:
                continue
            for lit in re.findall(r"'([^']+)'", m.group(1)):
                if lit.lower() not in task_lower:
                    return f"[{gate['id']}] {gate['message']}: '{lit}'"
    return None


def check_grounding_refs(refs: list[str], result_skus: set[str], security_gates: list[dict]) -> str | None:
    """Block grounding_refs not present in SQL result SKUs (sec-031)."""
    if not result_skus:
        return None
    for gate in security_gates:
        if gate.get("check") != "grounding_refs_in_result_skus":
            continue
        for ref in refs:
            sku = Path(ref).stem
            if sku and sku not in result_skus:
                return f"[{gate['id']}] {gate['message']}: {ref}"
    return None


def check_learn_output(
    rule_content: str,
    learn_hash: str,
    prior_hashes: set[str],
    security_gates: list[dict],
) -> str | None:
    """Check LearnOutput for stale replay (sec-041) and placeholder content (sec-066)."""
    for gate in security_gates:
        if gate.get("check") == "learnoutput_hash_replay":
            if learn_hash in prior_hashes:
                return f"[{gate['id']}] {gate['message']}"
        elif gate.get("check") == "rule_content_semantic_complexity":
            stripped = rule_content.strip()
            if not stripped or len(stripped) < 20:
                return f"[{gate['id']}] {gate['message']}: content too short ({len(stripped)} chars)"
            if set(stripped.lower().split()) <= _PLACEHOLDER_WORDS and len(stripped.split()) <= 5:
                return f"[{gate['id']}] {gate['message']}: placeholder detected: {stripped!r}"
    return None


def check_retry_loop(
    queries: list[str],
    prior_query_sets: list[frozenset],
    security_gates: list[dict],
) -> str | None:
    """Block identical query retry without Learn mutation (sec-073)."""
    for gate in security_gates:
        if gate.get("check") != "no_identical_query_retry_without_learn_mutation":
            continue
        if frozenset(queries) in prior_query_sets:
            return f"[{gate['id']}] {gate['message']}"
    return None


def make_json_hash(obj: object) -> str:
    return hashlib.sha256(_json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _is_select(sql: str) -> bool:
    return sql.strip().upper().startswith("SELECT")


def _has_where_clause(sql: str) -> bool:
    try:
        import sqlglot
        tree = sqlglot.parse_one(sql, dialect="sqlite")
        return bool(tree.find(sqlglot.exp.Where))
    except Exception:
        stripped = re.sub(r"'[^']*'", "", sql).upper()
        return "WHERE" in stripped.split()
