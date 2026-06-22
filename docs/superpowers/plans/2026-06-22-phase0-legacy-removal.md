---
review:
  plan_hash: 6dc1865e6a43fbc6
  spec_hash: 47f7f6d60c12ccda
  last_run: 2026-06-22
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings: []
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-22-phase0-current-impl-audit-legacy-removal-design.md
---

# Phase 0 — Legacy Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Subtractively shrink `agent/` by removing three unproven default-off experiments (harness-distill, INVESTIGATE data-paths, in-pipeline oracle-distill), pruning ~1149 inactive LEARN rules, and measuring whether Oracle retrieval is load-bearing — without dropping a single benchmark task.

**Architecture:** Each removal is an isolated subtractive commit. The deterministic INTENT→INVESTIGATE→PLAN→verify skeleton is untouched. `cc_client.py` is KEPT (separate benchmark-passing LLM tier — explicitly NOT removed). The harness **lint** engine (`load_checks`/`handler_for`/`_HANDLERS`, used by `interpreter.lint()`) STAYS; only the harness *distill* block is removed. The oracle *retrieval-into-PLAN* path STAYS pending a load-bearing measurement (decision-gated, Task 7); only the in-pipeline *distill* round-trips are removed. The offline `harness_to_oracle` bridge and `oracle_validate.py` STAY.

**Tech Stack:** Python 3, `uv` (deps + runner), `pytest`, PyYAML, Pydantic. Source spec: `docs/superpowers/specs/2026-06-22-phase0-current-impl-audit-legacy-removal-design.md`.

**Removal discipline (every removal task):** full suite green BEFORE → delete code + its tests + dead imports → full suite green AFTER → grep guard confirms no orphan reference → commit. A regression that survives the grep guard but reds a benchmark task proves that subsystem load-bearing → revert that one commit and document (per the spec's load-bearing threshold).

---

## File Structure

| File | Phase 0 change |
|------|----------------|
| `agent/harness.py` | MODIFY — delete distill block (`_DISTILL_SYS`, `distill`, `promote`, `save_checks`) + dead `call_llm_json` import; KEEP all lint handlers + `load_checks`/`handler_for`/`_HANDLERS` |
| `agent/harness_validate.py` | DELETE (whole file; only the removed harness-distill path used it) |
| `agent/pipeline.py` | MODIFY — delete `_load_good_plan`, `_maybe_harness_distill`, `_distill_call`, `_maybe_distill_and_validate`, `_brief_lessons_text`, `_data_path_seed`, their call sites + dead imports; KEEP `distill_from_grader`, oracle retrieval, brief→PLAN injection |
| `agent/investigate.py` | MODIFY — drop `data_paths` param + `_forced_data_probe` + data-probe loop; KEEP slim seed, `sufficient()`, ReAct loop, `investigate_stop` trace |
| `agent/trace.py` | MODIFY (cosmetic) — `log_investigate_stop` docstring drops the `ECOM_INVESTIGATE_DATA_PATHS` mention; record kept, always logs `(0,0)` |
| `scripts/prune_inactive_rules.py` | CREATE — prune `status != active` (non-`pinned`) entries from `data/learned/*.yaml` |
| `tests/test_prune_inactive_rules.py` | CREATE — TDD for the prune script |
| `tests/test_harness_distill.py` | DELETE (harness-distill only) |
| `tests/test_pipeline_distill.py` | DELETE (in-pipeline oracle-distill only) |
| `tests/test_investigate.py`, `tests/test_pipeline_interpreted.py`, `tests/test_pipeline_investigate.py` | MODIFY — delete data-paths flag-ON tests; fix one mock signature |
| `.env.example`, `CLAUDE.md`, `agent/CLAUDE.md` | MODIFY — strip now-dead env vars |
| `docs/wiki/{harness,pipeline,investigate,learning,data-files}.md` | REGENERATE via `iwiki:iwiki-ingest` |

---

### Task 1: Remove the harness-distill path (keep the lint engine)

**Files:**
- Modify: `agent/harness.py` (delete lines 195–239 distill block; lines 39–43 `save_checks`; line 19 import)
- Delete: `agent/harness_validate.py`
- Modify: `agent/pipeline.py` (delete `_load_good_plan`, `_maybe_harness_distill`, call site, comment banner)
- Delete: `tests/test_harness_distill.py`

- [ ] **Step 1: Baseline — full suite green before any edit**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS (record the pass count; this is the pre-removal baseline). Note any pre-existing reds (e.g. `test_corpus_replay`/t09 parity is a known stale fixture, not caused by this work).

- [ ] **Step 2: Strip the distill block from `agent/harness.py`**

Delete the import on line 19 (only `distill()` used it):
```python
from .llm import call_llm_json
```

Delete `save_checks` (lines 39–43 — only the distill block calls it):
```python
def save_checks(checks: list[dict], path=None) -> None:
    p = Path(path or _DEFAULT_CHECKS)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(checks, sort_keys=False, allow_unicode=True, width=100),
                 encoding="utf-8")
```

Delete the entire distill section (lines 195–239 — from the `# --- F8b:` banner through the end of `promote()`):
```python
# --- F8b: distill -> validate -> promote (gated off by default) -------------

_DISTILL_SYS = (
    "Distill ONE reusable plan-time CHECK-SPEC from an interpreter contract failure. "
    "Return JSON for a single check of an EXISTING kind "
    "(primitive_contract|sql_stdin|primitive_exists|primitive_arity): "
    "{id, kind, prim?, arg_index?, forbid_source?, severity:'error', message}. "
    "Only the closed structural fields — never natural-language logic."
)


def distill(plan, error, source_task=""):
    """Propose a `candidate` check-spec generalised from a failing step. LLM, reason
    tier; never raises. Returns the appended spec dict, or None (unknown kind, dup id,
    or no usable response). Caller gates on HARNESS_DISTILL."""
    from .llm import _resolve_model_for_phase
    user = f"PLAN:\n{plan.model_dump_json()[:4000]}\n\nERROR:\n{error}\n\nReturn the check JSON."
    try:
        out = call_llm_json(_DISTILL_SYS, user,
                            _resolve_model_for_phase("distill", os.environ.get("ECOM_MODEL", "")),
                            phase="HARNESS_DISTILL")
    except Exception:
        return None
    if not isinstance(out, dict) or out.get("kind") not in _HANDLERS:
        return None
    checks = load_checks()
    if any(c.get("id") == out.get("id") for c in checks):
        return None
    spec = {**out, "status": "candidate", "source_task": source_task}
    checks.append(spec)
    save_checks(checks)
    return spec


def promote(check_id, path=None) -> bool:
    """Flip a candidate check-spec to active. Returns True if found."""
    checks = load_checks(path)
    found = False
    for c in checks:
        if c.get("id") == check_id:
            c["status"] = "active"
            found = True
    if found:
        save_checks(checks, path)
    return found
```

Leave everything in lines 1–193 intact (`load_checks`, all `check_*` handlers, `_HANDLERS`, `handler_for`) — `interpreter.lint()` depends on them.

- [ ] **Step 3: Delete the file `agent/harness_validate.py`**

Run: `git rm agent/harness_validate.py`

- [ ] **Step 4: Strip the harness-distill hook from `agent/pipeline.py`**

Delete the comment banner (the three lines immediately before `_load_good_plan`):
```python
# ---------------------------------------------------------------------------
# F8b: gated distill -> validate -> promote hook
# ---------------------------------------------------------------------------
```

Delete `_load_good_plan`:
```python
def _load_good_plan(task_id):
    """Last persisted successful PlanIR for this task (known-good), or None. Persisted
    only on a success path (_persist_artifacts), so it exists once the task has passed
    at least once — the false-positive reference for inline check validation."""
    pp = Path("data/heuristics") / f"{task_id}.plan.json"
    if not pp.exists():
        return None
    try:
        from .ir_models import PlanIR
        return PlanIR.model_validate_json(pp.read_text(encoding="utf-8"))
    except Exception:
        return None
```

Delete `_maybe_harness_distill`:
```python
def _maybe_harness_distill(plan, error, task_id) -> None:
    """F8b (gated HARNESS_DISTILL=1, default 0): after an F1-class compute contract
    failure, propose a `candidate` check-spec. When HARNESS_VALIDATE_INLINE=1 (default),
    validate it — the candidate MUST flag this failing plan AND must NOT flag the last
    known-good plan — and promote (candidate -> active) on success; otherwise it stays a
    warn-only candidate for an offline promote. Never raises (cannot dead-end a run)."""
    if os.environ.get("ECOM_HARNESS_DISTILL", "0") != "1":
        return
    if "compute step" not in error and "custom_extract" not in error:
        return
    try:
        from . import harness
        candidate = harness.distill(plan, error, source_task=task_id)
        if not candidate or os.environ.get("ECOM_HARNESS_VALIDATE_INLINE", "1") != "1":
            return
        from .harness_validate import validate_check_via_grader
        if validate_check_via_grader(candidate, plan, _load_good_plan(task_id)):
            harness.promote(candidate["id"])
            print(f"{CLI_GREEN}[pipeline] check {candidate['id']} promoted (validated){CLI_CLR}")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] harness distill skipped: {e}{CLI_CLR}")
```

Delete the lone call site inside the `InterpretError` branch (the only `_maybe_harness_distill(...)` line):
```python
            _maybe_harness_distill(plan, last_error, task_id)
```

- [ ] **Step 5: Delete the test file `tests/test_harness_distill.py`**

Run: `git rm tests/test_harness_distill.py`

- [ ] **Step 6: Full suite green after removal**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS at the SAME pass count as Step 1 (minus the deleted `test_harness_distill.py` tests). Pay special attention to `tests/test_harness.py` and `tests/test_lint_telemetry.py` — they exercise the retained lint engine and MUST stay green.

- [ ] **Step 7: Grep guard — confirm no orphan references**

Run: `grep -rn "harness_validate\|_maybe_harness_distill\|_load_good_plan\|HARNESS_DISTILL\|HARNESS_VALIDATE\|\bsave_checks\b" agent/ tests/`
Expected: NO output. (The lint engine references `harness.load_checks`/`harness.handler_for` in `interpreter.py` only — those names are not in the pattern, so they correctly do not appear.)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(harness): remove unproven harness-distill path, keep lint engine

ECOM_HARNESS_DISTILL was default-off and never enabled in scoring runs.
Removes the distill->validate->promote block from harness.py, deletes
harness_validate.py, and removes the pipeline hook. The lint handlers
(load_checks/handler_for/_HANDLERS) that interpreter.lint() depends on
are untouched.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Remove the in-pipeline oracle-distill paths (keep retrieval + offline bridge)

**Files:**
- Modify: `agent/pipeline.py` (delete `_distill_call`, `_maybe_distill_and_validate`, `_brief_lessons_text`, lessons-enrichment block, call site, line-14 import)
- Delete: `tests/test_pipeline_distill.py`

- [ ] **Step 1: Baseline green**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS (continues from Task 1's commit).

- [ ] **Step 2: Delete the top-of-file import in `agent/pipeline.py` (line 14)**

```python
from .oracle_validate import validate_atom_via_grader
```
(Only `_maybe_distill_and_validate` used it. KEEP the lazy `from .oracle import KnowledgeOracle` inside `_new_oracle()` and `from datetime import date` — `distill_from_grader` still needs them.)

- [ ] **Step 3: Delete `_brief_lessons_text`**

```python
def _brief_lessons_text(brief) -> str:
    """One-line-per-step lessons from an investigation brief, for distillation."""
    if brief is None or not getattr(brief, "notes", None):
        return ""
    return "\n".join(f"- {n.lesson}" for n in brief.notes if n.lesson)
```

- [ ] **Step 4: Delete `_distill_call` and `_maybe_distill_and_validate`**

```python
def _distill_call(oracle, intent, plan, task_id, outcome_note):
    # `error` param is repurposed as a short success note; the distill prompt
    # strips all run-specific values, so a success note is fine (spec §Distill).
    return oracle.distill(design_intent=intent.objective,
                          error=outcome_note,
                          script_code=plan.model_dump_json(),
                          source_task=task_id)


def _maybe_distill_and_validate(intent, plan, task_id, outcome_note) -> None:
    """On a successful cycle, distill a candidate atom (ORACLE_DISTILL=1) and,
    when ORACLE_VALIDATE_INLINE=1, grader-validate then promote. Never raises."""
    if (os.environ.get("ECOM_ORACLE_ENABLED", "1") == "0"
            or os.environ.get("ECOM_ORACLE_DISTILL", "0") != "1"):
        return
    try:
        oracle = _new_oracle()
        atom = _distill_call(oracle, intent, plan, task_id, outcome_note)
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] oracle distill skipped: {e}{CLI_CLR}")
        return
    if not atom or os.environ.get("ECOM_ORACLE_VALIDATE_INLINE", "1") != "1":
        return
    try:
        if validate_atom_via_grader(atom, task_id, intent, plan):
            oracle.promote(atom.id, validated_by="grader-oracle",
                           validated_at=str(date.today()))
            print(f"{CLI_GREEN}[pipeline] atom {atom.id} promoted (grader-validated){CLI_CLR}")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] atom promote skipped: {e}{CLI_CLR}")
```

- [ ] **Step 5: Delete the success-path call site + its lessons-enrichment block**

Delete these lines (the lessons enrichment immediately precedes the distill call on the success path):
```python
            _lessons = _brief_lessons_text(brief)
            if _lessons:
                _note = _note + "\nINVESTIGATION_LESSONS:\n" + _lessons
            _maybe_distill_and_validate(intent, plan, task_id, _note)
```
If `_note` is now unused on the success path after this deletion, remove the line that builds `_note` as well. Verify by reading the surrounding success block; keep `_persist_artifacts`, `answer_once`, `save_last_run`, and the `return {...}` metrics intact.

- [ ] **Step 6: Delete the test file `tests/test_pipeline_distill.py`**

Run: `git rm tests/test_pipeline_distill.py`

- [ ] **Step 7: Full suite green**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS. `tests/test_oracle_distill.py`, `tests/test_oracle_validate.py`, `tests/test_oracle_promote.py`, `tests/test_oracle_full_run_validate.py`, `tests/test_harness_to_oracle.py` MUST stay green — they cover the oracle module + offline bridge that we KEPT.

- [ ] **Step 8: Grep guard**

Run: `grep -rn "_maybe_distill_and_validate\|_distill_call\|_brief_lessons_text\|validate_atom_via_grader\|ORACLE_DISTILL\|ORACLE_VALIDATE_INLINE" agent/ tests/`
Expected: NO output. (`distill_from_grader`, `oracle.distill`, `oracle.promote`, `validate_atom_via_full_run` are NOT in the pattern and correctly remain.)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(pipeline): remove in-pipeline oracle-distill round-trips

ECOM_ORACLE_DISTILL/ECOM_ORACLE_VALIDATE_INLINE were default-off and fired
expensive live grader round-trips mid-run. Removes the in-cycle distill ->
validate -> promote hook and its brief-lessons enrichment. Oracle
retrieval-into-PLAN, the offline harness_to_oracle bridge, oracle_validate.py,
and the post-trial distill_from_grader path are all KEPT.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Remove the INVESTIGATE data-paths branch (keep slim seed + stop trace)

**Files:**
- Modify: `agent/pipeline.py` (delete `_data_path_seed`, simplify the `investigate(...)` call)
- Modify: `agent/investigate.py` (drop `data_paths` param, `_forced_data_probe`, the data-probe loop)
- Modify: `agent/trace.py` (docstring only)
- Modify: `tests/test_investigate.py`, `tests/test_pipeline_interpreted.py`, `tests/test_pipeline_investigate.py`

- [ ] **Step 1: Baseline green**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS (continues from Task 2's commit).

- [ ] **Step 2: Delete `_data_path_seed` from `agent/pipeline.py`**

```python
def _data_path_seed(instruction: str, task_id: str) -> list[str]:
    """Deterministic data-path seed for INVESTIGATE: absolute-path literals in the
    instruction UNION learned prephase_deep_read absolute paths. Empty (no-op) unless
    ECOM_INVESTIGATE_DATA_PATHS=1. Bounded by ECOM_PREPHASE_PATH_LITERALS — no wandering.
    Imports are function-level: orchestrator imports pipeline, so a module-level import
    here would be a cycle; by call time orchestrator is fully loaded."""
    import os as _os
    if _os.environ.get("ECOM_INVESTIGATE_DATA_PATHS", "0") != "1":
        return []
    from .orchestrator import _extract_path_literals
    from .learned_store import load_prephase_deep_read
    seed = list(_extract_path_literals(instruction))
    for d in load_prephase_deep_read(task_id):
        if d.startswith("/") and d not in seed:
            seed.append(d)
    return seed
```

- [ ] **Step 3: Simplify the `investigate(...)` call site in `agent/pipeline.py`**

Before:
```python
            brief = investigate(vm, intent, seed=facts, oracle=_oracle,
                                data_paths=_data_path_seed(instruction, task_id))
```
After:
```python
            brief = investigate(vm, intent, seed=facts, oracle=_oracle)
```

- [ ] **Step 4: Drop the data-paths machinery from `agent/investigate.py`**

(a) Signature — remove the `data_paths` parameter:
```python
def investigate(vm, intent, seed=None, oracle=None, max_steps: int | None = None) -> "Brief":
```

(b) Delete these two locals near the top of the function body (`probed` and `data_seed` are only used by the data-probe path):
```python
    probed: set[str] = set()
```
```python
    data_seed = list(data_paths or [])
```

(c) Delete the `probe_seed = None` initialiser line inside the loop:
```python
                probe_seed = None
```

(d) Delete the priority-2 data-probe block:
```python
                if act is None:
                    while True:   # priority 2: probe seed data-paths (probe-once)
                        dp = _forced_data_probe(data_seed, probed)
                        if dp is None:
                            break
                        probed.add(dp["_seed"])           # mark probed regardless of outcome
                        if tool_signature(dp["tool"], dp["args"]) not in seen:
                            act = {"tool": dp["tool"], "args": dp["args"]}  # NB: drop _seed before dispatch
                            probe_seed = dp["_seed"]
                            break
                        # already fetched under another step → try the next seed
```

(e) Delete the probe-seed surfacing block:
```python
                if probe_seed is not None:                # surface the probed data-path for PLAN
                    brief.env.setdefault("data_paths", {})[probe_seed] = (observation or "")[:200]
```

(f) Simplify the sufficiency check:
Before:
```python
                if sufficient(intent, brief.env, data_seed, probed):
                    stop_reason = "data_probed" if data_seed else "sufficient"
                    break
```
After:
```python
                if sufficient(intent, brief.env):
                    stop_reason = "sufficient"
                    break
```

(g) Simplify the stop-trace emit (the record stays for A/B; counts are now always 0):
Before:
```python
        log_investigate_stop_auto(stop_reason, len(data_seed), len(probed))
```
After:
```python
        log_investigate_stop_auto(stop_reason, 0, 0)
```

(h) Delete `_forced_data_probe` entirely:
```python
def _forced_data_probe(data_paths, probed: set) -> "dict | None":
    """Return a read-only action for the first un-probed seed data-path, or None.
    Probe-tool heuristic: a '.' in the basename ⇒ a file ⇒ `read`; otherwise a directory
    ⇒ `list`. The caller marks the path probed (probe-once) when it dispatches, and must drop the
    `_seed` key before passing the action to run_tool/tool_signature."""
    for p in data_paths or []:
        if p in probed:
            continue
        base = p.rsplit("/", 1)[-1]
        tool = "read" if "." in base else "list"
        return {"tool": tool, "args": {"path": p}, "_seed": p}
    return None
```

Leave `sufficient()` unchanged — its `data_paths`/`probed` parameters default to `None`, so calling it with two args is inert (pre-feature baseline).

- [ ] **Step 5: Trace docstring cleanup in `agent/trace.py`**

In `log_investigate_stop`, remove the `ECOM_INVESTIGATE_DATA_PATHS` clause from the docstring (the method and the `investigate_stop` record stay). Change:
```python
        """Why the investigator stopped (sufficient | budget | data_probed) and how many
        seed data-paths it probed. Lets an A/B run compare flag-off vs flag-on
        (ECOM_INVESTIGATE_DATA_PATHS)."""
```
to:
```python
        """Why the investigator stopped (sufficient | budget). Retained as A/B telemetry;
        data-path counts are always 0 after the data-paths branch was removed."""
```

- [ ] **Step 6: Remove the data-paths tests**

Read each file first, then delete ONLY these flag-ON test functions from `tests/test_investigate.py`:
`test_forced_data_probe_picks_first_unprobed_dir_then_file`, `test_forced_data_probe_none_when_all_probed_or_empty`, `test_sufficient_false_when_data_path_unprobed`, `test_sufficient_true_when_all_data_paths_probed`, `test_investigate_probes_seed_data_path_and_records`, `test_investigate_requires_both_doc_ref_and_data_path`.

For `test_investigate_emits_stop_trace` (and any test asserting `data_paths_total`/`data_paths_probed`): keep the test but change its expectation to `0` for both count fields and stop passing `data_paths=`.

From `tests/test_pipeline_interpreted.py` delete: `test_data_path_seed_empty_when_flag_off`, `test_data_path_seed_unions_literals_and_deep_read`.

In `tests/test_pipeline_investigate.py`, update the `fake_investigate(...)` mock stub signature to match the new `investigate()` — drop the `data_paths=None` keyword so the monkeypatched stub matches the real call.

Locate them with:
```bash
grep -rn "data_path\|data_paths\|_forced_data_probe\|data_probed" tests/
```

- [ ] **Step 7: Full suite green**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS. The baseline INVESTIGATE tests (`test_sufficient_*` ref-grounding, `test_investigate_stops_on_sufficiency`, `test_investigate_respects_budget`, `test_investigate_escalates_on_empty`, `test_investigate_steps_appear_in_trace`) MUST stay green — they prove the slim seed + ReAct loop are intact.

- [ ] **Step 8: Grep guard**

Run: `grep -rn "ECOM_INVESTIGATE_DATA_PATHS\|_data_path_seed\|_forced_data_probe\|data_probed\|load_prephase_deep_read" agent/ tests/`
Expected: NO output in `agent/`. (`ECOM_PREPHASE_PATH_LITERALS` and `_extract_path_literals` are KEPT — they feed the prephase slim seed, not the data-paths branch — and must NOT appear here because they are not in the pattern.)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(investigate): remove unproven data-paths seed/probe branch

ECOM_INVESTIGATE_DATA_PATHS was default-off and UNPROVEN (no measured A/B lift).
Removes _data_path_seed, _forced_data_probe, and the priority-2 probe loop.
The slim INVESTIGATE seed, sufficient(), the ReAct loop, and the investigate_stop
trace record are all KEPT (the trace now always reports 0 probed paths).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Prune inactive LEARN rules

**Background:** `learned_store.load_entries(tid)` loads ONLY `status == "active"` entries — inactive rules never reach runtime, so pruning them is behaviour-neutral. ~1149 inactive entries across 55 files (~85%). `pinned: true` rules (currently zero in data) must be preserved even when inactive. The deletion commit IS the archive — git history retains the pruned content (spec's "git history note" option); do not also write a `legacy/` copy.

**Files:**
- Create: `scripts/prune_inactive_rules.py`
- Create: `tests/test_prune_inactive_rules.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prune_inactive_rules.py`:
```python
import yaml
from scripts.prune_inactive_rules import prune_entries


def test_prune_keeps_active_drops_inactive_unpinned():
    data = {
        "task_id": "tX",
        "entries": [
            {"id": "r1", "status": "active", "content": "keep me"},
            {"id": "r2", "status": "inactive", "content": "drop me"},
            {"id": "r3", "status": "inactive", "pinned": True, "content": "pinned survives"},
            {"id": "v1", "status": "active", "source": "verdict", "content": None},
        ],
        "last_run": {"status": "failure", "outcome": "X", "cycles_used": 2, "date": "2026-06-22"},
    }
    pruned, dropped = prune_entries(data)
    ids = [e["id"] for e in pruned["entries"]]
    assert ids == ["r1", "r3", "v1"]          # active kept, pinned-inactive kept, inactive-unpinned dropped
    assert dropped == 1
    assert pruned["last_run"] == data["last_run"]   # metadata untouched
    assert pruned["task_id"] == "tX"


def test_prune_empty_entries_is_noop():
    data = {"task_id": "tY", "entries": []}
    pruned, dropped = prune_entries(data)
    assert dropped == 0
    assert pruned["entries"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_prune_inactive_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.prune_inactive_rules'` (or import error for `prune_entries`).

- [ ] **Step 3: Write the script**

Create `scripts/prune_inactive_rules.py`:
```python
"""Phase 0 prune: drop inactive (status != 'active'), non-pinned entries from
data/learned/*.yaml. Behaviour-neutral — learned_store.load_entries() loads only
active entries, so inactive rules never reach runtime. Pinned entries always survive.
The git commit IS the archive (history retains pruned content); no legacy/ copy.

Usage:
    uv run python scripts/prune_inactive_rules.py            # prune all data/learned/*.yaml
    uv run python scripts/prune_inactive_rules.py --dry-run  # report counts only
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_LEARNED_DIR = Path(__file__).resolve().parent.parent / "data" / "learned"


def prune_entries(data: dict) -> tuple[dict, int]:
    """Return (pruned_data, dropped_count). Keep an entry iff status == 'active' OR
    pinned is truthy. All non-`entries` keys (task_id, last_run, ...) pass through."""
    entries = data.get("entries", []) or []
    kept = [e for e in entries
            if e.get("status") == "active" or e.get("pinned")]
    dropped = len(entries) - len(kept)
    out = dict(data)
    out["entries"] = kept
    return out, dropped


def prune_file(path: Path, dry_run: bool = False) -> int:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pruned, dropped = prune_entries(data)
    if dropped and not dry_run:
        path.write_text(
            yaml.safe_dump(pruned, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
    return dropped


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    total = 0
    files = sorted(_LEARNED_DIR.glob("*.yaml"))
    for p in files:
        d = prune_file(p, dry_run=dry_run)
        if d:
            print(f"{'[dry] ' if dry_run else ''}{p.name}: dropped {d}")
        total += d
    print(f"{'[dry] ' if dry_run else ''}Total dropped across {len(files)} files: {total}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_prune_inactive_rules.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Capture the pre-prune active-rule fingerprint (behaviour-neutrality proof)**

Run: `grep -hc "status: active" data/learned/*.yaml | paste -sd+ | bc`
Record the number (active entries that load_entries will keep loading). Also record inactive: `grep -h "status: inactive" data/learned/*.yaml | wc -l` (expected ~1149).

- [ ] **Step 6: Dry-run, then prune**

Run: `uv run python scripts/prune_inactive_rules.py --dry-run`
Expected: per-file dropped counts; total ≈ 1149.

Run: `uv run python scripts/prune_inactive_rules.py`
Expected: same totals, files rewritten.

- [ ] **Step 7: Verify active count unchanged + suite green**

Run: `grep -hc "status: active" data/learned/*.yaml | paste -sd+ | bc`
Expected: IDENTICAL to Step 5 (no active rule lost). Then:
Run: `uv run python -m pytest tests/ -q`
Expected: PASS (`tests/test_learned_store.py`, `tests/test_learned_store_cap.py` green — pruning does not touch the active surface).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore(learn): prune ~1149 inactive rules from data/learned/*.yaml

84% of LEARN rules were deactivated accretion. load_entries() loads only active
rules, so pruning inactive (non-pinned) entries is behaviour-neutral. Adds
scripts/prune_inactive_rules.py (+ test). Pruned content is retained in git
history (the archive); active and pinned rules are preserved unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Strip now-dead env vars from docs

**Files:**
- Modify: `.env.example` (lines 53, 90–91, 95–96)
- Modify: `CLAUDE.md` (repo root — env-var table rows)
- Modify: `agent/CLAUDE.md` (line 21 INVESTIGATE controls list)

- [ ] **Step 1: Strip from `.env.example`**

Delete these lines:
```
# ECOM_INVESTIGATE_DATA_PATHS=0   # 1 → INVESTIGATE probes seed data-paths before stopping (A/B; default 0)
```
```
ECOM_ORACLE_DISTILL=0                     # 1 = auto-distill candidate atoms after a successful cycle
ECOM_ORACLE_VALIDATE_INLINE=1             # 1 → grader-validate distilled atoms inline (only when ECOM_ORACLE_DISTILL=1)
```
```
ECOM_HARNESS_DISTILL=0                    # 1 = after an F1-class compute contract failure, distill a candidate lint check-spec (LLM, reason tier); default 0 (no cost)
ECOM_HARNESS_VALIDATE_INLINE=1            # 1 (default) → validate a distilled candidate (must flag the failing plan ∧ not the last known-good) and promote; only meaningful when ECOM_HARNESS_DISTILL=1
```
KEEP `ECOM_PREPHASE_PATH_LITERALS=3` (line 44) — still used by the prephase slim seed.

- [ ] **Step 2: Strip from root `CLAUDE.md`**

Delete the table rows for `ECOM_HARNESS_DISTILL`, `ECOM_HARNESS_VALIDATE_INLINE`, `ECOM_ORACLE_DISTILL`, `ECOM_ORACLE_VALIDATE_INLINE`, and `ECOM_INVESTIGATE_DATA_PATHS`. Locate with:
```bash
grep -n "ECOM_HARNESS_DISTILL\|ECOM_HARNESS_VALIDATE_INLINE\|ECOM_ORACLE_DISTILL\|ECOM_ORACLE_VALIDATE_INLINE\|ECOM_INVESTIGATE_DATA_PATHS" CLAUDE.md
```
Also remove the prose sentence in the Architecture section that describes the in-pipeline "Distill → validate → promote (success path, `ECOM_ORACLE_DISTILL=1`)" mechanism, and the `ECOM_HARNESS_DISTILL` paragraph, since those code paths are gone. Leave the oracle *retrieval* env vars (`ECOM_ORACLE_ENABLED`, `ECOM_ORACLE_TOPN`, `ECOM_ORACLE_K`, `ECOM_ORACLE_FLOOR`, `ECOM_MODEL_EMBED`, rerank) — retrieval is KEPT.

- [ ] **Step 3: Strip from `agent/CLAUDE.md`**

On line 21, remove `ECOM_INVESTIGATE_DATA_PATHS` from the INVESTIGATE controls list:
```
- `ECOM_INVESTIGATE_ENABLED` / `ECOM_INVESTIGATE_MAX_STEPS` / `ECOM_INVESTIGATE_ORACLE_K` / `ECOM_MODEL_INVESTIGATE` / `ECOM_INVESTIGATE_DATA_PATHS` — INVESTIGATE phase controls (see root `../CLAUDE.md`)
```
becomes:
```
- `ECOM_INVESTIGATE_ENABLED` / `ECOM_INVESTIGATE_MAX_STEPS` / `ECOM_INVESTIGATE_ORACLE_K` / `ECOM_MODEL_INVESTIGATE` — INVESTIGATE phase controls (see root `../CLAUDE.md`)
```
Leave the `ECOM_CC_ENABLED` / `claude-code/` routing line untouched — cc_client is KEPT.

- [ ] **Step 4: Grep guard**

Run: `grep -rn "ECOM_HARNESS_DISTILL\|ECOM_HARNESS_VALIDATE\|ECOM_ORACLE_DISTILL\|ECOM_ORACLE_VALIDATE_INLINE\|ECOM_INVESTIGATE_DATA_PATHS" .env.example CLAUDE.md agent/CLAUDE.md`
Expected: NO output.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: strip env vars for removed harness/oracle-distill + data-paths paths

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Regenerate the affected wiki pages

**Files:** `docs/wiki/{harness,pipeline,investigate,learning,data-files}.md` (regenerated, not hand-edited).

- [ ] **Step 1: Re-ingest each changed source via the iwiki skill**

Invoke the `iwiki:iwiki-ingest` skill on each changed source so its wiki page regenerates:
`agent/harness.py`, `agent/pipeline.py`, `agent/investigate.py`, `agent/learned_store.py` (+ `scripts/prune_inactive_rules.py`).

- [ ] **Step 2: Lint the wiki graph**

Run the `iwiki:iwiki-lint` skill.
Expected: no broken `[[refs]]`, no orphan/stale pages referencing the removed `harness_validate`, `_maybe_harness_distill`, `_data_path_seed`, or in-pipeline oracle-distill.

- [ ] **Step 3: Commit**

```bash
git add docs/wiki
git commit -m "docs(wiki): regenerate pages after Phase 0 legacy removal

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Oracle load-bearing measurement (decision-gated — NO removal here)

**Background:** Oracle retrieval-into-PLAN (~500 LOC) is NOT removed by this plan. This task MEASURES whether it is load-bearing using the existing `ECOM_ORACLE_ENABLED=0` lever (no code change). Removal is a separate, later decision per the spec's load-bearing threshold. This task produces a documented measurement, not a code edit.

**Measured subset (per spec):** the union of (a) every task that reached `OUTCOME_OK` in the two reference runs (`logs/20260621_232850_*`, `logs/20260622_063422_*`), and (b) every task whose trace shows an oracle atom injected. Pin the exact task ids in the report.

- [ ] **Step 1: Derive the measured subset task ids**

From the reference run logs, list the `OUTCOME_OK` task ids and any task whose trace shows oracle-atom injection. Record the id set (e.g. `TASKS='t.. ,t..'`).

- [ ] **Step 2: Baseline run (oracle ON) on the subset**

Run: `make task TASKS='<subset>'` (default env, `ECOM_ORACLE_ENABLED=1`).
Record per-task outcome → the pass-set P_on.

- [ ] **Step 3: Toggle run (oracle OFF) on the same subset**

Run: `ECOM_ORACLE_ENABLED=0 make task TASKS='<subset>'`.
Record per-task outcome → the pass-set P_off.

- [ ] **Step 4: Decide and document**

Compute `dropped = P_on \ P_off`.
- `dropped == 0` → Oracle is NOT load-bearing on the subset → file a follow-up to remove oracle retrieval (separate Phase; out of Phase 0 firm scope).
- `dropped >= 1` → Oracle IS load-bearing → KEEP; record which task(s) depend on it.

Write the result (subset ids, P_on, P_off, verdict) into a short note under `docs/superpowers/reports/`. No commit to `agent/` in this task.

---

### Task 8: Final verification — Δtasks = 0 and LOC report

- [ ] **Step 1: Full suite green (final)**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS (same baseline minus the deleted distill/data-path tests; no NEW reds vs Task 1 Step 1).

- [ ] **Step 2: Reproduce the pre-removal pass-count on the measured subset**

Run: `make task TASKS='<same subset as Task 7 Step 1>'` on the post-removal tree.
Expected: pass-count IDENTICAL to the pre-removal baseline (Δtasks = 0). Any task that regressed on a specific removal proves that subsystem load-bearing → `git revert` that one commit and document why (per the spec threshold).

- [ ] **Step 3: Report the actual `agent/` LOC delta**

Run: `git diff --stat <branch-point>..HEAD -- agent/ | tail -1`
Record the net `agent/` LOC reduction (expected ~150–240 firm, no numeric promise). Note that `cc_client.py` (396) was intentionally KEPT and the bulk removable LOC (Oracle ~500) remains pending Task 7's decision.

- [ ] **Step 4: Confirm the skeleton is intact**

Run: `grep -rn "load_checks\|handler_for\|_HANDLERS" agent/interpreter.py agent/harness.py`
Expected: lint engine present (interpreter.lint still wired to harness handlers). Spot-check that INTENT→INVESTIGATE→PLAN→verify still runs end-to-end via the subset run in Step 2.

---

## Self-Review

**Spec coverage:**
- "REMOVE — unproven: harness-distill" → Task 1. ✓
- "REMOVE — unproven: data-paths branch" → Task 3. ✓
- "REMOVE — unproven: oracle-distill paths" → Task 2. ✓
- "REMOVE/DEMOTE: LEARN — prune inactive now" → Task 4. ✓
- "REMOVE/DEMOTE: Oracle — decision-gated, measure load-bearing" → Task 7. ✓
- "REMOVE/DEMOTE: Training loop — DEFER" → not touched (correctly out of scope). ✓
- "KEEP: cc_client (separate tier)" → never removed; reaffirmed Task 5 Step 3. ✓
- "KEEP: harness lint engine" → Task 1 keeps lines 1–193. ✓
- "Execution plan: each REMOVE its own commit + delete its tests" → Tasks 1–4 each commit. ✓
- "Execution plan: pytest green per commit" → every task's penultimate step. ✓
- "Execution plan: strip dead env vars" → Task 5. ✓
- "Execution plan: regen docs/wiki + lint" → Task 6. ✓
- "Execution plan: archive corpora (git history note)" → Task 4 (commit = archive). ✓
- "Success criteria: retained tests pass" → Tasks 1–4 + Task 8 Step 1. ✓
- "Success criteria: Δtasks = 0 on subset" → Task 8 Step 2. ✓
- "Success criteria: report actual LOC, no numeric promise" → Task 8 Step 3. ✓

**Placeholder scan:** No TODO/TBD; every deletion quotes the exact current code; the new script + tests are complete. The only read-then-edit steps (Task 3 Step 6 test deletions, Task 5 doc rows) name exact test functions / grep locators because their surrounding line numbers shift as edits land — the content to act on is fully specified.

**Type consistency:** `prune_entries(data) -> (dict, int)` is defined once (Task 4 Step 3) and used identically in its tests (Task 4 Step 1). `investigate(...)` post-edit signature (Task 3 Step 4a) matches the simplified call site (Task 3 Step 3) and the mock-stub fix (Task 3 Step 6). `sufficient(intent, brief.env)` (Task 3 Step 4f) is valid because `sufficient`'s extra params default to `None`.

---

Previous step: `docs/superpowers/specs/2026-06-22-phase0-current-impl-audit-legacy-removal-design.md`
