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
    metrics = run_pipeline(vm, instruction=task_text, task_id=task_id, agents_md_text=agents_md_text)
    return {
        "model_used": os.environ.get("MODEL", ""),
        "task_type": "lookup",
        "cycles_used": metrics.get("cycles_used", 0),
        "outcome": metrics.get("outcome", ""),
        "input_tokens": 0,
        "output_tokens": 0,
    }
