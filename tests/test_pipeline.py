import json
import threading
from unittest.mock import MagicMock, patch
import pytest
from agent.pipeline import run_pipeline
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt
from pathlib import Path


def _mock_assemble(*args, **kwargs):
    return AssembledPrompt(unified_context="mocked-unified-context")


def _make_pre(agents_md="AGENTS", db_schema="CREATE TABLE products(id INT, sku TEXT, path TEXT)"):
    return PrephaseResult(
        agents_md_content=agents_md,
        agents_md_path="/AGENTS.MD",
        db_schema=db_schema,
        task_type="sql",
    )


def _sdd_json(queries=None):
    plan = []
    for q in (queries or ["SELECT COUNT(*) FROM products WHERE type='Lawn Mower'"]):
        plan.append({"type": "sql", "description": "count", "query": q})
    return json.dumps({
        "reasoning": "products table has type column",
        "spec": "return count of Lawn Mowers",
        "plan": plan,
        "agents_md_refs": [],
    })


def _test_gen_json():
    return json.dumps({
        "reasoning": "count query",
        "sql_tests": "def test_sql(results):\n    assert results\n",
        "answer_tests": "def test_answer(sql_results, answer):\n    assert answer['outcome'] == 'OUTCOME_OK'\n",
    })


def _answer_json(outcome="OUTCOME_OK", message="<YES> 3 found"):
    return json.dumps({
        "reasoning": "SQL returned 3 rows",
        "message": message,
        "outcome": outcome,
        "grounding_refs": ["/proc/catalog/ABC-001.json"],
        "completed_steps": ["ran SQL", "found products"],
    })


def _make_exec_result(stdout='[{"count":3}]'):
    r = MagicMock()
    r.stdout = stdout
    return r


def test_happy_path(tmp_path):
    """SDD → SECURITY ok → TEST_GEN → EXECUTE ok → SQL_TEST pass → ANSWER ok → ANSWER_TEST pass."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result('[{"count": 3}]')

    pre = _make_pre()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    llm_seq = [_sdd_json(), _test_gen_json(), _answer_json()]
    call_iter = iter(llm_seq)

    with patch("agent.pipeline.call_llm_raw", side_effect=lambda *a, **kw: next(call_iter)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._RULES_DIR", rules_dir), \
         patch("agent.pipeline.load_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", return_value=None), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        stats, _thread = run_pipeline(vm, "anthropic/claude-sonnet-4-6", "How many Lawn Mowers?", pre, {})

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 1
    assert _thread is None


def test_schema_fail_triggers_learn_then_retry(tmp_path):
    """SDD → SCHEMA blocked → LEARN → retry SDD → success."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result('[{"count": 3}]')
    pre = _make_pre()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    learn_json = json.dumps({
        "reasoning": "r",
        "conclusion": "c",
        "rule_content": "use correct column name",
        "agents_md_anchor": None,
    })

    call_seq = [_sdd_json(), learn_json, _sdd_json(), _test_gen_json(), _answer_json()]
    call_iter = iter(call_seq)

    with patch("agent.pipeline.call_llm_raw", side_effect=lambda *a, **kw: next(call_iter)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._RULES_DIR", rules_dir), \
         patch("agent.pipeline.load_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", side_effect=[
             "SCHEMA: unknown column bad_col",  # cycle 1 fail
             None,                               # cycle 2 pass
         ]), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        stats, _ = run_pipeline(vm, "model", "task", pre, {})

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 2


def test_all_cycles_exhausted(tmp_path):
    """All cycles fail → clarification outcome, no eval_thread (EVAL_ENABLED=0)."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result("")  # empty result
    pre = _make_pre()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    learn_json = json.dumps({
        "reasoning": "r",
        "conclusion": "c",
        "rule_content": "rule",
        "agents_md_anchor": None,
    })

    import agent.pipeline as pl
    max_cycles = pl._MAX_CYCLES
    call_seq = []
    for _ in range(max_cycles):
        call_seq.append(_sdd_json())
        call_seq.append(_test_gen_json())
        call_seq.append(learn_json)  # VERIFY fails → LEARN
    call_iter = iter(call_seq)

    with patch("agent.pipeline.call_llm_raw", side_effect=lambda *a, **kw: next(call_iter)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._RULES_DIR", rules_dir), \
         patch("agent.pipeline.load_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", return_value=None), \
         patch("agent.pipeline.run_tests", return_value=(False, "test failed", [])):
        stats, eval_thread = run_pipeline(vm, "model", "task", pre, {}, task_id="t01")

    assert stats["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    assert eval_thread is None  # EVAL_ENABLED=0 in test env


def test_learn_ctx_accumulates(tmp_path):
    """learn_ctx grows across cycles; each SDD user_msg contains all prior rules."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result('[{"count": 3}]')
    pre = _make_pre()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    captured_user_msgs = []

    def fake_llm(system, user_msg, model, cfg, **kw):
        captured_user_msgs.append(user_msg)
        if len(captured_user_msgs) == 1:
            return _sdd_json()  # SDD cycle 1
        if len(captured_user_msgs) == 2:
            return json.dumps({"reasoning":"r","conclusion":"c","rule_content":"rule_A","agents_md_anchor":None})  # LEARN
        if len(captured_user_msgs) == 3:
            return _sdd_json()  # SDD cycle 2
        if len(captured_user_msgs) == 4:
            return _test_gen_json()  # TDD
        if len(captured_user_msgs) == 5:
            return _answer_json()  # ANSWER
        return None

    with patch("agent.pipeline.call_llm_raw", side_effect=fake_llm), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._RULES_DIR", rules_dir), \
         patch("agent.pipeline.load_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", side_effect=[
             "SCHEMA: bad column",  # cycle 1 blocked
             None,                  # cycle 2 pass
         ]), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        stats, _ = run_pipeline(vm, "model", "task", pre, {})

    # Third call is SDD cycle 2 — user_msg must contain accumulated rule
    sdd_cycle2_msg = captured_user_msgs[2]
    assert "ACCUMULATED RULES" in sdd_cycle2_msg
    assert "rule_A" in sdd_cycle2_msg


def test_learn_compaction_replaces_ctx(tmp_path):
    """When compacted_ctx is valid non-empty, learn_ctx is replaced in-place."""
    import json
    from unittest.mock import patch, MagicMock
    from agent.pipeline import run_pipeline

    vm = MagicMock()
    vm.exec.return_value = _make_exec_result('[{"count": 3}]')
    pre = _make_pre()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    learn_json = json.dumps({
        "reasoning": "found dupe",
        "conclusion": "two rules merged",
        "rule_content": "always use sku column",
        "agents_md_anchor": None,
        "compacted_ctx": ["always use sku column"],
    })

    call_seq = [_sdd_json(), learn_json, _sdd_json(), _test_gen_json(), _answer_json()]
    call_iter = iter(call_seq)

    with patch("agent.pipeline.call_llm_raw", side_effect=lambda *a, **kw: next(call_iter)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._RULES_DIR", rules_dir), \
         patch("agent.pipeline.load_security_gates", return_value=[]), \
         patch("agent.pipeline.check_schema_compliance", side_effect=[
             "SCHEMA: bad column", None,
         ]), \
         patch("agent.pipeline.run_tests", return_value=(True, None, [])):
        stats, _ = run_pipeline(vm, "model", "task", pre, {}, task_id="t_compact")

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 2


def test_learn_compaction_fallback_on_empty(tmp_path):
    """When compacted_ctx is [], _run_learn falls back to append."""
    import json
    from unittest.mock import patch
    from agent.pipeline import _run_learn

    learn_ctx: list[str] = ["existing rule"]
    learn_json = json.dumps({
        "reasoning": "r", "conclusion": "c", "rule_content": "new rule",
        "agents_md_anchor": None, "compacted_ctx": [],
    })

    with patch("agent.pipeline.call_llm_raw", return_value=learn_json), \
         patch("agent.pipeline.load_security_gates", return_value=[]):
        _run_learn("ctx", "model", {}, "task", [], "err", [], learn_ctx, {})

    assert learn_ctx == ["existing rule", "new rule"]


def test_learn_compaction_fallback_on_none(tmp_path):
    """When compacted_ctx is None, _run_learn falls back to append."""
    import json
    from unittest.mock import patch
    from agent.pipeline import _run_learn

    learn_ctx: list[str] = ["rule A", "rule B"]
    learn_json = json.dumps({
        "reasoning": "r", "conclusion": "c", "rule_content": "rule C",
        "agents_md_anchor": None, "compacted_ctx": None,
    })

    with patch("agent.pipeline.call_llm_raw", return_value=learn_json), \
         patch("agent.pipeline.load_security_gates", return_value=[]):
        _run_learn("ctx", "model", {}, "task", [], "err", [], learn_ctx, {})

    assert learn_ctx == ["rule A", "rule B", "rule C"]
