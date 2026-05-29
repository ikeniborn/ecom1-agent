"""DESIGN → CODEGEN → fidelity → ANSWER pipeline (terminal one-shot ANSWER)."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from bitgn.vm.ecom.ecom_pb2 import AnswerRequest

from .codegen_v2 import CodegenError, run_codegen
from .design import DesignError, run_design
from .fidelity import exec_fidelity_in_subprocess, generate_fidelity_test
from .json_extract import _extract_json_from_text
from .learned_store import apply_learn_diff, load_entries, save_last_run
from .llm import (
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, CLI_YELLOW,
    OUTCOME_BY_NAME, _resolve_model_for_phase, call_llm_raw,
)
from .models import DesignOutput, LearnConsolidateOutput
from .prompt import load_prompt
from .sql_security import check_retry_loop
from .trace import get_trace

_MAX_STEPS = int(os.environ.get("MAX_STEPS", "3"))
_MAX_TOKENS_LEARN = int(os.environ.get("MAX_TOKENS_LEARN", "2048"))
_FIDELITY_TIMEOUT_S = int(os.environ.get("FIDELITY_TIMEOUT_S", "30"))

_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# SQL extraction for check_retry_loop (F-005)
# ---------------------------------------------------------------------------

def _extract_sql_literals(script_code: str) -> list[str]:
    """Return literal SQL strings passed to vm.exec(path='/bin/sql', args=[...]).

    Per F-005: walk ast.Constant nodes whose parent is a Call to vm.exec
    where args[0] == '/bin/sql'. Computed SQL (concat, f-strings) is ignored.
    Whitespace is collapsed via `_normalise` so downstream comparisons are
    insensitive to formatting.
    """
    try:
        tree = ast.parse(script_code)
    except SyntaxError:
        return []

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_vm_exec = (
            isinstance(func, ast.Attribute)
            and func.attr == "exec"
            and isinstance(func.value, ast.Name)
            and func.value.id == "vm"
        )
        if not is_vm_exec:
            continue
        path_val = None
        args_node = None
        for kw in node.keywords:
            if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                path_val = kw.value.value
            if kw.arg == "args":
                args_node = kw.value
        if path_val != "/bin/sql" or not isinstance(args_node, (ast.List, ast.Tuple)):
            continue
        for elt in args_node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(_normalise(elt.value))
    return out


def _normalise(sql: str) -> str:
    return _WHITESPACE_RE.sub(" ", sql).strip()


def _identical_sql_set(a: list[str], b: list[str]) -> bool:
    """Multiset equality after whitespace collapse + strip; case-sensitive."""
    return sorted(_normalise(s) for s in a) == sorted(_normalise(s) for s in b)


# ---------------------------------------------------------------------------
# Learn + consolidate (merged LLM call)
# ---------------------------------------------------------------------------

def _learn_consolidate(
    task_id: str,
    learn_ctx: list[dict],
    design: DesignOutput,
    error: str,
    script_code: str,
) -> None:
    """Single LLM call. Writes a diff to data/learned/{tid}.yaml and mutates learn_ctx."""
    guide = load_prompt("learn") or "# PHASE: LEARN"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]

    rules_lines = "\n".join(
        f"  - [{e.get('id', '?')}] {e.get('content', '')}" for e in learn_ctx
    ) or "(none)"
    user_msg = (
        f"TOOL_PLAN:\n{design.model_dump_json(indent=2)}\n\n"
        f"ERROR:\n{error}\n\n"
        f"SCRIPT_CODE:\n```python\n{script_code[:4000]}\n```\n\n"
        f"EXISTING_RULES:\n{rules_lines}"
    )

    model = _resolve_model_for_phase("learn", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_LEARN)
    if not raw:
        print(f"{CLI_YELLOW}[pipeline] LEARN: empty response, skipping{CLI_CLR}")
        return

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        print(f"{CLI_YELLOW}[pipeline] LEARN: unparseable response, skipping{CLI_CLR}")
        return

    try:
        out = LearnConsolidateOutput(**obj)
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] LEARN: validation failed: {e}{CLI_CLR}")
        return

    apply_learn_diff(task_id, out)

    if not out.skip:
        learn_ctx.append({
            "id": "in-session",
            "content": out.rule_content,
            "agents_md_anchor": out.agents_md_anchor,
        })


# ---------------------------------------------------------------------------
# Terminal exits — exactly one vm.answer() per task
# ---------------------------------------------------------------------------

def _terminal_clarification(vm, message: str) -> None:
    vm.answer(message=message[:800], outcome="OUTCOME_NONE_CLARIFICATION", refs=[])


def _terminal_outcome_override(vm, design: DesignOutput) -> None:
    vm.answer(
        message=design.answer_template.message,
        outcome=design.outcome_override,
        refs=list(design.answer_template.refs),
    )


# ---------------------------------------------------------------------------
# Real-VM exec
# ---------------------------------------------------------------------------

def _run_script_on_vm(script_code: str, vm, params: dict[str, str]) -> None:
    """Exec the script's top-level module; call its `run(vm, params)`."""
    ns: dict = {}
    exec(compile(script_code, "<heuristic>", "exec"), ns)
    fn = ns.get("run")
    if not callable(fn):
        raise RuntimeError("script does not define run(vm, params)")
    fn(vm, params)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_pipeline(
    vm,
    instruction: str,
    task_id: str,
    agents_md_text: str,
) -> None:
    """Per-task pipeline. Exactly one vm.answer() call before returning."""
    tlog = get_trace()
    if tlog:
        tlog.log_header(instruction, os.environ.get("MODEL", ""))
    learn_ctx = load_entries(task_id)
    print(f"{CLI_BLUE}[pipeline] task={task_id} active_rules={len(learn_ctx)}{CLI_CLR}")

    # ── DESIGN ──────────────────────────────────────────────────────────────
    try:
        design = run_design(instruction, agents_md_text)
    except DesignError as e:
        print(f"{CLI_RED}[pipeline] DESIGN failed: {e}{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=0)
        _terminal_clarification(vm, f"DESIGN failed: {e}")
        return

    if design.outcome_override:
        print(f"{CLI_YELLOW}[pipeline] outcome_override: {design.outcome_override}{CLI_CLR}")
        save_last_run(task_id, status="success", outcome=design.outcome_override, cycles_used=0)
        _terminal_outcome_override(vm, design)
        return

    # ── CODEGEN retry loop (unified MAX_STEPS counter, F-003) ──────────────
    last_error: str | None = None
    script_code: str | None = None
    prior_sql_sets: list[list[str]] = []

    for cycle in range(1, _MAX_STEPS + 1):
        print(f"{CLI_BLUE}[pipeline] cycle {cycle}/{_MAX_STEPS}{CLI_CLR}")

        try:
            cg = run_codegen(design, learn_ctx, last_error)
        except CodegenError as e:
            last_error = f"codegen_llm_fail: {e}"
            print(f"{CLI_YELLOW}[pipeline] CODEGEN llm fail: {e}{CLI_CLR}")
            continue   # no LEARN; just retry

        # Lint gate
        try:
            ast.parse(cg.script_code)
        except SyntaxError as e:
            last_error = f"lint: {e}"
            print(f"{CLI_YELLOW}[pipeline] lint fail: {e}{CLI_CLR}")
            _learn_consolidate(task_id, learn_ctx, design, last_error, cg.script_code)
            continue

        # check_retry_loop — anti-infinite-loop guard (HM4)
        sqls = _extract_sql_literals(cg.script_code)
        if prior_sql_sets and _identical_sql_set(sqls, prior_sql_sets[-1]):
            print(f"{CLI_RED}[pipeline] check_retry_loop: identical SQL set, breaking{CLI_CLR}")
            last_error = last_error or "identical SQL set across cycles"
            break
        loop_msg = check_retry_loop([_normalise(s) for s in sqls], [frozenset(_normalise(s) for s in p) for p in prior_sql_sets])
        if loop_msg:
            print(f"{CLI_RED}[pipeline] {loop_msg}{CLI_CLR}")
            last_error = loop_msg
            break
        prior_sql_sets.append(sqls)

        # Fidelity gate
        test_src = generate_fidelity_test(design, task_id)
        result = exec_fidelity_in_subprocess(test_src, cg.script_code, timeout_s=_FIDELITY_TIMEOUT_S)
        if not result.passed:
            last_error = f"fidelity: {result.error}"
            print(f"{CLI_YELLOW}[pipeline] fidelity fail: {result.error}{CLI_CLR}")
            _learn_consolidate(task_id, learn_ctx, design, last_error, cg.script_code)
            continue

        # Gate passed — break out of loop
        script_code = cg.script_code
        break

    if script_code is None:
        print(f"{CLI_RED}[pipeline] exhausted {_MAX_STEPS} cycles{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=_MAX_STEPS)
        _terminal_clarification(vm, last_error or "all cycles exhausted")
        return

    # ── Persist last-attempt script (reference for LEARN, not for re-exec) ─
    heur_dir = Path("data/heuristics")
    heur_dir.mkdir(parents=True, exist_ok=True)
    (heur_dir / f"{task_id}.py").write_text(script_code, encoding="utf-8")

    # ── ANSWER terminal one-shot (real VM) ──────────────────────────────────
    try:
        _run_script_on_vm(script_code, vm, design.params)
    except Exception as e:
        print(f"{CLI_RED}[pipeline] real-vm exec failed: {e}{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=cycle)
        _terminal_clarification(vm, f"real-vm exec: {e}")
        return

    print(f"{CLI_GREEN}[pipeline] success after {cycle} cycle(s){CLI_CLR}")
    save_last_run(task_id, status="success", outcome="OUTCOME_OK", cycles_used=cycle)
