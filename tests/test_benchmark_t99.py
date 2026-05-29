"""HM1 regression — t99 from empty learned state to OUTCOME_OK.

Env-gated. Set RUN_BENCHMARK=1 to enable (uses a real LLM tier).
"""
import os
import subprocess
import sys

import pytest
import yaml


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BENCHMARK") != "1",
    reason="RUN_BENCHMARK=1 not set",
)


def test_t99_runs_from_empty_to_outcome_ok(tmp_path, monkeypatch):
    learned = "data/learned/t99.yaml"
    monkeypatch.setenv("MAX_STEPS", "3")
    subprocess.run(["uv", "run", "python", "-m", "main", "--task", "t99"], check=True, timeout=600)
    data = yaml.safe_load(open(learned))
    assert data["last_run"]["status"] == "success"
    assert data["last_run"]["outcome"] == "OUTCOME_OK"
