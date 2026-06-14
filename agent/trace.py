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


class TraceLogger:
    def __init__(self, path: Path, task_id: str) -> None:
        self._fh = path.open("w", buffering=1, encoding="utf-8")
        self._task_id = task_id
        self._seen_sha: set[str] = set()

    def _ts(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    def _write(self, record: dict) -> None:
        record.setdefault("ts", self._ts())
        record.setdefault("task_id", self._task_id)
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")

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
    ) -> None:
        sha = self._ensure_header_system(system)
        self._write({
            "type": "llm_call",
            "cycle": cycle,
            "phase": phase,
            "system_sha256": sha,
            "user_msg": user_msg,
            "raw_response": raw_response,
            "parsed_output": parsed_output,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "duration_ms": duration_ms,
            "success": parsed_output is not None or bool(raw_response),
        })

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

    def log_tdd_warning(self, suite: str, warnings: list[str]) -> None:
        self._write({"type": "tdd_warning", "suite": suite, "warnings": warnings})

    def log_schema_refresh(self, cycle: int, added_tables: list[str]) -> None:
        self._write({
            "type": "schema_refresh",
            "cycle": cycle,
            "added_tables": list(added_tables),
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
