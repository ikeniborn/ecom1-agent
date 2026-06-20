"""Thread-local structured JSONL trace logger for per-task pipeline traces."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_tl = threading.local()


def get_trace() -> "TraceLogger | None":
    return getattr(_tl, "logger", None)


def set_trace(logger: "TraceLogger | None") -> None:
    _tl.logger = logger


def set_cycle(n: int) -> None:
    """Record the active pipeline cycle so funnel-logged llm_call records are tagged."""
    _tl.cycle = n


def current_cycle() -> int:
    return getattr(_tl, "cycle", 0)


def set_step_type(st: str) -> None:
    """Record the active step_type so VM/gate records emitted by the VM layer
    (which has no phase context) are tagged. PREPHASE_GATHER in the orchestrator,
    INTERPRET in the interpreter."""
    _tl.step_type = st


def current_step_type() -> str:
    return getattr(_tl, "step_type", "")


# Truncation caps for the deterministic-execution records (keep traces analysis-sized).
_VM_HEAD_CAP = 1000
_FACT_HEAD_CAP = 2000
_VM_ARG_KEYS = ("path", "root", "pattern", "args", "stdin")

_PHASE_TO_STEP_TYPE = {
    "INTENT": "INTENT", "PLAN": "PLAN", "ILEARN": "ILEARN", "LEARN": "ILEARN",
    "DOC_SELECT": "DOC_SELECT", "RERANK": "ORACLE_RETRIEVE",
    "DISTILL": "DISTILL", "HARNESS_DISTILL": "DISTILL",
}


def _step_type_for_phase(phase: str) -> str:
    p = (phase or "").upper()
    return _PHASE_TO_STEP_TYPE.get(p, p)


def _head(text: str, cap: int) -> str:
    text = text or ""
    if cap and len(text) > cap:
        return text[:cap] + f"… [+{len(text) - cap} chars]"
    return text


def _result_text(result) -> str:
    """Best-effort payload text from an RPC result (proto object or dict)."""
    if isinstance(result, str):
        return result
    stdout = getattr(result, "stdout", None)
    if stdout is None and isinstance(result, dict):
        stdout = result.get("stdout")
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    return str(stdout or content or "")


class TraceLogger:
    def __init__(self, path: Path, task_id: str) -> None:
        self.path = path
        # Readable digest, refreshed live after every record so it is watchable
        # mid-run (tail -f) — not just at task end.
        self._detail_path = path.with_suffix(".detail.log")
        self._records: list[dict] = []
        self._fh = path.open("w", buffering=1, encoding="utf-8")
        self._task_id = task_id
        self._seen_sha: set[str] = set()
        self._seq = 0
        self._last_llm_seq: int | None = None

    def _ts(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    def _write(self, record: dict) -> None:
        record.setdefault("seq", self._seq)
        self._seq += 1
        record.setdefault("ts", self._ts())
        record.setdefault("task_id", self._task_id)
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._records.append(record)
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        """Re-render the readable {tid}.detail.log live (best-effort).

        Cheap — a task emits only tens of records; re-rendering on each keeps the
        digest current so it can be `tail`-watched while the task runs.
        """
        try:
            self._detail_path.write_text(render_trace(self._records, color=False), encoding="utf-8")
        except Exception:
            pass

    def _sys_sha256(self, system: "str | list[dict]") -> str:
        raw = json.dumps(system, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _ensure_header_system(self, system: "str | list[dict]") -> str:
        sha = self._sys_sha256(system)
        if sha not in self._seen_sha:
            self._seen_sha.add(sha)
            blocks = system if isinstance(system, list) else [{"type": "text", "text": system}]
            self._write({"type": "header_system", "sha256": sha, "blocks": blocks})
        return sha

    def log_header(self, task_text: str, model: str) -> None:
        self._write({"type": "header", "task_text": task_text, "model": model})

    def log_llm_call(
        self,
        phase: str,
        cycle: int,
        system: "str | list[dict]",
        user_msg: str,
        raw_response: str,
        parsed_output: "dict | None",
        tokens_in: int,
        tokens_out: int,
        duration_ms: int,
        reasoning: str = "",
        reasoning_available: "bool | None" = None,
        raw_response_full: str = "",
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        sha = self._ensure_header_system(system)
        avail = bool(reasoning) if reasoning_available is None else bool(reasoning_available)
        rec = {
            "type": "llm_call",
            "cycle": cycle,
            "phase": phase,
            "step_type": _step_type_for_phase(phase),
            "prev_llm_seq": self._last_llm_seq,
            "system_sha256": sha,
            "user_msg": user_msg,
            "raw_response": raw_response,
            "raw_response_full": raw_response_full or raw_response,
            "reasoning": reasoning or "",
            "reasoning_available": avail,
            "parsed_output": parsed_output,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_read": cache_read,
            "cache_creation": cache_creation,
            "duration_ms": duration_ms,
            "success": parsed_output is not None or bool(raw_response),
        }
        self._last_llm_seq = self._seq  # seq this record will receive in _write
        self._write(rec)

    def log_gate_check(
        self,
        cycle: int,
        gate_type: str,
        queries: list[str],
        blocked: bool,
        error: "str | None",
    ) -> None:
        self._write({
            "type": "gate_check",
            "cycle": cycle,
            "gate_type": gate_type,
            "queries": queries,
            "blocked": blocked,
            "error": error,
        })

    def log_sql_validate(
        self,
        cycle: int,
        query: str,
        result: str,
        error: "str | None",
    ) -> None:
        self._write({
            "type": "sql_validate",
            "cycle": cycle,
            "query": query,
            "explain_result": result,
            "error": error,
        })

    def log_sql_execute(
        self,
        cycle: int,
        query: str,
        result: str,
        has_data: bool,
        duration_ms: int,
    ) -> None:
        self._write({
            "type": "sql_execute",
            "cycle": cycle,
            "query": query,
            "result": result,
            "has_data": has_data,
            "duration_ms": duration_ms,
        })

    def log_resolve_exec(self, query: str, result: str, value: str) -> None:
        self._write({
            "type": "resolve_exec",
            "query": query,
            "result": result,
            "value_extracted": value,
        })

    def log_test_gen(self, sql_tests_code: str, answer_tests_code: str) -> None:
        self._write({
            "type": "test_gen",
            "sql_tests": sql_tests_code,
            "answer_tests": answer_tests_code,
        })

    def log_test_run(
        self,
        cycle: int,
        suite: str,
        passed: bool,
        error: str,
        context_snapshot: str = "",
    ) -> None:
        self._write({
            "type": "test_run",
            "cycle": cycle,
            "suite": suite,
            "passed": passed,
            "error": error,
            "context_snapshot": context_snapshot,
        })

    def log_schema_refresh(self, cycle: int, added_tables: list[str]) -> None:
        self._write({
            "type": "schema_refresh",
            "cycle": cycle,
            "added_tables": list(added_tables),
        })

    def log_facts(self, facts) -> None:
        """Pre-phase grounding facts (docs/policies/schema/identity/status).

        Accepts a `PrePhaseFacts` (model_dump) or a plain dict. Long doc/schema
        bodies are truncated to `_FACT_HEAD_CAP` so the trace stays analysis-sized.
        """
        data = facts.model_dump() if hasattr(facts, "model_dump") else dict(facts or {})
        policies = {k: _head(v, _FACT_HEAD_CAP) for k, v in (data.get("policies") or {}).items()}
        targets = {k: _head(v, _FACT_HEAD_CAP) for k, v in (data.get("target_records") or {}).items()}
        self._write({
            "type": "facts",
            "docs_inventory": data.get("docs_inventory", ""),
            "policies": policies,
            "schema": _head(data.get("schema", ""), _FACT_HEAD_CAP),
            "sample_rows": _head(data.get("sample_rows", ""), _FACT_HEAD_CAP),
            "identity": data.get("identity", {}),
            "target_records": targets,
            "gather_status": data.get("gather_status", {}),
        })

    def log_vm_call(self, cycle: int, step_type: str, rpc: str, args: dict,
                    result, mutated: bool = False, *,
                    validation: str = "ok", duration_ms: int = 0) -> None:
        """One VM RPC: which call (filtered args), validation verdict, and result head.

        `step_type` is also mirrored to `phase` for backward-compatible readers.
        `bytes`/`has_data` are computed from the full result text before capping.
        """
        text = _result_text(result)
        self._write({
            "type": "vm_call",
            "cycle": cycle,
            "step_type": step_type,
            "phase": step_type,
            "rpc": rpc,
            "args": {k: v for k, v in (args or {}).items() if k in _VM_ARG_KEYS},
            "validation": validation,
            "bytes": len(text),
            "has_data": bool(text.strip()),
            "result_head": _head(text, _VM_HEAD_CAP),
            "mutated": bool(mutated),
            "duration_ms": duration_ms,
        })

    def log_gate(self, cycle: int, step_type: str, passed: bool, reason: str) -> None:
        """A deterministic gate verdict (LINT | INTERPRET | VERIFY). Supersedes the
        ad-hoc gate_check record."""
        self._write({
            "type": "gate",
            "cycle": cycle,
            "step_type": step_type,
            "passed": bool(passed),
            "reason": reason or "",
        })

    def log_answer(self, cycle: int, message: str, outcome: str, refs: list) -> None:
        """The final answer submitted to the grader — refs kept in full (small)."""
        self._write({
            "type": "answer",
            "cycle": cycle,
            "message": message,
            "outcome": outcome,
            "refs": list(refs or []),
        })

    def log_task_result(
        self,
        outcome: str,
        score: float,
        cycles: int,
        total_in: int,
        total_out: int,
        elapsed_ms: int,
        score_detail: list[str],
    ) -> None:
        self._write({
            "type": "task_result",
            "outcome": outcome,
            "score": score,
            "cycles_used": cycles,
            "total_tokens_in": total_in,
            "total_tokens_out": total_out,
            "elapsed_ms": elapsed_ms,
            "score_detail": score_detail,
        })

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()


# ---------------------------------------------------------------------------
# Rendering — shared by scripts/trace_view.py (CLI) and the auto {tid}.detail.log
# ---------------------------------------------------------------------------

_PALETTE = {
    "reset": "\x1b[0m", "dim": "\x1b[2m", "bold": "\x1b[1m", "red": "\x1b[31m",
    "green": "\x1b[32m", "yellow": "\x1b[33m", "blue": "\x1b[34m",
    "magenta": "\x1b[35m", "cyan": "\x1b[36m",
}


def _flatten_system(blocks) -> str:
    if isinstance(blocks, str):
        return blocks
    return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in (blocks or []))


def render_trace(source, *, color: bool = False, max_chars: int = 0, phase: str | None = None,
                 no_system: bool = False, full_system: bool = False, llm_only: bool = False) -> str:
    """Render a per-task trace (jsonl path or record list) to readable text.

    Returns a plain string (no trailing print). Pass `color=False` for files
    (the auto {tid}.detail.log) and `color=True` for an interactive terminal.
    """
    if isinstance(source, (str, Path)):
        records = [json.loads(l) for l in Path(source).read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        records = list(source)

    def c(text: str, key: str) -> str:
        return f"{_PALETTE[key]}{text}{_PALETTE['reset']}" if color else text

    def indent(text: str) -> str:
        body = text if not max_chars or len(text) <= max_chars else (
            text[:max_chars] + c(f"\n… [truncated {len(text) - max_chars} chars]", "dim"))
        return "\n".join("    " + line for line in body.splitlines()) or "    (empty)"

    systems = {r["sha256"]: r.get("blocks") for r in records if r.get("type") == "header_system"}
    shown: set[str] = set()
    out: list[str] = []
    bar = "━" * 72

    def llm_call(rec: dict) -> None:
        cyc, ph = rec.get("cycle", 0), rec.get("phase", "?")
        mark = c("OK", "green") if rec.get("success") else c("FAIL", "red")
        out.append(c(bar, "blue"))
        out.append(f"{c('cycle ' + str(cyc), 'bold')} · {c(ph, 'magenta')} · "
                   f"{rec.get('duration_ms', 0)}ms · tokens {rec.get('tokens_in', 0)}/"
                   f"{rec.get('tokens_out', 0)} · {mark}")
        sha = rec.get("system_sha256", "")
        if not no_system:
            if full_system or sha not in shown:
                shown.add(sha)
                out.append(c(f"┌ SYSTEM ({sha[:8]})", "cyan"))
                out.append(indent(_flatten_system(systems.get(sha))))
            else:
                out.append(c(f"┌ SYSTEM ({sha[:8]}) — same as above", "dim"))
        out.append(c("├ USER", "yellow"))
        out.append(indent(rec.get("user_msg", "")))
        out.append(c("└ ASSISTANT", "green"))
        out.append(indent(rec.get("raw_response", "")))
        out.append("")

    def facts(rec: dict) -> None:
        out.append(c("═══ PRE-PHASE FACTS ═══", "bold"))
        inv = [p for p in (rec.get("docs_inventory") or "").splitlines() if p]
        out.append(f"docs_inventory ({len(inv)}):")
        out.extend(f"    {p}" for p in inv)
        out.append(f"gather_status: {json.dumps(rec.get('gather_status') or {}, ensure_ascii=False)}")
        if rec.get("identity"):
            out.append(f"identity: {json.dumps(rec['identity'], ensure_ascii=False)}")
        for label in ("policies", "target_records"):
            block = rec.get(label) or {}
            if block:
                out.append(c(f"{label}:", "cyan"))
                for path, body in block.items():
                    out.append(c(f"  ┌ {path}", "dim"))
                    out.append(indent(body))
        for label in ("schema", "sample_rows"):
            if rec.get(label):
                out.append(c(f"{label}:", "cyan"))
                out.append(indent(rec[label]))
        out.append("")

    def vm_call(rec: dict) -> None:
        a = rec.get("args") or {}
        loc = a.get("path") or a.get("root") or a.get("pattern") or ""
        sql = ""
        if rec.get("rpc") == "Exec" and a.get("args"):
            sql = " " + " ".join(str(x) for x in a["args"])[:120]
        mut = c(" [MUTATED]", "red") if rec.get("mutated") else ""
        head = (rec.get("result_head") or "").strip()
        first = head.splitlines()[0] if head else "<empty>"
        out.append(c(f"  · [{rec.get('rpc')} {loc}{sql}]{mut} -> {first}", "dim"))
        rest = head.splitlines()[1:]
        out.extend("      " + line for line in rest)

    def answer(rec: dict) -> None:
        out.append(c(f"═══ ANSWER (cycle {rec.get('cycle', 0)}) ═══", "bold"))
        out.append(f"  msg={rec.get('message')!r}  {rec.get('outcome')}  "
                   f"refs={rec.get('refs')!r}")
        out.append("")

    def event(rec: dict) -> None:
        t = rec["type"]
        pre = c(f"  · [{t}]", "dim")
        cyc = rec.get("cycle", "")
        if t == "gate_check":
            out.append(f"{pre} c{cyc} {rec.get('gate_type')} "
                       f"{'BLOCKED' if rec.get('blocked') else 'pass'} {rec.get('error') or ''}")
        elif t == "sql_execute":
            out.append(f"{pre} c{cyc} {rec.get('duration_ms')}ms data={rec.get('has_data')} "
                       f"{rec.get('query', '')[:70]}")
        elif t == "test_run":
            s = c("pass", "green") if rec.get("passed") else c("FAIL", "red")
            out.append(f"{pre} c{cyc} {rec.get('suite')} {s} {rec.get('error', '')[:80]}")
        elif t == "test_gen":
            out.append(f"{pre} sql+answer tests generated")
        elif t == "schema_refresh":
            out.append(f"{pre} c{cyc} +tables {rec.get('added_tables')}")
        else:
            payload = {k: v for k, v in rec.items() if k not in ("ts", "task_id", "type")}
            out.append(f"{pre} {json.dumps(payload, ensure_ascii=False)[:120]}")

    for r in records:
        t = r.get("type")
        if t == "header":
            out.append(c("═" * 72, "bold"))
            out.append(c(f"TASK {r.get('task_id')}  ·  model={r.get('model')}", "bold"))
            out.append(f"  {r.get('task_text', '')}")
            out.append(c("═" * 72, "bold"))
            out.append("")
        elif t == "header_system":
            continue
        elif t == "facts":
            facts(r)
        elif t == "llm_call":
            if phase and r.get("phase") != phase:
                continue
            llm_call(r)
        elif t == "vm_call":
            vm_call(r)
        elif t == "answer":
            answer(r)
        elif t == "task_result":
            out.append(c("═" * 72, "bold"))
            out.append(c("RESULT", "bold") + f"  {r.get('outcome')}  score={r.get('score')}  "
                       f"cycles={r.get('cycles_used')}  tokens {r.get('total_tokens_in')}/"
                       f"{r.get('total_tokens_out')}  {r.get('elapsed_ms')}ms")
            for line in (r.get("score_detail") or []):
                out.append(f"  - {line}")
            out.append(c("═" * 72, "bold"))
        elif not llm_only:
            event(r)

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Best-effort auto-emit — used by the VM layer and the pipeline. Read the active
# logger + thread-local cycle/step_type. NEVER raise into a run (observability).
# ---------------------------------------------------------------------------

def log_vm_auto(rpc: str, args: dict, result, *, mutated: bool = False,
                validation: str = "ok", duration_ms: int = 0) -> None:
    t = get_trace()
    if t is None:
        return
    try:
        t.log_vm_call(current_cycle(), current_step_type() or "INTERPRET", rpc, args,
                      result, mutated=mutated, validation=validation,
                      duration_ms=duration_ms)
    except Exception:
        pass


def log_gate_auto(step_type: str, passed: bool, reason: str) -> None:
    t = get_trace()
    if t is None:
        return
    try:
        t.log_gate(current_cycle(), step_type, passed, reason)
    except Exception:
        pass
