"""Plan-IR interpreter pipeline (INTENT → loop[PLAN → lint → interpret → verify → answer-once])."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from .json_extract import _extract_json_from_text
from .learned_store import _format_entry, apply_learn_diff, load_entries, save_last_run
from .llm import (
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_YELLOW,
    OUTCOME_BY_NAME, _resolve_model_for_phase, call_llm_raw,
)
from .oracle_validate import validate_atom_via_grader
from .models import LearnConsolidateOutput
from .prompt import load_prompt
from .trace import log_gate_auto, set_cycle
from .investigate import investigate, render_brief

_IMAX_STEPS = int(os.environ.get("ECOM_INTERPRETER_MAX_STEPS", "6"))
_MAX_TOKENS_LEARN = int(os.environ.get("ECOM_MAX_TOKENS_LEARN", "2048"))
# Retries for transient INTENT parse/empty failures (CC subprocess truncation).
_DESIGN_MAX_ATTEMPTS = int(os.environ.get("ECOM_DESIGN_MAX_ATTEMPTS", "3"))
# Consecutive empty-PLAN responses tolerated before breaking to CLARIFICATION.
# An empty body carries nothing to learn from, so these cycles skip iLEARN and
# must not silently consume the whole INTERPRETER_MAX_STEPS budget.
_EMPTY_PLAN_MAX = int(os.environ.get("ECOM_EMPTY_PLAN_MAX", "2"))
# Consecutive cycles failing with the SAME (normalized) error before breaking to
# CLARIFICATION. Complements the plan-signature guard: when iLEARN keeps tweaking the
# plan (so signatures differ) but the interpret/verify error is identical every cycle,
# the model is stuck — break early instead of burning the whole budget + iLEARN calls
# (e.g. an OK answer whose required record_path ref the SQL never selects).
_SAME_ERROR_MAX = int(os.environ.get("ECOM_SAME_ERROR_MAX", "3"))


def _norm_err(e: str) -> str:
    """Stable, volatility-trimmed error key for the consecutive-error guard."""
    return " ".join(str(e or "").split())[:120]


def _norm_sql(s: str) -> str:
    return " ".join(str(s).lower().split())


def _plan_signature(plan) -> tuple:
    """Per-step identity over discovery + ops: SQL is whitespace/case-normalized;
    non-SQL step args (paths, patterns, branches) are included verbatim so a re-plan
    that changes only a Read/List path is NOT mistaken for 'no progress'.

    Consecutive-identical signatures => the plan stopped changing (R4 short-circuit).
    Note: A<->B oscillation is not caught here (consecutive-only); the cycle ceiling
    bounds that case."""
    steps = list(plan.discovery) + list(plan.ops)
    parts: list[tuple] = []
    for st in steps:
        if st.rpc == "Exec" and str(st.args.get("path", "")) == "/bin/sql":
            sql_bits = list(st.args.get("args", []) or [])
            if st.args.get("stdin"):
                sql_bits.append(st.args.get("stdin"))
            normed = tuple(sorted(_norm_sql(a) for a in sql_bits))
            parts.append((st.rpc, normed))
        else:
            parts.append((st.rpc, repr(sorted(st.args.items()))))
    return tuple(parts)


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


def _enrich_prim_error(err: str) -> str:
    """Append the failed primitive's contract so the retry sees the spec, not just the
    symptom. Matches the runtime forms ("compute step 'X'", "primitive 'X'") and the lint
    forms ("compute 'X'", "'X' expects ..."). No-op when the message names no known
    primitive (contract() is empty for non-primitives, so a stray quoted word is safe)."""
    import re as _re
    from .primitives import contract
    m = _re.search(r"(?:compute(?: step)?|primitive) '([a-z_]+)'", err)
    prim = m.group(1) if m else None
    if prim is None:
        # lint primitive_contract messages lead with the quoted primitive, e.g.
        # "'column' expects list[dict]; use 'get'..." — first quoted token that is a primitive.
        for tok in _re.findall(r"'([a-z_]+)'", err):
            if contract(tok):
                prim = tok
                break
    if prim:
        c = contract(prim)
        if c and c not in err:
            return f"{err}\nCONTRACT: {c}"
    return err


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
    prompt_name: str = "learn",
    surface: str = "codegen",
) -> None:
    """Message-building core of LEARN, driven by already-rendered strings.

    `plan_context` is the rendered IntentSpec JSON; `artifact` is the rendered
    PlanIR JSON. Writes a diff to data/learned/{tid}.yaml and mutates learn_ctx
    in-place. `observed` carries RPC stdouts captured during the failed run so
    LEARN can see WHY refs were empty (table missing, column wrong, search
    returned nothing).
    """
    guide = load_prompt(prompt_name) or "# PHASE: LEARN"
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

    model = _resolve_model_for_phase("learn", os.environ.get("ECOM_MODEL", ""))
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

    apply_learn_diff(task_id, out, surface=surface)

    deep = getattr(out, "prephase_deep_read", None)
    if surface == "ir" and deep:
        from .learned_store import append_prephase_deep_read
        append_prephase_deep_read(task_id, deep)

    if not out.skip and out.rule_content:
        learn_ctx.append({
            "id": "in-session",
            "content": out.rule_content,
            "agents_md_anchor": out.agents_md_anchor,
            "surface": surface,
        })


# ---------------------------------------------------------------------------
# Interpreted-path LEARN seam + artifact persistence
# ---------------------------------------------------------------------------

def _ilearn(task_id, learn_ctx, intent, plan_text, error, observed=None):
    """LEARN seam for the interpreted path — uses the PlanIR-framed ilearn.md prompt,
    stamps surface='ir', and persists any prephase_deep_read hints."""
    tk: dict = {}
    _learn_consolidate_text(
        task_id, learn_ctx,
        plan_context=intent.model_dump_json(indent=2),
        error=error, artifact=plan_text, token_out=tk, observed=observed,
        prompt_name="ilearn", surface="ir",
    )


def _persist_artifacts(task_id, intent, plan):
    heur = Path("data/heuristics"); heur.mkdir(parents=True, exist_ok=True)
    (heur / f"{task_id}.intent.json").write_text(intent.model_dump_json(indent=2), encoding="utf-8")
    (heur / f"{task_id}.plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def _new_oracle():
    from .oracle import KnowledgeOracle
    return KnowledgeOracle()


def _brief_lessons_text(brief) -> str:
    """One-line-per-step lessons from an investigation brief, for distillation."""
    if brief is None or not getattr(brief, "notes", None):
        return ""
    return "\n".join(f"- {n.lesson}" for n in brief.notes if n.lesson)


def _distill_call(oracle, intent, plan, task_id, outcome_note):
    # `error` param is repurposed as a short success note; the distill prompt
    # strips all run-specific values, so a success note is fine (spec §Distill).
    return oracle.distill(design_intent=intent.objective,
                          error=outcome_note,
                          script_code=plan.model_dump_json(),
                          source_task=task_id)


def _maybe_distill_and_validate(intent, plan, task_id, outcome_note) -> None:
    """On a successful cycle, distill a candidate atom (ORACLE_DISTILL=1) and,
    when ORACLE_VALIDATE_INLINE=1, grader-validate then promote. Never raises."""
    if (os.environ.get("ECOM_ORACLE_ENABLED", "1") == "0"
            or os.environ.get("ECOM_ORACLE_DISTILL", "0") != "1"):
        return
    try:
        oracle = _new_oracle()
        atom = _distill_call(oracle, intent, plan, task_id, outcome_note)
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] oracle distill skipped: {e}{CLI_CLR}")
        return
    if not atom or os.environ.get("ECOM_ORACLE_VALIDATE_INLINE", "1") != "1":
        return
    try:
        if validate_atom_via_grader(atom, task_id, intent, plan):
            oracle.promote(atom.id, validated_by="grader-oracle",
                           validated_at=str(date.today()))
            print(f"{CLI_GREEN}[pipeline] atom {atom.id} promoted (grader-validated){CLI_CLR}")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] atom promote skipped: {e}{CLI_CLR}")


def distill_from_grader(task_id: str, score: float, score_detail: list[str]) -> None:
    """End-of-run self-fill: distill an ACTIVE polarity atom from the grader score.

    pass (score >= 1.0) -> 'method' atom (effective knowledge);
    fail (score < 1.0)  -> 'anti_pattern' atom (failure cause, steers away next run).

    Uses the score already returned by SubmitRun — NOT a live grader round-trip
    (ORACLE_VALIDATE_INLINE stays 0 by default). Never raises; the run result is
    unchanged if distill yields nothing. Reads the persisted IntentSpec + PlanIR.
    """
    if os.environ.get("ECOM_ORACLE_ENABLED", "1") == "0":
        return
    heur = Path("data/heuristics")
    ip, pp = heur / f"{task_id}.intent.json", heur / f"{task_id}.plan.json"
    if not (ip.exists() and pp.exists()):
        return
    try:
        from .ir_models import IntentSpec, PlanIR
        intent = IntentSpec.model_validate_json(ip.read_text(encoding="utf-8"))
        plan = PlanIR.model_validate_json(pp.read_text(encoding="utf-8"))
        if score >= 1.0:
            note, polarity = "effective method (grader score 1.0)", "method"
        else:
            detail = " | ".join(s.strip() for s in score_detail if s.strip())
            note, polarity = f"failure to avoid; grader: {detail}", "anti_pattern"
        oracle = _new_oracle()
        oracle.distill(design_intent=intent.objective, error=note,
                       script_code=plan.model_dump_json(), source_task=task_id,
                       polarity=polarity, status="active")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] distill_from_grader skipped: {e}{CLI_CLR}")


# ---------------------------------------------------------------------------
# Answer-once guard (F4) — exactly one vm.answer() per task
# ---------------------------------------------------------------------------

def _make_answer_once(vm):
    """Return a guarded answer fn (F4): the first call lands vm.answer; later calls are
    suppressed no-ops. Guarantees the success path and any terminal can never both submit
    — eliminates the 'answer already provided' dead-end. Returns True if it submitted."""
    state = {"answered": False}

    def _answer(message: str, outcome: str, refs: list) -> bool:
        if state["answered"]:
            print(f"{CLI_YELLOW}[pipeline] duplicate answer suppressed{CLI_CLR}")
            return False
        state["answered"] = True
        vm.answer(message=message[:800], outcome=outcome, refs=list(refs or []))
        return True

    return _answer


# ---------------------------------------------------------------------------
# F8b: gated distill -> validate -> promote hook
# ---------------------------------------------------------------------------

def _load_good_plan(task_id):
    """Last persisted successful PlanIR for this task (known-good), or None. Persisted
    only on a success path (_persist_artifacts), so it exists once the task has passed
    at least once — the false-positive reference for inline check validation."""
    pp = Path("data/heuristics") / f"{task_id}.plan.json"
    if not pp.exists():
        return None
    try:
        from .ir_models import PlanIR
        return PlanIR.model_validate_json(pp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _maybe_harness_distill(plan, error, task_id) -> None:
    """F8b (gated HARNESS_DISTILL=1, default 0): after an F1-class compute contract
    failure, propose a `candidate` check-spec. When HARNESS_VALIDATE_INLINE=1 (default),
    validate it — the candidate MUST flag this failing plan AND must NOT flag the last
    known-good plan — and promote (candidate -> active) on success; otherwise it stays a
    warn-only candidate for an offline promote. Never raises (cannot dead-end a run)."""
    if os.environ.get("ECOM_HARNESS_DISTILL", "0") != "1":
        return
    if "compute step" not in error and "custom_extract" not in error:
        return
    try:
        from . import harness
        candidate = harness.distill(plan, error, source_task=task_id)
        if not candidate or os.environ.get("ECOM_HARNESS_VALIDATE_INLINE", "1") != "1":
            return
        from .harness_validate import validate_check_via_grader
        if validate_check_via_grader(candidate, plan, _load_good_plan(task_id)):
            harness.promote(candidate["id"])
            print(f"{CLI_GREEN}[pipeline] check {candidate['id']} promoted (validated){CLI_CLR}")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] harness distill skipped: {e}{CLI_CLR}")


# ---------------------------------------------------------------------------
# Main entry — Plan-IR interpreter pipeline
# ---------------------------------------------------------------------------

def run_pipeline(vm, instruction: str, task_id: str, agents_md_text: str, facts=None) -> dict:
    """INTENT (frozen, retried) -> loop[ PLAN -> lint -> interpret -> verify ->
    answer-once ] with LEARN between cycles. Mirrors the spec's error->LEARN table.

    Per-task pipeline; calls vm.answer exactly once before returning a metrics
    dict: {cycles_used, outcome, status, input_tokens, output_tokens, ...}.
    """
    from .interpreter import InterpretError, interpret, lint, repair_sql_stdin
    from .reason import IntentError, PlanEmptyError, PlanError, run_intent, run_plan
    from .verify import verify

    # Surface collapse (D5): PLAN sees all active rules; the grader-feedback
    # training-mode bug self-heals because learn_from_grader writes the same store.
    learn_ctx: list = load_entries(task_id)
    total_in = total_out = 0
    answer_once = _make_answer_once(vm)

    def _accum(tk):
        nonlocal total_in, total_out
        total_in += int(tk.get("input", 0) or 0)
        total_out += int(tk.get("output", 0) or 0)

    _investigate_on = os.environ.get("ECOM_INVESTIGATE_ENABLED", "1") != "0"
    oracle_atoms: list = []
    _oracle = None
    try:
        _oracle = _new_oracle()
        if not _investigate_on:
            oracle_atoms = _oracle.retrieve(instruction)   # legacy whole-instruction dump
    except Exception:
        _oracle = None

    # INTENT (frozen, retried on transient parse/empty)
    intent = None
    for _ in range(_DESIGN_MAX_ATTEMPTS):
        tk = {}
        try:
            intent = run_intent(facts, instruction, token_out=tk, learn_ctx=learn_ctx); _accum(tk); break
        except IntentError:
            _accum(tk)
    if intent is None:
        save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", 0)
        answer_once("INTENT failed", "OUTCOME_NONE_CLARIFICATION", [])
        return {"cycles_used": 0, "outcome": "OUTCOME_NONE_CLARIFICATION",
                "status": "failure", "input_tokens": total_in, "output_tokens": total_out}

    # INVESTIGATE (read-only ReAct) — build a compact brief the PLAN consumes in place
    # of the front-loaded facts dump. Skipped (oracle dumped eagerly above) when off.
    brief = None                                  # kept in scope for the success-path distill (Task 11)
    brief_block = None
    if _investigate_on:
        try:
            brief = investigate(vm, intent, seed=facts, oracle=_oracle)
            brief_block = render_brief(brief) or None
        except Exception as e:                    # graceful: fall back to the slim seed facts
            print(f"{CLI_YELLOW}[pipeline] investigate failed, using seed facts: {e}{CLI_CLR}")
            brief = None
            brief_block = None

    last_error = None
    last_observed = None
    prev_sig = None
    empty_streak = 0
    err_streak = 0
    prev_err_norm = None

    def _stuck_on_same_error(err: str) -> bool:
        """Track consecutive identical (normalized) errors; True once the same one
        has recurred _SAME_ERROR_MAX times (the model is not making progress on it)."""
        nonlocal err_streak, prev_err_norm
        norm = _norm_err(err)
        if norm and norm == prev_err_norm:
            err_streak += 1
        else:
            err_streak = 1
            prev_err_norm = norm
        return err_streak >= _SAME_ERROR_MAX

    cycle = 0
    for cycle in range(1, _IMAX_STEPS + 1):
        set_cycle(cycle)
        print(f"{CLI_BLUE}[pipeline] interpreted cycle {cycle}/{_IMAX_STEPS}{CLI_CLR}")
        tk = {}
        plan = None
        try:
            plan = run_plan(intent, facts, learn_ctx, last_error,
                            token_out=tk, oracle_atoms=oracle_atoms,
                            observed=last_observed, brief_block=brief_block); _accum(tk)
            plan = repair_sql_stdin(plan)
            lint(plan)
        except PlanEmptyError as e:
            # Empty PLAN body: nothing to learn from. Skip iLEARN (it would also
            # see no plan and emit no rule — a wasted LLM call) and retry cheaply;
            # break early once the model keeps emitting nothing so we do not burn
            # the whole cycle budget on a stuck model.
            empty_streak += 1; _accum(tk)
            last_error = f"plan: {e}"
            print(f"{CLI_YELLOW}[pipeline] empty PLAN "
                  f"({empty_streak}/{_EMPTY_PLAN_MAX}){CLI_CLR}")
            if empty_streak >= _EMPTY_PLAN_MAX:
                print(f"{CLI_YELLOW}[pipeline] repeated empty PLAN -> CLARIFICATION{CLI_CLR}")
                break
            continue
        except (PlanError, InterpretError) as e:
            empty_streak = 0
            last_error = _enrich_prim_error(f"plan: {e}"); _accum(tk)
            log_gate_auto("LINT", False, last_error)
            _ilearn(task_id, learn_ctx, intent,
                    plan.model_dump_json() if plan is not None else "", last_error)
            if _stuck_on_same_error(last_error):
                print(f"{CLI_YELLOW}[pipeline] same plan error x{_SAME_ERROR_MAX} -> CLARIFICATION{CLI_CLR}")
                break
            continue
        empty_streak = 0
        log_gate_auto("LINT", True, "")

        sig = _plan_signature(plan)
        if sig == prev_sig:
            last_error = "identical plan repeated (no progress)"
            print(f"{CLI_YELLOW}[pipeline] identical plan repeated -> CLARIFICATION{CLI_CLR}")
            break
        prev_sig = sig

        try:
            result = interpret(plan, intent, vm, facts)
        except InterpretError as e:
            last_error = _enrich_prim_error(f"interpret: {e}")
            log_gate_auto("INTERPRET", False, last_error)
            _ilearn(task_id, learn_ctx, intent, plan.model_dump_json(), last_error,
                    observed=None)
            _maybe_harness_distill(plan, last_error, task_id)
            if getattr(e, "mutation_landed", False):
                break
            if _stuck_on_same_error(last_error):
                print(f"{CLI_YELLOW}[pipeline] same interpret error x{_SAME_ERROR_MAX} -> CLARIFICATION{CLI_CLR}")
                break
            continue
        except Exception as e:                                   # real-VM exception
            last_error = f"real_vm: {e}"
            log_gate_auto("INTERPRET", False, last_error)
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
                if _stuck_on_same_error(last_error):
                    print(f"{CLI_YELLOW}[pipeline] same real_vm error x{_SAME_ERROR_MAX} -> CLARIFICATION{CLI_CLR}")
                    break
                continue
            break

        log_gate_auto("INTERPRET", True, "")
        last_observed = result.observations
        ok, verr = verify(result, intent)
        log_gate_auto("VERIFY", ok, "" if ok else verr)
        if ok:
            ans = result.captured
            refs = _ground_security_refs(ans.outcome, list(ans.refs))
            answer_once(ans.message, ans.outcome, refs)
            _persist_artifacts(task_id, intent, plan)
            _note = f"OK: {verr or 'verify passed'}"
            _lessons = _brief_lessons_text(brief)
            if _lessons:
                _note = _note + "\nINVESTIGATION_LESSONS:\n" + _lessons
            _maybe_distill_and_validate(intent, plan, task_id, _note)
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
        if _stuck_on_same_error(last_error):
            print(f"{CLI_YELLOW}[pipeline] same verify fail x{_SAME_ERROR_MAX} -> CLARIFICATION{CLI_CLR}")
            break

    save_last_run(task_id, "failure", "OUTCOME_NONE_CLARIFICATION", cycle)
    answer_once(last_error or "interpreter cycles exhausted", "OUTCOME_NONE_CLARIFICATION", [])
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

    Loads the IntentSpec + PlanIR persisted by the prior pipeline run (in
    data/heuristics/{tid}.intent.json + {tid}.plan.json) and reuses the IR-framed
    LEARN call. Returns True if a LEARN call was made, False if persisted state
    was unavailable.

    The pipeline cannot see grader feedback during a trial (the score
    arrives only on SubmitRun). This helper is the seam that lets a training
    loop in main.py feed grader output back into learned_store.
    """
    if not task_id or not score_detail:
        return False
    heur_dir = Path("data/heuristics")
    ir_intent = heur_dir / f"{task_id}.intent.json"
    ir_plan = heur_dir / f"{task_id}.plan.json"
    if not (ir_intent.exists() and ir_plan.exists()):
        return False
    learn_ctx = load_entries(task_id)
    error = "grader: " + " | ".join(s.strip() for s in score_detail if s.strip())
    _learn_consolidate_text(
        task_id, learn_ctx,
        plan_context=ir_intent.read_text(encoding="utf-8"),
        error=error, artifact=ir_plan.read_text(encoding="utf-8"),
        token_out=token_out, prompt_name="ilearn", surface="ir",
    )
    return True


# AGENTS.MD: "When you apply a policy from `docs`, include that policy document
# as a grounding reference in the final response." A security denial always
# applies /docs/security.md, so the grader requires it in refs even for refusals.
_SECURITY_POLICY_REF = "/docs/security.md"


def _ground_security_refs(outcome: str, refs: list[str]) -> list[str]:
    """Guarantee a DENIED_SECURITY answer cites the security policy it applied."""
    if outcome == "OUTCOME_DENIED_SECURITY" and _SECURITY_POLICY_REF not in refs:
        return [*refs, _SECURITY_POLICY_REF]
    return refs
