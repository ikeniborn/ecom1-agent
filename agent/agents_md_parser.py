import re


def parse_agents_md(content: str) -> dict[str, list[str]]:
    """Parse AGENTS.MD into {section_name: [lines]} for each ## section."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower().replace(" ", "_")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


_PATH_RE = re.compile(r"/[\w][\w./-]*")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_INVENTORY_CAP = 40


def render_inventory(content: str) -> str:
    """Compact, deterministic (0 LLM) tool/catalog inventory from AGENTS.MD.

    Collects backtick-quoted single tokens (tools/RPCs) and absolute path
    literals (catalog/dir paths). Used as a thin stand-in for the full document
    in both fact tiers so the verbose AGENTS.MD prose is not re-injected.
    """
    if not content:
        return ""
    tools: list[str] = []
    paths: list[str] = []
    for m in _CODE_RE.findall(content):
        t = m.strip()
        if t and " " not in t and "/" not in t and t not in tools:
            tools.append(t)
    for m in _PATH_RE.findall(content):
        p = m.rstrip(".,;:)'\"")
        if p and p not in paths:
            paths.append(p)
    lines: list[str] = []
    if tools:
        lines.append("tools/rpcs: " + ", ".join(tools[:_INVENTORY_CAP]))
    if paths:
        lines.append("catalog/paths: " + ", ".join(paths[:_INVENTORY_CAP]))
    return "\n".join(lines)
