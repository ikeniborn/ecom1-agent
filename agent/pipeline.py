"""SDD-based pipeline: PREPHASE → SDD → TDD → EXECUTE → VERIFY → ANSWER → VERIFY_ANSWER."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
from pathlib import Path

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import AnswerRequest, ExecRequest, ReadRequest

from .llm import (
    call_llm_raw, _resolve_model_for_phase, OUTCOME_BY_NAME,
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, CLI_YELLOW,
)
from .json_extract import _extract_json_from_text
from .models import SddOutput, TestOutput, LearnOutput, AnswerOutput
from .test_runner import run_tests
from .prephase import PrephaseResult, _format_schema_digest as _fmt_schema_digest, merge_schema_from_sqlite_results
from .prompt import load_prompt
from .prompt_assembler import assemble_prompt, load_learned_ctx, save_learned_ctx, clear_learned_ctx
from .rules_loader import RulesLoader, _RULES_DIR
from .schema_gate import check_schema_compliance
from .sql_security import (
    check_path_access, load_security_gates,
    check_grounding_refs, check_learn_output,
    check_retry_loop, make_json_hash,
)
from .trace import get_trace


_MAX_CYCLES = int(os.environ.get("MAX_STEPS", "3"))
_EVAL_ENABLED = os.environ.get("EVAL_ENABLED", "0") == "1"
_SDD_ENABLED = os.environ.get("SDD_ENABLED", "1") == "1"
_EVAL_LOG = Path(__file__).parent.parent / "data" / "eval_log.jsonl"
_SQLITE_SCHEMA_RE = re.compile(r"\bsqlite_(?:schema|master)\b", re.IGNORECASE)

# Compat stubs — referenced by older tests that patch these names; no-ops in new pipeline
_TDD_ENABLED = False


def run_resolve(vm, model: str, task_text: str, pre, cfg: dict) -> dict:
    """Compat stub — RESOLVE phase removed from SDD pipeline."""
    return {}


def _extract_discovery_results(queries: list[str], results: list[str], confirmed_values: dict) -> None:
    """Compat stub — discovery phase removed from SDD pipeline."""


def _format_confirmed_values(cv: dict) -> str:
    """Compat stub — confirmed_values removed from SDD pipeline."""
    return ""

_rules_loader_cache: "RulesLoader | None" = None
_security_gates_cache: "list[dict] | None" = None


def _get_rules_loader() -> RulesLoader:
    global _rules_loader_cache
    if _rules_loader_cache is None:
        _rules_loader_cache = RulesLoader(_RULES_DIR)
    return _rules_loader_cache


def _get_security_gates() -> list[dict]:
    global _security_gates_cache
    if _security_gates_cache is None:
        _security_gates_cache = load_security_gates()
    return _security_gates_cache


def _exec_result_text(result) -> str:
    if isinstance(result, Message):
        try:
            d = MessageToDict(result)
            return d.get("stdout", "") or d.get("output", "") or ""
        except Exception:
            pass
    return getattr(result, "stdout", "") or getattr(result, "output", "") or ""


def _csv_has_data(result_txt: str) -> bool:
    stripped = result_txt.strip()
    if not stripped:
        return False
    if stripped.startswith("["):
        return stripped not in ("[]",)
    if stripped.startswith("{"):
        return stripped not in ("{}",)
    lines = [l for l in stripped.splitlines() if l.strip()]
    return len(lines) > 1


def _call_llm_phase(
    system: "str | list[dict]",
    user_msg: str,
    model: str,
    cfg: dict,
    output_cls,
    max_tokens: int = 4096,
    phase: str = "",
    cycle: int = 0,
) -> tuple[object | None, dict, dict]:
    tok_info: dict = {}
    t0 = time.monotonic()
    raw = call_llm_raw(system, user_msg, model, cfg, max_tokens=max_tokens, token_out=tok_info)
    duration_ms = int((time.monotonic() - t0) * 1000)
    phase_name = phase or output_cls.__name__
    _system_preview = system[:300] if isinstance(system, str) else str(system)[:300]
    sgr_entry: dict = {
        "phase": phase_name,
        "guide_prompt": _system_preview,
        "reasoning": "",
        "output": raw or "",
    }
    parsed: dict | None = None
    if raw:
        extracted = _extract_json_from_text(raw)
        if isinstance(extracted, dict):
            parsed = extracted
    if parsed is not None:
        try:
            obj = output_cls.model_validate(parsed)
            sgr_entry["reasoning"] = obj.reasoning
            sgr_entry["output"] = parsed
            if t := get_trace():
                t.log_llm_call(
                    phase=phase_name, cycle=cycle, system=system,
                    user_msg=user_msg, raw_response=raw or "",
                    parsed_output=parsed,
                    tokens_in=tok_info.get("input", 0),
                    tokens_out=tok_info.get("output", 0),
                    duration_ms=duration_ms,
                )
            return obj, sgr_entry, tok_info
        except Exception:
            pass
    if t := get_trace():
        t.log_llm_call(
            phase=phase_name, cycle=cycle, system=system,
            user_msg=user_msg, raw_response=raw or "",
            parsed_output=None,
            tokens_in=tok_info.get("input", 0),
            tokens_out=tok_info.get("output", 0),
            duration_ms=duration_ms,
        )
    return None, sgr_entry, tok_info


_format_schema_digest = _fmt_schema_digest


def _build_sdd_user_msg(task_text: str, task_type: str, learn_ctx: list[str], last_error: str) -> str:
    parts: list[str] = []
    if learn_ctx:
        rules_block = "\n".join(f"- {r}" for r in learn_ctx)
        parts.append(f"# ACCUMULATED RULES\n{rules_block}")
    parts.append(f"TASK: {task_text}")
    parts.append(f"TASK_TYPE: {task_type}")
    if last_error:
        parts.append(f"PREVIOUS ERROR: {last_error}")
    return "\n\n".join(parts)


def _build_learn_user_msg(task_text: str, queries: list[str], error: str, error_type: str) -> str:
    return (
        f"TASK: {task_text}\n"
        f"FAILED QUERIES: {json.dumps(queries)}\n"
        f"ERROR: {error}\n"
        f"ERROR_TYPE: {error_type}"
    )


def _build_answer_user_msg(task_text: str, sql_results: list[str], auto_refs: list[str]) -> str:
    base = f"TASK: {task_text}\n\nSQL RESULTS:\n" + "\n---\n".join(sql_results)
    if not auto_refs:
        return base
    refs_block = "\n".join(auto_refs)
    return base + f"\n\nAUTO_REFS (catalogue paths for grounding_refs — use exactly as shown):\n{refs_block}"


def _extract_sku_refs(queries: list[str], results: list[str]) -> list[str]:
    refs: list[str] = []
    for result_txt in results:
        lines = [ln.strip() for ln in result_txt.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        headers = [h.strip().lower() for h in lines[0].split(",")]
        if "path" in headers:
            path_idx = headers.index("path")
            for row in lines[1:]:
                cols = row.split(",")
                if path_idx < len(cols):
                    path = cols[path_idx].strip().strip('"')
                    if path:
                        refs.append(path)
        elif "sku" in headers:
            sku_idx = headers.index("sku")
            for row in lines[1:]:
                cols = row.split(",")
                if sku_idx < len(cols):
                    sku = cols[sku_idx].strip().strip('"')
                    if sku:
                        refs.append(f"/proc/catalog/{sku}.json")
        if "store_id" in headers:
            store_idx = headers.index("store_id")
            for row in lines[1:]:
                cols = row.split(",")
                if store_idx < len(cols):
                    store_id = cols[store_idx].strip().strip('"')
                    if store_id:
                        refs.append(f"/proc/stores/{store_id}.json")
    return refs


def _run_test_gen(
    model: str,
    cfg: dict,
    task_text: str,
    sdd_spec: str,
    task_type: str,
    unified_context: str = "",
) -> "TestOutput | None":
    tdd_model = _resolve_model_for_phase("tdd", model)
    tdd_guide = load_prompt("tdd") or "# PHASE: tdd\nGenerate sql_tests and answer_tests as JSON."
    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": tdd_guide, "cache_control": {"type": "ephemeral"}},
    ]
    user_msg = f"TASK: {task_text}\n\nTASK_TYPE: {task_type}\n\nSDD_SPEC:\n{sdd_spec}"
    out, _, _ = _call_llm_phase(
        system, user_msg, tdd_model, cfg, TestOutput,
        phase="tdd", cycle=0,
    )
    if out:
        if t := get_trace():
            t.log_test_gen(out.sql_tests, out.answer_tests)
    return out


def _run_learn(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    queries: list[str],
    error: str,
    sgr_trace: list[dict],
    learn_ctx: list[str],
    agents_md_index: dict,
    error_type: str = "semantic",
    cycle: int = 0,
    prior_learn_hashes: "set[str] | None" = None,
    task_id: str = "",
) -> None:
    learn_model = _resolve_model_for_phase("learn", model)
    learn_guide = load_prompt("learn") or "# PHASE: learn"
    learn_system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": learn_guide, "cache_control": {"type": "ephemeral"}},
    ]
    learn_user = _build_learn_user_msg(task_text, queries, error, error_type)
    learn_out, sgr_learn, _ = _call_llm_phase(
        learn_system, learn_user, learn_model, cfg, LearnOutput,
        max_tokens=2048, phase="learn", cycle=cycle,
    )
    sgr_learn["error_type"] = error_type
    sgr_trace.append(sgr_learn)
    if learn_out and error_type != "llm_fail":
        if prior_learn_hashes is not None:
            learn_hash = make_json_hash(learn_out.model_dump())
            learn_gate_err = check_learn_output(
                learn_out.rule_content, learn_hash, prior_learn_hashes, _get_security_gates()
            )
            if learn_gate_err:
                print(f"{CLI_YELLOW}[pipeline] LEARN blocked: {learn_gate_err}{CLI_CLR}")
                return
            prior_learn_hashes.add(learn_hash)
        anchor = learn_out.agents_md_anchor
        if anchor:
            anchor_section = anchor.split(">")[0].strip()
            if anchor_section in agents_md_index:
                anchor_lines = agents_md_index[anchor_section]
                vault_rule = f"[{anchor_section}]\n" + "\n".join(anchor_lines)
                learn_ctx.append(vault_rule)
                if task_id:
                    save_learned_ctx(task_id, learn_ctx)
                print(f"{CLI_BLUE}[pipeline] LEARN: anchor={anchor!r}, vault rule added{CLI_CLR}")
                return  # compacted_ctx ignored when anchor path taken
        compacted = learn_out.compacted_ctx
        if compacted and len(compacted) > 0 and all(isinstance(r, str) for r in compacted):
            learn_ctx[:] = compacted
            print(f"{CLI_BLUE}[pipeline] LEARN: compacted to {len(learn_ctx)} rules{CLI_CLR}")
        else:
            learn_ctx.append(learn_out.rule_content)
            print(f"{CLI_BLUE}[pipeline] LEARN: rule added (total={len(learn_ctx)}){CLI_CLR}")
        if task_id:
            save_learned_ctx(task_id, learn_ctx)


def run_pipeline(
    vm: EcomRuntimeClientSync,
    model: str,
    task_text: str,
    pre: PrephaseResult,
    cfg: dict,
    task_id: str = "",
    injected_session_rules: list[str] | None = None,
    injected_prompt_addendum: str = "",
    injected_security_gates: list[dict] | None = None,
) -> tuple[dict, threading.Thread | None]:
    """SDD-based pipeline. Returns (stats dict, eval Thread or None)."""
    rules_loader = _get_rules_loader()
    security_gates = _get_security_gates() + (injected_security_gates or [])
    _persisted = load_learned_ctx(task_id) if task_id else []
    learn_ctx: list[str] = list(dict.fromkeys(_persisted + list(injected_session_rules or [])))
    sgr_trace: list[dict] = []
    total_in_tok = 0
    total_out_tok = 0

    last_error = ""
    sql_results: list[str] = []
    sku_refs: list[str] = []
    success = False
    cycles_used = 0
    prior_query_sets: list[frozenset] = []
    prior_learn_hashes: set[str] = set()

    task_type = pre.task_type or "sql"

    _skip_sdd = False
    outcome = "OUTCOME_NONE_CLARIFICATION"
    test_gen_out: TestOutput | None = None
    sdd_out: SddOutput | None = None
    consecutive_answer_test_fails = 0
    consecutive_sql_test_fails = 0
    unified_context = ""

    try:
        for cycle in range(_MAX_CYCLES):
            cycles_used = cycle + 1
            print(f"\n{CLI_BLUE}[pipeline] cycle={cycle + 1}/{_MAX_CYCLES}{CLI_CLR}")

            assembled = assemble_prompt(
                task_text=task_text,
                task_type=task_type,
                prephase_result=pre,
                learn_ctx=learn_ctx,
                model=model,
                cfg=cfg,
                task_id=task_id,
            )
            unified_context = assembled.unified_context

            if not _skip_sdd:
                # ── SDD ───────────────────────────────────────────────────────────
                sdd_model = _resolve_model_for_phase("sdd", model)
                user_msg = _build_sdd_user_msg(task_text, task_type, learn_ctx, last_error)
                sdd_guide = load_prompt("sdd") or "# PHASE: sdd"
                sdd_system: list[dict] = [
                    {"type": "text", "text": unified_context},
                    {"type": "text", "text": sdd_guide, "cache_control": {"type": "ephemeral"}},
                ]
                sdd_out, sgr_entry, tok = _call_llm_phase(
                    sdd_system, user_msg, sdd_model, cfg, SddOutput,
                    phase="sdd", cycle=cycle + 1,
                )
                total_in_tok += tok.get("input", 0)
                total_out_tok += tok.get("output", 0)
                sgr_trace.append(sgr_entry)

                if not sdd_out:
                    raw_sdd = sgr_entry.get("output", "") if isinstance(sgr_entry.get("output"), str) else ""
                    sdd_err_type = "semantic" if raw_sdd else "llm_fail"
                    print(f"{CLI_RED}[pipeline] SDD LLM parse failed ({sdd_err_type})"
                          f"{': ' + raw_sdd[:200] if raw_sdd else ''}{CLI_CLR}")
                    last_error = f"SDD phase: failed to parse LLM output. Raw response: {raw_sdd[:400]}" if raw_sdd else "SDD phase: LLM returned empty response"
                    _run_learn(unified_context, model, cfg, task_text, [], last_error,
                               sgr_trace, learn_ctx, pre.agents_md_index,
                               error_type=sdd_err_type, cycle=cycle + 1,
                               prior_learn_hashes=prior_learn_hashes, task_id=task_id)
                    continue

                # ── SDD ERROR CODES ────────────────────────────────────────────────
                def _policy_refs(text: str) -> list[str]:
                    t = text.lower()
                    refs = ["/docs/security.md"]
                    if any(k in t for k in ["3ds", "3d secure"]):
                        refs = ["/docs/payments/3ds.md"] + refs
                    elif any(k in t for k in ["discount", "service_recovery", "voucher"]):
                        refs = ["/docs/discounts.md"] + refs
                    elif any(k in t for k in ["checkout", "submit checkout", "place order"]):
                        refs = ["/docs/checkout.md"] + refs
                    return refs

                if sdd_out.error == "DENIED_SECURITY":
                    print(f"{CLI_YELLOW}[pipeline] SDD: security violation detected{CLI_CLR}")
                    _refs = _policy_refs(task_text)
                    try:
                        vm.answer(AnswerRequest(
                            message="Security violation detected — request rejected.",
                            outcome=OUTCOME_BY_NAME["OUTCOME_DENIED_SECURITY"],
                            refs=_refs,
                        ))
                    except Exception as e:
                        print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")
                    _append_eval_log(task_id, task_text, task_type, pre, sgr_trace, learn_ctx,
                                     cycles_used, "OUTCOME_DENIED_SECURITY", None)
                    success = True
                    break

                if sdd_out.error == "UNSUPPORTED":
                    print(f"{CLI_YELLOW}[pipeline] SDD: unsupported operation{CLI_CLR}")
                    _refs = _policy_refs(task_text)
                    if "/docs/checkout.md" not in _refs:
                        _refs = ["/docs/checkout.md"] + _refs
                    try:
                        vm.answer(AnswerRequest(
                            message="This operation is not supported by the database.",
                            outcome=OUTCOME_BY_NAME["OUTCOME_NONE_UNSUPPORTED"],
                            refs=_refs,
                        ))
                    except Exception as e:
                        print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")
                    _append_eval_log(task_id, task_text, task_type, pre, sgr_trace, learn_ctx,
                                     cycles_used, "OUTCOME_NONE_UNSUPPORTED", None)
                    success = True
                    break

                sql_queries = [s.query for s in sdd_out.plan if s.type == "sql" and s.query]
                print(f"{CLI_BLUE}[pipeline] SDD: {len(sdd_out.plan)} steps, {len(sql_queries)} SQL queries{CLI_CLR}")

                # ── AGENTS.MD REFS CHECK ──────────────────────────────────────────
                if not sdd_out.agents_md_refs and pre.agents_md_index:
                    task_lower = task_text.lower()
                    index_terms_in_task = [
                        k for k in pre.agents_md_index
                        if any(part in task_lower for part in k.split("_"))
                    ]
                    if index_terms_in_task:
                        last_error = "agents_md_refs empty despite known vocabulary terms in task"
                        print(f"{CLI_YELLOW}[pipeline] AGENTS.MD refs check failed{CLI_CLR}")
                        _run_learn(unified_context, model, cfg, task_text, sql_queries, last_error,
                                   sgr_trace, learn_ctx, pre.agents_md_index,
                                   error_type="semantic", cycle=cycle + 1,
                                   prior_learn_hashes=prior_learn_hashes, task_id=task_id)
                        continue

                # ── SECURITY CHECK (retry-loop guard only) ───────────────────────
                retry_err = check_retry_loop(sql_queries, prior_query_sets, security_gates)
                if retry_err:
                    print(f"{CLI_RED}[pipeline] SECURITY hard-stop: {retry_err}{CLI_CLR}")
                    last_error = retry_err
                    break
                prior_query_sets.append(frozenset(sql_queries))

                # ── SCHEMA GATE ───────────────────────────────────────────────────
                schema_err = check_schema_compliance(sql_queries, pre.schema_digest, {}, task_text)
                if t := get_trace():
                    t.log_gate_check(cycle + 1, "schema", sql_queries, bool(schema_err), schema_err or None)
                if schema_err:
                    print(f"{CLI_YELLOW}[pipeline] SCHEMA gate blocked: {schema_err}{CLI_CLR}")
                    last_error = schema_err
                    _run_learn(unified_context, model, cfg, task_text, sql_queries, last_error,
                               sgr_trace, learn_ctx, pre.agents_md_index,
                               error_type="security", cycle=cycle + 1,
                               prior_learn_hashes=prior_learn_hashes, task_id=task_id)
                    continue

                # ── TDD (mandatory) ──────────────────────────────────────────────
                test_gen_out = _run_test_gen(model, cfg, task_text, sdd_out.spec, task_type,
                                             unified_context=unified_context)
                if test_gen_out is None:
                    print(f"{CLI_RED}[pipeline] TDD LLM parse failed — running LEARN{CLI_CLR}")
                    last_error = "TDD phase: failed to parse test output"
                    _run_learn(unified_context, model, cfg, task_text, [], last_error,
                               sgr_trace, learn_ctx, pre.agents_md_index,
                               error_type="llm_fail", cycle=cycle + 1,
                               prior_learn_hashes=prior_learn_hashes, task_id=task_id)
                    continue

                # ── EXECUTE (SQL steps) ───────────────────────────────────────────
                _exec_path = "/bin/sql"
                execute_error = check_path_access(_exec_path, security_gates)
                sql_results = []
                executed_sql_queries: list[str] = []

                for step in sdd_out.plan:
                    if step.type != "sql" or not step.query:
                        continue
                    q = step.query
                    if execute_error:
                        break
                    # VERIFY (EXPLAIN)
                    try:
                        expl = vm.exec(ExecRequest(path="/bin/sql", args=[f"EXPLAIN {q}"]))
                        expl_txt = _exec_result_text(expl)
                        if "error" in expl_txt.lower():
                            execute_error = f"EXPLAIN error: {expl_txt[:200]}"
                            if t := get_trace():
                                t.log_sql_validate(cycle + 1, q, expl_txt, execute_error)
                            break
                        if t := get_trace():
                            t.log_sql_validate(cycle + 1, q, expl_txt, None)
                    except Exception as e:
                        execute_error = f"EXPLAIN exception: {e}"
                        break

                    # EXECUTE
                    try:
                        _t0 = time.monotonic()
                        result = vm.exec(ExecRequest(path=_exec_path, args=[q]))
                        _dur = int((time.monotonic() - _t0) * 1000)
                        result_txt = _exec_result_text(result)
                        sql_results.append(result_txt)
                        executed_sql_queries.append(q)
                        if t := get_trace():
                            t.log_sql_execute(cycle + 1, q, result_txt, _csv_has_data(result_txt), _dur)
                        print(f"{CLI_BLUE}[pipeline] EXECUTE: {q[:60]!r} → {result_txt[:80]}{CLI_CLR}")
                    except Exception as e:
                        execute_error = f"Execute exception: {e}"
                        break

                # ── EXECUTE (exec steps: discount, payments, etc.) ────────────────
                exec_results: list[str] = []
                exec_steps = [s for s in sdd_out.plan if s.type == "exec" and s.operation]
                if exec_steps and not execute_error:
                    for step in exec_steps:
                        op_path = step.operation
                        assert op_path  # type narrowing
                        path_err = check_path_access(op_path, security_gates)
                        if path_err:
                            execute_error = path_err
                            break
                        try:
                            _t0 = time.monotonic()
                            exec_res = vm.exec(ExecRequest(path=op_path, args=step.args or []))
                            _dur = int((time.monotonic() - _t0) * 1000)
                            exec_txt = _exec_result_text(exec_res)
                            exec_results.append(exec_txt)
                            sql_results.append(exec_txt)
                            print(f"{CLI_BLUE}[pipeline] EXEC: {op_path} {step.args} → {exec_txt[:80]}{CLI_CLR}")
                        except Exception as e:
                            execute_error = f"Exec exception: {e}"
                            break

                # ── EXECUTE (read steps: file reads) ─────────────────────────────
                read_results: list[str] = []
                read_steps = [s for s in sdd_out.plan if s.type == "read" and s.args]
                if read_steps and not execute_error:
                    for step in read_steps:
                        file_path = step.args[0] if step.args else (step.operation or "")
                        if not file_path or file_path == "read":
                            continue
                        try:
                            read_res = vm.read(ReadRequest(path=file_path))
                            read_txt = read_res.content or ""
                            read_results.append(read_txt)
                            sql_results.append(f"# READ: {file_path}\n{read_txt}")
                            sku_refs.append(file_path)
                            print(f"{CLI_BLUE}[pipeline] READ: {file_path} → {read_txt[:80]}{CLI_CLR}")
                        except Exception as e:
                            print(f"{CLI_YELLOW}[pipeline] READ failed: {file_path}: {e}{CLI_CLR}")

                has_exec_output = bool(exec_results) or bool(read_results)
                last_empty = not sql_results or (not _csv_has_data(sql_results[-1]) and not has_exec_output)
                if execute_error or last_empty:
                    err = execute_error or f"Empty result set: {(sql_results[-1] if sql_results else '').strip()[:120]}"
                    print(f"{CLI_YELLOW}[pipeline] EXECUTE failed: {err}{CLI_CLR}")
                    last_error = err
                    _run_learn(unified_context, model, cfg, task_text, sql_queries, last_error,
                               sgr_trace, learn_ctx, pre.agents_md_index,
                               error_type="empty" if last_empty and not execute_error else "semantic",
                               cycle=cycle + 1, prior_learn_hashes=prior_learn_hashes, task_id=task_id)
                    continue

                # ── SCHEMA REFRESH ────────────────────────────────────────────────
                refresh_inputs = [
                    r for q, r in zip(executed_sql_queries, sql_results)
                    if _SQLITE_SCHEMA_RE.search(q) and _csv_has_data(r)
                ]
                if refresh_inputs:
                    added = merge_schema_from_sqlite_results(pre.schema_digest, refresh_inputs)
                    if added:
                        print(f"{CLI_BLUE}[pipeline] SCHEMA REFRESH: +{added}{CLI_CLR}")

                new_refs = _extract_sku_refs(executed_sql_queries, sql_results)
                sku_refs.extend(new_refs)

                # ── VERIFY (sql_tests) ────────────────────────────────────────────
                sql_passed, sql_err, sql_warns = run_tests(
                    test_gen_out.sql_tests, "test_sql", {"results": sql_results},
                    task_text=task_text,
                    sql_queries=sql_queries,
                )
                if t := get_trace():
                    t.log_test_run(cycle + 1, "sql", sql_passed, sql_err,
                                   context_snapshot=json.dumps({"results": sql_results})[:3000])
                    if sql_warns:
                        t.log_tdd_warning("sql", sql_warns)
                if sql_warns:
                    print(f"{CLI_YELLOW}[VERIFY WARNING] sql: {sql_warns}{CLI_CLR}")
                if not sql_passed:
                    print(f"{CLI_YELLOW}[pipeline] SQL VERIFY failed: {sql_err[:80]}{CLI_CLR}")
                    last_error = sql_err[:500]
                    consecutive_sql_test_fails += 1
                    if consecutive_sql_test_fails >= 3:
                        print(f"{CLI_YELLOW}[pipeline] sql test fail × {consecutive_sql_test_fails} — skip to ANSWER{CLI_CLR}")
                        # fall through to ANSWER phase with current (possibly empty) results
                    else:
                        _skip_sdd = False
                        _run_learn(unified_context, model, cfg, task_text, sql_queries, last_error,
                                   sgr_trace, learn_ctx, pre.agents_md_index,
                                   error_type="test_fail", cycle=cycle + 1,
                                   prior_learn_hashes=prior_learn_hashes, task_id=task_id)
                        continue

            # ── ANSWER ───────────────────────────────────────────────────────────
            executor_model = _resolve_model_for_phase("executor", model)
            answer_user = _build_answer_user_msg(task_text, sql_results, sku_refs)
            answer_guide = load_prompt("answer") or "# PHASE: answer"
            answer_system: list[dict] = [
                {"type": "text", "text": unified_context},
                {"type": "text", "text": answer_guide, "cache_control": {"type": "ephemeral"}},
            ]
            answer_out, sgr_answer, tok = _call_llm_phase(
                answer_system, answer_user, executor_model, cfg, AnswerOutput,
                phase="answer", cycle=cycle + 1,
            )
            total_in_tok += tok.get("input", 0)
            total_out_tok += tok.get("output", 0)
            sgr_trace.append(sgr_answer)

            if not answer_out:
                print(f"{CLI_RED}[pipeline] ANSWER parse failed{CLI_CLR}")
                try:
                    vm.answer(AnswerRequest(
                        message="Could not synthesize an answer from available data.",
                        outcome=OUTCOME_BY_NAME["OUTCOME_NONE_CLARIFICATION"],
                        refs=[],
                    ))
                except Exception as e:
                    print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")
                break

            # ── VERIFY_ANSWER (answer_tests) ──────────────────────────────────────
            if test_gen_out:
                ans_passed, ans_err, ans_warns = run_tests(
                    test_gen_out.answer_tests, "test_answer",
                    {"sql_results": sql_results, "answer": answer_out.model_dump()},
                    task_text=task_text,
                )
                if t := get_trace():
                    snapshot = json.dumps({"sql_results": sql_results, "answer": answer_out.model_dump()})[:3000]
                    t.log_test_run(cycle + 1, "answer", ans_passed, ans_err, context_snapshot=snapshot)
                    if ans_warns:
                        t.log_tdd_warning("answer", ans_warns)
                if ans_warns:
                    print(f"{CLI_YELLOW}[VERIFY_ANSWER WARNING] answer: {ans_warns}{CLI_CLR}")
                if not ans_passed:
                    print(f"{CLI_YELLOW}[pipeline] VERIFY_ANSWER failed: {ans_err[:300]}{CLI_CLR}")
                    last_error = ans_err[:500]
                    consecutive_answer_test_fails += 1
                    if consecutive_answer_test_fails >= 3:
                        print(f"{CLI_YELLOW}[pipeline] answer test fail × {consecutive_answer_test_fails} — force submit{CLI_CLR}")
                    else:
                        _skip_sdd = True
                        _run_learn(unified_context, model, cfg, task_text,
                                   [s.query for s in (sdd_out.plan if sdd_out else []) if s.type == "sql" and s.query],
                                   last_error, sgr_trace, learn_ctx, pre.agents_md_index,
                                   error_type="test_fail", cycle=cycle + 1,
                                   prior_learn_hashes=prior_learn_hashes, task_id=task_id)
                        continue

            # ── SUCCESS ───────────────────────────────────────────────────────────
            consecutive_answer_test_fails = 0
            consecutive_sql_test_fails = 0
            outcome = answer_out.outcome
            print(f"{CLI_GREEN}[pipeline] ANSWER: {outcome} — {answer_out.message[:100]}{CLI_CLR}")
            ref_err = check_grounding_refs(
                answer_out.grounding_refs,
                {Path(r).stem for r in sku_refs},
                security_gates,
            )
            if ref_err:
                print(f"{CLI_YELLOW}[pipeline] ANSWER grounding_refs blocked: {ref_err}{CLI_CLR}")
            result_paths = set(sku_refs)
            clean_refs = (
                [r for r in answer_out.grounding_refs if r in result_paths]
                if result_paths else list(answer_out.grounding_refs)
            )
            try:
                vm.answer(AnswerRequest(
                    message=answer_out.message,
                    outcome=OUTCOME_BY_NAME[outcome],
                    refs=clean_refs,
                ))
            except Exception as e:
                print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")

            _append_eval_log(task_id, task_text, task_type, pre, sgr_trace, learn_ctx, cycles_used, outcome, None)
            if task_id and learn_ctx:
                print(f"{CLI_BLUE}[pipeline] learn_ctx ({len(learn_ctx)} rules) moved to eval_log, data/learned/{task_id}.yaml cleared{CLI_CLR}")
            clear_learned_ctx(task_id)
            success = True
            break

        if not success:
            print(f"{CLI_RED}[pipeline] All {_MAX_CYCLES} cycles exhausted — clarification{CLI_CLR}")
            try:
                vm.answer(AnswerRequest(
                    message="Could not retrieve data after multiple attempts.",
                    outcome=OUTCOME_BY_NAME["OUTCOME_NONE_CLARIFICATION"],
                    refs=[],
                ))
            except Exception as e:
                print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")
            if task_id and learn_ctx:
                print(f"{CLI_BLUE}[pipeline] learn_ctx preserved in data/learned/{task_id}.yaml (total={len(learn_ctx)}){CLI_CLR}")

    except Exception:
        print(f"{CLI_RED}[pipeline] UNHANDLED: {traceback.format_exc()}{CLI_CLR}")
        try:
            vm.answer(AnswerRequest(
                message="Internal pipeline error.",
                outcome=OUTCOME_BY_NAME["OUTCOME_NONE_CLARIFICATION"],
                refs=[],
            ))
        except Exception as e:
            print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")

    # ── EVALUATOR: only on success ────────────────────────────────────────────
    eval_thread: threading.Thread | None = None
    eval_model = _resolve_model_for_phase("evaluator", model)
    if success and _EVAL_ENABLED and eval_model:
        eval_thread = threading.Thread(
            target=_run_evaluator_safe,
            kwargs={
                "task_id": task_id,
                "task_text": task_text,
                "task_type": task_type,
                "prephase": {
                    "agents_md": pre.agents_md_content,
                    "schema_digest": pre.schema_digest,
                    "db_schema": pre.db_schema,
                },
                "learn_ctx": list(learn_ctx),
                "sgr_trace": sgr_trace,
                "cycles": cycles_used,
                "final_outcome": outcome,
                "model": eval_model,
                "cfg": cfg,
            },
            daemon=False,
        )
        eval_thread.start()

    stats = {
        "outcome": outcome,
        "cycles_used": cycles_used,
        "step_facts": [f"pipeline cycles={cycles_used}"],
        "done_ops": [],
        "input_tokens": total_in_tok,
        "output_tokens": total_out_tok,
        "total_elapsed_ms": 0,
    }
    return stats, eval_thread


def _append_eval_log(
    task_id: str,
    task_text: str,
    task_type: str,
    pre: PrephaseResult,
    sgr_trace: list[dict],
    learn_ctx: list[str],
    cycles: int,
    outcome: str,
    evaluator_result,
) -> None:
    entry: dict = {
        "task_id": task_id,
        "task_text": task_text,
        "task_type": task_type,
        "cycles_used": cycles,
        "prephase": {
            "agents_md": pre.agents_md_content[:500] if pre.agents_md_content else "",
            "schema_digest": pre.schema_digest,
        },
        "trace": sgr_trace,
        "learn_ctx": learn_ctx,
        "outcome": "ok" if outcome == "OUTCOME_OK" else "fail",
        "evaluator": None,
    }
    if evaluator_result is not None:
        entry["evaluator"] = {
            "best_cycle": getattr(evaluator_result, "best_cycle", 0),
            "best_answer": getattr(evaluator_result, "best_answer", ""),
            "score": getattr(evaluator_result, "score", 0.0),
            "prompt_optimization": getattr(evaluator_result, "prompt_optimization", []),
            "rule_optimization": getattr(evaluator_result, "rule_optimization", []),
            "security_optimization": getattr(evaluator_result, "security_optimization", []),
        }
    _EVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_EVAL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _run_evaluator_safe(
    task_id: str = "",
    task_text: str = "",
    task_type: str = "sql",
    prephase: dict | None = None,
    learn_ctx: list[str] | None = None,
    sgr_trace: list[dict] | None = None,
    cycles: int = 0,
    final_outcome: str = "",
    model: str = "",
    cfg: dict | None = None,
) -> None:
    try:
        from .evaluator import run_evaluator, EvalInput
        result = run_evaluator(
            EvalInput(
                task_id=task_id,
                task_text=task_text,
                task_type=task_type,
                prephase=prephase or {},
                learn_ctx=learn_ctx or [],
                sgr_trace=sgr_trace or [],
                cycles=cycles,
                final_outcome=final_outcome,
            ),
            model=model,
            cfg=cfg or {},
        )
        if result is not None:
            _EVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            try:
                lines = _EVAL_LOG.read_text(encoding="utf-8").splitlines()
            except Exception:
                pass
            for i in range(len(lines) - 1, -1, -1):
                try:
                    entry = json.loads(lines[i])
                    if entry.get("task_id") == task_id and entry.get("evaluator") is None:
                        entry["evaluator"] = {
                            "best_cycle": result.best_cycle,
                            "best_answer": result.best_answer,
                            "score": result.score,
                            "prompt_optimization": result.prompt_optimization,
                            "rule_optimization": result.rule_optimization,
                            "security_optimization": result.security_optimization,
                        }
                        lines[i] = json.dumps(entry, ensure_ascii=False)
                        _EVAL_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
                        break
                except Exception:
                    continue
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] evaluator error (non-fatal): {e}{CLI_CLR}")
