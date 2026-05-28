"""ASSEMBLE → IDD → SDD → PLAN → CODEGEN → ANSWER pipeline with fast path."""
from __future__ import annotations

import ast
import json
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import AnswerRequest

from .llm import (
    call_llm_raw, _resolve_model_for_phase, OUTCOME_BY_NAME,
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, CLI_YELLOW,
)
from .json_extract import _extract_json_from_text
from .mock_vm import MockVM
from .models import IddOutput, SddOutput, PlanOutput, LearnOutput, AnswerOutput, ConsolidateOutput, CodegenOutput
from .prephase import PrephaseResult, _format_schema_digest as _fmt_schema_digest
from .prompt import load_prompt
from .prompt_assembler import assemble_prompt, load_learned_ctx, load_learned_entries, _apply_learn_diff, save_last_run, load_last_run
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

_CODEGEN_MAX_TOKENS = int(os.environ.get("MAX_TOKENS_CODEGEN", "8192"))
_CODEGEN_LINT_RETRIES = int(os.environ.get("CODEGEN_LINT_RETRIES", "3"))
_HARD_ERROR_PREFIX = "HARD_STOP:"

_STOP_WORDS = frozenset({
    "from", "where", "select", "count", "inner", "join", "lower",
    "like", "true", "false", "none", "outcome", "message", "result",
    "python", "import", "return", "stdout", "strip", "items",
    "orders", "many", "much", "have", "what", "with", "this", "that",
    "find", "brand", "products", "product", "show", "list", "give",
    "query", "table", "column", "value", "field", "record", "data",
})


def _detect_hardcoded_params(script_code: str, task_text: str) -> str | None:
    """Return a reason string if script_code contains a string literal copied from task_text.

    Checks whether any meaningful token from task_text appears as a whole word inside
    any string constant in the script (e.g. a brand/SKU embedded in a SQL WHERE clause).

    Returns None if no hardcoded params detected or if script_code has a SyntaxError.
    """
    task_tokens = {
        t.lower() for t in re.findall(r"[A-Za-z0-9_-]{4,}", task_text)
        if t.lower() not in _STOP_WORDS
    }
    try:
        tree = ast.parse(script_code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            if val.lower() in task_tokens:
                return f"hardcoded value {val!r} from task_text"
            for tok in task_tokens:
                m = re.search(rf"\b{re.escape(tok)}\b", val, re.IGNORECASE)
                if m:
                    return f"hardcoded value {m.group()!r} from task_text"
    return None


# Compat stubs — referenced by older tests that patch these names; no-ops in new pipeline
def run_resolve(vm, model: str, task_text: str, pre, cfg: dict) -> dict:
    """Compat stub — RESOLVE phase removed from SDD pipeline."""
    return {}


def _extract_discovery_results(queries: list[str], results: list[str], confirmed_values: dict) -> None:
    """Compat stub — discovery phase removed from SDD pipeline."""


def _format_confirmed_values(cv: dict) -> str:
    """Compat stub — confirmed_values removed from SDD pipeline."""
    return ""




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
                limit = 16000
            elif action.startswith("search:"):
                limit = 20000
            else:
                # SDD only needs to know the file was read (not its content) to avoid re-reading.
                # Keeps SDD tok_in well under num_ctx even with 80+ accumulated file reads.
                limit = 80
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
    heuristic_code: str | None = None,
) -> str:
    parts = [
        f"TASK: {task_text}",
        f"ERROR: {error}",
        f"ERROR_TYPE: {error_type}",
    ]
    if error_type == "hardcoded_params":
        parts.insert(1, "ERROR_CATEGORY: script hardcodes task-specific values instead of parsing from task_text — write a rule describing the PARSING PATTERN, not the SQL logic")
    if idd_out and idd_out.stop_rules:
        parts.append("STOP_RULES:\n" + "\n".join(f"  - {r}" for r in idd_out.stop_rules))
    if sdd_out is not None:
        parts.append(f"SDD_OUTPUT:\n{sdd_out.model_dump_json(indent=2)}")
    if plan_out is not None:
        parts.append(f"PLAN_OUTPUT:\n{plan_out.model_dump_json(indent=2)}")
    if answer_out is not None:
        parts.append(f"ANSWER_OUTPUT:\n{answer_out.model_dump_json(indent=2)}")
    if heuristic_code:
        parts.append(f"HEURISTIC_CODE:\n```python\n{heuristic_code[:3000]}\n```")
    if existing_entries:
        rules_lines = "\n".join(
            f"  - id: {e['id']}\n    content: {e['content']!r}"
            for e in existing_entries
            if e.get("status") == "active"
        )
        if rules_lines:
            parts.append(f"EXISTING_RULES:\n{rules_lines}")
    return "\n\n".join(parts)




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



def _run_codegen(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    task_id: str,
    idd_out: "IddOutput",
    sdd_out: "SddOutput",
    plan_out: "PlanOutput",
    pre: "PrephaseResult",
    cycle: int,
    heuristic_hint: str = "",
) -> "tuple[CodegenOutput | None, str]":
    """CODEGEN phase: LLM generates heuristic script + mock test. Returns (CodegenOutput, error)."""
    codegen_model = _resolve_model_for_phase("codegen", model)
    codegen_guide = load_prompt("codegen") or "# PHASE: codegen"

    import json as _json

    user_parts = [
        f"TASK: {task_text}",
        f"TASK_ID: {task_id}",
        f"REFORMULATED_TASK: {idd_out.reformulated_task}",
        f"INTENT_TYPE: {idd_out.intent_type}",
    ]
    if idd_out.extracted_params:
        user_parts.append(f"EXTRACTED_PARAMS: {_json.dumps(idd_out.extracted_params)}")
    if idd_out.success_criteria:
        user_parts.append("SUCCESS_CRITERIA:\n" + "\n".join(f"  - {c}" for c in idd_out.success_criteria))
    user_parts.append(f"SDD_GOAL: {sdd_out.spec_goal}")
    user_parts.append(f"PLAN_ACTION: {plan_out.action}")
    if heuristic_hint:
        user_parts.append(heuristic_hint)
    user_msg = "\n\n".join(user_parts)

    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": codegen_guide, "cache_control": {"type": "ephemeral"}},
    ]

    lint_error: str | None = None
    script_code = ""
    test_code = ""
    _last_was_hardcoded = False
    _schema_str = pre.schema_digest if isinstance(pre.schema_digest, str) else str(pre.schema_digest)
    exec_globals_for_test: dict = {}

    for attempt in range(_CODEGEN_LINT_RETRIES):
        _last_was_hardcoded = False
        retry_msg = f"{user_msg}\n\nPREVIOUS_LINT_ERROR: {lint_error}\nFix and regenerate." if lint_error else user_msg

        tok_info: dict = {}
        raw = call_llm_raw(system, retry_msg, codegen_model, cfg,
                           max_tokens=_CODEGEN_MAX_TOKENS, token_out=tok_info)
        if not raw:
            lint_error = "LLM returned empty response"
            continue

        extracted = _extract_json_from_text(raw)
        if not isinstance(extracted, dict):
            lint_error = f"Could not parse JSON from LLM response: {raw[:200]}"
            continue

        script_code = extracted.get("script", "")
        test_code = extracted.get("test", "")

        # AST lint check
        lint_error = None
        for label, code in [("script", script_code), ("test", test_code)]:
            try:
                ast.parse(code)
            except SyntaxError as e:
                lint_error = f"{label} syntax error: {e}"
                break
        if lint_error:
            continue

        # AST hardcode detection
        hc_reason = _detect_hardcoded_params(script_code, task_text)
        if hc_reason:
            lint_error = (
                f"Hardcoded param detected: {hc_reason}. "
                f"Extract all task-specific values from the task_text variable using regex."
            )
            _last_was_hardcoded = True
            continue

        # Dual-run step 1: original task_text
        mock_vm_orig = MockVM(extracted_params=idd_out.extracted_params, schema_digest=_schema_str)
        _eg_orig: dict = {"vm": mock_vm_orig, "task_text": task_text, "_result": None}
        try:
            exec(compile(script_code, f"{task_id}.py", "exec"), _eg_orig)
        except Exception as e:
            lint_error = f"Script runtime error on original task_text: {e}"
            continue
        _raw_result = _eg_orig.get("_result")
        if not _raw_result or not isinstance(_raw_result, dict) \
                or "outcome" not in _raw_result or "message" not in _raw_result:
            lint_error = "Script did not set valid _result (needs outcome + message) on original task_text"
            continue

        # Dual-run step 2: mutated task_text
        _mutated = re.sub(
            r"[A-Za-z0-9_-]{4,}",
            lambda m: "SYNTHTOK" if m.group(0).lower() not in _STOP_WORDS else m.group(0),
            task_text,
        )
        mock_vm_mut = MockVM(extracted_params={}, schema_digest=_schema_str)
        _eg_mut: dict = {"vm": mock_vm_mut, "task_text": _mutated, "_result": None}
        try:
            exec(compile(script_code, f"{task_id}_mut.py", "exec"), _eg_mut)
        except (KeyError, IndexError, AttributeError) as e:
            lint_error = (
                f"Script crashed on mutated task_text ({type(e).__name__}: {e}). "
                f"Script must not rely on hardcoded values from task_text."
            )
            _last_was_hardcoded = True
            continue
        except Exception:
            pass  # Non-hardcode crash — not a generality failure

        exec_globals_for_test = _eg_orig
        break  # All checks passed

    if lint_error:
        if _last_was_hardcoded and script_code:
            partial: CodegenOutput | None = CodegenOutput(script_path="", script_code=script_code, test_code=test_code)
        else:
            partial = None
        prefix = "HARDCODED_PARAMS:" if _last_was_hardcoded else ""
        return partial, f"{prefix}CODEGEN lint failed after {_CODEGEN_LINT_RETRIES} attempts: {lint_error}"

    # Mock test — run test_code using exec_globals with _result from original run
    try:
        exec(compile(test_code, f"{task_id}_test.py", "exec"), exec_globals_for_test)
    except Exception as e:
        return None, f"CODEGEN mock test failed: {e}"

    # Persist script
    heuristics_dir = Path("data/heuristics")
    heuristics_dir.mkdir(exist_ok=True)
    script_path = f"data/heuristics/{task_id}.py"
    (heuristics_dir / f"{task_id}.py").write_text(script_code, encoding="utf-8")
    (heuristics_dir / f"{task_id}_test.py").write_text(test_code, encoding="utf-8")

    return CodegenOutput(script_path=script_path, script_code=script_code, test_code=test_code), ""


def _run_answer(
    vm,
    codegen_out: "CodegenOutput",
    task_text: str,
) -> "tuple[AnswerOutput | None, str]":
    """ANSWER phase: exec heuristic script, call vm.answer(). No LLM call."""
    exec_globals: dict = {"vm": vm, "task_text": task_text, "_result": None}
    try:
        exec(compile(codegen_out.script_code, codegen_out.script_path, "exec"), exec_globals)
    except (OSError, PermissionError) as e:
        return None, f"{_HARD_ERROR_PREFIX} Script filesystem error: {e}"
    except Exception as e:
        return None, f"Script runtime error: {e}"

    raw_result = exec_globals.get("_result")
    if not raw_result or not isinstance(raw_result, dict):
        return None, "Script did not set _result"
    if "outcome" not in raw_result or "message" not in raw_result:
        return None, "Script _result missing required fields: outcome, message"
    if raw_result["outcome"] not in OUTCOME_BY_NAME:
        return None, f"Unknown outcome code in _result: {raw_result['outcome']!r}"

    try:
        vm.answer(AnswerRequest(
            message=raw_result["message"],
            outcome=OUTCOME_BY_NAME[raw_result["outcome"]],
            refs=raw_result.get("refs", []),
        ))
    except Exception as e:
        return None, f"vm.answer() error: {e}"

    return AnswerOutput(
        reasoning="",
        message=raw_result["message"],
        outcome=raw_result["outcome"],
        grounding_refs=raw_result.get("refs", []),
        completed_steps=[],
    ), ""


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
    heuristic_code: str | None = None,
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
                                       idd_out=idd_out, heuristic_code=heuristic_code)
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


def _run_fast_path(
    vm,
    task_id: str,
    task_text: str,
    schema_hash: str = "",
) -> "tuple[bool, str, str]":
    """Execute existing heuristic script. Returns (ok, error_string, outcome_str)."""
    script_path = Path("data") / "heuristics" / f"{task_id}.py"
    try:
        script_code = script_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"fast path read error: {e}", ""

    exec_globals: dict = {"vm": vm, "task_text": task_text, "_result": None}
    try:
        exec(compile(script_code, str(script_path), "exec"), exec_globals)
    except (OSError, PermissionError) as e:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path filesystem error: {e}", ""
    except Exception as e:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path script error: {e}", ""

    raw_result = exec_globals.get("_result")
    if not raw_result or "outcome" not in raw_result or "message" not in raw_result:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, "fast path: script did not produce valid _result", ""

    if raw_result["outcome"] not in OUTCOME_BY_NAME:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path: unknown outcome {raw_result['outcome']!r}", ""

    script_outcome = raw_result["outcome"]
    try:
        vm.answer(AnswerRequest(
            message=raw_result["message"],
            outcome=OUTCOME_BY_NAME[script_outcome],
            refs=raw_result.get("refs", []),
        ))
    except Exception as e:
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION",
                      cycles_used=0, heuristic_valid=False)
        return False, f"fast path vm.answer error: {e}", ""

    save_last_run(task_id, status="success", outcome=script_outcome,
                  cycles_used=0, heuristic_valid=True, schema_hash=schema_hash)
    return True, "", script_outcome


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
    """ASSEMBLE → SDD → PLAN → CODEGEN → ANSWER pipeline. Returns (stats dict, None)."""
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

    # ── SCHEMA HASH ───────────────────────────────────────────────────────────
    import hashlib as _hashlib
    _schema_src = str(pre.schema_digest) if pre.schema_digest else ""
    _current_schema_hash = _hashlib.md5(_schema_src.encode()).hexdigest()[:8]

    # ── FAST PATH ─────────────────────────────────────────────────────────────
    if task_id:
        last_run_record = load_last_run(task_id)
        _heuristic_script = Path("data") / "heuristics" / f"{task_id}.py"
        _stored_schema_hash = (last_run_record or {}).get("schema_hash", "")
        _schema_hash_ok = (
            _stored_schema_hash == ""
            or _stored_schema_hash == _current_schema_hash
        )
        _fast_eligible = (
            last_run_record is not None
            and last_run_record.get("heuristic_valid") is True
            and _heuristic_script.exists()
            and _schema_hash_ok
        )
        if not _fast_eligible and last_run_record is not None \
                and last_run_record.get("heuristic_valid") is True \
                and _heuristic_script.exists() \
                and not _schema_hash_ok:
            last_error = f"schema changed since last heuristic ({_stored_schema_hash} → {_current_schema_hash})"
            print(f"{CLI_YELLOW}[pipeline] fast path skipped: schema changed{CLI_CLR}")
        if _fast_eligible:
            print(f"{CLI_BLUE}[pipeline] fast path: {task_id}{CLI_CLR}")
            _fp_ok, _fp_err, _fp_outcome = _run_fast_path(vm, task_id, task_text, schema_hash=_current_schema_hash)
            if _fp_ok:
                return {
                    "outcome": _fp_outcome,
                    "cycles_used": 0,
                    "grounding_refs_count": 0,
                    "step_facts": ["fast path: 0 LLM calls"],
                    "done_ops": [],
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_elapsed_ms": 0,
                }, None
            last_error = _fp_err
            print(f"{CLI_YELLOW}[pipeline] fast path failed: {_fp_err} — falling through to full path{CLI_CLR}")

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

            # ── CODEGEN ──────────────────────────────────────────────────────
            _heuristic_hint = ""
            if last_error.startswith("schema changed") and task_id:
                _h_path = Path("data") / "heuristics" / f"{task_id}.py"
                if _h_path.exists():
                    _heuristic_hint = (
                        f"HEURISTIC_HINT: data/heuristics/{task_id}.py may be reusable with updated schema.\n"
                        f"{last_error}. Review SQL/read calls for schema compatibility."
                    )
            _t0 = time.monotonic()
            codegen_out, codegen_error = _run_codegen(
                unified_context=unified_context,
                model=model,
                cfg=cfg,
                task_text=task_text,
                task_id=task_id,
                idd_out=idd_out,
                sdd_out=sdd_out,
                plan_out=plan_out,
                pre=pre,
                cycle=cycle + 1,
                heuristic_hint=_heuristic_hint,
            )
            _dur = int((time.monotonic() - _t0) * 1000)

            if codegen_error or codegen_out is None:
                err = codegen_error or "CODEGEN returned None"
                print(f"{CLI_YELLOW}[pipeline] CODEGEN failed: {err}{CLI_CLR}")
                last_error = err
                _learn_error_type = "hardcoded_params" if err.startswith("HARDCODED_PARAMS:") else "semantic"
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type=_learn_error_type, cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out,
                           heuristic_code=codegen_out.script_code if codegen_out else None)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            print(f"{CLI_BLUE}[pipeline] CODEGEN ok: {codegen_out.script_path}{CLI_CLR}")

            # ── ANSWER ────────────────────────────────────────────────────────
            answer_out, answer_error = _run_answer(vm, codegen_out, task_text)

            if answer_error or answer_out is None:
                err = answer_error or "ANSWER returned None"
                if (err or "").startswith(_HARD_ERROR_PREFIX):
                    print(f"{CLI_RED}[pipeline] ANSWER filesystem hard error: {err}{CLI_CLR}")
                    last_error = err
                    break
                print(f"{CLI_YELLOW}[pipeline] ANSWER failed: {err}{CLI_CLR}")
                last_error = err
                _run_learn(unified_context, model, cfg, task_text, last_error,
                           sgr_trace, learn_ctx, pre.agents_md_index,
                           error_type="semantic", cycle=cycle + 1, task_id=task_id,
                           sdd_out=sdd_out, plan_out=plan_out, idd_out=idd_out,
                           heuristic_code=codegen_out.script_code if codegen_out else None)
                _run_consolidate(unified_context, model, cfg, task_id, learn_ctx, cycle + 1)
                continue

            # ── SUCCESS ───────────────────────────────────────────────────────
            outcome = answer_out.outcome
            print(f"{CLI_GREEN}[pipeline] ANSWER: {outcome} — {answer_out.message[:100]}{CLI_CLR}")

            final_grounding_refs_count = len(answer_out.grounding_refs)
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
            heuristic_valid=success and outcome in _SUCCESSFUL_OUTCOMES,
            schema_hash=_current_schema_hash if (success and outcome in _SUCCESSFUL_OUTCOMES) else "",
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
