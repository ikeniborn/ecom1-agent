"""Deterministic fidelity gate.

Generates a Python test module from a DesignOutput tool_plan. Executes the
candidate script + test in a subprocess and asserts that the script's RPC
sequence matches the tool_plan exactly.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DesignOutput, ToolOp

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FidelityResult:
    passed: bool
    error: str | None = None
    stdout: str = ""
    stderr: str = ""


def _serialize_expected(ops: list[ToolOp]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for op in ops:
        out.append((op.rpc, dict(op.args)))
    return out


def _expected_answer_call(d: DesignOutput) -> tuple[str, dict[str, Any]]:
    return (
        "Answer",
        {
            "message": d.answer_template.message,
            "outcome": d.answer_template.outcome,
            "refs": list(d.answer_template.refs),
        },
    )


def generate_fidelity_test(design: DesignOutput, tid: str) -> str:
    """Emit a Python module string. Deterministic - same input => byte-equal output.

    Gate only checks the multiset of RPC names (Exec/Read/Write/Answer/...).
    Args, refs, message are NOT compared — CODEGEN may reshape them through LEARN.
    The gate's only purpose: catch hallucinated tools and skipped planned calls.
    """
    expected: list[tuple[str, dict]] = []
    expected.extend(_serialize_expected(design.discovery))
    expected.extend(_serialize_expected(design.ops))
    expected.append(_expected_answer_call(design))

    # repr (not json.dumps) — embeds as Python source, so True/False/None stay valid.
    # JSON true/false/null would become NameError at exec time.
    expected_lit = repr([list(item) for item in expected])
    params_lit = repr(dict(design.params))

    return (
        f"# auto-generated fidelity test for task {tid}\n"
        "from agent.mock_vm_spy import MockVMSpy\n"
        "\n"
        f"EXPECTED_CALLS = [tuple([rpc, args]) for rpc, args in {expected_lit}]\n"
        f"PARAMS = {params_lit}\n"
        "\n"
        "\n"
        "def test_fidelity():\n"
        "    vm = MockVMSpy(fixtures={})\n"
        "    run(vm, dict(PARAMS))   # noqa: F821 - `run` injected at exec time\n"
        "    got_rpcs = sorted(rpc for rpc, _ in vm.calls)\n"
        "    want_rpcs = sorted(rpc for rpc, _ in EXPECTED_CALLS)\n"
        "    if got_rpcs != want_rpcs:\n"
        "        raise AssertionError(\n"
        "            \"fidelity drift (RPC multiset)\\nexpected: \" + repr(want_rpcs)\n"
        "            + \"\\ngot: \" + repr(got_rpcs)\n"
        "        )\n"
    )


def exec_fidelity_in_subprocess(
    test_src: str,
    script_code: str,
    timeout_s: int = 30,
) -> FidelityResult:
    """Combine script + test in a single source, exec in a subprocess, gate on test_fidelity()."""
    combined = (
        script_code
        + "\n\n"
        + test_src
        + "\n\nif __name__ == '__main__':\n"
        + "    test_fidelity()\n"
        + "    print('FIDELITY_OK')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", combined],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(_PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired as e:
        return FidelityResult(passed=False, error=f"fidelity timeout after {timeout_s}s", stdout=e.stdout or "", stderr=e.stderr or "")

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if proc.returncode == 0 and "FIDELITY_OK" in stdout:
        return FidelityResult(passed=True, stdout=stdout, stderr=stderr)
    return FidelityResult(
        passed=False,
        error=(stderr or stdout).strip()[:2000],
        stdout=stdout,
        stderr=stderr,
    )
