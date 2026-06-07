"""JSON extraction from free-form LLM text output.

Public API:
  _obj_mutation_tool()      — check if a JSON object is a mutation action
  _richness_key()           — deterministic tie-break for same-tier candidates
  _extract_json_from_text() — multi-level priority JSON extraction
"""
import json
import re

from .llm import CLI_YELLOW, CLI_CLR


def _try_json5(text: str):
    """Try json5 parse; raises on failure (ImportError or parse error)."""
    import json5 as _j5
    return _j5.loads(text)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MUTATION_TOOLS = frozenset({"write", "delete", "exec"})

# Maps Req_XXX class names to canonical tool names used in JSON payloads.
# Some models emit "Action: Req_Read({...})" without a "tool" field inside the JSON.
_REQ_CLASS_TO_TOOL: dict[str, str] = {
    "req_read": "read", "req_write": "write", "req_delete": "delete",
    "req_list": "list", "req_search": "search", "req_find": "find",
    "req_tree": "tree", "req_stat": "stat", "req_exec": "exec",
}
# Regex: capture "Req_Xxx" prefix immediately before a JSON object — FIX-150
_REQ_PREFIX_RE = re.compile(r"Req_(\w+)\s*\(", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _obj_mutation_tool(obj: dict) -> str | None:
    """Return the mutation tool name if obj is a write/delete/exec action, else None."""
    tool = obj.get("tool")
    if not tool:
        fn = obj.get("function")
        if isinstance(fn, dict):
            tool = fn.get("tool", "")
    return tool if tool in _MUTATION_TOOLS else None


def _richness_key(obj: dict) -> tuple:
    """Lower tuple = preferred. Used by min() to break ties among same-tier candidates."""
    return (-len(obj),)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json_from_text(text: str) -> dict | None:
    """Extract the most actionable valid JSON object from free-form model output.

    Priority (highest first):
    1. ```json fenced block — explicit, return immediately
    2. First object whose tool is a mutation (write/delete/exec)
    3. First bare object with any known 'tool' key
    4. First valid JSON object (richest by key count)
    5. YAML fallback
    """
    # 1. ```json ... ``` fenced block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Collect ALL valid bracket-matched JSON objects.
    # FIX-150: detect "Req_XXX({...})" patterns and inject "tool" when absent.
    candidates: list[dict] = []
    pos = 0
    while True:
        start = text.find("{", pos)
        if start == -1:
            break
        prefix_match = None
        prefix_region = text[max(0, start - 20):start]
        pm = _REQ_PREFIX_RE.search(prefix_region)
        if pm:
            req_name = pm.group(1).lower()
            inferred_tool = _REQ_CLASS_TO_TOOL.get(f"req_{req_name}")
            if inferred_tool:
                prefix_match = inferred_tool
        depth = 0
        in_str = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            # String-aware: braces/quotes inside a JSON string value must not move
            # the brace depth, else an object whose value embeds Python code (e.g.
            # {"script_code": "x = {1: 2}"}) is mis-matched (t02 codegen parse fail).
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    fragment = text[start:idx + 1]
                    obj = None
                    try:
                        obj = json.loads(fragment)
                    except (json.JSONDecodeError, ValueError):
                        try:
                            obj = _try_json5(fragment)
                        except Exception:
                            pass
                    if obj is not None and isinstance(obj, dict):
                        if prefix_match and "tool" not in obj:
                            obj = {"tool": prefix_match, **obj}
                        candidates.append(obj)
                    pos = idx + 1
                    break
        else:
            # FIX-401: bracket-balance repair — truncated JSON at EOF
            repaired = text[start:] + "}" * depth
            for _load in (json.loads, _try_json5):
                try:
                    obj = _load(repaired)
                    if isinstance(obj, dict):
                        if prefix_match and "tool" not in obj:
                            obj = {"tool": prefix_match, **obj}
                        candidates.append(obj)
                        break
                except Exception:
                    continue
            break

    if candidates:
        # 2. Mutation (write/delete/exec)
        _muts = [o for o in candidates if _obj_mutation_tool(o)]
        if _muts:
            return min(_muts, key=_richness_key)
        # 3. Bare object with any known tool key
        _bare = [o for o in candidates if "tool" in o]
        if _bare:
            return min(_bare, key=_richness_key)
        # 4. Richest candidate
        return min(candidates, key=_richness_key)

    # 5. YAML fallback
    try:
        import yaml
        stripped = re.sub(r"```(?:yaml|markdown)?\s*", "", text.strip()).replace("```", "").strip()
        parsed_yaml = yaml.safe_load(stripped)
        if isinstance(parsed_yaml, dict) and "tool" in parsed_yaml:
            print(f"\x1B[33m[fallback] YAML fallback parsed successfully\x1B[0m")
            return parsed_yaml
    except Exception:
        pass

    return None
