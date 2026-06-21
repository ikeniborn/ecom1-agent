---
review:
  plan_hash: 964a5710f79a4fde
  spec_hash: 5ca33c546416695a
  last_run: 2026-06-21
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings: []
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-21-harness-oracle-teach-bridge-design.md
---
# Harness→Oracle Teach Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offline tool that turns a frequently-firing `data/harness/checks.yaml` lint check into a validated positive oracle `method` atom — distil it, validate by a full end-to-end re-run of the check's source task with the candidate force-active in PLAN, and auto-promote on a grader score of 1.0.

**Architecture:** Three units. (1) A 2-line retrieval seam in `agent/oracle.py:_active()` honouring `ECOM_ORACLE_FORCE_ACTIVE` so a candidate atom is retrievable for one validation run. (2) A new efficacy validator `grade_full_run`/`validate_atom_via_full_run` in `agent/oracle_validate.py` that re-runs a task through the whole agent with that env set. (3) An offline orchestrator `scripts/harness_to_oracle.py` that reads lint telemetry, picks hot checks, and runs distil→validate→promote per check. Everything else (distil, promote, dedup, telemetry aggregate) is reused.

**Tech Stack:** Python 3.12, pytest, `uv run`. Reused modules: `agent/oracle.py` (`KnowledgeOracle.distill/promote/_active`), `agent/oracle_validate.py` (`grade_candidate`/`parse_score` pattern), `agent/harness.py` (`load_checks`), `scripts/lint_report.py` (`aggregate`), `agent/orchestrator.py` (`run_agent`), `agent/oracle_atoms.py` (`Atom`).

**Spec:** `docs/superpowers/specs/2026-06-21-harness-oracle-teach-bridge-design.md`

> **Spec refinement (idempotency):** the spec says a near-duplicate distil "returns `None`". The real `KnowledgeOracle.add_candidate` returns the *pre-existing* atom on a cosine-dedup hit (not `None`), and `distill` returns whatever `add_candidate` returns. So the orchestrator detects "already bridged" by checking the returned atom's `status` (`active` → skip) rather than a `None`. Same intent (dedup → no rebloat), accurate mechanism. Implemented in Task 3.

---

## File Structure

- **Modify** `agent/oracle.py` — `_active()` gains a force-active env set (2 lines). Single retrieval seam.
- **Modify** `agent/oracle_validate.py` — append `grade_full_run(task_id, force_active_id)` and `validate_atom_via_full_run(atom, task_id, min_score=1.0)`. Reuses the module's harness client + `parse_score`.
- **Create** `scripts/harness_to_oracle.py` — offline CLI: `select_hot_checks`, `_source_artifacts`, `bridge_one`, `main`.
- **Create** `tests/test_oracle_force_active.py` — the retrieval seam.
- **Create** `tests/test_oracle_full_run_validate.py` — the efficacy validator (mocked harness + run_agent).
- **Create** `tests/test_harness_to_oracle.py` — the orchestrator (mocked distil/validate/promote).

Each task is a self-contained, committable change.

> Note: no dedicated worktree was created for this work; implement on the current branch (`heuristics`) unless you choose to branch first.

---

### Task 1: Retrieval injection seam — `oracle._active()` honours `ECOM_ORACLE_FORCE_ACTIVE`

**Files:**
- Modify: `agent/oracle.py:51-52` (`_active`)
- Test: `tests/test_oracle_force_active.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_oracle_force_active.py`:

```python
"""_active() honours ECOM_ORACLE_FORCE_ACTIVE: a candidate atom whose id is listed becomes
retrievable for one run, without mutating its persisted status."""
from agent.oracle import KnowledgeOracle
from agent.oracle_atoms import Atom


def _atom(id_, status):
    return Atom(id=id_, description="d", domain=[], content="c", source="distilled",
                validated_by="", validated_at="", status=status)


def test_force_active_includes_named_candidate(monkeypatch):
    o = KnowledgeOracle(atoms=[_atom("act1", "active"), _atom("cand1", "candidate")])
    monkeypatch.delenv("ECOM_ORACLE_FORCE_ACTIVE", raising=False)
    assert {a.id for a in o._active()} == {"act1"}
    monkeypatch.setenv("ECOM_ORACLE_FORCE_ACTIVE", "cand1")
    assert {a.id for a in o._active()} == {"act1", "cand1"}


def test_force_active_empty_env_is_noop(monkeypatch):
    o = KnowledgeOracle(atoms=[_atom("cand1", "candidate")])
    monkeypatch.setenv("ECOM_ORACLE_FORCE_ACTIVE", "")
    assert o._active() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_oracle_force_active.py -v`
Expected: FAIL — `test_force_active_includes_named_candidate` fails on the second assert (`cand1` not included; `_active` still active-only).

- [ ] **Step 3: Edit `_active()`**

In `agent/oracle.py`, replace:

```python
    def _active(self):
        return [a for a in self.atoms if a.status == "active"]
```

with:

```python
    def _active(self):
        force = {x for x in os.environ.get("ECOM_ORACLE_FORCE_ACTIVE", "").split(",") if x}
        return [a for a in self.atoms if a.status == "active" or a.id in force]
```

(`os` is already imported at the top of `agent/oracle.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_oracle_force_active.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the oracle suite for no regression**

Run: `uv run pytest tests/test_oracle_seed.py -q`
Expected: same result as before this task (the pre-existing `test_seed_atoms_present_and_valid` failure is unrelated — see Task 4; no NEW failures from this change).

- [ ] **Step 6: Commit**

```bash
git add agent/oracle.py tests/test_oracle_force_active.py
git commit -m "feat(oracle): _active honours ECOM_ORACLE_FORCE_ACTIVE retrieval seam"
```

---

### Task 2: Efficacy validator — `grade_full_run` + `validate_atom_via_full_run`

**Files:**
- Modify: `agent/oracle_validate.py` (append at end, after line 76)
- Test: `tests/test_oracle_full_run_validate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_oracle_full_run_validate.py`:

```python
"""Efficacy validator: grade_full_run runs the full agent for a task with the candidate atom
force-active, and validate_atom_via_full_run gates promotion on score >= 1.0."""
import os
import types

import pytest

import agent.oracle_validate as ov
from agent.oracle_atoms import Atom


def _atom(id_="cand1"):
    return Atom(id=id_, description="d", domain=[], content="c", source="distilled",
                validated_by="", validated_at="", status="candidate")


def test_validate_true_when_score_meets_min(monkeypatch):
    monkeypatch.setattr(ov, "grade_full_run", lambda tid, fid: (1.0, []))
    assert ov.validate_atom_via_full_run(_atom(), "t01") is True


def test_validate_false_when_score_below_min(monkeypatch):
    monkeypatch.setattr(ov, "grade_full_run", lambda tid, fid: (0.5, ["x"]))
    assert ov.validate_atom_via_full_run(_atom(), "t01") is False


def test_validate_false_when_grade_raises(monkeypatch):
    def boom(tid, fid):
        raise RuntimeError("no grader")
    monkeypatch.setattr(ov, "grade_full_run", boom)
    assert ov.validate_atom_via_full_run(_atom(), "t01") is False


def _fake_harness(monkeypatch, target_task):
    """Wire a fake harness client + EcomRuntime so grade_full_run drives one matching trial."""
    trial = types.SimpleNamespace(trial_id="trial-1", task_id=target_task,
                                  harness_url="http://vm", instruction="do the thing")
    submit = types.SimpleNamespace(trials=[types.SimpleNamespace(
        task_id=target_task, score=1.0, score_available=True, score_detail=[])])

    class FakeClient:
        def __init__(self, url): pass
        def start_run(self, req): return types.SimpleNamespace(run_id="run-1", trial_ids=["trial-1"])
        def start_trial(self, req): return trial
        def end_trial(self, req): return None
        def submit_run(self, req): return submit

    monkeypatch.setattr(ov, "HarnessServiceClientSync", FakeClient)
    monkeypatch.setattr(ov, "EcomRuntimeClientSync", lambda url: object())
    return trial


def test_grade_full_run_sets_and_clears_force_active(monkeypatch):
    _fake_harness(monkeypatch, "t01")
    seen = {}

    def fake_run_agent(cfg, url, text, task_id=""):
        seen["force"] = os.environ.get("ECOM_ORACLE_FORCE_ACTIVE")
        seen["url"] = url
        return {}

    import agent.orchestrator as orch
    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    monkeypatch.delenv("ECOM_ORACLE_FORCE_ACTIVE", raising=False)

    score, _detail = ov.grade_full_run("t01", "cand1")
    assert score == 1.0
    assert seen["force"] == "cand1"          # set during the run
    assert seen["url"] == "http://vm"
    assert "ECOM_ORACLE_FORCE_ACTIVE" not in os.environ   # cleared after


def test_grade_full_run_clears_force_active_on_raise(monkeypatch):
    _fake_harness(monkeypatch, "t01")

    def boom_run_agent(cfg, url, text, task_id=""):
        raise RuntimeError("pipeline blew up")

    import agent.orchestrator as orch
    monkeypatch.setattr(orch, "run_agent", boom_run_agent)
    monkeypatch.delenv("ECOM_ORACLE_FORCE_ACTIVE", raising=False)

    with pytest.raises(RuntimeError):
        ov.grade_full_run("t01", "cand1")
    assert "ECOM_ORACLE_FORCE_ACTIVE" not in os.environ   # finally cleared even on error
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_oracle_full_run_validate.py -v`
Expected: FAIL — `AttributeError: module 'agent.oracle_validate' has no attribute 'grade_full_run'` (and `validate_atom_via_full_run`).

- [ ] **Step 3: Append the validator to `agent/oracle_validate.py`**

Add at the END of `agent/oracle_validate.py`:

```python
def grade_full_run(task_id, force_active_id):
    """Run `task_id` end-to-end on a fresh StartRun with `force_active_id` force-active in the
    oracle (so a candidate atom is retrievable into PLAN), then return (score, detail).

    The full agent answers the VM itself, so — unlike `grade_candidate` — we do NOT call
    vm.answer here. `run_agent` is imported lazily to avoid an import cycle (this module is
    imported by `agent.pipeline`, which `run_agent` pulls in).
    """
    from agent.orchestrator import run_agent
    c = HarnessServiceClientSync(_URL)
    run = c.start_run(H.StartRunRequest(name=f"bridge-validate-{task_id}",
                                        benchmark_id=_BID, api_key=_KEY))
    for tid in run.trial_ids:
        try:
            t = c.start_trial(H.StartTrialRequest(trial_id=tid))
        except Exception:
            continue
        if t.task_id == task_id:
            os.environ["ECOM_ORACLE_FORCE_ACTIVE"] = force_active_id
            try:
                run_agent({}, t.harness_url, t.instruction, task_id=task_id)
            finally:
                os.environ.pop("ECOM_ORACLE_FORCE_ACTIVE", None)
        try:
            c.end_trial(H.EndTrialRequest(trial_id=t.trial_id))
        except Exception:
            pass
    res = c.submit_run(H.SubmitRunRequest(run_id=run.run_id, force=True))
    return parse_score(res, task_id)


def validate_atom_via_full_run(atom, task_id, min_score: float = 1.0) -> bool:
    """True iff a full end-to-end re-run of `task_id` with `atom` force-active scores >=
    min_score. Best-effort: any failure (no live grader, run error) returns False so the
    atom stays a candidate. Never raises."""
    try:
        score, _detail = grade_full_run(task_id, atom.id)
        return score is not None and score >= min_score
    except Exception:
        return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_oracle_full_run_validate.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/oracle_validate.py tests/test_oracle_full_run_validate.py
git commit -m "feat(oracle): grade_full_run + validate_atom_via_full_run efficacy gate"
```

---

### Task 3: Orchestrator — `scripts/harness_to_oracle.py`

**Files:**
- Create: `scripts/harness_to_oracle.py`
- Test: `tests/test_harness_to_oracle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_to_oracle.py`:

```python
"""Offline harness->oracle bridge orchestration: hot-check selection + per-check
distil->validate->promote routing."""
import types

import scripts.harness_to_oracle as hb
from agent.oracle_atoms import Atom


def _check(id_, kind="primitive_contract", src="t01", msg="m"):
    return {"id": id_, "kind": kind, "source_task": src, "message": msg, "status": "active"}


def test_select_hot_checks_threshold_rank_cap():
    stats = {"chk_a": {"fires": 5}, "chk_b": {"fires": 2}, "chk_c": {"fires": 10},
             "orphan": {"fires": 9}}                       # orphan not in checks -> excluded
    checks = [_check("chk_a"), _check("chk_b"), _check("chk_c")]
    hot = hb.select_hot_checks(stats, checks, min_fires=3, max_atoms=2)
    assert [c["id"] for c in hot] == ["chk_c", "chk_a"]    # ranked desc, capped at 2, chk_b below min


def _candidate_atom(id_="cand1", status="candidate"):
    return Atom(id=id_, description="d", domain=[], content="c", source="distilled",
                validated_by="", validated_at="", status=status)


class _FakeOracle:
    def __init__(self, atom):
        self._atom = atom
        self.promoted = []
        self.distilled = False
    def distill(self, **kw):
        self.distilled = True
        self._last_kw = kw
        return self._atom
    def promote(self, atom_id, validated_by, validated_at):
        self.promoted.append(atom_id)


def test_bridge_one_promotes_on_validation(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: ("objective", "{}"))
    oracle = _FakeOracle(_candidate_atom())
    out = hb.bridge_one(_check("chk_a"), oracle, validate_fn=lambda atom, tid: True)
    assert oracle.promoted == ["cand1"]
    assert "PROMOTED" in out


def test_bridge_one_leaves_candidate_on_failed_validation(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: ("objective", "{}"))
    oracle = _FakeOracle(_candidate_atom())
    out = hb.bridge_one(_check("chk_a"), oracle, validate_fn=lambda atom, tid: False)
    assert oracle.promoted == []
    assert "candidate" in out


def test_bridge_one_skips_when_no_source_artifacts(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: (None, None))
    oracle = _FakeOracle(_candidate_atom())
    out = hb.bridge_one(_check("chk_a", src=""), oracle, validate_fn=lambda atom, tid: True)
    assert oracle.distilled is False and oracle.promoted == []
    assert "skip" in out


def test_bridge_one_skips_already_bridged(monkeypatch):
    monkeypatch.setattr(hb, "_source_artifacts", lambda src: ("objective", "{}"))
    oracle = _FakeOracle(_candidate_atom(status="active"))   # dedup returned an active atom
    out = hb.bridge_one(_check("chk_a"), oracle, validate_fn=lambda atom, tid: True)
    assert oracle.promoted == []
    assert "already bridged" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_harness_to_oracle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.harness_to_oracle'`.

- [ ] **Step 3: Create `scripts/harness_to_oracle.py`**

```python
#!/usr/bin/env python3
"""Offline harness->oracle "teach" bridge: turn frequently-firing data/harness/checks.yaml
checks into validated positive oracle method-atoms.

Per hot check: distil a candidate `method` atom seeded by the check's contract, validate it by
re-running the check's source task end-to-end with the candidate force-active in PLAN, and
promote (candidate->active) on a grader score of 1.0. Reuses the oracle distil/validate/promote
machinery. Offline — grader round-trips happen out of band.

Usage:  uv run python scripts/harness_to_oracle.py [trace_dir]   (default: logs)
"""
from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from agent import harness
from agent.oracle import KnowledgeOracle
from agent.oracle_validate import validate_atom_via_full_run
from scripts.lint_report import aggregate


def select_hot_checks(stats, checks, min_fires, max_atoms):
    """Checks that fired >= min_fires, ranked by fires desc, capped at max_atoms.
    `stats` is the lint_report aggregate (check_id -> {fires, ...}); `checks` is
    harness.load_checks() (list of spec dicts). A check_id present in `stats` but absent
    from `checks` is ignored."""
    by_id = {c.get("id", ""): c for c in checks}
    hot = [(s.get("fires", 0), by_id[cid]) for cid, s in stats.items()
           if s.get("fires", 0) >= min_fires and cid in by_id]
    hot.sort(key=lambda t: t[0], reverse=True)
    return [c for _f, c in hot[:max_atoms]]


def _source_artifacts(source_task):
    """(objective, good_plan_json) for the check's source task, or (None, None) when the
    persisted intent/plan are missing."""
    heur = Path("data/heuristics")
    ip, pp = heur / f"{source_task}.intent.json", heur / f"{source_task}.plan.json"
    if not (source_task and ip.exists() and pp.exists()):
        return None, None
    try:
        from agent.ir_models import IntentSpec
        intent = IntentSpec.model_validate_json(ip.read_text(encoding="utf-8"))
        return intent.objective, pp.read_text(encoding="utf-8")
    except Exception:
        return None, None


def bridge_one(check, oracle, validate_fn=validate_atom_via_full_run):
    """distil -> validate -> promote for ONE hot check. Returns a one-line outcome string.
    Never raises."""
    cid = check.get("id", "")
    src = check.get("source_task", "")
    objective, good_plan = _source_artifacts(src)
    if objective is None:
        return f"{cid}: skip (no source_task / no known-good artifacts)"
    seed = (f"Avoid the anti-pattern caught by lint check '{cid}' "
            f"({check.get('kind', '')}): {check.get('message', '')}. "
            f"State the correct method generally.")
    try:
        atom = oracle.distill(design_intent=objective, error=seed, script_code=good_plan,
                              source_task=src, polarity="method", status="candidate")
    except Exception as e:
        return f"{cid}: skip (distill error: {e})"
    if atom is None:
        return f"{cid}: skip (distill produced nothing)"
    if atom.status == "active":
        return f"{cid}: skip (already bridged -> {atom.id})"
    if not validate_fn(atom, src):
        return f"{cid}: distilled {atom.id} (candidate; validation < 1.0)"
    oracle.promote(atom.id, validated_by="harness-bridge", validated_at=str(date.today()))
    return f"{cid}: PROMOTED {atom.id} (grader 1.0)"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Distil + auto-promote oracle method-atoms from hot lint checks.")
    ap.add_argument("trace_dir", nargs="?", default="logs",
                    help="directory scanned recursively for *.jsonl lint_fire telemetry (default: logs)")
    args = ap.parse_args(argv)
    min_fires = int(os.environ.get("ECOM_BRIDGE_MIN_FIRES", "3"))
    max_atoms = int(os.environ.get("ECOM_BRIDGE_MAX_ATOMS", "3"))
    stats = aggregate(args.trace_dir)
    checks = harness.load_checks()
    hot = select_hot_checks(stats, checks, min_fires, max_atoms)
    if not hot:
        print(f"no hot checks (>= {min_fires} fires) in {args.trace_dir}")
        return
    oracle = KnowledgeOracle()
    for check in hot:
        print(bridge_one(check, oracle))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_harness_to_oracle.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Smoke-run the script**

Run: `uv run python scripts/harness_to_oracle.py /tmp/nonexistent-dir-xyz`
Expected: prints `no hot checks (>= 3 fires) in /tmp/nonexistent-dir-xyz` (empty aggregate → no hot checks; no crash).

- [ ] **Step 6: Commit**

```bash
git add scripts/harness_to_oracle.py tests/test_harness_to_oracle.py
git commit -m "feat(scripts): harness_to_oracle teach-bridge orchestrator"
```

---

### Task 4: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite, excluding the pre-existing broken collection file**

Run: `uv run python -m pytest tests/ -q --ignore=tests/test_gen_excalidraw.py`
Expected: the 3 new test files pass (2 + 5 + 5 = 12 new tests). The pre-existing failures (`test_architecture_guide_refs.py`, `test_corpus_replay.py`, `test_learned_t01_method_rule.py`, `test_oracle_seed.py`, `test_reason_prompts.py`) are unrelated to this change — they fail identically on the base commit (confirmed in the prior slice: missing architecture-guide doc, modified `data/learned`+`data/oracle` working-tree files, replay fixtures). If the ONLY failures are that known set and the 12 new tests pass, the task is green.

- [ ] **Step 2: Confirm no NEW failures**

Compare the failing-test set against the known pre-existing set above. If a failure appears that is NOT in that set, STOP and investigate — it is a regression from this change.

- [ ] **Step 3: Commit (only if an incidental fixup was required)**

```bash
git add -A
git commit -m "test: full-suite green for harness-oracle teach bridge"
```

If Step 1 showed only the known pre-existing failures plus the 12 new passes, skip this commit.

---

## Self-Review

**1. Spec coverage:**
- Offline orchestrator (read telemetry → hot checks → distil→validate→promote, cap, skip reasons) → Task 3. ✓
- Distil seeded by check contract (kind+message), `polarity="method"`, candidate → Task 3 `bridge_one`. ✓
- Efficacy validator (full end-to-end re-run with candidate force-active, score≥1.0) → Task 2. ✓
- Retrieval seam (`ECOM_ORACLE_FORCE_ACTIVE` in `_active`) → Task 1. ✓
- Env vars `ECOM_BRIDGE_MIN_FIRES` / `ECOM_BRIDGE_MAX_ATOMS` / `ECOM_ORACLE_FORCE_ACTIVE` → Tasks 3 (`main`), 2 (`grade_full_run`). ✓
- Idempotency via dedup → Task 3 (`atom.status == "active"` skip; refines the spec's "returns None" — noted in header). ✓
- Error handling: per-check try/except, best-effort validator returns False, env cleared in `finally`, promote-only-on-pass → Tasks 2 & 3. ✓
- Non-goals (no in-pipeline hook, no anti→check, no ledger, no HTML) → respected; no task adds them. ✓
- Testing items (force-active, validator score-gate + env discipline, orchestrator selection/routing) → Tasks 1-3 tests. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has an expected result. ✓

**3. Type consistency:** `grade_full_run(task_id, force_active_id)` defined in Task 2 is called by `validate_atom_via_full_run(atom, task_id, min_score=1.0)` as `grade_full_run(task_id, atom.id)` (same arg order). `validate_atom_via_full_run(atom, task_id)` is the `validate_fn` signature used by `bridge_one` in Task 3 (`validate_fn(atom, src)`). `oracle.distill(design_intent=, error=, script_code=, source_task=, polarity=, status=)` matches the real signature. `oracle.promote(atom_id, validated_by, validated_at)` matches. `Atom(...)` constructor fields match `agent/oracle_atoms.py`. `select_hot_checks(stats, checks, min_fires, max_atoms)` and `_source_artifacts(source_task)` signatures are consistent between the script and its tests. ✓
