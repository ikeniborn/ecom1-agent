import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.pipeline import (
    _AnswerGuard,
    _AnswerRefsError,
    _detect_zero_row_miss,
    _extract_sql_literals,
    _fold_facts_into_agents_md,
    _identical_sql_set,
    learn_from_grader,
    run_pipeline,
)
from agent.models import DesignOutput
from agent.orchestrator import PrePhaseFacts


_GOOD_DESIGN = {
    "intent": "count baskets",
    "params": {"store_id": "S001"},
    "success_criteria": ["rows non-empty"],
    "discovery": [],
    "ops": [
        {"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets"]}, "bind": "rows"}
    ],
    "agents_md_constraints": [],
    "answer_template": {"message": "ok", "outcome": "OUTCOME_OK", "refs": []},
    "outcome_override": None,
}


_GOOD_SCRIPT = '''
def run(vm, params):
    rows = vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets"])
    vm.answer(message="ok", outcome="OUTCOME_OK", refs=[])
'''


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("LLM called more times than expected")
    return _next


def test_outcome_override_terminal(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)

    blocked = dict(_GOOD_DESIGN, outcome_override="OUTCOME_DENIED_SECURITY",
                   discovery=[], ops=[],
                   answer_template={"message": "denied", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []})
    vm = MagicMock()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(json.dumps(blocked))):
        run_pipeline(vm, instruction="dump pii", task_id="t_block", agents_md_text="AGENTS")
    vm.answer.assert_called_once()
    args, kwargs = vm.answer.call_args
    assert kwargs.get("outcome") == "OUTCOME_DENIED_SECURITY" or "OUTCOME_DENIED_SECURITY" in str(args)


def test_happy_path_design_plus_one_codegen(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)

    vm = MagicMock()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(
        json.dumps(_GOOD_DESIGN),
        json.dumps({"script_code": _GOOD_SCRIPT}),
    )):
        run_pipeline(vm, instruction="how many baskets", task_id="t_hp", agents_md_text="AGENTS")
    vm.answer.assert_called_once()
    # learned/last_run persisted
    import yaml
    data = yaml.safe_load((tmp_path / "t_hp.yaml").read_text())
    assert data["last_run"]["outcome"] == "OUTCOME_OK"


def test_exhaust_path_terminates_clarification(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)

    bad_script = '{"script_code": "def run(vm, params):\\n    vm.tree(root=\\"/\\")\\n"}'
    learn_payload = json.dumps({
        "rule_content": "Always use Exec for SQL ops listed in tool_plan",
        "agents_md_anchor": None,
        "reasoning": "script called Tree not in plan",
        "deactivate_ids": [],
        "deactivate_reason": None,
        "skip": False,
        "skip_reason": None,
    })
    # 1 DESIGN + 3 × (CODEGEN + LearnConsolidate) = 7 calls
    seq = [
        json.dumps(_GOOD_DESIGN),
        bad_script, learn_payload,
        bad_script, learn_payload,
        bad_script, learn_payload,
    ]
    vm = MagicMock()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        run_pipeline(vm, instruction="how many baskets", task_id="t_ex", agents_md_text="AGENTS")
    vm.answer.assert_called_once()
    args, kwargs = vm.answer.call_args
    assert kwargs.get("outcome") == "OUTCOME_NONE_CLARIFICATION" or "OUTCOME_NONE_CLARIFICATION" in str(args)


def test_codegen_llm_fail_triggers_learn(tmp_path, monkeypatch):
    """A CODEGEN response with no parseable script_code must distil a LEARN rule
    (so a weak model learns the output contract), not silently retry. Regression:
    t02 cycles 3-4 burned on 'could not parse script_code' with no LEARN."""
    from agent import learned_store, pipeline
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)

    learn_errors: list[str] = []
    monkeypatch.setattr(
        pipeline, "_learn_consolidate",
        lambda task_id, learn_ctx, design, error, script_code, **kw: learn_errors.append(error),
    )

    vm = MagicMock()
    bad_codegen = json.dumps({"oops": "no script_code field"})
    good_codegen = json.dumps({"script_code": _GOOD_SCRIPT})
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(
        json.dumps(_GOOD_DESIGN),
        bad_codegen,
        good_codegen,
    )):
        run_pipeline(vm, instruction="how many baskets", task_id="t_cgfail", agents_md_text="AGENTS")

    assert any(e.startswith("codegen_llm_fail:") for e in learn_errors)
    vm.answer.assert_called_once()


def test_extract_sql_literals_basic():
    code = '''
def run(vm, params):
    vm.exec(path="/bin/sql", args=["SELECT   1"])
    vm.exec(path="/bin/sql", args=["select 1"])
    vm.exec(path="/bin/sh", args=["ls"])
'''
    sqls = _extract_sql_literals(code)
    assert "SELECT 1" in sqls
    assert "select 1" in sqls
    assert all("ls" not in s for s in sqls)


def test_extract_sql_literals_ignores_fstrings():
    code = '''
def run(vm, params):
    q = f"SELECT * FROM t WHERE id={params['id']}"
    vm.exec(path="/bin/sql", args=[q])
'''
    sqls = _extract_sql_literals(code)
    assert sqls == []


def _design_with_template_refs(refs: list[str]) -> DesignOutput:
    obj = dict(_GOOD_DESIGN)
    obj["answer_template"] = {
        "message": "ok",
        "outcome": "OUTCOME_OK",
        "refs": refs,
    }
    return DesignOutput(**obj)


def test_answer_guard_passes_resolved_refs():
    vm = MagicMock()
    design = _design_with_template_refs(["$path"])
    g = _AnswerGuard(vm, design)
    g.answer(message="ok", outcome="OUTCOME_OK", refs=["/proc/catalog/abc.json"])
    vm.answer.assert_called_once_with(
        message="ok", outcome="OUTCOME_OK", refs=["/proc/catalog/abc.json"]
    )


def test_answer_guard_raises_on_unresolved_placeholder():
    vm = MagicMock()
    design = _design_with_template_refs(["$path"])
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="unresolved placeholder"):
        g.answer(message="ok", outcome="OUTCOME_OK", refs=["$path"])
    vm.answer.assert_not_called()


def test_answer_guard_raises_on_empty_refs_when_template_needs_runtime():
    vm = MagicMock()
    design = _design_with_template_refs(["$path"])
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="only static template"):
        g.answer(message="ok", outcome="OUTCOME_OK", refs=[])
    vm.answer.assert_not_called()


def test_answer_guard_allows_empty_refs_on_negative_answer():
    """yes/no <NO> answer legitimately cites nothing.

    AGENTS.MD: "should not reference unavailable products". When no row matched,
    the script emits <NO> with empty refs — that is correct, not a SQL failure.
    Regression: t02 looped all cycles on answer_refs for a legitimate <NO>.
    """
    vm = MagicMock()
    design = _design_with_template_refs(["$matches[*].record_path"])
    g = _AnswerGuard(vm, design)
    g.answer(message="<NO> No matching variant exists.", outcome="OUTCOME_OK", refs=[])
    vm.answer.assert_called_once()


def test_answer_guard_raises_on_empty_refs_for_positive_answer():
    """A <YES> answer asserting a match MUST still cite the runtime path."""
    vm = MagicMock()
    design = _design_with_template_refs(["$matches[*].record_path"])
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="only static template"):
        g.answer(message="<YES> Found the variant.", outcome="OUTCOME_OK", refs=[])
    vm.answer.assert_not_called()


def test_answer_guard_raises_when_only_static_refs_present():
    """Real regression: template ['/proc/catalog', '$path'], script returned only '/proc/catalog'."""
    vm = MagicMock()
    design = _design_with_template_refs(["/proc/catalog", "$path"])
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="only static template"):
        g.answer(message="ok", outcome="OUTCOME_OK", refs=["/proc/catalog"])
    vm.answer.assert_not_called()


# ---------------------------------------------------------------------------
# Zero-data-row miss gate (t02 non-determinism root cause)
# ---------------------------------------------------------------------------
# A discovery /bin/sql that returns header-only (0 data rows) for an existing
# product is silently accepted today via the <NO> escape, then fails the grader
# with "missing required reference". The gate must turn that into a red retry
# signal — but only when the task actually demands a runtime record_path ref.


def test_zero_row_miss_detected_on_negative_answer():
    design = _design_with_template_refs(["/proc/catalog/", "$record_path"])
    answer = {
        "message": "<NO> No matching product in catalogue",
        "outcome": "OUTCOME_OK",
        "refs": ["/proc/catalog/"],
    }
    err = _detect_zero_row_miss(design, ["product_sku,record_path"], answer)
    assert err and "zero_row_miss" in err


def test_zero_row_miss_silent_when_data_row_present():
    design = _design_with_template_refs(["/proc/catalog/", "$record_path"])
    answer = {
        "message": "<YES> Product found",
        "outcome": "OUTCOME_OK",
        "refs": ["/proc/catalog/", "/proc/catalog/ES/WRK-1.json"],
    }
    sql_results = ["product_sku,record_path\nWRK-1,/proc/catalog/ES/WRK-1.json"]
    assert _detect_zero_row_miss(design, sql_results, answer) is None


def test_zero_row_miss_silent_when_no_runtime_demanded():
    # COUNT-style task: no runtime record_path required → header-only is fine
    # (and a genuine count=0 / <NO> answer must not be forced into retries).
    design = _design_with_template_refs([])
    answer = {"message": "<NO> none", "outcome": "OUTCOME_OK", "refs": []}
    assert _detect_zero_row_miss(design, ["product_sku,record_path"], answer) is None


def test_zero_row_miss_silent_when_no_sql_ran():
    # No /bin/sql executed → cannot conclude "0 rows for an existing product".
    # Keeps the legitimate-<NO> path (test_answer_guard_allows_empty_refs_on_negative_answer) intact.
    design = _design_with_template_refs(["/proc/catalog/", "$record_path"])
    answer = {"message": "<NO> none", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog/"]}
    assert _detect_zero_row_miss(design, [], answer) is None


def test_learn_from_grader_missing_state_returns_false(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert learn_from_grader("nonexistent_task", ["something"]) is False


def test_learn_from_grader_invokes_learn_consolidate(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    heur_dir = tmp_path / "data" / "heuristics"
    heur_dir.mkdir(parents=True)

    design = DesignOutput(**_GOOD_DESIGN)
    (heur_dir / "t_learn.design.json").write_text(design.model_dump_json())
    (heur_dir / "t_learn.py").write_text("def run(vm, params): pass\n")

    learn_payload = json.dumps({
        "rule_content": "Always include the matched row's catalog path in refs",
        "agents_md_anchor": None,
        "reasoning": "Grader rejected answer missing path ref",
        "deactivate_ids": [],
        "deactivate_reason": None,
        "skip": False,
        "skip_reason": None,
    })
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(learn_payload)):
        assert learn_from_grader("t_learn", ["answer missing required reference 'X'"]) is True

    import yaml
    data = yaml.safe_load((tmp_path / "t_learn.yaml").read_text())
    assert data["entries"][-1]["content"].startswith("Always include")


def test_answer_guard_passes_with_static_plus_runtime_refs():
    vm = MagicMock()
    design = _design_with_template_refs(["/proc/catalog", "$path"])
    g = _AnswerGuard(vm, design)
    g.answer(
        message="ok",
        outcome="OUTCOME_OK",
        refs=["/proc/catalog", "/proc/catalog/FST-1.json"],
    )
    vm.answer.assert_called_once()


def test_answer_guard_allows_empty_refs_when_template_has_no_runtime():
    vm = MagicMock()
    design = _design_with_template_refs([])  # template has no $-placeholders
    g = _AnswerGuard(vm, design)
    g.answer(message="ok", outcome="OUTCOME_OK", refs=[])
    vm.answer.assert_called_once()


def test_answer_guard_infers_runtime_demand_from_success_criteria():
    """No $placeholder in template, but success_criteria mentions 'full path' → require runtime ref."""
    obj = dict(_GOOD_DESIGN)
    obj["success_criteria"] = ["Answer references matched product with full path"]
    obj["answer_template"] = {"message": "ok", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}
    design = DesignOutput(**obj)
    vm = MagicMock()
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="only static template"):
        g.answer(message="ok", outcome="OUTCOME_OK", refs=["/proc/catalog"])
    vm.answer.assert_not_called()


def test_answer_guard_infers_runtime_demand_from_agents_md_constraints():
    """AGENTS.MD constraint mentions 'reference' → require runtime ref."""
    obj = dict(_GOOD_DESIGN)
    obj["agents_md_constraints"] = [
        {"anchor": "#x", "rule": "When responding with reference - provide full path"}
    ]
    obj["answer_template"] = {"message": "ok", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}
    design = DesignOutput(**obj)
    vm = MagicMock()
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="only static template"):
        g.answer(message="ok", outcome="OUTCOME_OK", refs=["/proc/catalog"])
    vm.answer.assert_not_called()


def test_answer_guard_infers_runtime_demand_satisfied_by_path_like_ref():
    """Inferred demand satisfied when refs contain a non-static path."""
    obj = dict(_GOOD_DESIGN)
    obj["success_criteria"] = ["Answer references matched product with full path"]
    obj["answer_template"] = {"message": "ok", "outcome": "OUTCOME_OK", "refs": ["/proc/catalog"]}
    design = DesignOutput(**obj)
    vm = MagicMock()
    g = _AnswerGuard(vm, design)
    g.answer(message="ok", outcome="OUTCOME_OK", refs=["/proc/catalog", "/proc/catalog/FST-X.json"])
    vm.answer.assert_called_once()


def test_answer_guard_skips_refs_check_on_non_ok_outcome():
    """If the script gave up (e.g. CLARIFICATION), empty refs is fine."""
    vm = MagicMock()
    design = _design_with_template_refs(["$path"])
    g = _AnswerGuard(vm, design)
    g.answer(message="cannot find", outcome="OUTCOME_NONE_CLARIFICATION", refs=[])
    vm.answer.assert_called_once()


def test_answer_guard_passes_unsupported_when_template_expects_ok():
    """Non-OK outcomes are legitimate escape paths; grader-feedback (not pipeline)
    decides whether the script's verdict was right. Pipeline must not block."""
    vm = MagicMock()
    design = _design_with_template_refs([])
    g = _AnswerGuard(vm, design)
    g.answer(message="cannot do", outcome="OUTCOME_NONE_UNSUPPORTED", refs=[])
    vm.answer.assert_called_once()
    assert g.actual_outcome == "OUTCOME_NONE_UNSUPPORTED"


def test_answer_guard_requires_static_refs_on_unsupported():
    """Static template refs (e.g. /docs/security.md) are grader-required citations
    even for non-OK outcomes."""
    vm = MagicMock()
    design = _design_with_template_refs(["/docs/security.md"])
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="missing static template refs"):
        g.answer(message="cannot do", outcome="OUTCOME_NONE_UNSUPPORTED", refs=[])
    vm.answer.assert_not_called()


def test_answer_guard_requires_static_refs_on_denied():
    vm = MagicMock()
    design = _design_with_template_refs(["/docs/security.md"])
    g = _AnswerGuard(vm, design)
    with pytest.raises(_AnswerRefsError, match="missing static template refs"):
        g.answer(message="denied", outcome="OUTCOME_DENIED_SECURITY", refs=[])
    vm.answer.assert_not_called()


def test_answer_guard_passes_unsupported_with_static_refs_present():
    vm = MagicMock()
    design = _design_with_template_refs(["/docs/security.md"])
    g = _AnswerGuard(vm, design)
    g.answer(
        message="cannot do",
        outcome="OUTCOME_NONE_UNSUPPORTED",
        refs=["/docs/security.md"],
    )
    vm.answer.assert_called_once()


def test_answer_guard_clarification_skips_static_refs_check():
    """CLARIFICATION is the giveup path — refs can be dropped legitimately."""
    vm = MagicMock()
    design = _design_with_template_refs(["/docs/x.md"])
    g = _AnswerGuard(vm, design)
    g.answer(message="?", outcome="OUTCOME_NONE_CLARIFICATION", refs=[])
    vm.answer.assert_called_once()


def test_answer_guard_captures_actual_outcome():
    vm = MagicMock()
    design = _design_with_template_refs([])
    g = _AnswerGuard(vm, design)
    g.answer(message="ok", outcome="OUTCOME_OK", refs=[])
    assert g.actual_outcome == "OUTCOME_OK"


def test_answer_guard_captures_actual_outcome_on_clarification():
    vm = MagicMock()
    design = _design_with_template_refs([])
    g = _AnswerGuard(vm, design)
    g.answer(message="?", outcome="OUTCOME_NONE_CLARIFICATION", refs=[])
    assert g.actual_outcome == "OUTCOME_NONE_CLARIFICATION"


def test_answer_guard_allows_unsupported_when_template_outcome_matches():
    """If DESIGN itself plans UNSUPPORTED, script returning UNSUPPORTED is fine."""
    obj = dict(_GOOD_DESIGN)
    obj["answer_template"] = {
        "message": "no support",
        "outcome": "OUTCOME_NONE_UNSUPPORTED",
        "refs": [],
    }
    design = DesignOutput(**obj)
    vm = MagicMock()
    g = _AnswerGuard(vm, design)
    g.answer(message="no support", outcome="OUTCOME_NONE_UNSUPPORTED", refs=[])
    vm.answer.assert_called_once()
    assert g.actual_outcome == "OUTCOME_NONE_UNSUPPORTED"


def test_answer_guard_proxies_non_answer_attrs():
    vm = MagicMock()
    vm.exec.return_value = "stub"
    design = _design_with_template_refs([])
    g = _AnswerGuard(vm, design)
    assert g.exec(path="/bin/sql", args=["SELECT 1"]) == "stub"
    vm.exec.assert_called_once_with(path="/bin/sql", args=["SELECT 1"])


def test_identical_sql_set_normalises_whitespace():
    a = ["SELECT  1", "SELECT 2"]
    b = ["select 2", "SELECT 1"]   # different order, different case, extra ws
    # case-sensitive per F-005 ("no other casing or token rewrites")
    assert not _identical_sql_set(a, b)
    c = ["SELECT  1", "  SELECT 2  "]
    d = ["SELECT 1", "SELECT 2"]
    assert _identical_sql_set(c, d)


def test_retry_guard_skips_sql_orthogonal_errors():
    """check_retry_loop must NOT fire when the prior failure is orthogonal to
    SQL content. fidelity asserts the RPC-name multiset (never SQL text), lint
    is ast.parse, answer_refs is parsing/refs — identical SQL recurring is
    correct, not a stuck loop. Regression: t51 aborted at cycle 3 on fidelity.
    """
    from agent.pipeline import _retry_guard_applies
    assert _retry_guard_applies("fidelity: drift (RPC multiset) ...") is False
    assert _retry_guard_applies("lint: SyntaxError ...") is False
    assert _retry_guard_applies("answer_refs: only static template ...") is False


def test_retry_guard_fires_on_sql_driven_errors():
    """Plausibly SQL-content-driven failures keep the anti-loop guard active."""
    from agent.pipeline import _retry_guard_applies
    assert _retry_guard_applies("real_vm_exec: ...") is True
    assert _retry_guard_applies("intent_test: ...") is True
    assert _retry_guard_applies(None) is True


def test_is_retryable_vm_error_covers_ecom_not_found():
    """The ECOM runtime phrases a missing file/record as 'read failed: not found'.
    On a read-only plan that must be retryable so the loop LEARNs + retries rather
    than dead-ending at clarification (regression: t02 broke at cycle 5/10).
    """
    from agent.pipeline import _is_retryable_vm_error
    # ECOM phrasing — the regression case.
    assert _is_retryable_vm_error("read failed: not found") is True
    # POSIX-style phrasings the gate already intended to cover.
    assert _is_retryable_vm_error("[INVALID_ARGUMENT] no such file or directory") is True
    assert _is_retryable_vm_error("path does not exist") is True
    assert _is_retryable_vm_error("/docs is a directory") is True
    # Network transients stay retryable.
    assert _is_retryable_vm_error("The read operation timed out") is True
    # Non-deterministic / genuinely fatal errors stay non-retryable.
    assert _is_retryable_vm_error("permission denied") is False
    assert _is_retryable_vm_error("internal server error") is False


def test_answer_guard_captures_submitted_answer():
    design = DesignOutput(**_GOOD_DESIGN)
    vm = MagicMock()
    guard = _AnswerGuard(vm, design)
    guard.answer(message="Found 1 basket.", outcome="OUTCOME_OK", refs=["ref://basket/42"])
    assert guard._captured == {
        "message": "Found 1 basket.",
        "outcome": "OUTCOME_OK",
        "refs": ["ref://basket/42"],
    }


def test_answer_guard_captured_empty_before_answer():
    design = DesignOutput(**_GOOD_DESIGN)
    guard = _AnswerGuard(MagicMock(), design)
    assert guard._captured == {}


def _entries(n):
    return [{"id": f"r{i:03d}", "content": f"always do thing {i}", "status": "active"} for i in range(n)]


def test_compact_below_threshold_returns_unchanged(monkeypatch):
    from agent.pipeline import _compact_learn_ctx
    monkeypatch.setenv("COMPACTION_THRESHOLD", "15")
    ctx = _entries(10)
    assert _compact_learn_ctx(ctx) == ctx


def test_compact_above_threshold_summarizes_older(monkeypatch):
    from agent.pipeline import _compact_learn_ctx
    monkeypatch.setenv("COMPACTION_THRESHOLD", "5")
    monkeypatch.setenv("COMPACTION_KEEP_RECENT", "3")
    ctx = _entries(10)
    with patch("agent.pipeline.call_llm_raw", return_value="condensed summary of older rules"):
        out = _compact_learn_ctx(ctx)
    assert out[0] == {"id": "compacted", "content": "condensed summary of older rules", "source": "compaction"}
    assert out[1:] == ctx[-3:]
    assert len(out) == 4


def test_compact_empty_llm_response_returns_unchanged(monkeypatch):
    from agent.pipeline import _compact_learn_ctx
    monkeypatch.setenv("COMPACTION_THRESHOLD", "5")
    monkeypatch.setenv("COMPACTION_KEEP_RECENT", "3")
    ctx = _entries(10)
    with patch("agent.pipeline.call_llm_raw", return_value=""):
        out = _compact_learn_ctx(ctx)
    assert out == ctx


def test_compact_keep_recent_zero_is_guarded(monkeypatch):
    from agent.pipeline import _compact_learn_ctx
    monkeypatch.setenv("COMPACTION_THRESHOLD", "5")
    monkeypatch.setenv("COMPACTION_KEEP_RECENT", "0")
    ctx = _entries(10)
    with patch("agent.pipeline.call_llm_raw", return_value="condensed") as m:
        out = _compact_learn_ctx(ctx)
    # keep_recent must be clamped to >= 1: exactly one recent entry kept, older summarized
    assert out[0] == {"id": "compacted", "content": "condensed", "source": "compaction"}
    assert out[1:] == ctx[-1:]
    assert len(out) == 2
    m.assert_called_once()


def test_learn_consolidate_sends_full_script(tmp_path, monkeypatch):
    import agent.learned_store as ls
    from agent.pipeline import _learn_consolidate
    monkeypatch.setattr(ls, "_LEARNED_DIR", tmp_path)

    design = DesignOutput(**_GOOD_DESIGN)
    # Build a script where the tail (unique sentinel) lands well past char 4000
    padding = "    x = 1  # pad\n" * 600  # ~10 200 chars total
    unique_sentinel = "    return  # UNIQUE_TAIL_SENTINEL_XYZ"
    long_script = "def run(vm, params):\n" + padding + unique_sentinel + "\n"
    assert len(long_script) > 4000
    assert unique_sentinel not in long_script[:4000]  # sentinel is beyond the old cap

    captured = {}

    def _fake_llm(system, user_msg, model, opts, **kw):
        captured["user_msg"] = user_msg
        return json.dumps({"reasoning": "noop", "skip": True, "skip_reason": "noop", "deactivate_ids": []})

    with patch("agent.pipeline.call_llm_raw", side_effect=_fake_llm):
        _learn_consolidate("t10", [], design, "some error", long_script)

    assert unique_sentinel in captured["user_msg"]   # sentinel survived — no truncation


# ---------------------------------------------------------------------------
# T8: _fold_facts_into_agents_md
# ---------------------------------------------------------------------------


def test_fold_facts_appends_policies_and_status():
    facts = PrePhaseFacts(
        agents_md="RULES", policies={"/docs/p.md": "POLICY BODY"},
        docs_inventory="/docs/p.md", identity={"role": "employee"},
        gather_status={"policies": "ok"},
    )
    out = _fold_facts_into_agents_md("# AGENTS\n", facts)
    assert out.startswith("# AGENTS")
    assert "POLICY BODY" in out
    assert "/docs/p.md" in out
    assert "gather_status" in out


def test_fold_facts_noop_when_facts_none():
    assert _fold_facts_into_agents_md("# AGENTS\n", None) == "# AGENTS\n"
