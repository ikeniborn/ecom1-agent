"""ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER pipeline."""
from __future__ import annotations

import json
import math
import os
import re
import time
import traceback
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import (
    AnswerRequest, ExecRequest, FindRequest, ListRequest,
    ReadRequest, SearchRequest, TreeRequest,
)

from .llm import (
    call_llm_raw, _resolve_model_for_phase, OUTCOME_BY_NAME,
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, CLI_YELLOW,
)
from .json_extract import _extract_json_from_text
from .models import IddOutput, SddOutput, PlanOutput, ExecuteOutput, LearnOutput, AnswerOutput, ConsolidateOutput
from .prephase import PrephaseResult, _format_schema_digest as _fmt_schema_digest
from .prompt import load_prompt
from .prompt_assembler import assemble_prompt, load_learned_ctx, load_learned_entries, _apply_learn_diff, save_last_run
from .sql_security import check_retry_loop
from .trace import get_trace


_MAX_CYCLES = int(os.environ.get("MAX_STEPS", "3"))
_SDD_ENABLED = os.environ.get("SDD_ENABLED", "1") == "1"

_PHASE_MAX_TOKENS: dict[str, int] = {
    "idd":       int(os.environ.get("MAX_TOKENS_IDD",       "2048")),
    "sdd":       int(os.environ.get("MAX_TOKENS_SDD",       "8192")),
    "plan":      int(os.environ.get("MAX_TOKENS_PLAN",      "4096")),
    "learn":     int(os.environ.get("MAX_TOKENS_LEARN",     "2048")),
    "assembler": int(os.environ.get("MAX_TOKENS_ASSEMBLER", "4096")),
    "answer":    int(os.environ.get("MAX_TOKENS_ANSWER",    "4096")),
    "consolidate": int(os.environ.get("MAX_TOKENS_CONSOLIDATE", "2048")),
}

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
            stdout = d.get("stdout", "") or d.get("output", "") or ""
            stderr = d.get("stderr", "") or ""
            return stdout or stderr or ""
        except Exception:
            pass
    stdout = getattr(result, "stdout", "") or getattr(result, "output", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    return stdout or stderr or ""


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


def _build_sdd_user_msg(
    idd_out: IddOutput,
    last_error: str,
    prior_actions: list[str] | None = None,
    prior_results: list[tuple[str, str]] | None = None,
) -> str:
    parts: list[str] = [
        f"INTENT: {idd_out.intent_objective}",
        f"TASK: {idd_out.reformulated_task}",
        f"INTENT_TYPE: {idd_out.intent_type}",
    ]
    if idd_out.extracted_params:
        parts.append(f"EXTRACTED_PARAMS: {json.dumps(idd_out.extracted_params)}")
    if idd_out.success_criteria:
        parts.append("EXPECTATIONS:\n" + "\n".join(f"  - {c}" for c in idd_out.success_criteria))
    if idd_out.health_metrics:
        parts.append("CONSTRAINTS:\n" + "\n".join(f"  - {m}" for m in idd_out.health_metrics))
    if last_error:
        parts.append(f"PREVIOUS_ERROR: {last_error}")
    if prior_actions:
        parts.append("PRIOR_ACTIONS (already executed — apply persistence rules):\n" +
                     "\n".join(f"  - {a}" for a in prior_actions))
    if prior_results:
        pr_lines = []
        for action, result in prior_results:
            # Tree and search results need larger limits to avoid hiding entries
            if action.startswith("tree:"):
                limit = 8000
            elif action.startswith("search:"):
                limit = 20000
            else:
                limit = 1500
            result_preview = result.strip()[:limit] if result.strip() else "(empty)"
            pr_lines.append(f"  action: {action[:120]}\n  result: {result_preview}")
        parts.append("PRIOR_RESULTS (outputs from earlier executions — use these to derive specific file paths; do NOT re-run actions whose results appear here):\n" +
                     "\n\n".join(pr_lines))
    return "\n\n".join(parts)


def _build_idd_user_msg(task_text: str, last_error: str, prior_actions: list[str]) -> str:
    parts: list[str] = [f"TASK: {task_text}"]
    if last_error:
        parts.append(f"PREVIOUS_ERROR: {last_error}")
    if prior_actions:
        parts.append("PRIOR_ACTIONS:\n" + "\n".join(f"  - {a}" for a in prior_actions))
    return "\n\n".join(parts)


def _with_json_schema(cfg: dict, schema: dict) -> dict:
    """Return a copy of cfg with cc_json_schema injected into cc_options."""
    cc_opts = dict(cfg.get("cc_options") or {})
    cc_opts["cc_json_schema"] = schema
    return {**cfg, "cc_options": cc_opts}


_IDD_SCHEMA = IddOutput.model_json_schema()
_SDD_SCHEMA = SddOutput.model_json_schema()


def _run_idd(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    last_error: str,
    prior_actions: list[str],
    cycle: int,
) -> tuple[IddOutput | None, dict, dict]:
    idd_model = _resolve_model_for_phase("idd", model)
    idd_guide = load_prompt("idd") or "# PHASE: idd"
    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": idd_guide, "cache_control": {"type": "ephemeral"}},
    ]
    user_msg = _build_idd_user_msg(task_text, last_error, prior_actions)
    return _call_llm_phase(
        system, user_msg, idd_model, _with_json_schema(cfg, _IDD_SCHEMA), IddOutput,
        max_tokens=_PHASE_MAX_TOKENS["idd"],
        phase="idd", cycle=cycle,
    )


def _build_plan_user_msg(sdd_json: str, prior_actions: list[str] | None = None) -> str:
    parts = [sdd_json]
    if prior_actions:
        parts.append("PRIOR_ACTIONS (already tried — do NOT select these):\n" +
                     "\n".join(f"  - {a}" for a in prior_actions))
    return "\n\n".join(parts)


def _build_learn_user_msg(
    task_text: str,
    error: str,
    error_type: str,
    existing_entries: list[dict],
    sdd_out=None,
    plan_out=None,
    answer_out=None,
    idd_out: IddOutput | None = None,
) -> str:
    parts = [
        f"TASK: {task_text}",
        f"ERROR: {error}",
        f"ERROR_TYPE: {error_type}",
    ]
    if idd_out and idd_out.stop_rules:
        parts.append("STOP_RULES:\n" + "\n".join(f"  - {r}" for r in idd_out.stop_rules))
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


def _extract_file_paths_from_actions(actions: list[str]) -> list[str]:
    """Extract absolute file paths from action strings for grounding_refs hints."""
    paths: list[str] = []
    for a in actions:
        s = a.strip()
        if s.startswith("/") and not s.startswith("/bin/") and not s.startswith("/usr/"):
            paths.append(s)
        elif s.startswith("search:"):
            pass  # search results have paths extracted at answer time
    return paths


def _build_answer_user_msg(
    task_text: str,
    execute_out,
    prior_actions: list[str] | None = None,
    prior_results: list[tuple[str, str]] | None = None,
    runtime_identity: str | None = None,
    idd_out: IddOutput | None = None,
) -> str:
    parts = [f"TASK: {task_text}", f"EXECUTE_OUTPUT:\n{execute_out.model_dump_json(indent=2)}"]
    if idd_out and idd_out.success_criteria:
        parts.append("EXPECTATIONS:\n" + "\n".join(f"  - {c}" for c in idd_out.success_criteria))
    if prior_actions:
        parts.append("PRIOR_EXECUTIONS (actions run in earlier cycles — use their file paths in grounding_refs if relevant):\n" +
                     "\n".join(f"  - {a}" for a in prior_actions))
        file_paths = _extract_file_paths_from_actions(prior_actions)
        if file_paths:
            parts.append(
                "FILES_READ_IN_PRIOR_CYCLES (MANDATORY for grounding_refs — for DENIED_SECURITY include ALL of these; "
                "for OUTCOME_OK include all that were read to answer the task):\n" +
                "\n".join(f"  - {p}" for p in file_paths)
            )
    if prior_results:
        pr_lines = []
        for action, result in prior_results:
            if action.startswith("tree:"):
                limit = 8000
            elif action.startswith("search:"):
                limit = 20000
            else:
                # 400 chars captures full payment JSON fields (fingerprints, IDs, amounts, status)
                # to enable precise fraud pattern detection; num_ctx=32768 accommodates accumulation.
                limit = 400
            result_preview = result.strip()[:limit] if result.strip() else "(empty)"
            pr_lines.append(f"  action: {action[:120]}\n  result: {result_preview}")
        parts.append("PRIOR_RESULTS (outputs from earlier cycles — extract file paths for grounding_refs):\n" +
                     "\n\n".join(pr_lines))
    if runtime_identity:
        parts.append(f"## AGENT_CONTEXT\nruntime_identity: {runtime_identity}")
    return "\n\n".join(parts)


def _extract_tree_files(tree_action: str, tree_output: str) -> list[str]:
    """Extract sorted absolute file paths from a tree: action result."""
    dir_path = tree_action[len("tree:"):].rstrip("/")
    names = re.findall(r'name:\s*"([^"]+)"[^}]*?NODE_KIND_FILE', tree_output, re.DOTALL)
    return sorted(f"{dir_path}/{n}" for n in names)


def _infer_action_type(action: str) -> str:
    """Infer action type from plain string: sql | read | exec | list | search | find | tree."""
    s = action.strip()
    if re.match(r"^SELECT\b", s, re.IGNORECASE):
        return "sql"
    if s.startswith("list:"):
        return "list"
    if s.startswith("search:"):
        return "search"
    if s.startswith("find:"):
        return "find"
    if s.startswith("tree:"):
        return "tree"
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
        elif action_type == "list":
            path = action[len("list:"):].strip()
            result = vm.list(ListRequest(path=path))
            entries = getattr(result, "entries", [])
            raw = "\n".join(e.name for e in entries) if entries else ""
            return ExecuteOutput(results=[{"output": raw}], action=action), ""
        elif action_type == "search":
            # format: search:pattern /optional/root
            rest = action[len("search:"):].strip()
            parts = rest.split(None, 1)
            pattern = parts[0] if parts else rest
            root = parts[1].strip() if len(parts) > 1 else "/"
            result = vm.search(SearchRequest(root=root, pattern=pattern, limit=20))
            matches = getattr(result, "matches", [])
            raw = "\n".join(f"{m.path}:{m.line}:{m.line_text}" for m in matches) if matches else ""
            return ExecuteOutput(results=[{"output": raw}], action=action), ""
        elif action_type == "find":
            # format: find:name /optional/root
            rest = action[len("find:"):].strip()
            parts = rest.split(None, 1)
            name = parts[0] if parts else rest
            root = parts[1].strip() if len(parts) > 1 else "/"
            result = vm.find(FindRequest(root=root, name=name, limit=20))
            nodes = getattr(result, "nodes", [])
            raw = "\n".join(n.path for n in nodes) if nodes else ""
            return ExecuteOutput(results=[{"output": raw}], action=action), ""
        elif action_type == "tree":
            root = action[len("tree:"):].strip() or "/"
            result = vm.tree(TreeRequest(root=root, level=2))
            raw = str(result) if result else ""
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
    idd_out: IddOutput | None = None,
) -> None:
    learn_model = _resolve_model_for_phase("learn", model)
    learn_guide = load_prompt("learn") or "# PHASE: learn"
    learn_system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": learn_guide, "cache_control": {"type": "ephemeral"}},
    ]
    existing_entries = load_learned_entries(task_id) if task_id else []
    learn_user = _build_learn_user_msg(task_text, error, error_type, existing_entries,
                                       sdd_out=sdd_out, plan_out=plan_out, answer_out=answer_out,
                                       idd_out=idd_out)
    learn_out, sgr_learn, _ = _call_llm_phase(
        learn_system, learn_user, learn_model, cfg, LearnOutput,
        max_tokens=_PHASE_MAX_TOKENS["learn"], phase="learn", cycle=cycle,
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


def _run_consolidate(
    unified_context: str,
    model: str,
    cfg: dict,
    task_id: str,
    learn_ctx: list[str],
    cycle: int,
) -> None:
    entries = load_learned_entries(task_id)
    active = [e for e in entries if e.get("status") == "active"]
    if len(active) < 2:
        return
    consolidate_model = _resolve_model_for_phase("consolidate", model)
    consolidate_guide = load_prompt("consolidate") or "# PHASE: consolidate"
    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": consolidate_guide, "cache_control": {"type": "ephemeral"}},
    ]
    rules_lines = "\n".join(
        f"  - id: {e['id']}\n    content: {e['content']!r}"
        for e in active
    )
    user_msg = f"ACTIVE_RULES:\n{rules_lines}"
    out, _, _ = _call_llm_phase(
        system, user_msg, consolidate_model, cfg, ConsolidateOutput,
        max_tokens=_PHASE_MAX_TOKENS["consolidate"], phase="consolidate", cycle=cycle,
    )
    if not out or out.skip:
        return
    for item in out.consolidations:
        if not item.merged_rule or not item.deactivate:
            continue
        _apply_learn_diff(
            task_id,
            item.merged_rule,
            item.merged_reasoning,
            item.deactivate,
            "Consolidated: " + ", ".join(item.deactivate),
        )
        deactivate_contents = {
            e["content"] for e in active if e.get("id") in item.deactivate
        }
        learn_ctx[:] = [r for r in learn_ctx if r not in deactivate_contents]
        learn_ctx.append(item.merged_rule)
    print(f"[pipeline] CONSOLIDATE: {len(out.consolidations)} merge(s), active={len(learn_ctx)}")


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
    prior_results: list[tuple[str, str]] = []  # (action, raw_output) per cycle

    outcome = "OUTCOME_NONE_CLARIFICATION"
    sdd_out: SddOutput | None = None
    plan_out: PlanOutput | None = None
    unified_context = ""
    final_grounding_refs_count = 0

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

            # ── IDD ───────────────────────────────────────────────────────────
            _prior_for_idd = [a for s in prior_action_sets for a in s]
            idd_out, sgr_idd, tok = _run_idd(
                unified_context, model, cfg, task_text,
                last_error, _prior_for_idd, cycle + 1,
            )
            total_in_tok += tok.get("input", 0)
            total_out_tok += tok.get("output", 0)
            sgr_trace.append(sgr_idd)

            if not idd_out:
                last_error = "IDD phase: failed to parse LLM output"
                print(f"{CLI_RED}[pipeline] IDD parse failed{CLI_CLR}")
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="llm_fail", cycle=cycle + 1, task_id=task_id)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            if idd_out.decision == "hard_stop":
                print(f"{CLI_YELLOW}[pipeline] IDD hard_stop: {idd_out.stop_code}{CLI_CLR}")
                try:
                    vm.answer(AnswerRequest(
                        message=idd_out.stop_message,
                        outcome=OUTCOME_BY_NAME[idd_out.stop_code],
                        refs=idd_out.stop_refs,
                    ))
                except Exception as e:
                    print(f"{CLI_RED}[pipeline] vm.answer error: {e}{CLI_CLR}")
                success = True
                break

            print(f"{CLI_BLUE}[pipeline] IDD: {idd_out.intent_type} — {idd_out.reformulated_task[:60]!r}{CLI_CLR}")

            # ── SDD ───────────────────────────────────────────────────────────
            sdd_model = _resolve_model_for_phase("sdd", model)
            _prior_for_sdd = [a for s in prior_action_sets for a in s]
            sdd_user = _build_sdd_user_msg(idd_out, last_error, prior_actions=_prior_for_sdd, prior_results=prior_results or None)
            sdd_guide = load_prompt("sdd") or "# PHASE: sdd"
            sdd_system: list[dict] = [
                {"type": "text", "text": unified_context},
                {"type": "text", "text": sdd_guide, "cache_control": {"type": "ephemeral"}},
            ]
            sdd_out, sgr_entry, tok = _call_llm_phase(
                sdd_system, sdd_user, sdd_model, _with_json_schema(cfg, _SDD_SCHEMA), SddOutput,
                max_tokens=_PHASE_MAX_TOKENS["sdd"], phase="sdd", cycle=cycle + 1,
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
                           error_type=sdd_err_type, cycle=cycle + 1, task_id=task_id,
                           idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
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
                _basket_m = re.search(r'\b(basket_\w+|cart_\w+)\b', task_text, re.IGNORECASE)
                if _basket_m:
                    _basket_ref = f"/proc/baskets/{_basket_m.group(1)}.json"
                    if _basket_ref not in _refs:
                        _refs.append(_basket_ref)
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
            _prior = [a for s in prior_action_sets for a in s]
            plan_user = _build_plan_user_msg(sdd_out.model_dump_json(), prior_actions=_prior)
            plan_out, sgr_plan, tok = _call_llm_phase(
                plan_system, plan_user, plan_model, cfg, PlanOutput,
                max_tokens=_PHASE_MAX_TOKENS["plan"], phase="plan", cycle=cycle + 1,
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
                           cycle=cycle + 1, task_id=task_id, sdd_out=sdd_out,
                           idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            if not plan_out.action:
                last_error = "PLAN phase: action is empty"
                print(f"{CLI_YELLOW}[pipeline] PLAN: empty action{CLI_CLR}")
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            print(f"{CLI_BLUE}[pipeline] PLAN: {plan_out.action[:80]!r}{CLI_CLR}")

            # ── RETRY-LOOP GUARD ──────────────────────────────────────────────
            retry_err = check_retry_loop([plan_out.action], prior_action_sets)
            if retry_err:
                print(f"{CLI_RED}[pipeline] SECURITY hard-stop: {retry_err}{CLI_CLR}")
                last_error = f"Repeated action detected — must use a different query or approach. Action was: {plan_out.action[:120]}"
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue
            prior_action_sets.append(frozenset([plan_out.action]))

            # Inject issuer_id into /bin/discount commands (positional: BASKET_ID PERCENT REASON ISSUER_ID)
            if pre.agent_id and plan_out.action.startswith("/bin/discount "):
                _emp_m = re.search(r'\bemp_\d+\b', pre.agent_id)
                if _emp_m:
                    _issuer = _emp_m.group(0)
                    if _issuer not in plan_out.action:
                        plan_out = plan_out.model_copy(update={"action": f"{plan_out.action} {_issuer}"})
                        print(f"{CLI_BLUE}[pipeline] injected issuer_id {_issuer} into discount cmd{CLI_CLR}")

            # Inject store_id filter into basket SQL queries when agent_store_id is known
            if (pre.agent_store_id
                    and _infer_action_type(plan_out.action) == "sql"
                    and "FROM baskets" in plan_out.action
                    and f"store_id = '{pre.agent_store_id}'" not in plan_out.action):
                _store_filter = f"AND b.store_id = '{pre.agent_store_id}'"
                _act = plan_out.action
                # Insert before GROUP BY, ORDER BY, or LIMIT (in that priority order)
                for _kw in ("GROUP BY", "ORDER BY", "LIMIT"):
                    _ki = _act.upper().rfind(_kw)
                    if _ki >= 0:
                        _act = _act[:_ki].rstrip() + f" {_store_filter} " + _act[_ki:]
                        break
                else:
                    _act = _act.rstrip() + f" {_store_filter}"
                plan_out = plan_out.model_copy(update={"action": _act})
                print(f"{CLI_BLUE}[pipeline] injected store filter {_store_filter} into SQL{CLI_CLR}")

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
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            raw_output = execute_out.results[0].get("output", "") if execute_out.results else ""
            _action_type = _infer_action_type(plan_out.action)
            # exec-type actions (/bin/ tools) may legitimately return empty output on success;
            # only gate on empty result for data-returning operations (sql, read, search, list, find, tree)
            if _action_type != "exec" and not _csv_has_data(raw_output):
                last_error = f"Empty result: {raw_output.strip()[:120]}"
                print(f"{CLI_YELLOW}[pipeline] EXECUTE: empty result{CLI_CLR}")
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="empty", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            if t := get_trace():
                if _action_type == "sql":
                    t.log_sql_execute(cycle + 1, plan_out.action, raw_output, _csv_has_data(raw_output), _dur)

            prior_results.append((plan_out.action, raw_output))
            print(f"{CLI_BLUE}[pipeline] EXECUTE ok: {raw_output[:80]}{CLI_CLR}")

            # ── BATCH EXECUTE (homogeneous file reads) ────────────────────────
            # When SDD proposed additional file-read candidates (beyond the one
            # PLAN selected), execute them in the same cycle so ANSWER can
            # compare multiple records. Also runs when PLAN picked a tree/list
            # discovery action — any remaining read candidates are still useful.
            # Limited to 4 extras per cycle to cap context growth.
            if sdd_out and _action_type in ("read", "tree", "list", "search", "find"):
                _executed = {a2 for s2 in prior_action_sets for a2 in s2}
                # SDD-proposed candidates
                _sdd_extras = [
                    a for a in sdd_out.actions
                    if a != plan_out.action
                    and _infer_action_type(a) == "read"
                    and a not in _executed
                ]
                # Search-driven batch: if primary was search:, read ALL matching paths
                _search_extras: list[str] = []
                if _action_type == "search":
                    _search_extras = [
                        m for m in re.findall(r"^(/[^:\n]+):\d+:", raw_output, re.MULTILINE)
                        if m not in _executed and m != plan_out.action
                    ]
                # Tree-driven batch: fires when primary is a read OR when primary IS
                # the tree (same-cycle reads right after discovery).
                _tree_extras: list[str] = []
                if _action_type in ("read", "tree"):
                    if _action_type == "read":
                        _tree_dir = "/".join(plan_out.action.rstrip("/").split("/")[:-1])
                        _tree_key = (f"tree:{_tree_dir}/", f"tree:{_tree_dir}")
                    else:
                        # Primary was tree: use its own output
                        _tree_dir = plan_out.action[len("tree:"):].rstrip("/")
                        _tree_key = (plan_out.action, plan_out.action)
                    # Search prior_results for a matching tree result
                    _tree_source: str | None = None
                    for _ta, _tr in prior_results:
                        if _ta in _tree_key:
                            _tree_source = _tr
                            break
                    # Also check the just-executed output if primary was tree
                    if _action_type == "tree" and _tree_source is None:
                        _tree_source = raw_output
                    if _tree_source:
                        _raw_extras = [
                            f for f in _extract_tree_files(
                                f"tree:{_tree_dir}/", _tree_source
                            )
                            if f not in _executed and f != plan_out.action
                        ]
                        # Never auto-batch /docs/ tree extras. The SDD explicitly selects
                        # which policy doc to read via its actions array. Auto-batching all
                        # discovered docs wastes 50-80K context on irrelevant policy files.
                        if _tree_dir.rstrip("/") in ("/docs", "docs"):
                            _raw_extras = []
                        # Prioritise timestamp-named files (e.g. pay_20240413T…)
                        # over sequential ones (pay_001…) so fraud records surface first.
                        _tree_extras = sorted(
                            _raw_extras,
                            key=lambda p: (0 if re.search(r"\d{8}T\d{6}", p) else 1, p),
                        )
                # Merge: SDD first, then search-driven, then tree-driven fill.
                # Adaptive batch cap: use IDD scope_estimate if available.
                # Distributes remaining files evenly across remaining cycles.
                _scope_files = (idd_out.scope_estimate or {}).get("files_to_read", 0) if idd_out else 0
                _remaining_cycles = _MAX_CYCLES - cycle  # includes current cycle
                if _scope_files > 0 and _remaining_cycles > 0:
                    _batch_cap = min(40, max(6, math.ceil(_scope_files / _remaining_cycles) + 2))
                else:
                    _batch_cap = 6
                _seen: set[str] = set(_sdd_extras)
                _search_fill = [f for f in _search_extras if f not in _seen]
                _seen |= set(_search_fill)
                _tree_fill = [f for f in _tree_extras if f not in _seen]
                _batch_extras = (_sdd_extras + _search_fill + _tree_fill)[:_batch_cap]
                for _xact in _batch_extras:
                    _xplan = plan_out.model_copy(update={"action": _xact})
                    if check_retry_loop([_xact], prior_action_sets):
                        continue
                    _xout, _xerr = _run_execute(vm, _xplan, cycle + 1)
                    if _xout and not _xerr:
                        _xraw = _xout.results[0].get("output", "") if _xout.results else ""
                        if _csv_has_data(_xraw):
                            prior_results.append((_xact, _xraw))
                            prior_action_sets[-1] = prior_action_sets[-1] | frozenset([_xact])
                            _executed.add(_xact)
                            print(f"{CLI_BLUE}[pipeline] BATCH ok: {_xraw[:60]}{CLI_CLR}")

            # ── ANSWER ────────────────────────────────────────────────────────
            executor_model = _resolve_model_for_phase("executor", model)
            _prior_for_answer = [a for s in prior_action_sets for a in s]
            answer_user = _build_answer_user_msg(
                task_text, execute_out,
                prior_actions=_prior_for_answer,
                prior_results=prior_results,
                runtime_identity=pre.agent_id or None,
                idd_out=idd_out,
            )
            answer_guide = load_prompt("answer") or "# PHASE: answer"
            answer_system: list[dict] = [
                {"type": "text", "text": answer_guide, "cache_control": {"type": "ephemeral"}},
            ]
            answer_out, sgr_answer, tok = _call_llm_phase(
                answer_system, answer_user, executor_model, cfg, AnswerOutput,
                max_tokens=_PHASE_MAX_TOKENS["answer"], phase="answer", cycle=cycle + 1,
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
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            # ── ANSWER CLARIFICATION: retry if cycles remain ──────────────────
            if answer_out.outcome == "OUTCOME_NONE_CLARIFICATION" and cycle + 1 < _MAX_CYCLES:
                last_error = f"ANSWER clarification: {answer_out.message[:500]}"
                print(f"{CLI_YELLOW}[pipeline] ANSWER: OUTCOME_NONE_CLARIFICATION — retrying (cycle {cycle + 1}/{_MAX_CYCLES}){CLI_CLR}")
                # LEARN fires only when there is no execute data at all (genuine failure).
                # File-enumeration clarifications are intentional progress: the backtick path
                # in last_error already propagates to SDD via PREVIOUS_ERROR; running LEARN
                # here generates rules that break the backtick→SDD mechanism (e.g. r034).
                _is_file_enum_clarification = bool(re.search(
                    r"`/proc/", answer_out.message
                ))
                if not _csv_has_data(raw_output) and not _is_file_enum_clarification:
                    _run_learn(unified_context, model, cfg, task_text, last_error,
                               sgr_trace, learn_ctx, pre.agents_md_index,
                               error_type="semantic", cycle=cycle + 1, task_id=task_id,
                               sdd_out=sdd_out, plan_out=plan_out, answer_out=answer_out,
                               idd_out=idd_out)
                    _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            # ── SUCCESS ───────────────────────────────────────────────────────
            outcome = answer_out.outcome
            print(f"{CLI_GREEN}[pipeline] ANSWER: {outcome} — {answer_out.message[:100]}{CLI_CLR}")

            sku_refs: list[str] = []
            if _infer_action_type(plan_out.action) == "read":
                sku_refs.append(plan_out.action)

            clean_refs = list(answer_out.grounding_refs)
            final_grounding_refs_count = len(clean_refs)
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

    if task_id:
        _SUCCESSFUL_OUTCOMES = {"OUTCOME_OK", "OUTCOME_DENIED_SECURITY", "OUTCOME_NONE_UNSUPPORTED"}
        last_run_status = "success" if outcome in _SUCCESSFUL_OUTCOMES else "failure"
        save_last_run(
            task_id=task_id,
            status=last_run_status,
            outcome=outcome,
            cycles_used=cycles_used,
            grounding_refs_count=final_grounding_refs_count,
        )

    stats = {
        "outcome": outcome,
        "cycles_used": cycles_used,
        "grounding_refs_count": final_grounding_refs_count,
        "step_facts": [f"pipeline cycles={cycles_used}"],
        "done_ops": [],
        "input_tokens": total_in_tok,
        "output_tokens": total_out_tok,
        "total_elapsed_ms": 0,
    }
    return stats, None
