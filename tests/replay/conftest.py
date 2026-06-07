# tests/replay/conftest.py
import json
from pathlib import Path

from agent.ir_models import IntentSpec, PlanIR
from agent.interpreter import interpret
from agent.mock_vm_spy import MockVMSpy

_REPLAY = Path(__file__).parent
_MINIMAL_INTENT = IntentSpec(objective="o", desired_outcome="d",
                             outcome_space=["OUTCOME_OK", "OUTCOME_NONE_UNSUPPORTED",
                                            "OUTCOME_DENIED_SECURITY",
                                            "OUTCOME_NONE_CLARIFICATION"],
                             answer_shape={"required_ref_kinds": []})


def run_old_script(tid: str, fixtures: dict, params: dict) -> dict:
    code = Path(f"data/heuristics/{tid}.py").read_text(encoding="utf-8")
    ns: dict = {}
    exec(compile(code, f"<{tid}>", "exec"), ns)
    spy = MockVMSpy(fixtures=fixtures)
    ns["run"](spy, dict(params))
    for rpc, kw in reversed(spy.calls):
        if rpc == "Answer":
            return {"message": kw.get("message", ""), "outcome": kw.get("outcome", ""),
                    "refs": sorted(kw.get("refs") or [])}
    return {"message": "", "outcome": "", "refs": []}


def run_plan(tid: str, fixtures: dict, params: dict, intent=_MINIMAL_INTENT) -> dict:
    plan = PlanIR(**json.loads((_REPLAY / f"plan_{tid}.json").read_text()))
    spy = MockVMSpy(fixtures=fixtures)
    res = interpret(plan, intent.model_copy(update={"params": params}), spy)
    return {"message": res.captured.message, "outcome": res.captured.outcome,
            "refs": sorted(res.captured.refs)}
