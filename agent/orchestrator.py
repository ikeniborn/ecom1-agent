"""Minimal orchestrator for ecom benchmark."""
from __future__ import annotations

import os

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync

from agent.prephase import run_prephase
from agent.pipeline import run_pipeline

_MODEL = os.environ.get("MODEL", "")


def run_agent(
    model_configs: dict,
    harness_url: str,
    task_text: str,
    task_id: str = "",
    injected_session_rules: list[str] | None = None,
    injected_prompt_addendum: str = "",
) -> dict:
    """Execute a single benchmark task."""
    vm = EcomRuntimeClientSync(harness_url)
    model = _MODEL
    cfg = model_configs.get(model, {}) if model_configs else {}
    pre = run_prephase(vm, task_text)
    stats, _ = run_pipeline(
        vm, model, task_text, pre, cfg,
        task_id=task_id,
        injected_session_rules=injected_session_rules or [],
        injected_prompt_addendum=injected_prompt_addendum,
    )
    stats["model_used"] = model
    stats["task_type"] = "lookup"
    return stats
