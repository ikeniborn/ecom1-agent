# tests/test_pipeline_interpreted.py
import json
from unittest.mock import MagicMock, patch
import pytest

from agent.pipeline import run_pipeline
from agent.mock_vm_spy import fixture_key


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        return next(it)
    return _next


_INTENT = json.dumps({
    "objective": "count", "desired_outcome": "int", "params": {},
    "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
    "constraints": [], "success_criteria": [],
    "answer_shape": {},
})
_PLAN = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 1 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "{row0.cnt}", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}},
    "custom_extract": [],
})


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    from agent import learned_store
    monkeypatch.setenv("INTERPRETER_ENABLED", "1")
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


def test_interpreted_happy_path_answers_once():
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(_INTENT, _PLAN)):
        m = run_pipeline(vm, instruction="how many", task_id="t_int", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"


def test_interpreted_genuine_verify_fail_via_success_criteria(monkeypatch):
    # Exercises the genuine verify() failure path: interpret() SUCCEEDS (no InterpretError)
    # then verify() returns (False, ...) because success_criteria[0] requires row0.cnt == "999"
    # but plan yields "5". Three cycles: interpret() resolves normally each time, verify() rejects
    # each time -> LEARN -> exhaust -> OUTCOME_NONE_CLARIFICATION. vm.answer called exactly once.
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 3)
    intent_no_runtime_req = json.dumps({
        "objective": "count", "desired_outcome": "int", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [],
        # success_criteria: row0.cnt must equal "999", but plan produces "5" -> always False
        "success_criteria": [{"op": "eq", "lhs": "$row0.cnt", "rhs": "999"}],
        "answer_shape": {},
    })
    learn = json.dumps({"rule_content": "cnt must be 999", "reasoning": "verify failed",
                        "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    # 1 INTENT + 3x(PLAN + LEARN)
    seq = [intent_no_runtime_req, _PLAN, learn, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="how many items", task_id="t_gvf", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"


def test_interpreted_verify_fail_then_learn_then_exhaust(monkeypatch):
    # Exercises the interpreter REFUSE-INVARIANT path (InterpretError), not verify():
    # answer_shape demands runtime ref but plan emits only a static ref -> InterpretError every cycle
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 3)
    intent_runtime = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [],
        "answer_shape": {},
        "required_refs": {"OUTCOME_OK": [{"kind": "record_path", "source": "$missing"}]},
    })
    learn = json.dumps({"rule_content": "Always bind a runtime $ref for OK answers",
                        "reasoning": "verify failed", "deactivate_ids": [], "skip": False})
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    # 1 INTENT + 3x(PLAN + LEARN)
    seq = [intent_runtime, _PLAN, learn, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="x", task_id="t_vf", agents_md_text="A")
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"


def test_interpreted_surfaces_all_active_learned_rules(monkeypatch, tmp_path):
    # Surface collapse (D5): ALL active rules (any surface) now reach the PLAN prompt.
    # _enabled autouse fixture already sets INTERPRETER_ENABLED + chdir + _LEARNED_DIR=tmp_path.
    import yaml as _yaml
    from agent import learned_store

    SENTINEL = "ALL_SURFACES_ACTIVE_RULE_ZZZ"
    (tmp_path / "t_iso.yaml").write_text(_yaml.safe_dump({
        "entries": [{"id": "r1", "active": True, "status": "active", "content": SENTINEL}],
        "last_run": {},
    }))

    captured = []

    def _rec(system, user, *a, **kw):
        captured.append(user)
        # first call → INTENT, subsequent → PLAN
        return _INTENT if len(captured) == 1 else _PLAN

    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_rec):
        run_pipeline(vm, instruction="x", task_id="t_iso", agents_md_text="A")

    assert captured, "no LLM calls captured"
    # After surface collapse, any active rule (regardless of surface tag) must appear in PLAN prompt.
    assert any(SENTINEL in u for u in captured), (
        "active learned rule missing from PLAN prompt after surface collapse"
    )


def test_ilearn_stamps_ir_surface_and_persists_deep_read():
    from agent import learned_store, pipeline
    from agent.ir_models import IntentSpec
    intent = IntentSpec(objective="o", desired_outcome="d", outcome_space=["OUTCOME_OK"],
                        answer_shape={})
    learn_json = json.dumps({
        "rule_content": "Always list the instruction-named directory before projecting refs",
        "reasoning": "missing ref", "deactivate_ids": [], "skip": False,
        "prephase_deep_read": ["/proc/incoming/payments"],
    })
    with patch("agent.pipeline.call_llm_raw", return_value=learn_json):
        pipeline._ilearn("t_ir", [], intent, "{}", "verify: missing ref", observed=["[List /x] a"])
    data = learned_store._read("t_ir")
    assert data["entries"][0]["surface"] == "ir"
    assert learned_store.load_prephase_deep_read("t_ir") == ["/proc/incoming/payments"]


def test_interpreter_seeds_all_active_rules_and_uses_imax(monkeypatch):
    from agent import learned_store, pipeline
    # Surface collapse (D5): ALL active rules reach run_plan's learn_ctx regardless of surface.
    learned_store._write("t_seed", {"task_id": "t_seed", "entries": [
        {"id": "r001", "content": "Always project the record_path ref", "status": "active", "surface": "ir"},
        {"id": "r002", "content": "codegen-era noise", "status": "active", "surface": "codegen"},
    ]})
    seen = {}

    def _capture_plan(intent, facts, learn_ctx, prev_error, **kw):
        seen["ctx"] = [e["id"] for e in learn_ctx]
        from agent.ir_models import PlanIR
        return PlanIR(**json.loads(_PLAN))

    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 2)
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(_INTENT)), \
         patch("agent.reason.run_plan", side_effect=_capture_plan):
        pipeline.run_pipeline(vm, instruction="how many", task_id="t_seed", agents_md_text="A")
    # After surface collapse both ir- and codegen-surface rules reach PLAN.
    assert set(seen["ctx"]) == {"r001", "r002"}


def test_interpreter_max_steps_default_and_override(monkeypatch):
    # Constants & budgets DoD: default AND one env override for _IMAX_STEPS.
    # Avoid reloading agent.pipeline (cross-module patched refs) — assert the module
    # default and that the same os.environ.get expression resolves the override.
    import os
    from agent import pipeline
    assert pipeline._IMAX_STEPS == 6                                  # default
    monkeypatch.setenv("ECOM_INTERPRETER_MAX_STEPS", "9")
    assert int(os.environ.get("ECOM_INTERPRETER_MAX_STEPS", "6")) == 9     # override resolves


def test_plan_signature_normalizes_sql_and_rpcs():
    from agent.pipeline import _plan_signature
    from agent.ir_models import PlanIR
    a = PlanIR(**json.loads(_PLAN))
    b = PlanIR(**json.loads(_PLAN.replace("SELECT 1 AS cnt", "select   1   AS   cnt")))
    assert _plan_signature(a) == _plan_signature(b)   # whitespace/case-insensitive


def test_interpreter_breaks_on_repeated_plan(monkeypatch):
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 5)
    # Same plan every cycle, but verify always fails -> 2nd identical sig breaks.
    intent = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [{"op": "eq", "lhs": "$row0.cnt", "rhs": "999"}],
        "answer_shape": {},
    })
    learn = json.dumps({"rule_content": "cnt must be 999 for this task type", "reasoning": "x",
                        "deactivate_ids": [], "skip": False})
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    # INTENT, then PLAN/LEARN pairs; the 2nd identical plan must break before exhausting 5 cycles.
    seq = [intent, _PLAN, learn, _PLAN, learn, _PLAN, learn, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="how many", task_id="t_rep", agents_md_text="A")
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    assert m["cycles_used"] <= 2          # broke on the 2nd identical signature


def test_plan_signature_differs_on_nonsql_arg():
    # Regression: two plans identical in SQL + RPC names but differing only in a
    # non-SQL step's path arg must produce DIFFERENT signatures so the identical-plan
    # guard does NOT false-fire and kill a legitimate re-plan (e.g. LEARN changed a
    # Read/List path). Variant is built by injecting a List discovery step at a
    # different path into an otherwise identical PlanIR.
    from agent.pipeline import _plan_signature
    from agent.ir_models import PlanIR

    base_dict = json.loads(_PLAN)

    # Add a List step with path="/proc/a" to the base plan's discovery.
    plan_a_dict = dict(base_dict)
    plan_a_dict["discovery"] = list(base_dict["discovery"]) + [
        {"rpc": "List", "args": {"path": "/proc/a"}}
    ]

    # Same structure but with path="/proc/b" — the only difference.
    plan_b_dict = dict(base_dict)
    plan_b_dict["discovery"] = list(base_dict["discovery"]) + [
        {"rpc": "List", "args": {"path": "/proc/b"}}
    ]

    a = PlanIR(**plan_a_dict)
    b = PlanIR(**plan_b_dict)
    assert _plan_signature(a) != _plan_signature(b), (
        "_plan_signature must distinguish plans that differ only in a non-SQL step arg"
    )


def test_plan_signature_includes_stdin_sql():
    from agent.pipeline import _plan_signature
    from agent.ir_models import PlanIR
    base = json.loads(_PLAN)
    a = dict(base); a["discovery"] = [{"rpc": "Exec",
        "args": {"path": "/bin/sql", "args": [], "stdin": "SELECT 1"}}]
    b = dict(base); b["discovery"] = [{"rpc": "Exec",
        "args": {"path": "/bin/sql", "args": [], "stdin": "SELECT 2"}}]
    assert _plan_signature(PlanIR(**a)) != _plan_signature(PlanIR(**b))


def test_answer_once_suppresses_second_answer():
    # F4: the first guarded answer lands vm.answer; any later answer is a no-op, so the
    # success path and a terminal can never both submit ("answer already provided").
    from agent.pipeline import _make_answer_once
    vm = MagicMock()
    ans = _make_answer_once(vm)
    assert ans("first", "OUTCOME_OK", ["/a"]) is True
    assert ans("second", "OUTCOME_NONE_CLARIFICATION", []) is False
    vm.answer.assert_called_once()
    _, kw = vm.answer.call_args
    assert kw["outcome"] == "OUTCOME_OK" and kw["message"] == "first"


def test_ok_with_unresolved_required_ref_never_submits_ok(monkeypatch):
    # F5 lock: an OUTCOME_OK whose required record_path ref cannot resolve must refuse
    # inside interpret (mutation_landed False) and route to CLARIFICATION — never submit a
    # broken OK. Locks F1-F4 against regressions.
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 2)
    intent = json.dumps({
        "objective": "o", "desired_outcome": "d", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"],
        "constraints": [], "success_criteria": [], "answer_shape": {},
        "required_refs": {"OUTCOME_OK": [{"kind": "record_path", "source": "$missing"}]},
    })
    learn = json.dumps({"rule_content": "Always bind the record_path ref for OK answers",
                        "reasoning": "x", "deactivate_ids": [], "skip": False})
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    seq = [intent, _PLAN, learn, _PLAN, learn]
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        m = run_pipeline(vm, instruction="x", task_id="t_f5", agents_md_text="A")
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    vm.answer.assert_called_once()
    assert vm.answer.call_args.kwargs["outcome"] != "OUTCOME_OK"


def test_empty_plan_skips_ilearn_and_breaks_early(monkeypatch):
    # Stability: an empty PLAN body carries nothing to learn from. The loop must NOT
    # fire iLEARN (a wasted LLM call) and must break to CLARIFICATION after
    # _EMPTY_PLAN_MAX consecutive empties instead of burning the whole cycle budget.
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 6)
    monkeypatch.setattr(pipeline, "_EMPTY_PLAN_MAX", 2)
    ilearn = MagicMock()
    monkeypatch.setattr(pipeline, "_ilearn", ilearn)
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    # 1 INTENT + 2 empty PLAN bodies; if iLEARN fired it would need another seq item.
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(_INTENT, "", "")):
        m = run_pipeline(vm, instruction="how many", task_id="t_empty", agents_md_text="A")
    ilearn.assert_not_called()
    assert m["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    assert m["cycles_used"] == 2          # broke at the 2nd empty, not at _IMAX_STEPS=6
    vm.answer.assert_called_once()
    assert vm.answer.call_args.kwargs["outcome"] != "OUTCOME_OK"


def test_single_empty_plan_recovers_on_next_cycle(monkeypatch):
    # A single transient empty PLAN must not kill the task: empty_streak resets when a
    # valid plan arrives, and the task answers OK normally.
    from agent import pipeline
    monkeypatch.setattr(pipeline, "_IMAX_STEPS", 6)
    monkeypatch.setattr(pipeline, "_EMPTY_PLAN_MAX", 2)
    vm = MagicMock(); vm.exec.return_value = {"stdout": "cnt\n5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(_INTENT, "", _PLAN)):
        m = run_pipeline(vm, instruction="how many", task_id="t_empty_ok", agents_md_text="A")
    assert m["outcome"] == "OUTCOME_OK"
    vm.answer.assert_called_once()


def test_learn_from_grader_consumes_ir_artifacts(tmp_path, monkeypatch):
    from agent import learned_store
    from agent.pipeline import learn_from_grader
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    heur = tmp_path / "data" / "heuristics"; heur.mkdir(parents=True, exist_ok=True)
    (heur / "t_ir.intent.json").write_text(_INTENT)
    (heur / "t_ir.plan.json").write_text(_PLAN)
    learn = json.dumps({"rule_content": "Always cite the record path in refs",
                        "reasoning": "grader said missing ref", "deactivate_ids": [], "skip": False})
    with patch("agent.pipeline.call_llm_raw", return_value=learn):
        made = learn_from_grader("t_ir", ["answer missing required reference"])
    assert made is True
    data = __import__("yaml").safe_load((tmp_path / "t_ir.yaml").read_text())
    assert any(e.get("content") for e in data["entries"])
