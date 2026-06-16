---
title: Pipeline Unification Implementation Plan
date: 2026-06-16
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-16-pipeline-unification-design.md
review:
  plan_hash: 8e8e4caf2c38ce69
  spec_hash: 106f6b1fa68d0b85
  last_run: 2026-06-16
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: verifiability
      severity: WARNING
      section: "## Task 6: Env, docs, and test cleanup + merge gate"
      section_hash: 4fb6f336e0793ff6
      text: >-
        Task 6 Steps 4 & 5 (rewrite CLAUDE.md and agent/CLAUDE.md) carry no
        verification command or measurable DoD — only "mirror/rewrite per spec".
        All other steps end in a Run/Expected check. Suggest a grep-based
        acceptance (e.g. the env table contains MODEL_REASON/MODEL_FAST and no
        MAX_STEPS/INTERPRETER_ENABLED) so the doc edits are verifiable. Low
        severity — prose edits, the dead-reference grep at Step 6 still gates merge.
      verdict: fixed
      verdict_at: 2026-06-16
---

# Pipeline Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the dual legacy DESIGN/CODEGEN pipeline and the Plan-IR interpreter into one pipeline (the interpreter) with a single knowledge contour (surface-collapsed learned rules + oracle distill→validate→promote wired in) and clean per-phase model routing (reason / fast / no-LLM tiers).

**Architecture:** `run_pipeline()` loses its `INTERPRETER_ENABLED` fork; its body becomes the former `_run_interpreted` (INTENT → loop[PLAN → lint → interpret → verify → answer-once] → CLARIFICATION). Learned rules load with no surface filter. On a successful cycle, when `ORACLE_DISTILL=1`, a candidate atom is distilled and (when `ORACLE_VALIDATE_INLINE=1`) grader-validated then promoted. Model routing resolves `MODEL_<PHASE> → tier env (MODEL_REASON / MODEL_FAST / EMBED_MODEL) → MODEL`, read live from the environment. Legacy modules, models, prompts, env vars, and tests are deleted in a final cutover.

**Tech Stack:** Python 3, Pydantic v2, pytest, `uv` (run everything via `uv run`), YAML stores under `data/`.

**Source spec:** `docs/superpowers/specs/2026-06-16-pipeline-unification-design.md` (decisions D1–D6).

**Single cutover PR (D1).** Each Task below is one commit. Order is load-bearing: nothing imports a deleted symbol mid-PR. Run `uv run python -m pytest tests/ -q` green at the end of every Task before committing.

---

## File Structure

Files created or modified, by responsibility:

- `agent/oracle_atoms.py` — **modify**: gains `build_oracle_block` (moved from `codegen_v2.py`). Leaf module (stdlib + yaml + `Atom`), no import cycles.
- `agent/codegen_v2.py` — **modify** (Task 1: re-export shim) then **delete** (Task 5).
- `agent/reason.py` — **modify**: import `build_oracle_block` from `oracle_atoms`; phase keys `"design"/"codegen"` → `"intent"/"plan"`.
- `agent/llm.py` — **modify**: replace `_PHASE_MODEL_MAP` import-time map with a live env-reading tiered resolver + `_think_for_phase`; flip ollama think precedence so `models.json` wins.
- `agent/orchestrator.py` — **modify**: DOC_SELECT routes through `"docselect"` (fast tier) instead of `"learn"`.
- `agent/oracle.py` — **modify**: `distill()` model resolves via the `"distill"` phase (reason tier).
- `agent/oracle_validate.py` — **modify**: add `validate_atom_via_grader(atom, task_id, intent, plan)`.
- `agent/pipeline.py` — **modify**: drop the surface filter; add `_maybe_distill_and_validate`; remove the fork and the entire legacy body + legacy-only helpers/imports; fix `learn_from_grader` to the single IR path.
- `agent/design.py`, `agent/fidelity.py`, `agent/testgen.py` — **delete** (Task 5).
- `agent/models.py` — **modify**: remove `DesignOutput`, `CodegenOutput`, `TestSpec`; keep `ToolOp`, `AgentsMdRef`, `AnswerTemplate`*, `AnswerOutput`, `LearnConsolidateOutput`. (*`AnswerTemplate` is only referenced by `DesignOutput`; see Task 5 Step for the keep/drop check.)
- `data/prompts/{design,codegen,test}.md` — **delete** (Task 5). Keep `intent`, `plan`, `ilearn`, `learn`, `compact`.
- `tests/test_llm_routing.py` — **create** (Task 2).
- `tests/test_oracle_atoms.py` — **modify/create**: absorb `build_oracle_block` test from `test_codegen_oracle.py`.
- `tests/test_pipeline_distill.py` — **create** (Task 3): distill-on-success + inline-validate gating.
- `tests/test_codegen_oracle.py`, `tests/test_design.py`, `tests/test_codegen_v2.py`, `tests/test_fidelity.py`, `tests/test_testgen.py` — **delete** (Tasks 1/6).
- `tests/test_models.py`, `tests/test_learn_consolidate.py`, `tests/test_pipeline_v2.py`, `tests/test_pipeline_tdd.py`, `tests/test_llm_module.py` — **modify**: drop assertions on deleted symbols (Task 6).
- `.env.example`, `CLAUDE.md`, `agent/CLAUDE.md` — **modify** (Task 6).

---

## Task 1: Move `build_oracle_block` (the shared blocker)

`build_oracle_block` lives in `codegen_v2.py:30` and is imported by both `design.py:10` (legacy) and `reason.py:8` (interpreter). It must leave `codegen_v2.py` before that module can be deleted. Move it to the leaf module `oracle_atoms.py`; leave a re-export in `codegen_v2.py` so `design.py` keeps working until Task 5.

**Files:**
- Modify: `agent/oracle_atoms.py` (add function)
- Modify: `agent/codegen_v2.py:30-37` (replace def with re-export import)
- Modify: `agent/reason.py:8` (import from new location)
- Create: `tests/test_oracle_atoms.py` (absorb the moved test)
- Delete: `tests/test_codegen_oracle.py`

- [ ] **Step 1: Write the failing test for the new location**

Create `tests/test_oracle_atoms.py`:

```python
from agent.oracle_atoms import Atom, build_oracle_block


def _atom():
    return Atom(id="sql-no-name-binds", description="d", domain=["sql"],
                content="inline quoted literals in IN()", source="s",
                validated_by="grader", validated_at="d", status="active",
                embedding_hash="")


def test_block_lists_atom_content():
    block = build_oracle_block([_atom()])
    assert "VALIDATED KNOWLEDGE" in block
    assert "inline quoted literals" in block


def test_empty_atoms_yields_empty_block():
    assert build_oracle_block([]) == ""


def test_codegen_v2_reexports_build_oracle_block():
    # design.py imports it from codegen_v2 until Task 5; the re-export must hold.
    from agent.codegen_v2 import build_oracle_block as via_codegen
    assert via_codegen([]) == ""
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_oracle_atoms.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_oracle_block' from 'agent.oracle_atoms'`

- [ ] **Step 3: Add the function to `oracle_atoms.py`**

Append to `agent/oracle_atoms.py` (after `save_atoms`):

```python
def build_oracle_block(oracle_atoms) -> str:
    """Render retrieved knowledge atoms as a context block for the PLAN prompt."""
    if not oracle_atoms:
        return ""
    lines = ["## VALIDATED KNOWLEDGE (apply when relevant; verified methods)"]
    for a in oracle_atoms:
        lines.append(f"- ({', '.join(a.domain)}) {a.content.strip()}")
    return "\n".join(lines)
```

- [ ] **Step 4: Replace the def in `codegen_v2.py` with a re-export**

In `agent/codegen_v2.py`, delete the `def build_oracle_block(...)` block (lines 30-37) and add, with the other imports near the top:

```python
from .oracle_atoms import build_oracle_block  # re-export: legacy design.py still imports it here
```

(`run_codegen` keeps calling `build_oracle_block(...)` — it resolves via the module namespace.)

- [ ] **Step 5: Point `reason.py` at the new home**

In `agent/reason.py:8` change:

```python
from .codegen_v2 import build_oracle_block
```
to:
```python
from .oracle_atoms import build_oracle_block
```

- [ ] **Step 6: Delete the old test file**

Run: `git rm tests/test_codegen_oracle.py`

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_oracle_atoms.py tests/test_reason.py tests/test_reason_prompts.py -q`
Expected: PASS. Then the full suite: `uv run python -m pytest tests/ -q` — green (interpreter no longer depends on `codegen_v2` for the block).

- [ ] **Step 8: Commit**

```bash
git add agent/oracle_atoms.py agent/codegen_v2.py agent/reason.py tests/test_oracle_atoms.py tests/test_codegen_oracle.py
git commit -m "refactor(oracle): move build_oracle_block to oracle_atoms; reason imports new home"
```

---

## Task 2: Model routing — tiers + per-phase override + think

Replace the import-time `_PHASE_MODEL_MAP` (resolved once, so tests must reload) with a resolver that reads env **live**: `MODEL_<PHASE>` → tier env (`MODEL_REASON` / `MODEL_FAST` / `EMBED_MODEL`) → `MODEL`. Add `_think_for_phase` (reason→on, fast→off, else unchanged). Wire `think` from the phase inside `call_llm_raw`, and flip the ollama think precedence so `models.json` `ollama_think` overrides the tier default.

**Files:**
- Modify: `agent/llm.py:70-80` (map → tier table + resolver), `:301-454` (think wiring/precedence), `:540` (call_llm_raw derives think)
- Modify: `agent/reason.py:64,95` (phase keys)
- Modify: `agent/orchestrator.py:375` (DOC_SELECT phase key)
- Create: `tests/test_llm_routing.py`
- Modify: `tests/test_llm_module.py:57-90` (drop old `_PHASE_MODEL_MAP` tests)

- [ ] **Step 1: Write the failing routing tests**

Create `tests/test_llm_routing.py`:

```python
import agent.llm as llm


def _clear(monkeypatch, *names):
    for n in names:
        monkeypatch.delenv(n, raising=False)


def test_per_phase_override_wins(monkeypatch):
    _clear(monkeypatch, "MODEL_REASON", "MODEL_FAST")
    monkeypatch.setenv("MODEL_PLAN", "anthropic/claude-opus-4-8")
    assert llm._resolve_model_for_phase("plan", "base") == "anthropic/claude-opus-4-8"


def test_reason_tier_used_when_no_override(monkeypatch):
    _clear(monkeypatch, "MODEL_PLAN")
    monkeypatch.setenv("MODEL_REASON", "reason-model")
    assert llm._resolve_model_for_phase("plan", "base") == "reason-model"
    assert llm._resolve_model_for_phase("intent", "base") == "reason-model"


def test_fast_tier_for_docselect(monkeypatch):
    _clear(monkeypatch, "MODEL_DOCSELECT", "MODEL_REASON")
    monkeypatch.setenv("MODEL_FAST", "fast-model")
    assert llm._resolve_model_for_phase("docselect", "base") == "fast-model"


def test_falls_back_to_default(monkeypatch):
    _clear(monkeypatch, "MODEL_PLAN", "MODEL_REASON", "MODEL_FAST")
    assert llm._resolve_model_for_phase("plan", "base") == "base"


def test_think_on_for_reason_off_for_fast_none_for_unlisted():
    assert llm._think_for_phase("plan") is True
    assert llm._think_for_phase("INTENT") is True
    assert llm._think_for_phase("docselect") is False
    assert llm._think_for_phase("DOC_SELECT") is False
    assert llm._think_for_phase("llm") is None
    assert llm._think_for_phase("compaction") is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_llm_routing.py -q`
Expected: FAIL — `_think_for_phase` does not exist; `_resolve_model_for_phase` does not honor `MODEL_REASON`/`MODEL_FAST`.

- [ ] **Step 3: Replace the map + resolver in `llm.py`**

In `agent/llm.py`, replace the `_PHASE_MODEL_MAP` block and `_resolve_model_for_phase` (lines 66-80) with:

```python
# Phase → model tier. Reason where the phase reasons; fast where it is light.
# Phases not listed default to the reason tier for model resolution, but to
# think=None (unchanged) so probe/compaction calls are not perturbed.
_PHASE_TIER: dict[str, str] = {
    "intent":    "reason",
    "plan":      "reason",
    "ilearn":    "reason",
    "learn":     "reason",
    "distill":   "reason",
    "docselect": "fast",
    "rerank":    "fast",
}
_TIER_ENV = {"reason": "MODEL_REASON", "fast": "MODEL_FAST", "embed": "EMBED_MODEL"}


def _norm_phase(phase: str) -> str:
    return (phase or "").lower().replace("_", "")


def _resolve_model_for_phase(phase: str, default_model: str) -> str:
    """Resolve a model id for a phase, read live from os.environ:
    MODEL_<PHASE> → tier env (MODEL_REASON/MODEL_FAST/EMBED_MODEL) → default_model.

    Live read so a test's monkeypatch.setenv applies without reloading the module.
    With only MODEL set, every phase resolves to MODEL (back-compatible)."""
    p = _norm_phase(phase)
    per_phase = os.environ.get(f"MODEL_{p.upper()}")
    if per_phase:
        return per_phase
    tier_env = _TIER_ENV.get(_PHASE_TIER.get(p, "reason"))
    if tier_env:
        tier_model = os.environ.get(tier_env)
        if tier_model:
            return tier_model
    return default_model


def _think_for_phase(phase: str) -> bool | None:
    """Reason tier → think on; fast tier → think off; unlisted → None (unchanged)."""
    tier = _PHASE_TIER.get(_norm_phase(phase))
    if tier == "reason":
        return True
    if tier == "fast":
        return False
    return None
```

- [ ] **Step 4: Derive think from phase in `call_llm_raw`**

In `agent/llm.py:call_llm_raw` (after the docstring, before `_tok = ...` at ~line 550) add:

```python
    if think is None:
        think = _think_for_phase(phase)
```

- [ ] **Step 5: Flip ollama think precedence so models.json wins**

First verify `_think_flag` is ollama-scoped (used only at the `_ollama_extra` assignment):

Run: `grep -n "_think_flag" agent/llm.py`
Expected: definition at ~451 and use at ~453-454 only.

Then in `agent/llm.py` replace (line ~450-451):

```python
    # explicit think= overrides cfg; None means use cfg default
    _think_flag = think if think is not None else cfg.get("ollama_think")
```
with:
```python
    # models.json ollama_think overrides the per-call/tier think; else use think.
    _cfg_think = cfg.get("ollama_think")
    _think_flag = _cfg_think if _cfg_think is not None else think
```

- [ ] **Step 6: Add a test for the precedence flip**

Append to `tests/test_llm_routing.py`:

```python
def test_models_json_think_overrides_tier(monkeypatch):
    # cfg.ollama_think present → wins over the tier-derived think.
    import agent.llm as llm_mod
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["think"] = kw.get("think")
        return "ok"

    monkeypatch.setattr(llm_mod, "_call_raw_single_model", _fake_single)
    # PLAN is reason tier → tier think True; cfg overrides to False.
    llm_mod.call_llm_raw([], "u", "ollama/x", {"ollama_think": False},
                         max_tokens=8, phase="PLAN")
    # call_llm_raw passes think=True (from phase) to _call_raw_single_model,
    # and the precedence flip inside applies cfg — assert the value reaching the tier.
    assert captured["think"] is True  # call_llm_raw forwards tier think; cfg applied downstream
```

> Note: `call_llm_raw` forwards the tier `think` to `_call_raw_single_model`; the cfg override happens **inside** `_call_raw_single_model`. This test pins the forwarded value. The cfg precedence itself is exercised by the existing ollama tests in `tests/test_llm_module.py`; if none assert it, add an assertion there reading `_ollama_extra`. Keep this step's assertion to the forwarded value to avoid over-mocking.

- [ ] **Step 7: Rename phase keys at the call sites**

`agent/reason.py:64` — `run_intent`:
```python
    model = _resolve_model_for_phase("intent", os.environ.get("MODEL", ""))
```
`agent/reason.py:95` — `run_plan`:
```python
    model = _resolve_model_for_phase("plan", os.environ.get("MODEL", ""))
```
`agent/orchestrator.py:375` — DOC_SELECT:
```python
    model = _resolve_model_for_phase("docselect", os.environ.get("MODEL", ""))
```

- [ ] **Step 8: Drop the stale resolver tests in `test_llm_module.py`**

Open `tests/test_llm_module.py` and delete the four tests that monkeypatch `_PHASE_MODEL_MAP` / set `MODEL_CODEGEN` (currently lines 57-90: `test_resolve_model_for_phase_uses_env`, `test_resolve_model_for_phase_falls_back_to_default`, `test_resolve_model_for_phase_unknown_phase`, `test_resolve_codegen_phase_uses_model_codegen`). Their replacements live in `tests/test_llm_routing.py`.

- [ ] **Step 9: Run tests**

Run: `uv run pytest tests/test_llm_routing.py tests/test_llm_module.py tests/test_reason.py tests/test_orchestrator.py -q`
Expected: PASS. Then full suite green: `uv run python -m pytest tests/ -q`.

- [ ] **Step 10: Commit**

```bash
git add agent/llm.py agent/reason.py agent/orchestrator.py tests/test_llm_routing.py tests/test_llm_module.py
git commit -m "feat(routing): per-phase model tiers (reason/fast) + think wiring; phase keys intent/plan/docselect"
```

---

## Task 3: Knowledge contour — surface collapse + distill→validate→promote

Drop the `surface="ir"` filter so PLAN sees all active rules (the `learn_from_grader` training-mode bug self-heals). Wire candidate-atom distillation on a **successful** cycle behind `ORACLE_DISTILL=1`, and inline grader-validation+promotion behind `ORACLE_VALIDATE_INLINE` (default `"1"`, only reachable when distill is on). Route `distill()`'s model through the reason tier.

**Files:**
- Modify: `agent/pipeline.py:351` (drop surface filter), add `_maybe_distill_and_validate` + call in success branch
- Modify: `agent/oracle.py:122-126` (distill model via `"distill"` phase)
- Modify: `agent/oracle_validate.py` (add `validate_atom_via_grader`)
- Create: `tests/test_pipeline_distill.py`

- [ ] **Step 1: Write failing tests for distill gating + surface collapse**

Create `tests/test_pipeline_distill.py`:

```python
import agent.pipeline as pipeline
from agent.ir_models import (AnswerShape, IntentSpec, PlanIR, DecisionTree,
                             AnswerTemplateIR)


def _intent():
    return IntentSpec(objective="count baskets", desired_outcome="OUTCOME_OK",
                      outcome_space=["OUTCOME_OK"], answer_shape=AnswerShape())


def _plan():
    return PlanIR(decision=DecisionTree(default_label="ok"),
                  answer={"ok": AnswerTemplateIR(message="m", outcome="OUTCOME_OK")})


def test_distill_skipped_when_flag_off(monkeypatch):
    monkeypatch.setenv("ORACLE_DISTILL", "0")
    called = {"distill": False}
    monkeypatch.setattr(pipeline, "_distill_call",
                        lambda *a, **k: called.__setitem__("distill", True))
    pipeline._maybe_distill_and_validate(_intent(), _plan(), "t01", "OK: verified")
    assert called["distill"] is False


def test_distill_writes_candidate_and_promotes_when_validated(monkeypatch):
    monkeypatch.setenv("ORACLE_DISTILL", "1")
    monkeypatch.setenv("ORACLE_VALIDATE_INLINE", "1")

    class FakeAtom:
        id = "a1"

    class FakeOracle:
        def __init__(self): self.promoted = None
        def distill(self, **kw): return FakeAtom()
        def promote(self, atom_id, validated_by, validated_at):
            self.promoted = (atom_id, validated_by)

    fake = FakeOracle()
    monkeypatch.setattr(pipeline, "_new_oracle", lambda: fake)
    monkeypatch.setattr(pipeline, "validate_atom_via_grader", lambda *a, **k: True)
    pipeline._maybe_distill_and_validate(_intent(), _plan(), "t01", "OK: verified")
    assert fake.promoted == ("a1", "grader-oracle")


def test_distill_keeps_candidate_when_inline_off(monkeypatch):
    monkeypatch.setenv("ORACLE_DISTILL", "1")
    monkeypatch.setenv("ORACLE_VALIDATE_INLINE", "0")

    class FakeAtom: id = "a1"
    class FakeOracle:
        def __init__(self): self.promoted = None
        def distill(self, **kw): return FakeAtom()
        def promote(self, *a, **k): self.promoted = a

    fake = FakeOracle()
    monkeypatch.setattr(pipeline, "_new_oracle", lambda: fake)
    pipeline._maybe_distill_and_validate(_intent(), _plan(), "t01", "OK: verified")
    assert fake.promoted is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/test_pipeline_distill.py -q`
Expected: FAIL — `_maybe_distill_and_validate`, `_distill_call`, `_new_oracle`, `validate_atom_via_grader` do not exist on `pipeline`.

- [ ] **Step 3: Add `validate_atom_via_grader` to `oracle_validate.py`**

Append to `agent/oracle_validate.py`:

```python
def validate_atom_via_grader(atom, task_id, intent, plan, min_score: float = 1.0) -> bool:
    """Re-run `plan` on a fresh StartRun and report whether the grader score
    meets `min_score`. Best-effort: any failure (no live grader, replay error)
    returns False so the atom stays candidate — never raises.

    Limitation: the fresh-VM replay runs `interpret(plan, intent, vm, facts=None)`.
    Plans whose predicates read `$_facts.*` (pre-phase grounding) degrade on the
    fresh VM and may under-promote; this is conservative by design.
    """
    try:
        from agent.interpreter import interpret

        def _builder(vm):
            res = interpret(plan, intent, vm, facts=None)
            a = res.captured
            return a.message[:800], a.outcome, list(a.refs)

        score, _detail = grade_candidate(task_id, _builder)
        return score is not None and score >= min_score
    except Exception:
        return False
```

- [ ] **Step 4: Route `distill()` model through the reason tier**

In `agent/oracle.py:distill` (lines 125-126) replace:

```python
        out = call_llm_json(self._DISTILL_SYS, user,
                            os.environ.get("MODEL_LEARN") or os.environ.get("MODEL", ""))
```
with:
```python
        from .llm import _resolve_model_for_phase
        out = call_llm_json(self._DISTILL_SYS, user,
                            _resolve_model_for_phase("distill", os.environ.get("MODEL", "")))
```

- [ ] **Step 5: Add the distill+validate helper to `pipeline.py`**

In `agent/pipeline.py`, add near the other interpreter helpers (after `_persist_artifacts`):

```python
def _new_oracle():
    from .oracle import KnowledgeOracle
    return KnowledgeOracle()


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
    if (os.environ.get("ORACLE_ENABLED", "1") == "0"
            or os.environ.get("ORACLE_DISTILL", "0") != "1"):
        return
    try:
        oracle = _new_oracle()
        atom = _distill_call(oracle, intent, plan, task_id, outcome_note)
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] oracle distill skipped: {e}{CLI_CLR}")
        return
    if not atom or os.environ.get("ORACLE_VALIDATE_INLINE", "1") != "1":
        return
    try:
        if validate_atom_via_grader(atom, task_id, intent, plan):
            oracle.promote(atom.id, validated_by="grader-oracle",
                           validated_at=str(date.today()))
            print(f"{CLI_GREEN}[pipeline] atom {atom.id} promoted (grader-validated){CLI_CLR}")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] inline atom validate skipped: {e}{CLI_CLR}")
```

Add the imports at the top of `agent/pipeline.py`:

```python
from datetime import date
from .oracle_validate import validate_atom_via_grader
```

- [ ] **Step 6: Drop the surface filter and wire the helper into the success branch**

In `agent/pipeline.py:_run_interpreted` change line 351:

```python
    learn_ctx: list = load_entries(task_id, surface="ir")
```
to:
```python
    # Surface collapse (D5): PLAN sees all active rules; the grader-feedback
    # training-mode bug self-heals because learn_from_grader writes the same store.
    learn_ctx: list = load_entries(task_id)
```

In the success branch (after `_persist_artifacts(task_id, intent, plan)`, ~line 437) add:

```python
            _maybe_distill_and_validate(intent, plan, task_id,
                                        f"OK: {verr or 'verify passed'}")
```

(`verr` is `""` on success; the note becomes `"OK: verify passed"`.)

- [ ] **Step 7: Run the distill tests**

Run: `uv run pytest tests/test_pipeline_distill.py -q`
Expected: PASS.

- [ ] **Step 8: Run the oracle + learned-store suites**

Run: `uv run pytest tests/test_oracle_distill.py tests/test_oracle_promote.py tests/test_oracle_retrieve.py tests/test_learned_store.py -q`
Expected: PASS (no surface regressions).

- [ ] **Step 9: Commit**

```bash
git add agent/pipeline.py agent/oracle.py agent/oracle_validate.py tests/test_pipeline_distill.py
git commit -m "feat(oracle): wire distill→inline-validate→promote on success; collapse learned-rule surface"
```

---

## Task 4: Unify the entrypoint — remove the fork + legacy body

Promote `_run_interpreted` into `run_pipeline` and delete the legacy DESIGN→CODEGEN body, the `INTERPRETER_ENABLED` fork, legacy-only helpers, and the now-unused legacy imports. Fix `learn_from_grader` to the IR-only path. After this commit, `agent/` no longer imports `design.py`, `codegen_v2.py`, `fidelity.py`, or `testgen.py`.

**Files:**
- Modify: `agent/pipeline.py` (large deletion + rename)

- [ ] **Step 1: Confirm legacy-only helpers before deleting**

Run:
```bash
grep -n "_compact_learn_ctx\|_retry_guard_applies\|_is_retryable_vm_error\|_extract_sql_literals\|_identical_sql_set\|_fold_facts_into_agents_md\|_AnswerGuard\|_run_intent_tests\|_mock_run\|_detect_zero_row_miss\|_demands_runtime_ref\|_learn_consolidate\b\|generate_fidelity\|run_codegen\|run_design\|run_test_gen\|TestSpec" agent/pipeline.py
```
Expected: every hit is inside the legacy `run_pipeline` body (lines ~946-1280) or its helpers. `_is_retryable_vm_error` is also used by `_run_interpreted` (line ~427) — **keep it**. `_plan_signature`, `_ground_security_refs`, `_terminal_clarification`, `_persist_artifacts`, `_ilearn`, `_maybe_distill_and_validate` are interpreter-path — **keep them**.

- [ ] **Step 2: Rename `_run_interpreted` to `run_pipeline` and delete the fork + legacy body**

In `agent/pipeline.py`:
1. Delete the current `def run_pipeline(...)` (lines ~928-1280) entirely.
2. Rename `def _run_interpreted(vm, instruction, task_id, agents_md_text, facts) -> dict:` to `def run_pipeline(vm, instruction: str, task_id: str, agents_md_text: str, facts=None) -> dict:`.
3. The interpreter imports done inside the function body (`from .interpreter import ...`, `from .reason import ...`, `from .verify import verify`) stay.

- [ ] **Step 3: Fix `learn_from_grader` to the IR-only path**

In `agent/pipeline.py:learn_from_grader` keep only the IR-artifact branch (lines 478-490). Delete the legacy fallback that reads `{tid}.py` + `{tid}.design.json` and calls `_learn_consolidate` (lines 491-505). Result:

```python
def learn_from_grader(task_id, score_detail, token_out=None) -> bool:
    if not task_id or not score_detail:
        return False
    heur_dir = Path("data/heuristics")
    ir_intent = heur_dir / f"{task_id}.intent.json"
    ir_plan = heur_dir / f"{task_id}.plan.json"
    if not (ir_intent.exists() and ir_plan.exists()):
        return False
    learn_ctx = load_entries(task_id)
    error = "grader: " + " | ".join(s.strip() for s in score_detail if s.strip())
    _learn_consolidate_text(
        task_id, learn_ctx,
        plan_context=ir_intent.read_text(encoding="utf-8"),
        error=error, artifact=ir_plan.read_text(encoding="utf-8"),
        token_out=token_out, prompt_name="ilearn", surface="ir",
    )
    return True
```

(Note the added `prompt_name="ilearn", surface="ir"` so grader feedback uses the IR seam consistently.)

- [ ] **Step 4: Delete legacy-only helpers**

Delete from `agent/pipeline.py`: `_learn_consolidate` (the `DesignOutput` wrapper, lines ~271-309), `_compact_learn_ctx` (~512-541), `_fold_facts_into_agents_md` (~123-139), `_extract_sql_literals` (~55-93), `_identical_sql_set` (~142-144), `_retry_guard_applies` + `_RETRY_GUARD_SKIP_PREFIXES` (~147-164), `_AnswerGuard` class + `_AnswerRefsError` (~666-859), `_detect_zero_row_miss` (~617-663), `_demands_runtime_ref` + `_RUNTIME_REF_HINT_RE` (~593-614), `_run_intent_tests` (~866-898), `_mock_run` (~901-921), `_terminal_outcome_override` (~565-570), `_run_script_on_vm` (~577-584). Keep `_normalise`/`_norm_sql`/`_plan_signature`, `_ground_security_refs` + `_SECURITY_POLICY_REF`, `_terminal_clarification`, `_is_retryable_vm_error` + `_RETRYABLE_VM_ERROR_PATTERNS`, `_learn_consolidate_text`, `_ilearn`, `_persist_artifacts`, the distill helpers.

- [ ] **Step 5: Clean the legacy imports + module constants**

At the top of `agent/pipeline.py` delete imports that only the legacy body used:

```python
from .codegen_v2 import CodegenError, run_codegen        # delete
from .design import DesignError, run_design              # delete
from .fidelity import exec_fidelity_in_subprocess, generate_fidelity_test  # delete
from .mock_vm_spy import MockVMSpy, fixture_key           # delete
from .models import DesignOutput, LearnConsolidateOutput, TestSpec  # → keep only LearnConsolidateOutput
from .testgen import TestGenError, run_test_gen           # delete
from .test_runner import run_tests                        # delete
from .sql_security import check_retry_loop                # delete (legacy guard)
```

Keep `LearnConsolidateOutput`. Delete the now-unused module constants: `_MAX_STEPS`, `_TDD_ENABLED`, `_TDD_MOCK_ENABLED`, `_TDD_FORCE_SUBMIT_AFTER`, `_FIDELITY_TIMEOUT_S`, `_INTERPRETER_ENABLED`, `_WHITESPACE_RE` (only `_normalise` uses it — keep if `_plan_signature`/`_norm_sql` still need it; `_norm_sql` uses `.split()`, `_normalise` uses `_WHITESPACE_RE` — keep `_WHITESPACE_RE` and `_normalise` only if still referenced, else delete). Keep `_IMAX_STEPS`, `_MAX_TOKENS_LEARN`, `_DESIGN_MAX_ATTEMPTS`.

- [ ] **Step 6: Run the import + dead-reference check**

Run:
```bash
uv run python -c "import agent.pipeline"
grep -nE "design\.py|codegen_v2|fidelity|testgen|DesignOutput|CodegenOutput|run_codegen|run_design|generate_fidelity|run_test_gen|INTERPRETER_ENABLED" agent/pipeline.py
```
Expected: import succeeds; grep returns no hits in `pipeline.py`.

- [ ] **Step 7: Run the interpreter pipeline tests**

Run: `uv run pytest tests/test_pipeline_interpreted.py tests/test_integration_interpreter.py tests/test_pipeline_distill.py -q`
Expected: PASS. (`tests/test_pipeline_v2.py` and `tests/test_pipeline_tdd.py` will fail here — they target the deleted legacy body; they are reconciled in Task 6. Run the rest: `uv run pytest tests/ -q --deselect tests/test_pipeline_v2.py --deselect tests/test_pipeline_tdd.py` to confirm the unified path is green before the test cleanup.)

- [ ] **Step 8: Commit**

```bash
git add agent/pipeline.py
git commit -m "refactor(pipeline): remove INTERPRETER_ENABLED fork + legacy DESIGN/CODEGEN body; IR-only learn_from_grader"
```

---

## Task 5: Delete legacy modules, models, and prompts

Now that nothing in `agent/` references them, delete the legacy modules and the unused model/prompt artifacts.

**Files:**
- Delete: `agent/design.py`, `agent/codegen_v2.py`, `agent/fidelity.py`, `agent/testgen.py`
- Modify: `agent/models.py` (remove `DesignOutput`, `CodegenOutput`, `TestSpec`, and `AnswerTemplate`/`ToolOp`/`AgentsMdRef` iff unused)
- Delete: `data/prompts/{design,codegen,test}.md`

- [ ] **Step 1: Confirm no `agent/` or `main.py` references remain**

Run:
```bash
grep -rnE "codegen_v2|from agent.design|from .design|agent\.fidelity|from .fidelity|agent\.testgen|from .testgen" agent/ main.py
```
Expected: zero hits (the Task 1 re-export in `codegen_v2.py` is the only thing keeping `design.py` alive; `design.py` is being deleted now, so the shim goes with `codegen_v2.py`).

- [ ] **Step 2: Delete the modules**

Run:
```bash
git rm agent/design.py agent/codegen_v2.py agent/fidelity.py agent/testgen.py
```

- [ ] **Step 3: Determine which models are now orphaned**

Run:
```bash
grep -rnE "DesignOutput|CodegenOutput|TestSpec|AnswerTemplate\b|ToolOp|AgentsMdRef" agent/ main.py tests/
```
`DesignOutput`, `CodegenOutput`, `TestSpec` must show hits only in `tests/` (deleted in Task 6) and `agent/models.py`. `AnswerTemplate`, `ToolOp`, `AgentsMdRef` are only referenced by `DesignOutput` — confirm no other live reference, then remove them too. `AnswerOutput` and `LearnConsolidateOutput` stay (IR + learn).

- [ ] **Step 4: Trim `agent/models.py`**

Delete `DesignOutput`, `CodegenOutput`, `TestSpec`, and (if Step 3 confirms unused) `ToolOp`, `AgentsMdRef`, `AnswerTemplate`. Keep `AnswerOutput`, `LearnConsolidateOutput`. The IR types live in `ir_models.py` — untouched.

- [ ] **Step 5: Delete legacy prompts**

Run:
```bash
git rm data/prompts/design.md data/prompts/codegen.md data/prompts/test.md
```

- [ ] **Step 6: Verify import + prompt-loader**

Run:
```bash
uv run python -c "import agent.pipeline, agent.models, agent.reason, agent.orchestrator"
uv run pytest tests/test_prompt_loader.py tests/test_reason_prompts.py -q
```
Expected: imports succeed; prompt tests pass (`intent`/`plan`/`ilearn` still load).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: delete legacy design/codegen/fidelity/testgen modules, models, and prompts"
```

---

## Task 6: Env, docs, and test cleanup + merge gate

Remove dead env vars, add the new ones, update both CLAUDE.md files, delete legacy test files, reconcile mixed test files, and run the dead-reference audit.

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`, `agent/CLAUDE.md`
- Delete: `tests/test_design.py`, `tests/test_codegen_v2.py`, `tests/test_fidelity.py`, `tests/test_testgen.py`, `tests/test_pipeline_tdd.py`
- Modify: `tests/test_pipeline_v2.py`, `tests/test_models.py`, `tests/test_learn_consolidate.py`

- [ ] **Step 1: Delete legacy test files**

Run:
```bash
git rm tests/test_design.py tests/test_codegen_v2.py tests/test_fidelity.py tests/test_testgen.py tests/test_pipeline_tdd.py
```

- [ ] **Step 2: Reconcile mixed test files**

- `tests/test_models.py`: remove imports/assertions for `DesignOutput`, `CodegenOutput`, `TestSpec` (and `ToolOp`/`AgentsMdRef`/`AnswerTemplate` if removed in Task 5). Keep `AnswerOutput`/`LearnConsolidateOutput` tests.
- `tests/test_learn_consolidate.py`: drop any case that constructs a `DesignOutput` or calls `_learn_consolidate` (the `DesignOutput` wrapper). Keep cases exercising `_learn_consolidate_text` / `apply_learn_diff`.
- `tests/test_pipeline_v2.py`: cut branches that exercise the legacy DESIGN→CODEGEN loop, fidelity gate, or `_AnswerGuard`. Keep any assertions that still hold for the unified `run_pipeline` (terminal CLARIFICATION shape, exactly-one-answer). If the file becomes empty of valid cases, `git rm` it and rely on `test_pipeline_interpreted.py`.

Run after each edit: `uv run pytest <file> -q`.

- [ ] **Step 3: Update `.env.example`**

Remove: `MAX_STEPS`, `MODEL_DESIGN`, `MODEL_CODEGEN`, `MODEL_TEST`, `MAX_TOKENS_DESIGN`, `MAX_TOKENS_CODEGEN`, `MAX_TOKENS_TEST`, `FIDELITY_TIMEOUT_S`, `INTERPRETER_ENABLED`, the entire `TDD` block (`TDD_ENABLED`, `TDD_MOCK_ENABLED`, `TDD_FORCE_SUBMIT_AFTER`).

Add:
```
MODEL_REASON=                        # reason-tier model (INTENT/PLAN/iLEARN/distill); defaults to MODEL
MODEL_FAST=                          # fast-tier model (DOC_SELECT/rerank); defaults to MODEL
ORACLE_VALIDATE_INLINE=1             # 1 → grader-validate distilled atoms inline (only when ORACLE_DISTILL=1)
```
Keep `MODEL_LEARN` (reason-tier per-phase override still honored), `INTERPRETER_MAX_STEPS`, `MAX_TOKENS_INTENT`, `MAX_TOKENS_PLAN`, `MAX_TOKENS_LEARN`, the `ORACLE_*` block, `EMBED_MODEL`.

- [ ] **Step 4: Update `CLAUDE.md` (repo root)**

In the Architecture section: replace the DESIGN→CODEGEN→fidelity→ANSWER flow with the unified INTENT → loop[PLAN → lint → interpret → verify → answer] → CLARIFICATION flow (mirror the spec §Target Architecture pseudo-code). In the Environment Variables table: drop the removed vars, add `MODEL_REASON`/`MODEL_FAST`/`ORACLE_VALIDATE_INLINE`, and the model-tier note (`MODEL_<PHASE> → tier → MODEL`). In Key Data Files: `data/heuristics/{tid}.intent.json` + `{tid}.plan.json` replace `{tid}.py` + `{tid}.design.json`. Update the Prompt Engineering Rules list to `design/codegen/learn` → `intent/plan/ilearn/learn/compact`.

Verify:
```bash
grep -q "MODEL_REASON" CLAUDE.md && grep -q "MODEL_FAST" CLAUDE.md && echo OK-added
grep -qvE "INTERPRETER_ENABLED|MAX_STEPS|FIDELITY_TIMEOUT_S|MODEL_CODEGEN" CLAUDE.md \
  && ! grep -qE "INTERPRETER_ENABLED|^\| ?\`MAX_STEPS|FIDELITY_TIMEOUT_S|MODEL_CODEGEN" CLAUDE.md && echo OK-removed
grep -qE "INTENT|intent\.json" CLAUDE.md && echo OK-flow
```
Expected: `OK-added`, `OK-removed`, `OK-flow` all print (removed vars gone from the env table; new vars + interpreter flow present).

- [ ] **Step 5: Update `agent/CLAUDE.md`**

Rewrite the "Agent Package Architecture" per-task flow to the interpreter (INTENT/PLAN/interpret/verify, no DESIGN/CODEGEN/fidelity/TEST-GEN/`_AnswerGuard`). Update the Pydantic models list (drop `DesignOutput`/`CodegenOutput`/`TestSpec`/`ToolOp`/`AgentsMdRef`/`AnswerTemplate` as removed; keep `AnswerOutput`/`LearnConsolidateOutput`; point to `ir_models.py` for IntentSpec/PlanIR). Update LLM routing to the tier model.

Verify:
```bash
! grep -qE "DesignOutput|CodegenOutput|TestSpec|fidelity|TEST-GEN|_AnswerGuard|run_codegen|run_design" agent/CLAUDE.md && echo OK-clean
grep -qE "IntentSpec|PlanIR|interpret" agent/CLAUDE.md && echo OK-ir
```
Expected: `OK-clean` and `OK-ir` both print (no legacy symbols remain; interpreter types documented).

- [ ] **Step 6: Dead-reference audit (merge gate)**

Run:
```bash
grep -rnE "design\.py|codegen_v2|fidelity|testgen|DesignOutput|CodegenOutput|run_codegen|run_design|generate_fidelity|run_test_gen|INTERPRETER_ENABLED" agent/ main.py
```
Expected: **zero hits**. If any remain, fix before committing.

- [ ] **Step 7: Full regression suite**

Run: `uv run python -m pytest tests/ -q`
Expected: green. Investigate every failure; do not commit red.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: env/docs/tests cleanup for unified pipeline; dead-reference audit clean"
```

---

## E2E Verification (manual, after the 6 commits)

Per the spec §Testing & Verification and the concurrent-run-contention note: **`pgrep -af "python main.py"` first; do not start a timed run while another session is looping, and never kill its runs.**

- [ ] Run a small set on `deepseek` via the unified path:
  ```bash
  ORACLE_DISTILL=1 ORACLE_VALIDATE_INLINE=0 make task TASKS='t01,t38,t55'
  ```
  Assert: (a) iLEARN writes rules to `data/learned/{tid}.yaml`; (b) `data/oracle/atoms.yaml` gains `status: candidate` atoms; (c) scores recorded in `last_run`.
- [ ] One task with inline validation on (cost: one extra StartRun per distilled atom):
  ```bash
  ORACLE_DISTILL=1 ORACLE_VALIDATE_INLINE=1 make task TASKS='t01'
  ```
  Assert: a validated atom flips to `status: active` (or stays candidate with a logged skip — never an exception).

---

## Out of Scope (from the spec)

- Per-phase prompt rewrites beyond the `design/codegen` → `intent/plan` key rename.
- Re-tuning `verify()` or `INTERPRETER_MAX_STEPS`.
- An offline `promote-atoms` batch target (`agent/promote.py` + `make promote` already exist and are untouched).
- Fixing individual task heuristics (t01 yes/no token, t38 SQL parse, t55 last-by-timestamp).

---

## Self-Review

**1. Spec coverage.**
- D1 single cutover PR, commits per step → Tasks 1–6, one commit each. ✓
- D2 model routing 3 tiers + per-phase override → Task 2. ✓
- D3 atom lifecycle candidate→validate→active → Task 3 (`distill` writes candidate, `validate_atom_via_grader` + `promote`). ✓
- D4 inline validation behind `ORACLE_VALIDATE_INLINE` → Task 3 Step 5 + Task 6 Step 3. ✓
- D5 surface collapse → Task 3 Step 6. ✓
- D6 delete TESTGEN/TDD + fidelity, `verify()` sole gate → Tasks 4 (TDD/fidelity body), 5 (modules/prompts), 6 (tests/env). ✓
- Commit 1 move `build_oracle_block` → Task 1. ✓
- Dead-reference grep gate → Task 4 Step 6 + Task 6 Step 6. ✓
- E2E (deepseek, atoms grow, scores recorded, contention note) → E2E section. ✓

**2. Placeholder scan.** No `TBD`/`TODO`/"add error handling"/"write tests for the above" — every code step shows the code; every command shows expected output. ✓

**3. Type consistency.** `IntentSpec.objective` used in `_distill_call` (matches `ir_models.py:83`). `validate_atom_via_grader(atom, task_id, intent, plan, min_score)` signature matches its call in `_maybe_distill_and_validate`. `_new_oracle`/`_distill_call` are monkeypatch seams referenced identically in `tests/test_pipeline_distill.py` and `pipeline.py`. `_resolve_model_for_phase(phase, default)` and `_think_for_phase(phase)` signatures match call sites in `reason.py`/`orchestrator.py`/`call_llm_raw`. `grade_candidate(task_id, answer_builder)` matches the existing `oracle_validate.py` signature. ✓

**Known limitation (documented, not a gap):** `validate_atom_via_grader` replays with `facts=None`, so plans whose predicates read `$_facts.*` under-promote on the fresh VM. Conservative by design (never wrongly promotes); flagged in the function docstring.
