"""ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER pipeline."""
from __future__ import annotations

import os
import re
import time
import traceback
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import AnswerRequest, ExecRequest, ReadRequest

from .llm import (
    call_llm_raw, _resolve_model_for_phase, OUTCOME_BY_NAME,
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, CLI_YELLOW,
)
from .json_extract import _extract_json_from_text
from .models import SddOutput, PlanOutput, ExecuteOutput, LearnOutput, AnswerOutput
from .prephase import PrephaseResult, _format_schema_digest as _fmt_schema_digest
from .prompt import load_prompt
from .prompt_assembler import assemble_prompt, load_learned_ctx, load_learned_entries, _apply_learn_diff
from .sql_security import check_retry_loop
from .trace import get_trace


_MAX_CYCLES = int(os.environ.get("MAX_STEPS", "3"))
_SDD_ENABLED = os.environ.get("SDD_ENABLED", "1") == "1"

# Compat stubs — referenced by older tests that patch these names; no-ops in new pipeline
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
) -> tuple[Any, dict, dict]:
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
            sgr_entry["reasoning"] = getattr(obj, "reasoning", "")
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


def _build_sdd_user_msg(task_text: str, last_error: str) -> str:
    parts: list[str] = [f"TASK: {task_text}"]
    if last_error:
        parts.append(f"PREVIOUS ERROR: {last_error}")
    return "\n\n".join(parts)


def _build_learn_user_msg(
    task_text: str,
    error: str,
    error_type: str,
    existing_entries: list[dict],
    sdd_out=None,
    plan_out=None,
    answer_out=None,
) -> str:
    parts = [
        f"TASK: {task_text}",
        f"ERROR: {error}",
        f"ERROR_TYPE: {error_type}",
    ]
    if sdd_out is not None:
        parts.append(f"SDD_OUTPUT:\n{sdd_out.model_dump_json(indent=2)}")
    if plan_out is not None:
        parts.append(f"PLAN_OUTPUT:\n{plan_out.model_dump_json(indent=2)}")
    if answer_out is not None:
        parts.append(f"ANSWER_OUTPUT:\n{answer_out.model_dump_json(indent=2)}")
    if existing_entries:
        rules_lines = "\n".join(
            f"  - id: {e['id']}\n    content: {e['content']!r}"
            for e in existing_entries
            if e.get("status") == "active"
        )
        if rules_lines:
            parts.append(f"EXISTING_RULES:\n{rules_lines}")
    return "\n\n".join(parts)


def _build_answer_user_msg(task_text: str, execute_out) -> str:
    return f"TASK: {task_text}\n\nEXECUTE_OUTPUT:\n{execute_out.model_dump_json(indent=2)}"


def _infer_action_type(action: str) -> str:
    """Infer action type from plain string: sql | read | exec."""
    s = action.strip()
    if re.match(r"^SELECT\b", s, re.IGNORECASE):
        return "sql"
    if s.startswith("/bin/") or s.startswith("/usr/"):
        return "exec"
    if s.startswith("/"):
        return "read"
    return "exec"


def _run_execute(vm, plan_out, cycle: int) -> "tuple[ExecuteOutput | None, str]":
    """Execute plan_out.action. approach/steps available for diagnostic context."""
    action = plan_out.action
    action_type = _infer_action_type(action)
    try:
        if action_type == "sql":
            expl = vm.exec(ExecRequest(path="/bin/sql", args=[f"EXPLAIN {action}"]))
            expl_txt = _exec_result_text(expl)
            if "error" in expl_txt.lower():
                return None, f"EXPLAIN error [{plan_out.approach!r:.60}]: {expl_txt[:200]}"
            result = vm.exec(ExecRequest(path="/bin/sql", args=[action]))
            raw = _exec_result_text(result)
            return ExecuteOutput(results=[{"output": raw}], action=action), ""
        elif action_type == "read":
            result = vm.read(ReadRequest(path=action))
            raw = result.content or ""
            return ExecuteOutput(results=[{"output": raw}], action=action), ""
        else:
            parts = action.split()
            path, args = parts[0], parts[1:]
            result = vm.exec(ExecRequest(path=path, args=args))
            raw = _exec_result_text(result)
            return ExecuteOutput(results=[{"output": raw}], action=action), ""
    except Exception as e:
        return None, f"Execute exception [{plan_out.approach!r:.60}]: {e}"


def _run_learn(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    error: str,
    sgr_trace: list[dict],
    learn_ctx: list[str],
    agents_md_index: dict,
    error_type: str = "semantic",
    cycle: int = 0,
    task_id: str = "",
    sdd_out=None,
    plan_out=None,
    answer_out=None,
) -> None:
    learn_model = _resolve_model_for_phase("learn", model)
    learn_guide = load_prompt("learn") or "# PHASE: learn"
    learn_system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": learn_guide, "cache_control": {"type": "ephemeral"}},
    ]
    existing_entries = load_learned_entries(task_id) if task_id else []
    learn_user = _build_learn_user_msg(task_text, error, error_type, existing_entries,
                                       sdd_out=sdd_out, plan_out=plan_out, answer_out=answer_out)
    learn_out, sgr_learn, _ = _call_llm_phase(
        learn_system, learn_user, learn_model, cfg, LearnOutput,
        max_tokens=2048, phase="learn", cycle=cycle,
    )
    sgr_learn["error_type"] = error_type
    sgr_trace.append(sgr_learn)
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
    """ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER pipeline. Returns (stats dict, None)."""
    _persisted = load_learned_ctx(task_id) if task_id else []
    learn_ctx: list[str] = list(dict.fromkeys(_persisted + list(injected_session_rules or [])))
    sgr_trace: list[dict] = []
    total_in_tok = 0
    total_out_tok = 0

    last_error = ""
    success = False
    cycles_used = 0
    prior_action_sets: list[frozenset] = []

    outcome = "OUTCOME_NONE_CLARIFICATION"
    sdd_out: SddOutput | None = None
    plan_out: PlanOutput | None = None
    unified_context = ""

    try:
        for cycle in range(_MAX_CYCLES):
            cycles_used = cycle + 1
            print(f"\n{CLI_BLUE}[pipeline] cycle={cycle + 1}/{_MAX_CYCLES}{CLI_CLR}")

            assembled = assemble_prompt(
                task_text=task_text,
                task_type=pre.task_type or "sql",
                prephase_result=pre,
                learn_ctx=learn_ctx,
                model=model,
                cfg=cfg,
                task_id=task_id,
            )
            unified_context = assembled.unified_context

            # ── SDD ───────────────────────────────────────────────────────────
            sdd_model = _resolve_model_for_phase("sdd", model)
            sdd_user = _build_sdd_user_msg(task_text, last_error)
            sdd_guide = load_prompt("sdd") or "# PHASE: sdd"
            sdd_system: list[dict] = [
                {"type": "text", "text": unified_context},
                {"type": "text", "text": sdd_guide, "cache_control": {"type": "ephemeral"}},
            ]
            sdd_out, sgr_entry, tok = _call_llm_phase(
                sdd_system, sdd_user, sdd_model, cfg, SddOutput,
                phase="sdd", cycle=cycle + 1,
            )
            total_in_tok += tok.get("input", 0)
            total_out_tok += tok.get("output", 0)
            sgr_trace.append(sgr_entry)

            if not sdd_out:
                raw_sdd = sgr_entry.get("output", "") if isinstance(sgr_entry.get("output"), str) else ""
                sdd_err_type = "semantic" if raw_sdd else "llm_fail"
                last_error = f"SDD phase: failed to parse LLM output. Raw: {raw_sdd[:400]}" if raw_sdd else "SDD phase: LLM returned empty response"
                print(f"{CLI_RED}[pipeline] SDD parse failed ({sdd_err_type}){CLI_CLR}")
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type=sdd_err_type, cycle=cycle + 1, task_id=task_id)
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

            if sdd_out.error_code == "DENIED_SECURITY":
                print(f"{CLI_YELLOW}[pipeline] SDD: security violation{CLI_CLR}")
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

            if sdd_out.error_code in ("UNSUPPORTED", "OUTCOME_NONE_UNSUPPORTED"):
                print(f"{CLI_YELLOW}[pipeline] SDD: unsupported operation{CLI_CLR}")
                _refs = _policy_refs(task_text)
                if "/docs/checkout.md" not in _refs:
                    _refs = ["/docs/checkout.md"] + _refs
                try:
                    vm.answer(AnswerRequest(
                        message="This operation is not supported.",
                        outcome=OUTCOME_BY_NAME["OUTCOME_NONE_UNSUPPORTED"],
                        refs=_refs,
                    ))
                except Exception as e:
                    print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")
                success = True
                break

            print(f"{CLI_BLUE}[pipeline] SDD: goal={sdd_out.spec_goal!r:.60}, actions={len(sdd_out.actions)}{CLI_CLR}")

            # ── PLAN ──────────────────────────────────────────────────────────
            plan_model = _resolve_model_for_phase("plan", model)
            plan_guide = load_prompt("plan") or "# PHASE: plan"
            plan_system: list[dict] = [
                {"type": "text", "text": unified_context},
                {"type": "text", "text": plan_guide, "cache_control": {"type": "ephemeral"}},
            ]
            plan_out, sgr_plan, tok = _call_llm_phase(
                plan_system, sdd_out.model_dump_json(), plan_model, cfg, PlanOutput,
                phase="plan", cycle=cycle + 1,
            )
            total_in_tok += tok.get("input", 0)
            total_out_tok += tok.get("output", 0)
            sgr_trace.append(sgr_plan)

            if not plan_out:
                raw_plan = sgr_plan.get("output", "") if isinstance(sgr_plan.get("output"), str) else ""
                last_error = f"PLAN phase: failed to parse LLM output. Raw: {raw_plan[:400]}" if raw_plan else "PLAN phase: LLM returned empty response"
                print(f"{CLI_RED}[pipeline] PLAN parse failed{CLI_CLR}")
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="llm_fail" if not raw_plan else "semantic",
                           cycle=cycle + 1, task_id=task_id, sdd_out=sdd_out)
                continue

            if not plan_out.action:
                last_error = "PLAN phase: action is empty"
                print(f"{CLI_YELLOW}[pipeline] PLAN: empty action{CLI_CLR}")
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                continue

            print(f"{CLI_BLUE}[pipeline] PLAN: {plan_out.action[:80]!r}{CLI_CLR}")

            # ── RETRY-LOOP GUARD ──────────────────────────────────────────────
            retry_err = check_retry_loop([plan_out.action], prior_action_sets)
            if retry_err:
                print(f"{CLI_RED}[pipeline] SECURITY hard-stop: {retry_err}{CLI_CLR}")
                last_error = retry_err
                break
            prior_action_sets.append(frozenset([plan_out.action]))

            # ── EXECUTE ───────────────────────────────────────────────────────
            _t0 = time.monotonic()
            execute_out, execute_error = _run_execute(vm, plan_out, cycle + 1)
            _dur = int((time.monotonic() - _t0) * 1000)

            if execute_error or execute_out is None:
                err = execute_error or "Execute returned None"
                print(f"{CLI_YELLOW}[pipeline] EXECUTE failed: {err}{CLI_CLR}")
                last_error = err
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                continue

            raw_output = execute_out.results[0].get("output", "") if execute_out.results else ""
            if not _csv_has_data(raw_output):
                last_error = f"Empty result: {raw_output.strip()[:120]}"
                print(f"{CLI_YELLOW}[pipeline] EXECUTE: empty result{CLI_CLR}")
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="empty", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                continue

            if t := get_trace():
                action_type = _infer_action_type(plan_out.action)
                if action_type == "sql":
                    t.log_sql_execute(cycle + 1, plan_out.action, raw_output, _csv_has_data(raw_output), _dur)

            print(f"{CLI_BLUE}[pipeline] EXECUTE ok: {raw_output[:80]}{CLI_CLR}")

            # ── ANSWER ────────────────────────────────────────────────────────
            executor_model = _resolve_model_for_phase("executor", model)
            answer_user = _build_answer_user_msg(task_text, execute_out)
            answer_guide = load_prompt("answer") or "# PHASE: answer"
            answer_system: list[dict] = [
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
                last_error = "ANSWER phase: failed to parse LLM output"
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out)
                continue

            # ── SUCCESS ───────────────────────────────────────────────────────
            outcome = answer_out.outcome
            print(f"{CLI_GREEN}[pipeline] ANSWER: {outcome} — {answer_out.message[:100]}{CLI_CLR}")

            sku_refs: list[str] = []
            if _infer_action_type(plan_out.action) == "read":
                sku_refs.append(plan_out.action)

            clean_refs = list(answer_out.grounding_refs)
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
                print(f"{CLI_BLUE}[pipeline] learn_ctx preserved (total={len(learn_ctx)}){CLI_CLR}")

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
