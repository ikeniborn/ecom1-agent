import json
from unittest.mock import patch

from agent.pipeline import _learn_consolidate
from agent.models import (
    DesignOutput, ToolOp, AnswerTemplate, LearnConsolidateOutput,
)


def _design():
    return DesignOutput(
        intent="x", params={}, success_criteria=["y"],
        discovery=[], ops=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": ["SELECT 1"]}, bind="r")],
        agents_md_constraints=[],
        answer_template=AnswerTemplate(message="ok", outcome="OUTCOME_OK", refs=[]),
    )


def test_learn_consolidate_writes_rule(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)

    payload = json.dumps({
        "rule_content": "Never hardcode SKUs from the instruction text",
        "agents_md_anchor": None,
        "reasoning": "prev hardcoded value",
        "deactivate_ids": [],
        "deactivate_reason": None,
        "skip": False,
        "skip_reason": None,
    })
    with patch("agent.pipeline.call_llm_raw", return_value=payload):
        learn_ctx: list[dict] = []
        _learn_consolidate("tX", learn_ctx, _design(), "lint: bad syntax", "def run(): pass")
    import yaml
    data = yaml.safe_load((tmp_path / "tX.yaml").read_text())
    assert data["entries"][0]["content"].startswith("Never hardcode")


def test_learn_consolidate_skip_does_not_write(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)

    payload = json.dumps({
        "rule_content": "",
        "agents_md_anchor": None,
        "reasoning": "duplicate of r001",
        "deactivate_ids": [],
        "deactivate_reason": None,
        "skip": True,
        "skip_reason": "r001",
    })
    with patch("agent.pipeline.call_llm_raw", return_value=payload):
        _learn_consolidate("tY", [], _design(), "fidelity: drift", "def run(): pass")
    assert not (tmp_path / "tY.yaml").exists()
