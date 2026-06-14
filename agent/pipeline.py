"""DESIGN → CODEGEN → fidelity → ANSWER pipeline (terminal one-shot ANSWER)."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from .codegen_v2 import CodegenError, run_codegen
from .design import DesignError, run_design
from .fidelity import exec_fidelity_in_subprocess, generate_fidelity_test
from .json_extract import _extract_json_from_text
from .learned_store import _format_entry, apply_learn_diff, load_entries, save_last_run
from .llm import (
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, CLI_YELLOW,
    OUTCOME_BY_NAME, _resolve_model_for_phase, call_llm_raw,
)
from .mock_vm_spy import MockVMSpy, fixture_key
from .models import DesignOutput, LearnConsolidateOutput, TestSpec
from .prompt import load_prompt
from .sql_security import check_retry_loop  # noqa: F401  (retained for backward import compat)
from .testgen import TestGenError, run_test_gen
from .trace import set_cycle
from .test_runner import run_tests

_MAX_STEPS = int(os.environ.get("MAX_STEPS", "3"))
_MAX_TOKENS_LEARN = int(os.environ.get("MAX_TOKENS_LEARN", "2048"))
_FIDELITY_TIMEOUT_S = int(os.environ.get("FIDELITY_TIMEOUT_S", "30"))
# Retries for transient DESIGN parse/empty failures (CC subprocess truncation).
_DESIGN_MAX_ATTEMPTS = int(os.environ.get("DESIGN_MAX_ATTEMPTS", "3"))

# Intent-driven TDD gate. Off by default so the green baseline can't regress;
# flip on after validation. TDD_MOCK_ENABLED adds the in-loop MockVMSpy fail-fast
# pre-check (best-effort — see run_pipeline). TDD_FORCE_SUBMIT_AFTER mirrors the
# legacy "N consecutive test fails → submit best answer" escape so a bad test
# can't downgrade an otherwise-green task to CLARIFICATION.
_TDD_ENABLED = os.environ.get("TDD_ENABLED", "0") == "1"
_TDD_MOCK_ENABLED = os.environ.get("TDD_MOCK_ENABLED", "0") == "1"
_TDD_FORCE_SUBMIT_AFTER = int(os.environ.get("TDD_FORCE_SUBMIT_AFTER", "3"))

# Deterministic Plan-IR interpreter path. Off by default so the legacy
# DESIGN→CODEGEN baseline can't regress. Gated on a FRESH os.environ read inside
# run_pipeline so a test's monkeypatch.setenv takes effect (the module-level
# constant is evaluated at import time and kept for documentation only).
_INTERPRETER_ENABLED = os.environ.get("INTERPRETER_ENABLED", "0") == "1"

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


# Errors whose fix lives downstream of SQL CONTENT — identical SQL recurring is
# correct, not a stuck loop, so check_retry_loop must NOT fire on them. fidelity
# asserts the RPC-name multiset (never SQL text); lint is ast.parse; answer_refs
# is parsing/refs/answer_template. None are caused by the SQL statement itself.
_RETRY_GUARD_SKIP_PREFIXES = ("answer_refs:", "fidelity:", "lint:")


def _retry_guard_applies(last_error: str | None) -> bool:
    """True only when the prior failure is plausibly SQL-content-driven.

    The anti-infinite-loop guard breaks on 3 identical SQL multisets. That signal
    is meaningful only when the SQL itself is what codegen keeps getting wrong;
    for shape/refs/lint failures the SQL is correct and stable while the fix lives
    elsewhere, so the guard would mis-fire and starve the cycle budget (t51).
    """
    if not last_error:
        return True
    return not last_error.startswith(_RETRY_GUARD_SKIP_PREFIXES)


# Real-VM exceptions whose fix is a deterministic input-validation failure
# (bad tool path, reading a directory, missing file/record) OR a network
# transient. On a read-only plan these are safe to re-run, so the loop should
# LEARN + retry rather than dead-end at clarification. Matched against
# str(exc).lower(); the read-only guard lives at the call site (has_mutations).
_RETRYABLE_VM_ERROR_PATTERNS = (
    # Missing path/record. The ECOM runtime phrases this "read failed: not found";
    # POSIX-style backends say "no such file" / "does not exist". Cover both, else
    # a read-only plan that probes a non-existent path dead-ends instead of
    # retrying (regression: t02 broke at cycle 5/10 on "read failed: not found").
    "not found",
    "is a directory",
    "does not exist",
    "no such file",
    "not a file",
    # Network/VM transients. Read-only plans are safe to re-run; mutating
    # plans are guarded by `has_mutations` (set from design.ops).
    "the read operation timed out",
    "the write operation timed out",
    "connection reset",
    "remote disconnected",
    "connection aborted",
)


def _is_retryable_vm_error(msg: str) -> bool:
    """True when a real-VM exception is a deterministic input or transient
    failure that a read-only plan can safely re-run (see patterns above)."""
    msg = msg.lower()
    return any(p in msg for p in _RETRYABLE_VM_ERROR_PATTERNS)


# ---------------------------------------------------------------------------
# Learn + consolidate (merged LLM call)
# ---------------------------------------------------------------------------

def _learn_consolidate_text(
    task_id: str,
    learn_ctx: list[dict],
    plan_context: str,
    error: str,
    artifact: str,
    token_out: dict | None = None,
    observed: list[str] | None = None,
) -> None:
    """Message-building core of LEARN, driven by already-rendered strings.

    `plan_context` is the rendered "tool plan" (legacy: DesignOutput JSON;
    interpreted path: IntentSpec JSON). `artifact` is the rendered candidate
    (legacy: script_code; interpreted path: PlanIR JSON). Writes a diff to
    data/learned/{tid}.yaml and mutates learn_ctx in-place. `observed` carries
    RPC stdouts captured during the failed run so LEARN can see WHY refs were
    empty (table missing, column wrong, search returned nothing).
    """
    guide = load_prompt("learn") or "# PHASE: LEARN"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]

    rules_lines = "\n".join(_format_entry(e) for e in learn_ctx) or "(none)"
    observed_block = ""
    if observed:
        observed_block = "OBSERVED_RPC_OUTPUTS:\n" + "\n".join(observed) + "\n\n"
    user_msg = (
        f"TOOL_PLAN:\n{plan_context}\n\n"
        f"ERROR:\n{error}\n\n"
        f"{observed_block}"
        f"SCRIPT_CODE:\n```python\n{artifact}\n```\n\n"
        f"EXISTING_RULES:\n{rules_lines}"
    )

    model = _resolve_model_for_phase("learn", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_LEARN, token_out=token_out, phase="LEARN")
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

    if not out.skip and out.rule_content:
        learn_ctx.append({
            "id": "in-session",
            "content": out.rule_content,
            "agents_md_anchor": out.agents_md_anchor,
        })


def _learn_consolidate(
    task_id: str,
    learn_ctx: list[dict],
    design: DesignOutput,
    error: str,
    script_code: str,
    token_out: dict | None = None,
    observed: list[str] | None = None,
) -> None:
    """Single LLM call. Writes a diff to data/learned/{tid}.yaml and mutates learn_ctx.

    Thin wrapper over `_learn_consolidate_text`: renders the DesignOutput and
    script to strings, then handles the legacy oracle-distill opt-in.

    `observed` carries RPC stdouts captured during the failed real-VM run so
    LEARN can see WHY refs were empty (table missing, column wrong, search
    returned nothing). Without it LEARN only sees the guard error string and
    tends to write the same rule each cycle.
    """
    _learn_consolidate_text(
        task_id, learn_ctx,
        plan_context=design.model_dump_json(indent=2),
        error=error, artifact=script_code,
        token_out=token_out, observed=observed,
    )

    # Opt-in: distill a general candidate atom for the knowledge oracle (never raises).
    if (os.environ.get("ORACLE_ENABLED", "1") != "0"
            and os.environ.get("ORACLE_DISTILL", "0") == "1"):
        try:
            from .oracle import KnowledgeOracle
            KnowledgeOracle().distill(
                design_intent=getattr(design, "intent", ""),
                error=error or "",
                script_code=script_code or "",
                source_task=task_id,
            )
        except Exception as e:
            print(f"{CLI_YELLOW}[pipeline] oracle distill skipped: {e}{CLI_CLR}")


# ---------------------------------------------------------------------------
# Interpreted-path LEARN seam + artifact persistence
# ---------------------------------------------------------------------------

def _ilearn(task_id, learn_ctx, intent, plan_text, error, observed=None):
    """LEARN seam for the interpreted path - reuses _learn_consolidate's LLM call.

    The interpreted path passes the IntentSpec JSON as the 'plan context' and the
    PlanIR JSON as the 'artifact'. The distilled rule still lands in data/learned/{tid}.yaml.
    """
    tk: dict = {}
    _learn_consolidate_text(task_id, learn_ctx,
                            plan_context=intent.model_dump_json(indent=2),
                            error=error, artifact=plan_text, token_out=tk, observed=observed)


def _persist_artifacts(task_id, intent, plan):
    heur = Path("data/heuristics"); heur.mkdir(parents=True, exist_ok=True)
    (heur / f"{task_id}.intent.json").write_text(intent.model_dump_json(indent=2), encoding="utf-8")
    (heur / f"{task_id}.plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Interpreted pipeline branch (INTERPRETER_ENABLED)
# ---------------------------------------------------------------------------

def _run_interpreted(vm, instruction: str, task_id: str, agents_md_text: str, facts) -> dict:
    """INTENT (frozen, retried) -> loop[ PLAN -> lint -> interpret -> verify ->
    answer-once ] with LEARN between cycles. Mirrors the spec's error->LEARN table.

    Returns the same metrics dict shape as run_pipeline. Calls vm.answer exactly once.
    """
    from .interpreter import InterpretError, interpret, lint_security_first
    from .reason import IntentError, PlanError, run_intent, run_plan
    from .verify import verify

    # The IR PLAN LLM must not inherit codegen-era learned rules: they reference the
    # old codegen surface (tool_plan/vm.answer/script/fidelity) and some bake literal
    # paths/ids, which sabotages grounding under per-run re-seeding. Start clean; the
    # interpreter self-corrects within a run via the per-cycle prev_error fed to run_plan
    # (and any IR-distilled rules accumulate in-memory across this run's cycles).
    learn_ctx: list = []
    total_in = total_out = 0

    def _accum(tk):
        nonlocal total_in, total_out
        total_in += int(tk.get("input", 0) or 0)
        total_out += int(tk.get("output", 0) or 0)

    oracle_atoms: list = []
    try:
        from .oracle import KnowledgeOracle
        oracle_atoms = KnowledgeOracle().retrieve(instruction)
    except Exception:
        pass

    # INTENT (frozen, retried on transient parse/empty)
    intent = None
    for _ in range(_DESIGN_MAX_ATTEMPTS):
        tk = {}
        try:
            intent = run_intent(facts, instruction, token_out=tk); _accum(tk); break
        except IntentError:
            _accum(tk)
    if intent is None:
        save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", 0)
        _terminal_clarification(vm, "INTENT failed")
        return {"cycles_used": 0, "outcome": "OUTCOME_NONE_CLARIFICATION",
                "status": "failure", "input_tokens": total_in, "output_tokens": total_out}

    last_error = None
    cycle = 0
    for cycle in range(1, _MAX_STEPS + 1):
        set_cycle(cycle)
        print(f"{CLI_BLUE}[pipeline] interpreted cycle {cycle}/{_MAX_STEPS}{CLI_CLR}")
        tk = {}
        plan = None
        try:
            plan = run_plan(intent, facts, learn_ctx, last_error,
                            token_out=tk, oracle_atoms=oracle_atoms); _accum(tk)
            lint_security_first(plan)
        except (PlanError, InterpretError) as e:
            last_error = f"plan: {e}"; _accum(tk)
            _ilearn(task_id, learn_ctx, intent,
                    plan.model_dump_json() if plan is not None else "", last_error)
            continue

        try:
            result = interpret(plan, intent, vm, facts)
        except InterpretError as e:
            last_error = f"interpret: {e}"
            _ilearn(task_id, learn_ctx, intent, plan.model_dump_json(), last_error,
                    observed=None)
            if getattr(e, "mutation_landed", False):
                break
            continue
        except Exception as e:                                   # real-VM exception
            last_error = f"real_vm: {e}"
            _ilearn(task_id, learn_ctx, intent, plan.model_dump_json(), last_error)
            # A mutating plan may have landed a Write/Delete/bin-mutation before the
            # raise - retry only when the plan is read-only (mirrors legacy has_mutations).
            plan_mutates = any(
                op.rpc in {"Write", "Delete"}
                or (op.rpc == "Exec" and str(op.args.get("path", "")).startswith("/bin/")
                    and op.args.get("path") != "/bin/sql")
                for op in plan.ops
            )
            if _is_retryable_vm_error(str(e)) and not plan_mutates:
                continue
            break

        ok, verr = verify(result, intent)
        if ok:
            ans = result.captured
            refs = _ground_security_refs(ans.outcome, list(ans.refs))
            vm.answer(message=ans.message[:800], outcome=ans.outcome, refs=refs)
            _persist_artifacts(task_id, intent, plan)
            status = "success" if ans.outcome == "OUTCOME_OK" else "failure"
            save_last_run(task_id, status, ans.outcome, cycle)
            return {"cycles_used": cycle, "outcome": ans.outcome, "status": status,
                    "input_tokens": total_in, "output_tokens": total_out,
                    "answer_message": ans.message, "answer_refs": refs}

        last_error = f"verify: {verr}"
        print(f"{CLI_YELLOW}[pipeline] verify fail: {verr[:160]}{CLI_CLR}")
        if result.mutation_landed:
            break
        _ilearn(task_id, learn_ctx, intent, plan.model_dump_json(), last_error,
                observed=result.observations)

    save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", cycle)
    _terminal_clarification(vm, last_error or "interpreter cycles exhausted")
    return {"cycles_used": cycle, "outcome": "OUTCOME_NONE_CLARIFICATION",
            "status": "failure", "input_tokens": total_in, "output_tokens": total_out}


# ---------------------------------------------------------------------------
# Post-trial LEARN — grader feedback distilled via the same LEARN pipeline
# ---------------------------------------------------------------------------

def learn_from_grader(
    task_id: str,
    score_detail: list[str],
    token_out: dict | None = None,
) -> bool:
    """Distill a LEARN rule from grader-side feedback for the next training cycle.

    Loads the DesignOutput + script_code persisted by the prior pipeline run
    (in data/heuristics/{tid}.*) and reuses `_learn_consolidate`. Returns
    True if a LEARN call was made, False if persisted state was unavailable.

    The pipeline cannot see grader feedback during a trial (the score
    arrives only on SubmitRun). This helper is the seam that lets a training
    loop in main.py feed grader output back into learned_store.
    """
    if not task_id or not score_detail:
        return False
    heur_dir = Path("data/heuristics")
    ir_intent = heur_dir / f"{task_id}.intent.json"
    ir_plan = heur_dir / f"{task_id}.plan.json"
    if ir_intent.exists() and ir_plan.exists():
        learn_ctx = load_entries(task_id)
        error = "grader: " + " | ".join(s.strip() for s in score_detail if s.strip())
        _learn_consolidate_text(
            task_id, learn_ctx,
            plan_context=ir_intent.read_text(encoding="utf-8"),
            error=error, artifact=ir_plan.read_text(encoding="utf-8"),
            token_out=token_out,
        )
        return True
    script_path = heur_dir / f"{task_id}.py"
    design_path = heur_dir / f"{task_id}.design.json"
    if not script_path.exists() or not design_path.exists():
        return False
    try:
        design = DesignOutput.model_validate_json(
            design_path.read_text(encoding="utf-8")
        )
    except Exception:
        return False
    script_code = script_path.read_text(encoding="utf-8")
    learn_ctx = load_entries(task_id)
    error = "grader: " + " | ".join(s.strip() for s in score_detail if s.strip())
    _learn_consolidate(task_id, learn_ctx, design, error, script_code, token_out=token_out)
    return True


# ---------------------------------------------------------------------------
# Context compaction — bound learn_ctx growth in-memory (YAML untouched)
# ---------------------------------------------------------------------------

def _compact_learn_ctx(
    learn_ctx: list[dict],
    token_out: dict | None = None,
) -> list[dict]:
    """Summarize older learn_ctx entries via one LLM call when the list grows
    past COMPACTION_THRESHOLD. In-memory only — the YAML store is never
    rewritten, so each run compacts fresh from the full stored list. On empty
    or failed LLM response, return the input unchanged (green tasks must not
    regress)."""
    threshold = int(os.environ.get("COMPACTION_THRESHOLD", "15"))
    keep_recent = max(1, int(os.environ.get("COMPACTION_KEEP_RECENT", "5")))
    if len(learn_ctx) <= threshold:
        return learn_ctx

    older = learn_ctx[:-keep_recent]
    recent = learn_ctx[-keep_recent:]

    guide = load_prompt("compact") or "# PHASE: COMPACT"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]
    user_msg = "\n".join(_format_entry(e) for e in older)

    model = _resolve_model_for_phase("learn", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_LEARN, token_out=token_out, phase="COMPACTION")
    summary = (raw or "").strip()
    if not summary:
        print(f"{CLI_YELLOW}[pipeline] compaction: empty response, keeping full ctx{CLI_CLR}")
        return learn_ctx

    print(f"{CLI_BLUE}[pipeline] compacted {len(older)} entries → 1 summary{CLI_CLR}")
    return [{"id": "compacted", "content": summary, "source": "compaction"}] + recent


# ---------------------------------------------------------------------------
# Terminal exits — exactly one vm.answer() per task
# ---------------------------------------------------------------------------

def _terminal_clarification(vm, message: str) -> None:
    vm.answer(message=message[:800], outcome="OUTCOME_NONE_CLARIFICATION", refs=[])


# AGENTS.MD: "When you apply a policy from `docs`, include that policy document
# as a grounding reference in the final response." A security denial always
# applies /docs/security.md, so the grader requires it in refs even for refusals.
_SECURITY_POLICY_REF = "/docs/security.md"


def _ground_security_refs(outcome: str, refs: list[str]) -> list[str]:
    """Guarantee a DENIED_SECURITY answer cites the security policy it applied."""
    if outcome == "OUTCOME_DENIED_SECURITY" and _SECURITY_POLICY_REF not in refs:
        return [*refs, _SECURITY_POLICY_REF]
    return refs


def _terminal_outcome_override(vm, design: DesignOutput) -> None:
    vm.answer(
        message=design.answer_template.message,
        outcome=design.outcome_override,
        refs=_ground_security_refs(design.outcome_override or "", list(design.answer_template.refs)),
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
# AnswerGuard — refs pre-check before real vm.answer
# ---------------------------------------------------------------------------

# Phrases in success_criteria / agents_md_constraints that imply the answer
# must cite a runtime-discovered path (a record_path-style grounding ref).
_RUNTIME_REF_HINT_RE = re.compile(
    r"\b(reference|full path|grounding|file path|path to|object path|"
    r"matched row|matched product|matched file|catalog (file|path|entry))\b",
    re.IGNORECASE,
)


def _demands_runtime_ref(design: DesignOutput) -> bool:
    """True if the task requires a runtime-bound (record_path-style) ref.

    Sources, in order: a `$`-placeholder in answer_template.refs, or a ref-hint
    phrase in success_criteria / agents_md_constraints. Shared by `_AnswerGuard`
    and `_detect_zero_row_miss` so both agree on what "needs grounding" means.
    """
    template_refs = list(design.answer_template.refs or [])
    if any(isinstance(r, str) and "$" in r for r in template_refs):
        return True
    if any(_RUNTIME_REF_HINT_RE.search(s or "") for s in design.success_criteria):
        return True
    return any(
        _RUNTIME_REF_HINT_RE.search(c.rule or "") for c in design.agents_md_constraints
    )


def _detect_zero_row_miss(
    design: DesignOutput, sql_results: list[str], answer: dict
) -> str | None:
    """Catch a `<NO>`/un-grounded OK answer backed by 0 data rows from /bin/sql.

    For lookup tasks the seeded product exists, so the only correct answer is
    `<YES>` + record_path. When a discovery /bin/sql returns header-only output
    (0 data rows), the script emits `<NO>` with no runtime ref — today silently
    accepted via the negative-answer escape, then failed by the grader. Turn it
    into a precise red signal so LEARN/CODEGEN can reshape the binding/predicates.

    Returns an error string when ALL hold, else None:
      - outcome is OUTCOME_OK;
      - task demands a runtime ref (`_demands_runtime_ref`);
      - actual refs carry no non-static (runtime) entry;
      - at least one /bin/sql ran and EVERY result has 0 data rows.
    """
    if answer.get("outcome") != "OUTCOME_OK":
        return None
    if not _demands_runtime_ref(design):
        return None

    template_refs = list(design.answer_template.refs or [])
    static_template = {r for r in template_refs if isinstance(r, str) and "$" not in r}
    refs_list = list(answer.get("refs") or [])
    has_runtime_ref = any(r not in static_template for r in refs_list)
    if has_runtime_ref:
        return None

    # /bin/sql emits CSV with a leading column-name header row; data_rows =
    # non-empty lines minus that header. No query at all → cannot conclude.
    if not sql_results:
        return None
    max_data_rows = max(
        max(len([ln for ln in (s or "").splitlines() if ln.strip()]) - 1, 0)
        for s in sql_results
    )
    if max_data_rows > 0:
        return None

    return (
        "zero_row_miss: discovery /bin/sql returned header-only (0 data rows) on "
        "real VM while the answer is <NO>/un-grounded, but the task requires a "
        "runtime record_path ref — :name bindings likely unbound or predicates "
        "too strict; the product may exist. Reshape the SQL binding/predicates "
        "so the query returns the matching row."
    )


class _AnswerRefsError(RuntimeError):
    """Raised when the script's vm.answer call has invalid refs.

    Grader-side feedback ('answer missing required reference') is not visible
    to the pipeline. This guard catches the precursor — unresolved `$name`
    placeholders or empty refs when the template demanded runtime-bound refs —
    so LEARN can react before the trial closes.
    """


class _AnswerGuard:
    """Proxy passing all RPCs through to `_vm` while intercepting `answer`.

    Also captures the head of each RPC stdout into `self.observed` so the
    next LEARN cycle can see WHY refs were empty (table missing? column
    wrong? search returned nothing?). Without this, LEARN sees only the
    guard error string and writes the same rule each cycle.
    """

    _OBS_PER_CALL = 800
    _OBS_TOTAL_MAX = 8000

    # rpc method name -> (MockVMSpy-compatible RPC label, kwarg used as the
    # fixture-key "path"). tree/find/search key on `root`, not `path`.
    _FIXTURE_KEY_FIELD = {
        "read": ("Read", "path"), "list": ("List", "path"),
        "tree": ("Tree", "root"), "find": ("Find", "root"),
        "search": ("Search", "root"), "exec": ("Exec", "path"),
        "stat": ("Stat", "path"), "write": ("Write", "path"),
        "delete": ("Delete", "path"),
    }

    def __init__(self, vm, design: DesignOutput, defer_submit: bool = False):
        self._vm = vm
        self._design = design
        # When True, `answer` validates + captures but does NOT call the real
        # vm.answer — the pipeline submits explicitly via `submit()` only after
        # intent-tests pass. Keeps the terminal one-shot answer behind the gate.
        self._defer_submit = defer_submit
        self.observed: list[str] = []
        self._observed_total = 0
        self.actual_outcome: str = ""
        self._captured: dict = {}
        # fixture_key(...) -> raw RPC result, replayable by MockVMSpy for the
        # SAME script next cycle. sql_results: /bin/sql Exec stdouts in call order.
        self.fixtures: dict = {}
        self.sql_results: list[str] = []

    @staticmethod
    def _extract_payload(result) -> str:
        stdout = getattr(result, "stdout", None)
        if stdout is None and isinstance(result, dict):
            stdout = result.get("stdout", "")
        content = getattr(result, "content", None)
        if content is None and isinstance(result, dict):
            content = result.get("content", "")
        return (stdout or content or "").strip()

    def _capture_fixture(self, rpc: str, kwargs: dict, result) -> None:
        """Key the raw result so MockVMSpy can replay the SAME script next cycle,
        and collect /bin/sql stdouts in call order for test_sql(results=...)."""
        label_field = self._FIXTURE_KEY_FIELD.get(rpc)
        if not label_field:
            return
        label, path_kw = label_field
        path_val = kwargs.get(path_kw, "") or ""
        args_val = list(kwargs.get("args") or []) if rpc == "exec" else None
        self.fixtures[fixture_key(label, path_val, args_val)] = result
        if rpc == "exec" and path_val == "/bin/sql":
            self.sql_results.append(self._extract_payload(result))

    def _record(self, rpc: str, kwargs: dict, result) -> None:
        if self._observed_total >= self._OBS_TOTAL_MAX:
            return
        payload = self._extract_payload(result)
        if not payload:
            payload = "<empty>"
        head = payload[: self._OBS_PER_CALL]
        # show what was called so LEARN can map output back to plan step
        key_args = {k: v for k, v in kwargs.items() if k in ("path", "root", "pattern", "stdin", "args")}
        entry = f"[{rpc} {key_args}] {head}"
        self.observed.append(entry)
        self._observed_total += len(entry)

    def _wrap(self, rpc: str):
        method = getattr(self._vm, rpc)

        def _call(**kwargs):
            result = method(**kwargs)
            try:
                self._record(rpc, kwargs, result)
                self._capture_fixture(rpc, kwargs, result)
            except Exception:
                pass
            return result

        return _call

    def __getattr__(self, name):
        if name in ("read", "list", "tree", "find", "search", "exec", "stat", "write", "delete"):
            return self._wrap(name)
        return getattr(self._vm, name)

    def answer(self, *, message: str, outcome: str, refs=None) -> None:
        refs_list = list(refs or [])
        self.actual_outcome = outcome
        template_refs = list(self._design.answer_template.refs or [])
        static_template = {
            r for r in template_refs if isinstance(r, str) and "$" not in r
        }
        runtime_placeholders = [
            r for r in template_refs if isinstance(r, str) and "$" in r
        ]

        for r in refs_list:
            if isinstance(r, str) and r.startswith("$"):
                raise _AnswerRefsError(
                    f"unresolved placeholder {r!r} in refs — "
                    "bind runtime value from a discovery/op result"
                )

        # Static template refs are grader requirements — DESIGN listed them
        # because AGENTS.MD/instruction demands citation (e.g. /docs/security.md
        # for DENIED, /docs/checkout.md for UNSUPPORTED). Must appear in actual
        # refs regardless of outcome. CLARIFICATION is the only legitimate
        # path where refs can be dropped (script gave up before discovery).
        missing_static = static_template - set(refs_list)
        if missing_static and outcome != "OUTCOME_NONE_CLARIFICATION":
            raise _AnswerRefsError(
                f"missing static template refs {sorted(missing_static)!r}; "
                f"actual refs {refs_list!r}. Static refs are grader-required "
                "citations — always pass them through."
            )

        # Non-OK outcomes (UNSUPPORTED/CLARIFICATION/DENIED) are legitimate
        # escape paths — pipeline cannot tell whether the script's verdict
        # matches grader expectation. Pass through; grader feedback drives
        # LEARN via `learn_from_grader` between training cycles.
        if outcome != "OUTCOME_OK":
            refs_list = _ground_security_refs(outcome, refs_list)
            self._emit(message, outcome, refs_list)
            return

        # Safety net: even if the template forgot a $placeholder, the
        # DESIGN's own success_criteria / agents_md_constraints may demand
        # a runtime reference. Infer the demand from those fields.
        demands_runtime = _demands_runtime_ref(self._design)

        # A negative yes/no answer (<NO>) legitimately cites nothing — AGENTS.MD:
        # "should not reference unavailable products". The empty-refs demand only
        # applies when the answer asserts a match. Without this, a correct <NO>
        # (no matching row) loops on answer_refs until the cycle budget exhausts
        # and degrades to CLARIFICATION (t02).
        negative_answer = "<NO>" in (message or "") and "<YES>" not in (message or "")

        if demands_runtime and not negative_answer:
            non_static = [r for r in refs_list if r not in static_template]
            if not non_static:
                hint = (
                    f"({runtime_placeholders!r})" if runtime_placeholders
                    else "(inferred from success_criteria/agents_md_constraints)"
                )
                raise _AnswerRefsError(
                    f"template/constraints require runtime refs {hint} but "
                    f"actual refs {refs_list!r} contain only static template "
                    f"entries {sorted(static_template)!r} — SQL likely returned "
                    "no rows or row parsing dropped the path column; "
                    "check `:name` bindings on /bin/sql and the SELECT columns"
                )

        self._emit(message, outcome, refs_list)

    def _emit(self, message: str, outcome: str, refs_list: list) -> None:
        """Capture the answer; submit to the real VM now unless deferred."""
        self._captured = {"message": message, "outcome": outcome, "refs": refs_list}
        if not self._defer_submit:
            self._vm.answer(message=message, outcome=outcome, refs=refs_list)

    def submit(self) -> bool:
        """Flush a deferred captured answer to the real VM. Returns True if sent."""
        if not self._captured:
            return False
        self._vm.answer(**self._captured)
        return True


# ---------------------------------------------------------------------------
# Intent-driven test gate (TDD_ENABLED)
# ---------------------------------------------------------------------------

def _run_intent_tests(
    test_spec: TestSpec,
    sql_results: list[str],
    answer: dict,
    task_text: str = "",
) -> tuple[bool, str]:
    """Run test_sql + test_answer against captured runtime data via test_runner.

    Returns (passed, error). `answer` carries {message, outcome, refs}; a
    `grounding_refs` alias is added for back-compat with older-style asserts.
    """
    answer_ctx = dict(answer)
    answer_ctx.setdefault("grounding_refs", answer_ctx.get("refs", []))

    sql_ok, sql_err, sql_warns = run_tests(
        test_spec.sql_tests, "test_sql", {"results": sql_results},
        task_text=task_text,
    )
    for w in sql_warns:
        print(f"{CLI_YELLOW}[tdd] test_sql warning: {w}{CLI_CLR}")
    if not sql_ok:
        return False, f"test_sql: {sql_err}"

    ans_ok, ans_err, ans_warns = run_tests(
        test_spec.answer_tests, "test_answer",
        {"sql_results": sql_results, "answer": answer_ctx},
        task_text=task_text,
    )
    for w in ans_warns:
        print(f"{CLI_YELLOW}[tdd] test_answer warning: {w}{CLI_CLR}")
    if not ans_ok:
        return False, f"test_answer: {ans_err}"
    return True, ""


def _mock_run(script_code: str, params: dict, fixtures: dict) -> tuple[dict, list[str]]:
    """Replay the script against MockVMSpy(fixtures), returning (answer, sql_results).

    Used by the optional in-loop fail-fast gate. `fixtures` come from the prior
    cycle's real run (empty on cycle 1 → empty answer → expected-red). No refs
    validation here — this only feeds the intent-tests."""
    spy = MockVMSpy(fixtures=fixtures)
    _run_script_on_vm(script_code, spy, params)
    answer: dict = {}
    sql_results: list[str] = []
    for rpc, kw in spy.calls:
        if rpc == "Exec" and kw.get("path") == "/bin/sql":
            res = spy._lookup("Exec", "/bin/sql", kw.get("args"))
            sql_results.append(_AnswerGuard._extract_payload(res))
        elif rpc == "Answer":
            answer = {
                "message": kw.get("message", ""),
                "outcome": kw.get("outcome", ""),
                "refs": list(kw.get("refs") or []),
            }
    return answer, sql_results


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_pipeline(
    vm,
    instruction: str,
    task_id: str,
    agents_md_text: str,
    facts=None,
) -> dict:
    """Per-task pipeline. Exactly one vm.answer() call before returning.

    Returns metrics dict: {cycles_used, outcome, status}.
    """
    # main.py already emits log_header for this task; pipeline doesn't re-emit.
    learn_ctx = load_entries(task_id)

    # Deterministic Plan-IR interpreter path (read flag fresh so test setenv works).
    if os.environ.get("INTERPRETER_ENABLED", "0") == "1":
        return _run_interpreted(vm, instruction, task_id, agents_md_text, facts)

    total_in = 0
    total_out = 0

    def _accum(tk: dict) -> None:
        nonlocal total_in, total_out
        total_in += int(tk.get("input", 0) or 0)
        total_out += int(tk.get("output", 0) or 0)

    _tk_compact: dict = {}
    learn_ctx = _compact_learn_ctx(learn_ctx, token_out=_tk_compact)
    _accum(_tk_compact)
    print(f"{CLI_BLUE}[pipeline] task={task_id} active_rules={len(learn_ctx)}{CLI_CLR}")

    # Knowledge oracle: retrieve validated general atoms (augments per-task learn_ctx).
    oracle_atoms: list = []
    try:
        from .oracle import KnowledgeOracle
        oracle_atoms = KnowledgeOracle().retrieve(instruction)
        if oracle_atoms:
            print(f"{CLI_BLUE}[pipeline] oracle retrieved {len(oracle_atoms)} atom(s): "
                  f"{[a.id for a in oracle_atoms]}{CLI_CLR}")
    except Exception as e:  # oracle must never break the pipeline
        print(f"{CLI_YELLOW}[pipeline] oracle retrieve skipped: {e}{CLI_CLR}")

    # ── DESIGN ──────────────────────────────────────────────────────────────
    # DESIGN is a single frozen call, but the CC subprocess tier intermittently
    # truncates/empties its JSON (SIGTERM exit=143 under load), so a parse/empty
    # DesignError here is usually transient. Retry the call a few times before
    # giving up — far cheaper than losing the whole training pass to one flake.
    design = None
    design_err: DesignError | None = None
    _tk: dict = {}
    for _design_attempt in range(_DESIGN_MAX_ATTEMPTS):
        _tk = {}
        try:
            design = run_design(instruction, agents_md_text, token_out=_tk,
                                oracle_atoms=oracle_atoms)
            _accum(_tk)
            break
        except DesignError as e:
            design_err = e
            _accum(_tk)
            if _design_attempt + 1 < _DESIGN_MAX_ATTEMPTS:
                print(
                    f"{CLI_YELLOW}[pipeline] DESIGN parse/empty fail "
                    f"(attempt {_design_attempt + 1}/{_DESIGN_MAX_ATTEMPTS}), retrying: {e}{CLI_CLR}"
                )
    if design is None:
        print(f"{CLI_RED}[pipeline] DESIGN failed: {design_err}{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=0)
        _terminal_clarification(vm, f"DESIGN failed: {design_err}")
        return {
            "cycles_used": 0,
            "outcome": "OUTCOME_NONE_CLARIFICATION",
            "status": "failure",
            "input_tokens": total_in,
            "output_tokens": total_out,
        }

    if design.outcome_override:
        print(f"{CLI_YELLOW}[pipeline] outcome_override: {design.outcome_override}{CLI_CLR}")
        save_last_run(task_id, status="success", outcome=design.outcome_override, cycles_used=0)
        _terminal_outcome_override(vm, design)
        return {
            "cycles_used": 0,
            "outcome": design.outcome_override,
            "status": "success",
            "input_tokens": total_in,
            "output_tokens": total_out,
        }

    # Mutations make real-VM retry unsafe: if a Write/Delete already landed in
    # an earlier cycle we cannot re-run the script. Read-only ops (Exec, Read,
    # List, Tree, Find, Search, Stat) are idempotent for benchmark tasks, so
    # _AnswerRefsError is retryable then. Anything else → terminal.
    mutating_rpcs = {"Write", "Delete"}
    has_mutations = any(op.rpc in mutating_rpcs for op in design.ops)

    # ── TEST-GEN (intent-driven acceptance tests, frozen for the run) ──────
    # Generated once from DESIGN intent. Degrades gracefully: on TestGenError the
    # task falls back to fidelity-only (test_spec=None disables the gate).
    test_spec: TestSpec | None = None
    if _TDD_ENABLED:
        try:
            _tk = {}
            test_spec = run_test_gen(design, instruction, token_out=_tk)
            _accum(_tk)
            print(f"{CLI_BLUE}[pipeline] TEST-GEN ok (intent tests ready){CLI_CLR}")
        except TestGenError as e:
            print(f"{CLI_YELLOW}[pipeline] TEST-GEN failed, fidelity-only: {e}{CLI_CLR}")

    # ── CODEGEN+ANSWER retry loop (unified MAX_STEPS counter) ──────────────
    last_error: str | None = None
    prior_sql_sets: list[list[str]] = []
    cycle = 0  # bound for the post-loop branches when _MAX_STEPS < 1 is misconfigured
    answered = False
    actual_outcome = "OUTCOME_OK"
    guarded_vm: _AnswerGuard | None = None
    # TDD state: fixtures captured from the prior real run feed the mock fail-fast
    # gate; the fail counter drives force-submit so a bad test can't sink the task.
    prev_fixtures: dict = {}
    test_fail_streak = 0

    for cycle in range(1, _MAX_STEPS + 1):
        set_cycle(cycle)
        print(f"{CLI_BLUE}[pipeline] cycle {cycle}/{_MAX_STEPS}{CLI_CLR}")

        try:
            _tk = {}
            cg = run_codegen(design, learn_ctx, last_error, token_out=_tk, oracle_atoms=oracle_atoms)
            _accum(_tk)
        except CodegenError as e:
            last_error = f"codegen_llm_fail: {e}"
            print(f"{CLI_YELLOW}[pipeline] CODEGEN llm fail: {e}{CLI_CLR}")
            # Distil a LEARN rule so a weak model learns the output contract
            # (emit script_code as a plain field, not a fenced/escaped JSON blob).
            # No script parsed yet → the error string is the only signal.
            _tk = {}
            _learn_consolidate(task_id, learn_ctx, design, last_error, "", token_out=_tk)
            _accum(_tk)
            continue

        # Lint gate
        try:
            ast.parse(cg.script_code)
        except SyntaxError as e:
            last_error = f"lint: {e}"
            print(f"{CLI_YELLOW}[pipeline] lint fail: {e}{CLI_CLR}")
            _tk = {}
            _learn_consolidate(task_id, learn_ctx, design, last_error, cg.script_code, token_out=_tk)
            _accum(_tk)
            continue

        # check_retry_loop — anti-infinite-loop guard (HM4).
        # DESIGN is a starting point; CODEGEN reshapes through LEARN. Same SQL across
        # cycles is normal when the bug is elsewhere (shape, refs, lint). Break only
        # after 3 consecutive identical SQL multisets — gives LEARN 2 chances to refine.
        # _retry_guard_applies suppresses the break for SQL-orthogonal failures
        # (fidelity/lint/answer_refs): the SQL is correct and stable while the fix
        # lives elsewhere, so identical SQL is expected, not a stuck loop (t51).
        sqls = _extract_sql_literals(cg.script_code)
        if (
            _retry_guard_applies(last_error)
            and len(prior_sql_sets) >= 2
            and _identical_sql_set(sqls, prior_sql_sets[-1])
            and _identical_sql_set(prior_sql_sets[-1], prior_sql_sets[-2])
        ):
            print(f"{CLI_RED}[pipeline] check_retry_loop: 3rd identical SQL set, breaking{CLI_CLR}")
            last_error = last_error or "identical SQL set across 3 cycles"
            break
        prior_sql_sets.append(sqls)

        # Fidelity gate
        test_src = generate_fidelity_test(design, task_id)
        result = exec_fidelity_in_subprocess(test_src, cg.script_code, timeout_s=_FIDELITY_TIMEOUT_S)
        if not result.passed:
            last_error = f"fidelity: {result.error}"
            print(f"{CLI_YELLOW}[pipeline] fidelity fail: {result.error}{CLI_CLR}")
            _tk = {}
            _learn_consolidate(task_id, learn_ctx, design, last_error, cg.script_code, token_out=_tk)
            _accum(_tk)
            continue

        # Persist last-attempt script + design (consumed by learn_from_grader
        # for post-SubmitRun training cycles). Persist on every gate-pass so
        # the latest script is on disk even when ANSWER later fails.
        heur_dir = Path("data/heuristics")
        heur_dir.mkdir(parents=True, exist_ok=True)
        (heur_dir / f"{task_id}.py").write_text(cg.script_code, encoding="utf-8")
        (heur_dir / f"{task_id}.design.json").write_text(
            design.model_dump_json(indent=2), encoding="utf-8"
        )

        # ── Mock fail-fast gate (best-effort) ──────────────────────────────
        # Replay the script against fixtures captured from the PRIOR real run.
        # Catches an OK-outcome answer that fails the intent-test before spending
        # a real-VM pass. Only meaningful from cycle ≥2 (prev_fixtures populated)
        # and read-only plans; weak under RPC-shape reshape (fixture miss → skip).
        if (
            _TDD_ENABLED and _TDD_MOCK_ENABLED and test_spec is not None
            and not has_mutations and prev_fixtures
        ):
            try:
                m_answer, m_sql = _mock_run(cg.script_code, design.params, prev_fixtures)
                if m_answer.get("outcome") == "OUTCOME_OK":
                    m_ok, m_err = _run_intent_tests(test_spec, m_sql, m_answer, task_text=instruction)
                    if not m_ok:
                        last_error = f"mock_test: {m_err}"
                        print(f"{CLI_YELLOW}[pipeline] mock test fail-fast: {m_err[:120]}{CLI_CLR}")
                        _tk = {}
                        _learn_consolidate(task_id, learn_ctx, design, last_error, cg.script_code, token_out=_tk)
                        _accum(_tk)
                        continue
            except Exception as e:
                print(f"{CLI_YELLOW}[pipeline] mock gate skipped: {e}{CLI_CLR}")

        # ── ANSWER on real VM (guarded) ────────────────────────────────────
        # Real-VM exceptions and answer-refs gaps are the two failure categories
        # that bypass the in-loop gates. Without these hooks both classes vanish
        # after _terminal_clarification — next run starts blind. The guard also
        # captures stdouts so LEARN can see WHY refs were empty.
        tdd_active = _TDD_ENABLED and test_spec is not None
        guarded_vm = _AnswerGuard(vm, design, defer_submit=tdd_active)
        try:
            _run_script_on_vm(cg.script_code, guarded_vm, design.params)
        except _AnswerRefsError as e:
            last_error = f"answer_refs: {e}"
            print(f"{CLI_RED}[pipeline] answer refs check failed: {e}{CLI_CLR}")
            _tk = {}
            _learn_consolidate(
                task_id, learn_ctx, design, last_error, cg.script_code,
                token_out=_tk, observed=guarded_vm.observed,
            )
            _accum(_tk)
            if has_mutations:
                print(f"{CLI_RED}[pipeline] mutations in plan — refs retry unsafe, terminating{CLI_CLR}")
                break
            continue
        except Exception as e:
            # Deterministic input-validation failures (bad tool path, reading a
            # directory, missing file/record) and network transients surface from
            # the failing op itself — partial mutations BEFORE them are still
            # possible, so retry is only safe when the plan is read-only.
            is_retryable = _is_retryable_vm_error(str(e))
            last_error = f"real_vm_exec: {e}"
            print(f"{CLI_RED}[pipeline] real-vm exec failed: {e}{CLI_CLR}")
            _tk = {}
            _learn_consolidate(
                task_id, learn_ctx, design, last_error, cg.script_code,
                token_out=_tk, observed=guarded_vm.observed,
            )
            _accum(_tk)
            if is_retryable and not has_mutations:
                continue
            # Other real-VM exec errors can land mid-script (after partial
            # writes); never retry — break to terminal clarification.
            break

        # Script ran clean. Without TDD the answer was already submitted inline.
        actual_outcome = guarded_vm.actual_outcome or "OUTCOME_OK"
        if not tdd_active or test_spec is None:
            answered = True
            break

        # ── Intent-test gate (TDD) — answer captured, not yet submitted ────
        # Non-OK outcomes are explicit escape paths (CLARIFICATION/UNSUPPORTED/
        # DENIED) — submit directly; the intent-test targets OK answers only.
        if actual_outcome != "OUTCOME_OK":
            guarded_vm.submit()
            answered = True
            break

        # Deterministic precheck before the LLM intent test: a <NO>/un-grounded
        # OK answer backed by 0 data rows is a SQL miss, not a real negative —
        # the LLM test_sql can't tell (it passes on a header-only row). Feed the
        # precise signal to LEARN instead of submitting an answer the grader
        # will reject for a missing record_path ref (t02 root cause).
        zr_err = _detect_zero_row_miss(design, guarded_vm.sql_results, guarded_vm._captured)
        if zr_err:
            ok, err = False, zr_err
        else:
            ok, err = _run_intent_tests(
                test_spec, guarded_vm.sql_results, guarded_vm._captured, task_text=instruction
            )
        if ok:
            print(f"{CLI_GREEN}[pipeline] intent tests green — submitting{CLI_CLR}")
            guarded_vm.submit()
            answered = True
            break

        # Red. Distil a LEARN rule, seed mock fixtures, retry — unless force-submit.
        test_fail_streak += 1
        last_error = f"intent_test: {err}"
        print(f"{CLI_YELLOW}[pipeline] intent test fail ({test_fail_streak}): {err[:160]}{CLI_CLR}")
        _tk = {}
        _learn_consolidate(
            task_id, learn_ctx, design, last_error, cg.script_code,
            token_out=_tk, observed=guarded_vm.observed,
        )
        _accum(_tk)
        prev_fixtures = guarded_vm.fixtures
        # Mutations already landed → retry unsafe. Force-submit best captured.
        if has_mutations or test_fail_streak >= _TDD_FORCE_SUBMIT_AFTER:
            why = "mutations in plan" if has_mutations else f"{test_fail_streak} consecutive fails"
            print(f"{CLI_RED}[pipeline] force-submit best answer ({why}){CLI_CLR}")
            if guarded_vm.submit():   # False only if the script never called answer
                answered = True
            break
        continue

    # TDD exhausted the loop without a green answer, but a captured OK answer
    # exists (deferred, never submitted). Submitting it beats CLARIFICATION —
    # the script may be correct and the test merely strict (grader is truth).
    if (
        not answered and _TDD_ENABLED and guarded_vm is not None
        and guarded_vm._captured
        and guarded_vm._captured.get("outcome") == "OUTCOME_OK"
    ):
        print(f"{CLI_RED}[pipeline] loop exhausted — force-submit last captured OK answer{CLI_CLR}")
        guarded_vm.submit()
        answered = True
        actual_outcome = "OUTCOME_OK"

    if not answered:
        reason = (
            f"loop broken at cycle {cycle}/{_MAX_STEPS}"
            if cycle < _MAX_STEPS else f"exhausted {_MAX_STEPS} cycles"
        )
        print(f"{CLI_RED}[pipeline] {reason}: {last_error or 'no error'}{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=cycle)
        _terminal_clarification(vm, last_error or "all cycles exhausted")
        return {
            "cycles_used": cycle,
            "outcome": "OUTCOME_NONE_CLARIFICATION",
            "status": "failure",
            "input_tokens": total_in,
            "output_tokens": total_out,
        }

    status = "success" if actual_outcome == "OUTCOME_OK" else "failure"
    print(f"{CLI_GREEN}[pipeline] {status} after {cycle} cycle(s) outcome={actual_outcome}{CLI_CLR}")
    save_last_run(task_id, status=status, outcome=actual_outcome, cycles_used=cycle)
    captured = guarded_vm._captured if guarded_vm is not None else {}
    return {
        "cycles_used": cycle,
        "outcome": captured.get("outcome", actual_outcome),
        "status": status,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "answer_message": captured.get("message", ""),
        "answer_refs": captured.get("refs", []),
    }
