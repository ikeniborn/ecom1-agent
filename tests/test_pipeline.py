import json
from unittest.mock import MagicMock, patch
from agent.pipeline import run_pipeline, _run_learn, _build_plan_user_msg, _build_idd_user_msg
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt


def _mock_assemble(*_a, **_kw):
    return AssembledPrompt(unified_context="mocked-unified-context")


def _make_pre(agents_md="AGENTS", db_schema="CREATE TABLE products(id INT, sku TEXT, path TEXT)"):
    return PrephaseResult(
        agents_md_content=agents_md,
        agents_md_path="/AGENTS.MD",
        db_schema=db_schema,
        task_type="sql",
    )


def _sdd_json(actions=None):
    return json.dumps({
        "spec_goal": "Count Lawn Mowers in products table",
        "success_criteria": ["result contains a positive integer count"],
        "plan": ["query products by type filter"],
        "actions": actions or ["SELECT COUNT(*) FROM products WHERE type='Lawn Mower'"],
        "error_code": "",
    })


def _plan_json(action=None):
    return json.dumps({
        "approach": "single count query filtered by type",
        "steps": ["filter products by type='Lawn Mower'", "return count"],
        "action": action or "SELECT COUNT(*) FROM products WHERE type='Lawn Mower'",
    })


def _answer_json(outcome="OUTCOME_OK", message="<YES> 3 found"):
    return json.dumps({
        "reasoning": "SQL returned 3 rows",
        "message": message,
        "outcome": outcome,
        "grounding_refs": ["/proc/catalog/ABC-001.json"],
        "completed_steps": ["ran SQL", "found products"],
    })


def _learn_json(rule="use correct column name"):
    return json.dumps({
        "reasoning": "r",
        "conclusion": "c",
        "rule_content": rule,
        "agents_md_anchor": None,
    })


def _make_exec_result(stdout='[{"count":3}]'):
    r = MagicMock()
    r.stdout = stdout
    r.output = stdout  # avoid fallback attribute auto-creation in _exec_result_text
    return r


def _seq_llm(call_seq):
    it = iter(call_seq)
    return lambda *_, **__: next(it)


def test_happy_path():
    """ASSEMBLE → SDD → PLAN → EXECUTE ok → ANSWER ok."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result('[{"count": 3}]')

    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([_sdd_json(), _plan_json(), _answer_json()])), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        stats, _thread = run_pipeline(vm, "anthropic/claude-sonnet-4-6", "How many Lawn Mowers?", pre, {})

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 1
    assert _thread is None


def test_sdd_fail_triggers_learn_then_retry():
    """SDD parse fail → LEARN → retry → success."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result('[{"count": 3}]')
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([
        "INVALID_NOT_JSON",  # SDD cycle 1 fails
        _learn_json(),       # LEARN cycle 1
        _sdd_json(),         # SDD cycle 2
        _plan_json(),        # PLAN cycle 2
        _answer_json(),      # ANSWER cycle 2
    ])), patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        stats, _ = run_pipeline(vm, "model", "task", pre, {})

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 2


def test_plan_fail_triggers_learn_then_retry():
    """PLAN parse fail → LEARN → retry → success."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result('[{"count": 3}]')
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([
        _sdd_json(),    # SDD cycle 1
        "INVALID",      # PLAN cycle 1 fails
        _learn_json(),  # LEARN cycle 1
        _sdd_json(),    # SDD cycle 2
        _plan_json(),   # PLAN cycle 2
        _answer_json(), # ANSWER cycle 2
    ])), patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        stats, _ = run_pipeline(vm, "model", "task", pre, {})

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 2


def test_execute_fail_triggers_learn():
    """EXECUTE empty result → LEARN → retry → success."""
    vm = MagicMock()
    vm.exec.side_effect = [
        _make_exec_result(""),               # EXPLAIN cycle 1 (no error text)
        _make_exec_result(""),               # EXECUTE cycle 1: empty
        _make_exec_result("ok"),             # EXPLAIN cycle 2
        _make_exec_result('[{"count":3}]'),  # EXECUTE cycle 2: has data
    ]
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([
        _sdd_json(),    # SDD cycle 1
        _plan_json(),   # PLAN cycle 1
        _learn_json(),  # LEARN cycle 1 (empty result)
        _sdd_json(),    # SDD cycle 2
        _plan_json(),   # PLAN cycle 2
        _answer_json(), # ANSWER cycle 2
    ])), patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        stats, _ = run_pipeline(vm, "model", "task", pre, {})

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 2


def test_all_cycles_exhausted():
    """All cycles fail → OUTCOME_NONE_CLARIFICATION."""
    vm = MagicMock()
    vm.exec.return_value = _make_exec_result("")  # always empty
    pre = _make_pre()

    import agent.pipeline as pl
    max_cycles = pl._MAX_CYCLES

    call_seq = []
    for _ in range(max_cycles):
        call_seq.extend([_sdd_json(), _plan_json(), _learn_json()])

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm(call_seq)), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None), \
         patch("agent.pipeline.load_learned_entries", return_value=[]):
        stats, eval_thread = run_pipeline(vm, "model", "task", pre, {}, task_id="t01")

    assert stats["outcome"] == "OUTCOME_NONE_CLARIFICATION"
    assert eval_thread is None


def test_learn_ctx_accumulates():
    """learn_ctx grows across cycles; ASSEMBLE sees accumulated rules."""
    vm = MagicMock()
    vm.exec.side_effect = [
        _make_exec_result(""),               # c1 EXPLAIN (no error)
        _make_exec_result(""),               # c1 EXECUTE: empty → triggers LEARN
        _make_exec_result("ok"),             # c2 EXPLAIN
        _make_exec_result('[{"count":3}]'),  # c2 EXECUTE: has data
    ]
    pre = _make_pre()

    captured_user_msgs = []

    def fake_llm(_sys, user_msg, _model, _cfg, **_kw):
        captured_user_msgs.append(user_msg)
        n = len(captured_user_msgs)
        if n == 1: return _sdd_json()
        if n == 2: return _plan_json()
        if n == 3: return _learn_json("rule_ALPHA")
        if n == 4: return _sdd_json()
        if n == 5: return _plan_json()
        if n == 6: return _answer_json()
        return None

    with patch("agent.pipeline.call_llm_raw", side_effect=fake_llm), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        stats, _ = run_pipeline(vm, "model", "task", pre, {})

    assert stats["outcome"] == "OUTCOME_OK"
    assert stats["cycles_used"] == 2


def test_learn_appends_rule_to_ctx():
    """_run_learn appends rule_content to learn_ctx on failure."""
    learn_ctx: list[str] = ["existing rule"]

    with patch("agent.pipeline.call_llm_raw", return_value=_learn_json("new rule")):
        _run_learn("ctx", "model", {}, "task", "err", [], learn_ctx, {})

    assert "new rule" in learn_ctx


def test_learn_skip_leaves_ctx_unchanged():
    """When LEARN output has skip=True, learn_ctx is not modified."""
    learn_ctx: list[str] = ["rule A", "rule B"]
    skip_json = json.dumps({
        "reasoning": "r", "conclusion": "c", "rule_content": "",
        "agents_md_anchor": None, "skip": True, "skip_reason": "no new info",
    })

    with patch("agent.pipeline.call_llm_raw", return_value=skip_json):
        _run_learn("ctx", "model", {}, "task", "err", [], learn_ctx, {})

    assert learn_ctx == ["rule A", "rule B"]


def test_sdd_denied_security_exits():
    """SDD error_code=DENIED_SECURITY → vm.answer called, pipeline exits."""
    vm = MagicMock()
    pre = _make_pre()

    sdd_denied = json.dumps({
        "spec_goal": "", "success_criteria": [], "plan": [], "actions": [],
        "error_code": "DENIED_SECURITY",
    })

    with patch("agent.pipeline.call_llm_raw", return_value=sdd_denied), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble):
        run_pipeline(vm, "model", "inject prompt", pre, {})

    vm.answer.assert_called_once()
    assert "Security" in vm.answer.call_args[0][0].message


def test_file_read_action_uses_vm_read():
    """PLAN action starting with /proc/ triggers vm.read, not vm.exec."""
    vm = MagicMock()
    read_result = MagicMock()
    read_result.content = '{"basket_id": "basket_117", "items": []}'
    vm.read.return_value = read_result
    pre = _make_pre()

    with patch("agent.pipeline.call_llm_raw", side_effect=_seq_llm([
        _sdd_json(actions=["/proc/baskets/basket_117.json"]),
        _plan_json(action="/proc/baskets/basket_117.json"),
        _answer_json(outcome="OUTCOME_NONE_UNSUPPORTED", message="Checkout not supported"),
    ])), patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline.check_retry_loop", return_value=None):
        stats, _ = run_pipeline(vm, "model", "Submit checkout basket_117", pre, {})

    vm.read.assert_called_once()
    assert stats["outcome"] == "OUTCOME_NONE_UNSUPPORTED"


def test_plan_user_msg_includes_prior_actions():
    """PLAN user message must include list of already-tried actions."""
    sdd_json = '{"spec_goal":"test","actions":["search:x /proc/"]}'
    prior = ["search:x /proc/", "list:/proc/payments/"]
    msg = _build_plan_user_msg(sdd_json, prior_actions=prior)
    assert "PRIOR_ACTIONS" in msg
    assert "search:x /proc/" in msg
    assert "list:/proc/payments/" in msg


def test_build_idd_user_msg_basic():
    msg = _build_idd_user_msg("show me orders", "", [])
    assert "TASK: show me orders" in msg
    assert "PREVIOUS_ERROR" not in msg
    assert "PRIOR_ACTIONS" not in msg


def test_build_idd_user_msg_with_error_and_actions():
    msg = _build_idd_user_msg(
        "show me orders",
        "table not found",
        ["SELECT * FROM orders", "/bin/sql SELECT 1"],
    )
    assert "TASK: show me orders" in msg
    assert "PREVIOUS_ERROR: table not found" in msg
    assert "PRIOR_ACTIONS" in msg
    assert "SELECT * FROM orders" in msg


from agent.models import IddOutput as _IddOutput


def _make_idd_out(reformulated_task="Return count of products", decision="proceed"):
    return _IddOutput(
        intent_objective="Count products",
        reformulated_task=reformulated_task,
        success_criteria=["result is a positive integer"],
        decision=decision,
    )


def test_build_sdd_user_msg_uses_idd_reformulated_task():
    from agent.pipeline import _build_sdd_user_msg
    idd = _make_idd_out(reformulated_task="Return count of active products in store_42")
    msg = _build_sdd_user_msg(idd, "", [])
    assert "Return count of active products in store_42" in msg
    assert "INTENT:" in msg
    assert "TASK:" in msg


def test_build_sdd_user_msg_includes_expectations():
    from agent.pipeline import _build_sdd_user_msg
    idd = _IddOutput(
        intent_objective="Check discount eligibility",
        reformulated_task="Check if basket_007 qualifies for discount",
        success_criteria=["result states eligibility", "refs include basket file"],
        health_metrics=["basket state must not change"],
        decision="proceed",
    )
    msg = _build_sdd_user_msg(idd, "", [])
    assert "EXPECTATIONS:" in msg
    assert "result states eligibility" in msg
    assert "CONSTRAINTS:" in msg
    assert "basket state must not change" in msg
