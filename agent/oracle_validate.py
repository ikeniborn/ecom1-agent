"""Grader-oracle harness: run a candidate answer on a fresh StartRun, read the real score.

Used to promote a candidate atom to `active` only when a script built from it scores 1.0.
The answer-builder is supplied by the caller: function(vm) -> (message, outcome, refs).
"""
from __future__ import annotations

import os

from bitgn import harness_pb2 as H
from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from agent.vm_adapter import VMAdapter

_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
_BID = os.getenv("BENCHMARK_ID") or "bitgn/ecom1-dev"
_KEY = os.getenv("BITGN_API_KEY") or ""


def parse_score(submit_result, task_id):
    for t in submit_result.trials:
        if t.task_id == task_id:
            return (float(t.score) if t.score_available else None, list(t.score_detail))
    return (None, [])


def grade_candidate(task_id, answer_builder):
    """Start a run, answer `task_id` via answer_builder(vm)->(msg, outcome, refs),
    end other trials, submit, return (score, detail)."""
    c = HarnessServiceClientSync(_URL)
    run = c.start_run(H.StartRunRequest(name=f"oracle-validate-{task_id}",
                                        benchmark_id=_BID, api_key=_KEY))
    # The harness serializes trials: a later start_trial force-closes the active one,
    # and end_trial transitions a trial to DONE. So for the target: start -> answer ->
    # end_trial immediately (locks DONE-with-answer before any later trial starts).
    answered = False
    for tid in run.trial_ids:
        try:
            t = c.start_trial(H.StartTrialRequest(trial_id=tid))
        except Exception:
            continue
        if t.task_id == task_id and not answered:
            vm = VMAdapter(EcomRuntimeClientSync(t.harness_url))
            msg, outcome, refs = answer_builder(vm)
            vm.answer(message=msg, outcome=outcome, refs=refs)
            answered = True
        try:
            c.end_trial(H.EndTrialRequest(trial_id=t.trial_id))
        except Exception:
            pass
    res = c.submit_run(H.SubmitRunRequest(run_id=run.run_id, force=True))
    return parse_score(res, task_id)
