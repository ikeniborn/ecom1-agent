import json
from unittest.mock import MagicMock, patch

import pytest

from agent.pipeline import negative_outcome_by_precedence, run_pipeline


def test_precedence_prefers_unsupported():
    assert negative_outcome_by_precedence(
        ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION", "OUTCOME_NONE_UNSUPPORTED"]
    ) == "OUTCOME_NONE_UNSUPPORTED"


def test_precedence_clarification_when_only_it():
    assert negative_outcome_by_precedence(
        ["OUTCOME_OK", "OUTCOME_NONE_CLARIFICATION"]) == "OUTCOME_NONE_CLARIFICATION"


def test_precedence_none_when_no_negative():
    assert negative_outcome_by_precedence(
        ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"]) is None


def test_precedence_handles_empty_and_none():
    assert negative_outcome_by_precedence([]) is None
    assert negative_outcome_by_precedence(None) is None


@pytest.fixture
def _isolate(monkeypatch, tmp_path):
    # Mirror tests/test_pipeline_decide.py: skip the ReAct + oracle phases, isolate the
    # learned-rule store and the heuristics dir into tmp.
    from agent import learned_store
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")
    monkeypatch.setenv("ECOM_ORACLE_ENABLED", "0")
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


def test_terminal_emits_in_space_negative_on_exhaust(_isolate):
    # Loop exhausts via the identical-plan short-circuit. outcome_space lists UNSUPPORTED
    # but NOT CLARIFICATION -> the terminal must answer the in-space negative
    # OUTCOME_NONE_UNSUPPORTED (B), not the hardcoded CLARIFICATION.
    intent = json.dumps({
        "objective": "x", "desired_outcome": "OUTCOME_OK", "params": {},
        "outcome_space": ["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED"],
        "constraints": [],
        "success_criteria": {"OUTCOME_OK": [{"op": "eq", "lhs": "__never__", "rhs": "__nope__"}]},
        "answer_shape": {},
        "required_refs": {"OUTCOME_OK": [{"kind": "policy_doc", "path": "/docs/never.md"}]},
    })
    # Plan authors OK; the interpreter auto-injects /docs/never.md so I1 passes, but the
    # guaranteed-false OUTCOME_OK success_criteria (__never__ == __nope__) fails verify.
    plan = json.dumps({
        "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 5 AS cnt"]}, "bind": "raw"}],
        "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
        "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
        "decision": {"branches": [], "default_label": "ok"}, "ops": [],
        "answer": {"ok": {"message": "{row0.cnt} in stock", "outcome": "OUTCOME_OK", "refs": []}},
        "custom_extract": [],
    })

    def _seq(*items):
        it = iter(items)
        return lambda *a, **kw: next(it)

    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n5"}
    # _ilearn patched to a no-op so it never consumes an LLM response from the sequence.
    # Sequence: intent, then the SAME plan twice — cycle 1 fails verify (success_criteria
    # eq("__never__","__nope__") is always False; the required ref is auto-injected so I1
    # passes), cycle 2 is identical -> short-circuit break -> single terminal answer.
    with patch("agent.pipeline._ilearn"), \
         patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, plan, plan)):
        m = run_pipeline(vm, instruction="q", task_id="t_term_neg",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_NONE_UNSUPPORTED"
