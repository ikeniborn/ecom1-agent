"""Integration tests for the intent-driven TDD gate (TDD_ENABLED)."""
import json
from unittest.mock import patch

from agent.pipeline import run_pipeline


_DESIGN = {
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

# TEST-GEN output: test_answer requires a <YES> token in the message.
_TEST_REQUIRE_YES = json.dumps({
    "reasoning": "yes/no answer must carry a token",
    "sql_tests": "def test_sql(results):\n    assert results, 'no sql results'\n",
    "answer_tests": (
        "def test_answer(sql_results, answer):\n"
        "    assert answer['outcome'] == 'OUTCOME_OK', answer['outcome']\n"
        "    assert '<yes>' in answer['message'].lower(), answer['message']\n"
    ),
})

_SCRIPT_NO_TOKEN = json.dumps({"script_code": (
    'def run(vm, params):\n'
    '    vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets"])\n'
    '    vm.answer(message="ok", outcome="OUTCOME_OK", refs=[])\n'
)})

_SCRIPT_WITH_TOKEN = json.dumps({"script_code": (
    'def run(vm, params):\n'
    '    vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets"])\n'
    '    vm.answer(message="<YES> ok", outcome="OUTCOME_OK", refs=[])\n'
)})

_LEARN = json.dumps({
    "reasoning": "must include the <YES> token",
    "rule_content": "Include <YES>/<NO> token in yes/no answers",
    "agents_md_anchor": None,
    "deactivate_ids": [],
    "deactivate_reason": None,
    "skip": False,
    "skip_reason": None,
})


class _FakeVM:
    """Minimal VM returning JSON-serializable stdout (run_tests json.dumps the context)."""

    def __init__(self, sql_stdout="cnt\n5"):
        self.sql_stdout = sql_stdout
        self.answered: list[dict] = []

    def exec(self, path="", args=None, stdin="", **kw):
        return {"stdout": self.sql_stdout}

    def answer(self, message="", outcome="", refs=None, **kw):
        self.answered.append({"message": message, "outcome": outcome, "refs": list(refs or [])})


def _seq(*items):
    it = iter(items)

    def _next(*a, **kw):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("LLM called more times than expected")
    return _next


def _prep(tmp_path, monkeypatch, tdd=True, force_after=3):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)
    monkeypatch.setattr("agent.pipeline._TDD_ENABLED", tdd)
    monkeypatch.setattr("agent.pipeline._TDD_FORCE_SUBMIT_AFTER", force_after)
    # oracle off — keep the LLM call sequence deterministic
    monkeypatch.setenv("ORACLE_ENABLED", "0")


def test_tdd_green_first_cycle_submits_once(tmp_path, monkeypatch):
    """DESIGN → TEST-GEN → CODEGEN(green) → intent-test pass → exactly one answer."""
    _prep(tmp_path, monkeypatch)
    vm = _FakeVM()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(
        json.dumps(_DESIGN),
        _TEST_REQUIRE_YES,
        _SCRIPT_WITH_TOKEN,
    )):
        run_pipeline(vm, instruction="how many baskets?", task_id="t_green", agents_md_text="A")
    assert len(vm.answered) == 1
    assert vm.answered[0]["outcome"] == "OUTCOME_OK"
    assert "<YES>" in vm.answered[0]["message"]


def test_tdd_red_then_green_retries(tmp_path, monkeypatch):
    """Red answer (no token) → LEARN → next cycle → green. One answer, with token."""
    _prep(tmp_path, monkeypatch)
    vm = _FakeVM()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(
        json.dumps(_DESIGN),
        _TEST_REQUIRE_YES,
        _SCRIPT_NO_TOKEN,   # cycle 1: red
        _LEARN,
        _SCRIPT_WITH_TOKEN,  # cycle 2: green
    )):
        run_pipeline(vm, instruction="how many baskets?", task_id="t_rg", agents_md_text="A")
    assert len(vm.answered) == 1
    assert "<YES>" in vm.answered[0]["message"]


def test_tdd_force_submit_after_threshold(tmp_path, monkeypatch):
    """Test stays red; force-submit at streak >= threshold beats CLARIFICATION."""
    _prep(tmp_path, monkeypatch, force_after=1)
    vm = _FakeVM()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(
        json.dumps(_DESIGN),
        _TEST_REQUIRE_YES,
        _SCRIPT_NO_TOKEN,   # red → streak=1 >= 1 → force submit best captured
        _LEARN,
    )):
        run_pipeline(vm, instruction="how many baskets?", task_id="t_force", agents_md_text="A")
    assert len(vm.answered) == 1
    # forced: the captured (red) OK answer is submitted, not CLARIFICATION
    assert vm.answered[0]["outcome"] == "OUTCOME_OK"


def test_tdd_disabled_skips_test_gen(tmp_path, monkeypatch):
    """TDD off → no TEST-GEN call; DESIGN + CODEGEN only, answer submitted inline."""
    _prep(tmp_path, monkeypatch, tdd=False)
    vm = _FakeVM()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(
        json.dumps(_DESIGN),
        _SCRIPT_WITH_TOKEN,   # no TEST-GEN entry between DESIGN and CODEGEN
    )):
        run_pipeline(vm, instruction="how many baskets?", task_id="t_off", agents_md_text="A")
    assert len(vm.answered) == 1
