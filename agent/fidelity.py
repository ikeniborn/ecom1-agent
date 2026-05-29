"""Deterministic fidelity gate.

Generates a Python test module from a DesignOutput tool_plan. Executes the
candidate script + test in a subprocess and asserts that the script's RPC
sequence matches the tool_plan exactly.
"""
from __future__ import annotations

import json
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
    """Emit a Python module string. Deterministic - same input => byte-equal output."""
    expected: list[tuple[str, dict]] = []
    expected.extend(_serialize_expected(design.discovery))
    expected.extend(_serialize_expected(design.ops))
    expected.append(_expected_answer_call(design))

    expected_lit = json.dumps([list(item) for item in expected], sort_keys=False, indent=2)
    params_lit = json.dumps(design.params, sort_keys=True)
    template_msg = json.dumps(design.answer_template.message)
    template_outcome = json.dumps(design.answer_template.outcome)
    template_refs = json.dumps(list(design.answer_template.refs))

    return (
        f"# auto-generated fidelity test for task {tid}\n"
        "from agent.mock_vm_spy import MockVMSpy\n"
        "\n"
        f"EXPECTED_CALLS = [tuple([rpc, args]) for rpc, args in {expected_lit}]\n"
        f"PARAMS = {params_lit}\n"
        "\n"
        "# Recognise the canned Answer call even if the script reuses the template literally\n"
        "EXPECTED_ANSWER = (\"Answer\", {\n"
        f"    \"message\": {template_msg},\n"
        f"    \"outcome\": {template_outcome},\n"
        f"    \"refs\": {template_refs},\n"
        "})\n"
        "\n"
        "\n"
        "def _normalise_calls(calls):\n"
        "    return [(rpc, dict(args)) for rpc, args in calls]\n"
        "\n"
        "\n"
        "def test_fidelity():\n"
        "    vm = MockVMSpy(fixtures={})\n"
        "    run(vm, dict(PARAMS))   # noqa: F821 - `run` injected at exec time\n"
        "    got = _normalise_calls(vm.calls)\n"
        "    want = _normalise_calls(EXPECTED_CALLS)\n"
        "    # Tool sequence (everything before Answer) must match exactly.\n"
        "    if got[:-1] != want[:-1]:\n"
        "        raise AssertionError(\n"
        "            \"fidelity drift\\nexpected: \" + repr(want) + \"\\ngot: \" + repr(got)\n"
        "        )\n"
        "    # Final call must be Answer with matching outcome and refs (message is rendered at runtime).\n"
        "    if not got:\n"
        "        raise AssertionError(\"fidelity drift: no calls emitted\")\n"
        "    last_rpc, last_args = got[-1]\n"
        "    if last_rpc != \"Answer\":\n"
        "        raise AssertionError(\"fidelity drift: final call is \" + last_rpc + \", not Answer\")\n"
        "    if last_args.get(\"outcome\") != EXPECTED_ANSWER[1][\"outcome\"]:\n"
        "        raise AssertionError(\"fidelity drift: Answer outcome mismatch \" + repr(last_args))\n"
        "    if list(last_args.get(\"refs\", [])) != EXPECTED_ANSWER[1][\"refs\"]:\n"
        "        raise AssertionError(\"fidelity drift: Answer refs mismatch \" + repr(last_args))\n"
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
