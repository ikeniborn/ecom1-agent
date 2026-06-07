"""Deterministic executor of a PlanIR against the real VM (or MockVMSpy).

Execution order: seed -> discovery -> rowsets -> compute/custom_extract ->
decision -> ops -> answer assembly -> refuse invariant. The interpreter NEVER
calls vm.answer — it returns a CapturedAnswer; the pipeline submits after VERIFY.
"""
from __future__ import annotations

import csv as _csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .ir_models import IntentSpec, PlanIR, RowSet
from .predicates import resolve


class InterpretError(RuntimeError):
    mutation_landed: bool = False   # set True when a mutation already landed -> retry unsafe


class CapturedAnswer(BaseModel):
    message: str
    outcome: str
    refs: list[str] = []


@dataclass
class InterpretResult:
    captured: CapturedAnswer
    env: dict
    observations: list[str] = field(default_factory=list)
    sql_results: list[str] = field(default_factory=list)
    mutation_landed: bool = False
    label: str = ""


_MUTATING = {"Write", "Delete"}
_OBS_PER_CALL = 800


def _payload(result: Any) -> str:
    stdout = getattr(result, "stdout", None)
    if stdout is None and isinstance(result, dict):
        stdout = result.get("stdout", "")
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content", "")
    return (stdout or content or "").strip()


def _resolve_args(args: dict, env: dict) -> dict:
    out: dict = {}
    for k, v in (args or {}).items():
        if isinstance(v, list):
            out[k] = [resolve(x, env) for x in v]
        else:
            out[k] = resolve(v, env)
    return out


def _delim_for(text: str, fmt: str) -> str:
    if fmt == "tsv":
        return "\t"
    if fmt == "csv":
        return ","
    if fmt == "pipe":
        return "|"
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    for d in ("|", "\t", ","):
        if d in first:
            return d
    return ","


def _parse_rowset(text: str, rs: RowSet) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    if rs.format == "json":
        try:
            data = json.loads(text)
        except ValueError:
            return []
        return data if isinstance(data, list) else [data]
    delim = _delim_for(text, rs.format)
    reader = _csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out = [dict(zip(header, (c.strip() for c in r))) for r in rows[1:]]
    for col in rs.columns:                       # ColResolve: alias first present header
        src = next((h for h in header if h.lower() in
                    {c.lower() for c in col.candidates}), None)
        if src and src != col.into:
            for row in out:
                row[col.into] = row.get(src)
    return out


def interpret(plan: PlanIR, intent: IntentSpec, vm, facts=None) -> InterpretResult:
    env: dict = dict(intent.params or {})
    if facts is not None:
        env["_facts"] = facts
    observations: list[str] = []
    sql_results: list[str] = []
    mutation_landed = False

    # 2. discovery (read-only, in order)
    for step in plan.discovery:
        kwargs = _resolve_args(step.args, env)
        result = getattr(vm, step.rpc.lower())(**kwargs)
        if step.bind:
            env[step.bind] = result
        pay = _payload(result)
        observations.append(f"[{step.rpc} {kwargs.get('path', kwargs.get('root', ''))}] {pay[:_OBS_PER_CALL]}")
        if step.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(pay)

    # 3. rowsets
    for rs in plan.rowsets:
        env[rs.into] = _parse_rowset(_payload(env.get(rs.from_)), rs)

    # 4. compute + custom_extract
    from .primitives import run_parser, run_primitive
    for cs in plan.compute:
        cargs = [resolve(a, env) for a in cs.args]
        env[cs.into] = run_primitive(cs.prim, cargs)
    for ce in plan.custom_extract:
        env[ce.into] = run_parser(ce.name, _payload(env.get(ce.input)), intent.params or {})

    # (compute / custom_extract / decision / ops / answer added in later tasks)
    captured = CapturedAnswer(message="", outcome="OUTCOME_NONE_CLARIFICATION", refs=[])
    return InterpretResult(captured=captured, env=env, observations=observations,
                           sql_results=sql_results, mutation_landed=mutation_landed)
