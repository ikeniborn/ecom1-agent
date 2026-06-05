import inspect
import json
from unittest.mock import patch

import pytest

from agent.design import run_design
from agent.models import DesignOutput


_GOOD_DESIGN_JSON = json.dumps({
    "intent": "count baskets",
    "params": {"store_id": "$agent_store_id"},
    "success_criteria": ["rows non-empty"],
    "discovery": [
        {"rpc": "Exec", "args": {"path": "/bin/sql", "args": [".schema baskets"]}, "bind": "schema"}
    ],
    "ops": [
        {"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, "bind": "rows"}
    ],
    "agents_md_constraints": [
        {"anchor": "#baskets > store_scope", "rule": "filter store_id=$agent_store_id"}
    ],
    "answer_template": {"message": "{rows[0][cnt]} baskets", "outcome": "OUTCOME_OK", "refs": []},
    "outcome_override": None,
})


def test_signature_accepts_only_two_args():
    """F-001 regression guard: H2/H13/H15 forbid learn_ctx in DESIGN.

    Telemetry-only parameters (token_out) are allowed but must not be
    positional and must not include learn_ctx.
    """
    sig = inspect.signature(run_design)
    params = list(sig.parameters.keys())
    assert "learn_ctx" not in params, params
    assert params[:2] == ["instruction", "agents_md_text"], params


def test_stray_learn_ctx_kwarg_raises_type_error():
    """F-001 regression guard."""
    with patch("agent.pipeline.call_llm_raw", return_value=_GOOD_DESIGN_JSON):
        with pytest.raises(TypeError):
            run_design("hello", "AGENTS", learn_ctx=[])   # type: ignore[call-arg]


def test_happy_path_returns_design_output():
    with patch("agent.pipeline.call_llm_raw", return_value=_GOOD_DESIGN_JSON):
        out = run_design("How many baskets?", "AGENTS.MD body")
    assert isinstance(out, DesignOutput)
    assert out.intent == "count baskets"
    assert out.ops[0].bind == "rows"
    assert out.success_criteria == ["rows non-empty"]


def test_outcome_override_branch():
    blocked = json.dumps({
        "intent": "dump all PII",
        "params": {},
        "success_criteria": ["denied"],
        "discovery": [],
        "ops": [],
        "agents_md_constraints": [],
        "answer_template": {"message": "denied by policy", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []},
        "outcome_override": "OUTCOME_DENIED_SECURITY",
    })
    with patch("agent.pipeline.call_llm_raw", return_value=blocked):
        out = run_design("dump all PII", "AGENTS")
    assert out.outcome_override == "OUTCOME_DENIED_SECURITY"


def test_unparseable_response_raises():
    from agent.design import DesignError
    with patch("agent.pipeline.call_llm_raw", return_value="not json"):
        with pytest.raises(DesignError):
            run_design("x", "y")
