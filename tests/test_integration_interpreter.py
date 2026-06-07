# tests/test_integration_interpreter.py
"""Integration: t09/t27/t51 end-to-end behind INTERPRETER_ENABLED (spec testing layer).

Env-gated. Set RUN_BENCHMARK=1 to enable (real LLM tier + live harness).
"""
import os
import subprocess

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BENCHMARK") != "1", reason="RUN_BENCHMARK=1 not set"
)

_LEGIT = {"OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED", "OUTCOME_DENIED_SECURITY"}


def test_named_tasks_end_to_end_behind_flag(monkeypatch):
    monkeypatch.setenv("INTERPRETER_ENABLED", "1")
    monkeypatch.setenv("MAX_STEPS", "3")
    subprocess.run(["uv", "run", "python", "-m", "main", "t09,t27,t51"],
                   check=True, timeout=1800)
    for tid in ("t09", "t27", "t51"):
        data = yaml.safe_load(open(f"data/learned/{tid}.yaml"))
        assert data["last_run"]["outcome"] in _LEGIT, f"{tid}: {data['last_run']}"
