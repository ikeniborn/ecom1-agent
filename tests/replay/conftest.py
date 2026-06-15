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
                             answer_shape={})


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


def _required_refs_from_plan(plan) -> dict:
    """Transitional parity shim: derive required_refs from a golden plan's
    answer refs so the new projection reproduces the old script's refs."""
    rr: dict = {}
    for tmpl in plan.answer.values():
        bucket = rr.setdefault(tmpl.outcome, [])
        for r in tmpl.refs:
            spec = ({"kind": "record_path", "source": r}
                    if isinstance(r, str) and r.startswith("$")
                    else {"kind": "policy_doc", "path": str(r)})
            if spec not in bucket:
                bucket.append(spec)
    return rr


def run_plan(tid: str, fixtures: dict, params: dict, intent=_MINIMAL_INTENT) -> dict:
    plan = PlanIR(**json.loads((_REPLAY / f"plan_{tid}.json").read_text()))
    spy = MockVMSpy(fixtures=fixtures)
    d = intent.model_dump()
    d["params"] = params
    d["required_refs"] = _required_refs_from_plan(plan)
    intent = IntentSpec.model_validate(d)
    res = interpret(plan, intent, spy)
    return {"message": res.captured.message, "outcome": res.captured.outcome,
            "refs": sorted(res.captured.refs)}
