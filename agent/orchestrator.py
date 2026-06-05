"""Minimal orchestrator — reads AGENTS.MD then dispatches the pipeline."""
from __future__ import annotations

import os

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import ReadRequest

from agent.pipeline import run_pipeline
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
    schema_text = _discover_schema(vm)
    table_names = _discover_table_names(vm) if schema_text else []
    sample_rows = _discover_sample_rows(vm, table_names) if table_names else ""
    agents_md_text = _augment_agents_md(agents_md_text, schema_text, sample_rows)
    metrics = run_pipeline(vm, instruction=task_text, task_id=task_id, agents_md_text=agents_md_text)
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
