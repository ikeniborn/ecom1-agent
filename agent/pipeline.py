"""SDD-based pipeline: PREPHASE → SDD → TDD → EXECUTE → VERIFY → ANSWER → VERIFY_ANSWER."""
from __future__ import annotations

import json
import os
import re
import time
import traceback

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
from .prompt_assembler import assemble_prompt, load_learned_ctx, load_learned_entries, _apply_learn_diff
from .schema_gate import check_schema_compliance
from .sql_security import check_retry_loop
from .trace import get_trace


_MAX_CYCLES = int(os.environ.get("MAX_STEPS", "3"))
_SDD_ENABLED = os.environ.get("SDD_ENABLED", "1") == "1"
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


def _build_learn_user_msg(
    task_text: str,
    queries: list[str],
    error: str,
    error_type: str,
    existing_entries: list[dict],
) -> str:
    base = (
        f"TASK: {task_text}\n"
        f"FAILED QUERIES: {json.dumps(queries)}\n"
        f"ERROR: {error}\n"
        f"ERROR_TYPE: {error_type}"
    )
    if existing_entries:
        rules_lines = "\n".join(
            f"  - id: {e['id']}\n    content: {e['content']!r}"
            for e in existing_entries
            if e.get("status") == "active"
        )
        if rules_lines:
            base += f"\n\nEXISTING_RULES:\n{rules_lines}"
    return base


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
    task_id: str = "",
) -> None:
    learn_model = _resolve_model_for_phase("learn", model)
    learn_guide = load_prompt("learn") or "# PHASE: learn"
    learn_system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": learn_guide, "cache_control": {"type": "ephemeral"}},
    ]
    existing_entries = load_learned_entries(task_id) if task_id else []
    learn_user = _build_learn_user_msg(task_text, queries, error, error_type, existing_entries)
    learn_out, sgr_learn, _ = _call_llm_phase(
        learn_system, learn_user, learn_model, cfg, LearnOutput,
        max_tokens=2048, phase="learn", cycle=cycle,
    )
    sgr_lean = sgr_learn
    sgr_lean["error_type"] = error_type
    sgr_trace.append(sgr_lean)
    if not learn_out or error_type == "llm_fail":
        return
    if learn_out.skip:
        print(f"{CLI_BLUE}[pipeline] LEARN: skipped ({learn_out.skip_reason}){CLI_CLR}")
        return
    anchor = learn_out.agents_md_anchor
    if anchor:
        anchor_section = anchor.split(">")[0].strip()
        if anchor_section in agents_md_index:
            anchor_lines = agents_md_index[anchor_section]
            vault_rule = f"[{anchor_section}]\n" + "\n".join(anchor_lines)
            if task_id:
                _apply_learn_diff(task_id, vault_rule, f"anchor:{anchor}", [], None, source="learn")
            learn_ctx.append(vault_rule)
            print(f"{CLI_BLUE}[pipeline] LEARN: anchor={anchor!r}, vault rule added{CLI_CLR}")
            return
    if task_id:
        _apply_learn_diff(
            task_id,
            learn_out.rule_content,
            learn_out.reasoning,
            learn_out.deactivate,
            learn_out.deactivate_reason,
            source="learn",
        )
    if learn_out.deactivate:
        deactivate_contents = {
            e["content"] for e in existing_entries
            if e.get("id") in learn_out.deactivate
        }
        learn_ctx[:] = [r for r in learn_ctx if r not in deactivate_contents]
    learn_ctx.append(learn_out.rule_content)
    print(f"{CLI_BLUE}[pipeline] LEARN: rule added, deactivated={learn_out.deactivate} (total active={len(learn_ctx)}){CLI_CLR}")


def run_pipeline(
    vm: EcomRuntimeClientSync,
    model: str,
    task_text: str,
    pre: PrephaseResult,
    cfg: dict,
    task_id: str = "",
    injected_session_rules: list[str] | None = None,
    injected_prompt_addendum: str = "",
) -> tuple[dict, None]:
    """SDD-based pipeline. Returns (stats dict, None)."""
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
                               task_id=task_id)
                    continue

                # ── SDD ERROR CODES ────────────────────────────────────────────────
                def _policy_refs(text: str) -> list[str]:
                    t = text.lower()
                    refs = ["/docs/security.md"]
                    if any(k in t for k in ["3ds", "3d secure"]):
                        refs = ["/docs/payments/3ds.md"] + refs
                    elif any(k in t for k in ["discount", "service_recovery", "voucher"]):
                        refs = ["/docs/discounts.md"] + refs
                    elif any(k in t for k in ["checkout", "check out", "submit checkout", "place order", "complete order"]):
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
                    success = True
                    break

                if sdd_out.error in ("UNSUPPORTED", "OUTCOME_NONE_UNSUPPORTED"):
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
                                   task_id=task_id)
                        continue

                # ── SECURITY CHECK (retry-loop guard only) ───────────────────────
                retry_err = check_retry_loop(sql_queries, prior_query_sets)
                if retry_err:
                    print(f"{CLI_RED}[pipeline] SECURITY hard-stop: {retry_err}{CLI_CLR}")
                    last_error = retry_err
                    break
                prior_query_sets.append(frozenset(sql_queries))

                # ── SCHEMA GATE ───────────────────────────────────────────────────
                _task_lower = task_text.lower()
                _pre_confirmed: dict = {}
                if any(k in _task_lower for k in ["checkout", "check out", "submit checkout", "place order", "complete order"]):
                    _bm = re.search(r'\b(basket_\w+|cart_\w+)\b', task_text, re.IGNORECASE)
                    if _bm:
                        _pre_confirmed = {"basket_id": [_bm.group(1)]}
                schema_err = check_schema_compliance(sql_queries, pre.schema_digest, _pre_confirmed, task_text)
                if t := get_trace():
                    t.log_gate_check(cycle + 1, "schema", sql_queries, bool(schema_err), schema_err or None)
                if schema_err:
                    print(f"{CLI_YELLOW}[pipeline] SCHEMA gate blocked: {schema_err}{CLI_CLR}")
                    last_error = schema_err
                    _run_learn(unified_context, model, cfg, task_text, sql_queries, last_error,
                               sgr_trace, learn_ctx, pre.agents_md_index,
                               error_type="security", cycle=cycle + 1,
                               task_id=task_id)
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
                               task_id=task_id)
                    continue

                # ── EXECUTE (SQL steps) ───────────────────────────────────────────
                execute_error = ""
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
                               cycle=cycle + 1, task_id=task_id)
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
                                   task_id=task_id)
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
                    if consecutive_answer_test_fails >= 3 or answer_out.outcome == "OUTCOME_NONE_UNSUPPORTED":
                        print(f"{CLI_YELLOW}[pipeline] answer test fail × {consecutive_answer_test_fails} — force submit{CLI_CLR}")
                    else:
                        _skip_sdd = True
                        _run_learn(unified_context, model, cfg, task_text,
                                   [s.query for s in (sdd_out.plan if sdd_out else []) if s.type == "sql" and s.query],
                                   last_error, sgr_trace, learn_ctx, pre.agents_md_index,
                                   error_type="test_fail", cycle=cycle + 1,
                                   task_id=task_id)
                        continue

            # ── SUCCESS ───────────────────────────────────────────────────────────
            consecutive_answer_test_fails = 0
            consecutive_sql_test_fails = 0
            outcome = answer_out.outcome
            print(f"{CLI_GREEN}[pipeline] ANSWER: {outcome} — {answer_out.message[:100]}{CLI_CLR}")
            result_paths = set(sku_refs)
            clean_refs = (
                [r for r in answer_out.grounding_refs if r in result_paths]
                if result_paths else list(answer_out.grounding_refs)
            )
            if outcome == "OUTCOME_NONE_UNSUPPORTED":
                t_lower = task_text.lower()
                policy_refs = ["/docs/security.md"]
                if any(k in t_lower for k in ["checkout", "check out", "submit checkout", "place order", "complete order"]):
                    policy_refs = ["/docs/checkout.md"] + policy_refs
                    basket_m = re.search(r'\b(basket_\w+|cart_\w+)\b', task_text, re.IGNORECASE)
                    if basket_m:
                        basket_ref = f"/proc/baskets/{basket_m.group(1)}.json"
                        if basket_ref not in clean_refs:
                            clean_refs.append(basket_ref)
                elif any(k in t_lower for k in ["3ds", "3d secure"]):
                    policy_refs = ["/docs/payments/3ds.md"] + policy_refs
                elif any(k in t_lower for k in ["discount", "service_recovery", "voucher"]):
                    policy_refs = ["/docs/discounts.md"] + policy_refs
                for pr in reversed(policy_refs):
                    if pr not in clean_refs:
                        clean_refs.insert(0, pr)
            try:
                vm.answer(AnswerRequest(
                    message=answer_out.message,
                    outcome=OUTCOME_BY_NAME[outcome],
                    refs=clean_refs,
                ))
            except Exception as e:
                print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")

            if task_id:
                print(f"{CLI_BLUE}[pipeline] SUCCESS: {len(learn_ctx)} active rules in data/learned/{task_id}.yaml{CLI_CLR}")
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

    stats = {
        "outcome": outcome,
        "cycles_used": cycles_used,
        "step_facts": [f"pipeline cycles={cycles_used}"],
        "done_ops": [],
        "input_tokens": total_in_tok,
        "output_tokens": total_out_tok,
        "total_elapsed_ms": 0,
    }
    return stats, None
