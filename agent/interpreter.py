"""Deterministic executor of a PlanIR against the real VM (or MockVMSpy).

Execution order: seed -> discovery -> rowsets -> compute/custom_extract ->
decision -> ops -> answer assembly -> refuse invariant. The interpreter NEVER
calls vm.answer — it returns a CapturedAnswer; the pipeline submits after VERIFY.
"""
from __future__ import annotations

import csv as _csv
import io
import json
import re as _re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .ir_models import IntentSpec, PlanIR, RowSet
from .predicates import evaluate, resolve
from .trace import current_cycle, get_trace


def _trace_vm(phase: str, rpc: str, kwargs: dict, payload: str, mutated: bool) -> None:
    """Best-effort VM-call trace; no-op when no TraceLogger is attached (tests).

    Tracing is pure observability and must NEVER break execution — any logger
    error (e.g. a stale/closed handle) is swallowed.
    """
    t = get_trace()
    if t is None:
        return
    try:
        t.log_vm_call(current_cycle(), phase, rpc, kwargs, payload, mutated)
    except Exception:
        pass


def _trace_answer(message: str, outcome: str, refs: list) -> None:
    """Best-effort answer trace (see `_trace_vm`)."""
    t = get_trace()
    if t is None:
        return
    try:
        t.log_answer(current_cycle(), message, outcome, refs)
    except Exception:
        pass


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


def _exit_code(result: Any) -> int:
    code = getattr(result, "exit_code", None)
    if code is None and isinstance(result, dict):
        code = result.get("exit_code", 0)
    return int(code or 0)


def _classify_from_exit(spec, result) -> str:
    if _exit_code(result) == 0:
        return spec.ok_outcome
    blob = (_payload(result) + " " +
            (getattr(result, "stderr", "") or
             (result.get("stderr", "") if isinstance(result, dict) else ""))).lower()
    for bucket in spec.keyword_buckets:
        if any(k.lower() in blob for k in bucket.keywords):
            return bucket.outcome
    return spec.default_outcome


def _payload(result: Any) -> str:
    stdout = getattr(result, "stdout", None)
    if stdout is None and isinstance(result, dict):
        stdout = result.get("stdout", "")
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content", "")
    return (stdout or content or "").strip()


def _is_sql_banner(payload: str) -> bool:
    """True when /bin/sql returned its usage banner instead of data — a runtime backstop
    to the pre-lint repair. Detect it so the pipeline retries instead of parsing an empty
    rowset."""
    head = (payload or "").lstrip()
    return head.startswith("# /bin/sql") or "Send SQL on stdin" in head


def _resolve_args(args: dict, env: dict) -> dict:
    out: dict = {}
    for k, v in (args or {}).items():
        if isinstance(v, list):
            out[k] = [resolve(x, env) for x in v]
        else:
            out[k] = resolve(v, env)
    return out


_SLOT_RE = _re.compile(r"\{([^{}]+)\}")


def _fill_slots(message: str, env: dict) -> str:
    def repl(m):
        val = resolve("$" + m.group(1), env)
        return "" if val is None else str(val)
    return _SLOT_RE.sub(repl, message)


def _project_required_refs(intent: "IntentSpec", outcome: str, env: dict) -> tuple[list[str], list[str]]:
    """Build answer.refs from intent.required_refs[outcome]. Return (refs, unresolved).

    policy_doc -> literal `path`; record_path -> resolve(`source`, env).
    A record_path that resolves to None/"" lands in `unresolved`.
    """
    out, unresolved = [], []
    for r in intent.required_refs.get(outcome, []):
        if r.kind == "policy_doc":
            if r.path:
                out.append(r.path)
            else:
                unresolved.append(f"policy_doc:{r.kind}")
        else:  # record_path
            val = resolve(r.source, env)
            if val in (None, ""):
                unresolved.append(r.source)
            else:
                out.append(str(val))
    return out, unresolved


def _resolve_authored_refs(authored, env: dict) -> list[str]:
    """Best-effort resolution of PLAN-authored answer.refs for CONDITIONAL grounding.
    A `$ref` is resolved against env; one that resolves to None/"" is DROPPED (not refused)
    — this is how a ref needed only on some branches (e.g. a record_path present only when a
    match is found) is grounded without forcing it on the empty branch. A plain string is a
    literal. Enforced (always-required) refs stay in intent.required_refs; this only ADDS."""
    out: list[str] = []
    for r in authored or []:
        if isinstance(r, str) and r.startswith("$"):
            val = resolve(r, env)
            if val not in (None, ""):
                out.append(str(val))
        elif isinstance(r, str) and r:
            out.append(r)
    return out


def _refuse(msg: str, mutation_landed: bool) -> InterpretError:
    """Build an InterpretError tagged with mutation state (retry-safety)."""
    err = InterpretError(msg)
    err.mutation_landed = mutation_landed
    return err


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


def lint_security_first(plan: PlanIR) -> None:
    """H3: every branch whose label -> DENIED_SECURITY must precede non-DENIED branches."""
    denied = {lbl for lbl, tmpl in plan.answer.items()
              if tmpl.outcome == "OUTCOME_DENIED_SECURITY"}
    last_denied = -1
    first_nondenied = len(plan.decision.branches)
    for i, br in enumerate(plan.decision.branches):
        if br.label in denied:
            last_denied = i
        elif first_nondenied == len(plan.decision.branches):
            first_nondenied = i
    if last_denied > first_nondenied:
        raise InterpretError(
            "security-first violation: a DENIED_SECURITY branch follows a "
            "non-DENIED branch in the decision tree"
        )


def repair_sql_stdin(plan: PlanIR) -> PlanIR:
    """Deterministic pre-lint repair (F3): deliver /bin/sql SQL on stdin (the reliable
    channel) instead of args (nondeterministic — intermittently yields the usage banner).
    For each Exec /bin/sql step carrying SQL in args with empty stdin, move the SQL into
    stdin and clear args. Idempotent; mutates the plan's step args in place and returns it."""
    for st in list(plan.discovery) + list(plan.ops):
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            sql_args = st.args.get("args") or []
            stdin = str(st.args.get("stdin") or "").strip()
            if sql_args and not stdin:
                st.args["stdin"] = "\n".join(str(a) for a in sql_args)
                st.args["args"] = []
    return plan


def lint(plan: PlanIR) -> None:
    """Registry-driven plan-time lint (F8). Dispatches each non-inactive check-spec in
    data/harness/checks.yaml to its `kind` handler. An ACTIVE error-severity violation
    raises InterpretError (blocks); a `candidate` entry, or a `warn`-severity one, logs
    only. Unknown kinds / malformed specs / handler errors degrade to a logged no-op."""
    from . import harness
    for spec in harness.load_checks():
        if not isinstance(spec, dict) or spec.get("status") == "inactive":
            continue
        handler = harness.handler_for(spec.get("kind"))
        if handler is None:
            print(f"[lint] unknown check kind {spec.get('kind')!r} (id={spec.get('id')}) — skipped")
            continue
        try:
            violations = handler(plan, spec)
        except Exception as e:                       # a bad handler/spec is never fatal
            print(f"[lint] check {spec.get('id')!r} errored: {e} — skipped")
            continue
        if not violations:
            continue
        blocking = (spec.get("status", "active") == "active"
                    and spec.get("severity", "error") == "error")
        if blocking:
            raise InterpretError("; ".join(violations))
        print(f"[lint] warn ({spec.get('id')}): {violations[0]}")


def interpret(plan: PlanIR, intent: IntentSpec, vm, facts=None) -> InterpretResult:
    lint_security_first(plan)
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
        _trace_vm("INTERPRET", step.rpc, kwargs, pay, mutated=False)
        observations.append(f"[{step.rpc} {kwargs.get('path', kwargs.get('root', ''))}] {pay[:_OBS_PER_CALL]}")
        if step.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            sql_results.append(pay)
            if _is_sql_banner(pay):
                raise _refuse("sql returned usage banner — SQL not delivered via stdin", False)

    # 3. rowsets
    for rs in plan.rowsets:
        env[rs.into] = _parse_rowset(_payload(env.get(rs.from_)), rs)

    # 4. compute + custom_extract — a type-incorrect step (e.g. a list-op on a single
    #    dict) becomes a retryable InterpretError, never a bare crash the pipeline would
    #    misclassify as a real-VM error (F1). compute runs before any op, so
    #    mutation_landed is still False here -> the pipeline safely retries.
    from .primitives import run_parser, run_primitive
    for cs in plan.compute:
        try:
            cargs = [resolve(a, env) for a in cs.args]
            env[cs.into] = run_primitive(cs.prim, cargs)
        except (TypeError, AttributeError, KeyError, IndexError) as e:
            raise _refuse(f"compute step '{cs.prim}' failed: {e}", mutation_landed)
    for ce in plan.custom_extract:
        try:
            env[ce.into] = run_parser(ce.name, _payload(env.get(ce.input)), intent.params or {})
        except (TypeError, AttributeError, KeyError, IndexError) as e:
            raise _refuse(f"custom_extract '{ce.name}' failed: {e}", mutation_landed)

    # 5. decision (security branch ordering enforced by lint_security_first)
    label = plan.decision.default_label
    for br in plan.decision.branches:
        if evaluate(br.when, env):
            label = br.label
            break

    # 6. guarded ops
    exit_outcome: str | None = None
    for op in plan.ops:
        if op.guard_label is not None and op.guard_label != label:
            continue                                   # decide-then-guard
        kwargs = _resolve_args(op.args, env)
        result = getattr(vm, op.rpc.lower())(**kwargs)
        if op.bind:
            env[op.bind] = result
        _mut = op.rpc in _MUTATING or (op.rpc == "Exec" and str(kwargs.get("path", "")).startswith("/bin/")
                                       and kwargs.get("path") != "/bin/sql")
        if _mut:
            mutation_landed = True
        _trace_vm("INTERPRET", op.rpc, kwargs, _payload(result), mutated=_mut)
        if op.rpc == "Exec" and kwargs.get("path") == "/bin/sql":
            pay = _payload(result)
            sql_results.append(pay)
            if _is_sql_banner(pay):
                raise _refuse("sql returned usage banner — SQL not delivered via stdin",
                              mutation_landed)
        if op.outcome_from_exit is not None:           # mutate-then-classify
            exit_outcome = _classify_from_exit(op.outcome_from_exit, result)

    # 7. answer assembly — ENFORCED refs are projected from intent.required_refs[outcome];
    #    the selected template's authored refs add best-effort CONDITIONAL grounding
    #    (resolved $refs that land, dropped if they resolve to nothing — per-branch refs).
    tmpl = plan.answer.get(label) or next(iter(plan.answer.values()))
    outcome = exit_outcome or tmpl.outcome
    message = _fill_slots(tmpl.message, env)
    refs, unresolved = _project_required_refs(intent, outcome, env)

    # 8. refuse invariant: an OK answer whose required record_path ref did not
    #    resolve carries mutation_landed so the pipeline routes to terminal.
    if outcome == "OUTCOME_OK" and unresolved:
        raise _refuse(f"unresolved required ref(s) {unresolved!r} on OK answer", mutation_landed)
    for r in _resolve_authored_refs(tmpl.refs, env):   # conditional grounding (deduped)
        if r not in refs:
            refs.append(r)
    _trace_answer(message, outcome, refs)
    captured = CapturedAnswer(message=message, outcome=outcome, refs=refs)
    return InterpretResult(captured=captured, env=env, observations=observations,
                           sql_results=sql_results, mutation_landed=mutation_landed,
                           label=label)
