import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.pipeline import run_pipeline, _extract_sql_literals, _identical_sql_set


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


def test_identical_sql_set_normalises_whitespace():
    a = ["SELECT  1", "SELECT 2"]
    b = ["select 2", "SELECT 1"]   # different order, different case, extra ws
    # case-sensitive per F-005 ("no other casing or token rewrites")
    assert not _identical_sql_set(a, b)
    c = ["SELECT  1", "  SELECT 2  "]
    d = ["SELECT 1", "SELECT 2"]
    assert _identical_sql_set(c, d)
