"""Explicit, validated tool catalog (Workstream C).

PLAN emits stringly-typed `rpc`+`args`. Without a contract the model guesses RPC
names, arg keys, and column names (the r012 stdin-key bug class). This catalog is
the single source of truth: it grounds the PLAN prompt (build_tool_catalog_block)
and structurally validates each dispatch (validate_step). Validation is FUNCTIONAL
— a violation raises InterpretError (-> iLEARN), distinct from swallowed logging.
"""
from __future__ import annotations

# Each entry: purpose, required (set), optional (set), mode (read|mutate),
# when_to_use (str), example (dict), and an optional structural `note`.
TOOL_CATALOG: dict[str, dict] = {
    "Read": {
        "purpose": "Read a file (optionally line-numbered range).",
        "required": {"path"},
        "optional": {"number", "start_line", "end_line"},
        "mode": "read",
        "when_to_use": "Fetch a known file's content (policy doc, /proc record).",
        "example": {"rpc": "Read", "args": {"path": "/docs/security.md"}},
    },
    "List": {
        "purpose": "List a directory's entries.",
        "required": {"path"},
        "optional": set(),
        "mode": "read",
        "when_to_use": "Enumerate a dir before reading specific children.",
        "example": {"rpc": "List", "args": {"path": "/proc"}},
    },
    "Tree": {
        "purpose": "Recursive tree under a root (level=0 unlimited).",
        "required": {"root"},
        "optional": {"level"},
        "mode": "read",
        "when_to_use": "Discover a subtree's shape; prefer Find/Search when targeted.",
        "example": {"rpc": "Tree", "args": {"root": "/docs", "level": 0}},
    },
    "Find": {
        "purpose": "Path search by name under a root.",
        "required": {"root"},
        "optional": {"name", "kind", "limit"},
        "mode": "read",
        "when_to_use": "Locate a file by name when its dir is unknown.",
        "example": {"rpc": "Find", "args": {"root": "/", "name": "security.md"}},
    },
    "Search": {
        "purpose": "Regex content search; returns path+line+text.",
        "required": {"root", "pattern"},
        "optional": {"limit"},
        "mode": "read",
        "when_to_use": "Find docs/records mentioning an entity token.",
        "example": {"rpc": "Search", "args": {"root": "/docs", "pattern": "refund", "limit": 30}},
    },
    "Exec": {
        "purpose": "Run a runtime tool (e.g. /bin/sql, /bin/id).",
        "required": {"path"},
        "optional": {"args", "stdin"},
        "mode": "read",
        "when_to_use": "Query the catalog DB via /bin/sql; read identity via /bin/id.",
        "example": {"rpc": "Exec", "args": {"path": "/bin/sql", "stdin": "SELECT 1;"}},
        "note": ("/bin/sql reads the query from the real STDIN channel. Put the SQL in "
                 "`stdin` (a string); do NOT inline it anywhere else. `args` is also "
                 "accepted and is moved to stdin by the pre-lint repair. The runner "
                 "returns its usage banner if the SQL never reaches stdin (the r012 bug)."),
    },
    "Write": {
        "purpose": "Write a file (optional compare-and-swap).",
        "required": {"path", "content"},
        "optional": {"if_match_sha256", "idempotency_key"},
        "mode": "mutate",
        "when_to_use": "Persist a mutation; belongs in `ops`, never `discovery`.",
        "example": {"rpc": "Write", "args": {"path": "/proc/x.json", "content": "{}"}},
    },
    "Delete": {
        "purpose": "Delete a file or directory.",
        "required": {"path"},
        "optional": set(),
        "mode": "mutate",
        "when_to_use": "Remove a record; belongs in `ops`.",
        "example": {"rpc": "Delete", "args": {"path": "/proc/x.json"}},
    },
    "Stat": {
        "purpose": "Metadata for a path (kind, content_type).",
        "required": {"path"},
        "optional": set(),
        "mode": "read",
        "when_to_use": "Check existence/kind before Read.",
        "example": {"rpc": "Stat", "args": {"path": "/docs"}},
    },
}


def validate_step(rpc: str, args: dict | None) -> str | None:
    """Return None when (rpc, args) is structurally valid, else a precise error.

    Checks: rpc in catalog; every arg key in (required | optional); every required
    key present. `bind`/`guard_label`/`outcome_from_exit` live on the Step/GuardedOp
    envelope, not in `args`, so they are never seen here.
    """
    entry = TOOL_CATALOG.get(rpc)
    if entry is None:
        return f"rpc {rpc!r} not in catalog (valid: {', '.join(sorted(TOOL_CATALOG))})"
    allowed = entry["required"] | entry["optional"]
    keys = set((args or {}).keys())
    extra = keys - allowed
    if extra:
        bad = sorted(extra)[0]
        return (f"arg {bad!r} not accepted by {rpc} "
                f"(accepts: {', '.join(sorted(allowed)) or 'none'})")
    missing = entry["required"] - keys
    if missing:
        return f"{rpc} missing required arg(s): {', '.join(sorted(missing))}"
    return None


def build_tool_catalog_block() -> str:
    """Markdown block injected into the PLAN prompt — the grounded, code-backed RPC
    surface (replaces the ad-hoc table previously inline in plan.md)."""
    lines = ["## TOOL CATALOG (validated — exact rpc names + arg keys)", ""]
    for rpc, e in TOOL_CATALOG.items():
        req = ", ".join(sorted(e["required"])) or "—"
        opt = ", ".join(sorted(e["optional"])) or "—"
        lines.append(f"### {rpc} ({e['mode']})")
        lines.append(f"- purpose: {e['purpose']}")
        lines.append(f"- required args: {req}")
        lines.append(f"- optional args: {opt}")
        lines.append(f"- when: {e['when_to_use']}")
        if e.get("note"):
            lines.append(f"- NOTE: {e['note']}")
        lines.append(f"- example: {e['example']}")
        lines.append("")
    lines.append("Use ONLY these rpc names and arg keys. An unknown rpc or arg key is "
                 "rejected by the interpreter and returned to you to fix.")
    return "\n".join(lines)
