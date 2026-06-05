---
chain:
  intent: docs/superpowers/intents/2026-05-28-pipeline-redesign-intent.md
  spec: docs/superpowers/specs/2026-05-28-pipeline-redesign-design.md
review:
  plan_hash: b3cf4bb5589e827d
  spec_hash: 91576957dc845394
  last_run: '2026-05-29'
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-007
      phase: coverage
      severity: WARNING
      section: Task 12 / Task 13
      section_hash: fd55e83536ae40ac
      text: "Tasks 12 and 13 add MODEL_DESIGN to .env.example and to CLAUDE.md env-vars table, but agent/llm.py:_PHASE_MODEL_MAP is not extended with a 'design' key. agent/llm.py is in spec Keep-source and in intent No-autonomy zone. Result: MODEL_DESIGN env var is read by _resolve_model_for_phase('design', MODEL) which falls back to MODEL because the map has no 'design' entry — the knob is non-functional. Plan must either drop MODEL_DESIGN or escalate per intent Stop Rules (touching agent/llm.py)."
      verdict: fixed
      fix: "MODEL_DESIGN dropped from .env.example (Task 12) and from CLAUDE.md env-vars table (Task 13). File-structure note explains the rationale: _PHASE_MODEL_MAP lacks 'design' key; llm.py untouchable per No-autonomy. Phase falls back to MODEL."
    - id: F-008
      phase: coverage
      severity: WARNING
      section: Task 8 — pipeline rewrite
      section_hash: 2d7d8062a0957b7a
      text: "Pipeline check_retry_loop integration mismatches normalisation. Plan calls check_retry_loop(sqls, [frozenset(_normalise(s) for s in p) for p in prior_sql_sets]): the `sqls` argument is raw (not normalised) while prior_query_sets are normalised. Inside check_retry_loop the comparison is `frozenset(queries) in prior_query_sets` — raw vs normalised sets never match for inputs differing only in whitespace, defeating the anti-loop guard for the second-tier check. Fix: pass [_normalise(s) for s in sqls]."
      verdict: fixed
      fix: "Task 8 call updated to check_retry_loop([_normalise(s) for s in sqls], [frozenset(_normalise(s) for s in p) for p in prior_sql_sets]). Both arguments now share the same whitespace-collapsed form."
    - id: F-009
      phase: coverage
      severity: WARNING
      section: Task 14 — verification
      section_hash: fc96e1e136d38b6c
      text: "Spec test plan integration tests `test_benchmark_t01.py` and `test_benchmark_t99.py` (HM1 enforcement, env-gated, real LLM) are not created. Plan Task 14 Step 2 substitutes `make task TASKS='t01,t99'` smoke. HM1 verification path divergent from spec — no automated regression net for the two reference tasks."
      verdict: fixed
      fix: "Task 14 gained a new Step 1 creating tests/test_benchmark_t01.py and tests/test_benchmark_t99.py, env-gated via pytest.mark.skipif(os.environ.get('RUN_BENCHMARK') != '1'). Subsequent steps renumbered. File-structure Create row now lists both benchmark test files."
    - id: F-010
      phase: coverage
      severity: WARNING
      section: Task 8 — pipeline rewrite
      section_hash: 2d7d8062a0957b7a
      text: "Plan's run_pipeline rewrite omits `trace.header(task_id, instruction)` shown in spec pseudocode (Pipeline loop, line 351). `agent/trace.py` listed in spec Keep-source; observability entry-point is silently dropped. Either include trace.header (matches spec) or update spec to mark trace removed."
      verdict: fixed
      fix: "Task 8 now imports get_trace and emits tlog.log_header(instruction, os.environ.get('MODEL', '')) at run_pipeline entry. (Real agent/trace.py API is log_header(task_text, model) — spec's trace.header(...) pseudocode was incorrect; the plan uses the real method name.)"
    - id: F-011
      phase: verifiability
      severity: WARNING
      section: Task 12 + Task 13
      section_hash: fd55e83536ae40ac
      text: "Task 12 (`.env.example`) and Task 13 (`CLAUDE.md`) have no measurable verify step between Step 1 (edit) and Step 2 (commit). No grep assertion that removed vars are absent, no markdown lint, no anchor check. Reviewer cannot mechanically confirm Step 1 done."
      verdict: fixed
      fix: "Task 12 gained Step 2 grep verify (removed vars absent, new vars present); commit renumbered. Task 13 gained Step 5 grep verify of CLAUDE.md table; commit renumbered. Both produce explicit OK / FAIL token."
    - id: F-012
      phase: consistency
      severity: WARNING
      section: Task 10 — deletes
      section_hash: eae7bf9422349ca5
      text: "Plan deletes `agent/mock_vm.py` (Step 1 + File-structure table) but spec Delete-source lists only `prephase.py`, `prompt_assembler.py`, `evaluator.py`. Plan note 'Superseded by mock_vm_spy.py' is reasonable but extends scope beyond spec. Either update spec or remove the extra delete from plan."
      verdict: fixed
      fix: "Task 10 no longer deletes agent/mock_vm.py or tests/test_mock_vm.py. File-structure rows removed from delete list. Rationale added: keep mock_vm.py untouched — fidelity gate uses mock_vm_spy.py, but legacy mock_vm.py is referenced by retained code paths outside scope."
---

# Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse `PREPHASE + ASSEMBLE + IDD + SDD + PLAN` into a single deterministic `DESIGN` phase grounded in `docs/proto-api-reference.md` + `/AGENTS.MD`. Iterate only on `CODEGEN`. Replace LLM-generated mock test with a deterministic tool-plan fidelity gate. Remove the fast path. `ANSWER` becomes a terminal one-shot outside the retry loop.

**Architecture:** Per-task flow `ENTRY → vm.read("/AGENTS.MD") → DESIGN (1 LLM call, frozen for run) → LOOP[CODEGEN → ast.parse → fidelity gate → on fail: LearnConsolidate, on pass: break] → ANSWER terminal (exec script on real VM, or CLARIFICATION on exhaust)`. Single unified `MAX_STEPS=3` counter wraps every failure mode. `LEARN` and `CONSOLIDATE` merged into a single LLM call (`LearnConsolidateOutput`) so worst-case budget = `DESIGN + 3 × (CODEGEN + LearnConsolidate) = 7` calls.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, `ast` (stdlib), `subprocess` (stdlib), uv/pytest.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `agent/models.py` | Rewrite | `DesignOutput`, `ToolOp`, `AgentsMdRef`, `AnswerTemplate`, `CodegenOutput`, `LearnConsolidateOutput`, `AnswerOutput`. Delete `IddOutput`, `SddOutput`, `PlanOutput`, `ExecuteOutput`, `ConsolidateOutput`, `ConsolidationItem`, `ResolveCandidate`, `ResolveOutput`, `LearnOutput`, `TestOutput` |
| `agent/learned_store.py` | Create | `load_entries(tid)`, `apply_learn_diff(tid, out)`, `save_last_run(tid, ...)`; no `heuristic_valid` / `schema_hash` |
| `agent/design.py` | Create | `run_design(instruction, agents_md_text) → DesignOutput`; H2/H13/H15: signature accepts ONLY these 2 args |
| `agent/codegen_v2.py` | Create | `run_codegen(design, learn_ctx, prev_error) → CodegenOutput` |
| `agent/fidelity.py` | Create | `generate_fidelity_test(design, tid) → str`; `exec_fidelity_in_subprocess(test_src, script_code, timeout_s) → FidelityResult` |
| `agent/mock_vm_spy.py` | Create | `MockVMSpy(fixtures)` — records `(rpc, args)` calls, returns canned fixture responses |
| `agent/pipeline.py` | Rewrite | Unified `MAX_STEPS` loop, `_learn_consolidate`, `_terminal_clarification`, `check_retry_loop` integration via ast.walk SQL extraction, `trace.log_header` entry hook |
| `agent/orchestrator.py` | Modify | Drop `run_prephase`; read `/AGENTS.MD` directly; pass `agents_md_text` to `run_pipeline` |
| `agent/prephase.py` | Delete | Removed (H1) |
| `agent/prompt_assembler.py` | Delete | Removed (helpers migrated to `learned_store.py`) |
| `agent/evaluator.py` | Delete | Removed |
| `data/prompts/design.md` | Create | DESIGN guide; embeds `proto-api-reference.md` as cached block |
| `data/prompts/codegen.md` | Rewrite | Input = `tool_plan` + AGENTS.MD constraints; output = `script_code` |
| `data/prompts/learn.md` | Rewrite | Output = `LearnConsolidateOutput` (merged) |
| `data/prompts/idd.md`, `sdd.md`, `plan.md`, `assembler.md`, `tdd.md`, `answer.md`, `consolidate.md` | Delete | Phases removed |
| `data/eval_log.jsonl` | Delete | H7 |
| `data/heuristics/t01.py`, `data/heuristics/t99.py`, `data/heuristics/*_test.py` | Delete | Orphans |
| `data/learned/t01.yaml`, `data/learned/t99.yaml` | Reset | `{task_id, entries: [], last_run: null}` |
| `tests/test_design.py`, `test_codegen_v2.py`, `test_fidelity.py`, `test_mock_vm_spy.py`, `test_pipeline_v2.py`, `test_learn_consolidate.py`, `test_learned_store.py`, `test_benchmark_t01.py`, `test_benchmark_t99.py` | Create | TDD coverage of new modules + env-gated benchmark regression (HM1) |
| `tests/test_pipeline.py`, `test_prephase.py`, `test_prompt_assembler.py`, `test_codegen.py`, `test_fast_path.py`, `test_orchestrator_pipeline.py`, `test_sdd_action_fix.py`, `test_schema_gate.py`, `test_pipeline_models.py`, `test_models_cleanup.py`, `test_models_consolidate.py`, `test_models_json_cleanup.py`, `test_test_runner.py`, `test_trace_pipeline.py`, `test_ref_bugs.py`, `test_answer.py` | Delete | Obsolete |
| `tests/test_consolidate.py`, `test_learned_storage.py`, `test_llm_phases.py`, `test_models.py`, `test_prompt_loader.py` | Rewrite | Folded into new tests |
| `.env.example` | Modify | Add `MAX_TOKENS_DESIGN`, `FIDELITY_TIMEOUT_S`; drop `CODEGEN_LINT_RETRIES`, `SDD_ENABLED`, `MODEL_IDD`/`MODEL_SDD`/`MODEL_PLAN`/`MODEL_ASSEMBLER`/`MODEL_CONSOLIDATE`/`MAX_TOKENS_IDD`/`MAX_TOKENS_SDD`/`MAX_TOKENS_PLAN`/`MAX_TOKENS_ANSWER`/`MAX_TOKENS_ASSEMBLER`/`MAX_TOKENS_CONSOLIDATE` (keep `MAX_TOKENS_LEARN`). `MODEL_DESIGN` intentionally NOT added — `agent/llm.py:_PHASE_MODEL_MAP` lacks a `design` key and llm.py is in spec Keep-source / intent No-autonomy; phase falls back to `MODEL` |
| `CLAUDE.md` | Modify | Rewrite Execution Flow + Env Vars sections; document fidelity gate |

---

## Task 1: Rewrite `agent/models.py`

**Files:**
- Modify: `agent/models.py`
- Create: `tests/test_models.py` (overwrite existing)

- [ ] **Step 1: Write failing tests**

Overwrite `tests/test_models.py`:

```python
import pytest
from agent.models import (
    DesignOutput, ToolOp, AgentsMdRef, AnswerTemplate,
    CodegenOutput, LearnConsolidateOutput, AnswerOutput,
)


def _design_kwargs(**over):
    base = dict(
        intent="count baskets by store",
        params={"store_id": "$agent_store_id"},
        success_criteria=["rows non-empty", "cnt >= 0"],
        discovery=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": [".schema baskets"]}, bind="schema")],
        ops=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, bind="rows")],
        agents_md_constraints=[AgentsMdRef(anchor="#baskets > store_scope", rule="filter store_id=$agent_store_id")],
        answer_template=AnswerTemplate(message="{rows[0].cnt} baskets", outcome="OUTCOME_OK", refs=[]),
        outcome_override=None,
    )
    base.update(over)
    return base


def test_design_output_full_shape():
    d = DesignOutput(**_design_kwargs())
    assert d.intent == "count baskets by store"
    assert d.success_criteria == ["rows non-empty", "cnt >= 0"]
    assert d.ops[0].bind == "rows"
    assert d.agents_md_constraints[0].anchor == "#baskets > store_scope"
    assert d.outcome_override is None


def test_design_output_success_criteria_required():
    """F-002: success_criteria is a required field per H10."""
    kw = _design_kwargs()
    del kw["success_criteria"]
    with pytest.raises(Exception):
        DesignOutput(**kw)


def test_design_output_outcome_override_allowed():
    d = DesignOutput(**_design_kwargs(outcome_override="OUTCOME_DENIED_SECURITY"))
    assert d.outcome_override == "OUTCOME_DENIED_SECURITY"


def test_tool_op_bind_optional():
    op = ToolOp(rpc="Read", args={"path": "/AGENTS.MD"})
    assert op.bind is None


def test_codegen_output_minimal():
    cg = CodegenOutput(script_code="def run(vm, params): pass\n")
    assert "def run" in cg.script_code


def test_learn_consolidate_output_minimal():
    lc = LearnConsolidateOutput(
        rule_content="Never hardcode SKUs from task_text",
        reasoning="prior cycle hardcoded value",
        deactivate_ids=[],
        skip=False,
    )
    assert lc.skip is False
    assert lc.agents_md_anchor is None
    assert lc.deactivate_reason is None


def test_learn_consolidate_skip_path():
    lc = LearnConsolidateOutput(
        rule_content="",
        reasoning="duplicate of r001",
        deactivate_ids=[],
        skip=True,
        skip_reason="r001",
    )
    assert lc.skip is True
    assert lc.skip_reason == "r001"


def test_answer_output_basic():
    a = AnswerOutput(message="3 baskets", outcome="OUTCOME_OK", grounding_refs=["/proc/baskets/b1.json"])
    assert a.outcome == "OUTCOME_OK"


def test_deleted_models_no_longer_importable():
    import agent.models as m
    for name in ("IddOutput", "SddOutput", "PlanOutput", "ExecuteOutput",
                 "ConsolidateOutput", "ConsolidationItem", "ResolveCandidate",
                 "ResolveOutput", "LearnOutput", "TestOutput"):
        assert not hasattr(m, name), f"{name} must be deleted"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_models.py -v
```

Expected: FAIL — `ImportError` on `DesignOutput`, etc.

- [ ] **Step 3: Replace `agent/models.py`**

Overwrite `agent/models.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ToolOp(BaseModel):
    rpc: str                           # Read|List|Tree|Find|Search|Exec|Write|Delete|Stat|Answer
    args: dict[str, Any]
    bind: str | None = None            # variable name for result chaining


class AgentsMdRef(BaseModel):
    anchor: str                        # "#section > entry"
    rule: str                          # verbatim rule text


class AnswerTemplate(BaseModel):
    message: str                       # e.g. "{rows[0].cnt} baskets"
    outcome: str = "OUTCOME_OK"
    refs: list[str] = []


class DesignOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str
    params: dict[str, str]
    success_criteria: list[str]        # F-002 / H10
    discovery: list[ToolOp] = []
    ops: list[ToolOp]
    agents_md_constraints: list[AgentsMdRef] = []
    answer_template: AnswerTemplate
    outcome_override: Literal[
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_NONE_CLARIFICATION",
    ] | None = None


class CodegenOutput(BaseModel):
    script_code: str                   # standalone module exporting `run(vm, params)`


class LearnConsolidateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_content: str
    agents_md_anchor: str | None = None
    reasoning: str
    deactivate_ids: list[str] = []
    deactivate_reason: str | None = None
    skip: bool = False
    skip_reason: str | None = None


class AnswerOutput(BaseModel):
    message: str
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_DENIED_SECURITY",
    ]
    grounding_refs: list[str] = []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_models.py -v
```

Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/models.py tests/test_models.py
git commit -m "refactor(models): collapse IDD/SDD/PLAN/Execute/Consolidate/Resolve/Learn/Test into DesignOutput + LearnConsolidateOutput"
```

---

## Task 2: Create `agent/learned_store.py`

**Files:**
- Create: `agent/learned_store.py`
- Create: `tests/test_learned_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_learned_store.py`:

```python
from pathlib import Path

import pytest
import yaml

from agent import learned_store
from agent.models import LearnConsolidateOutput


@pytest.fixture
def tid_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    return tmp_path


def _seed(tid_dir, tid, entries=None, last_run=None):
    data = {"task_id": tid, "entries": entries or [], "last_run": last_run}
    (tid_dir / f"{tid}.yaml").write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def test_load_entries_active_only(tid_dir):
    _seed(tid_dir, "t01", entries=[
        {"id": "r001", "content": "Use LIKE for series names", "status": "active"},
        {"id": "r002", "content": "old rule", "status": "inactive"},
    ])
    entries = learned_store.load_entries("t01")
    assert [e["id"] for e in entries] == ["r001"]


def test_load_entries_missing_file_returns_empty(tid_dir):
    assert learned_store.load_entries("t_missing") == []


def test_apply_learn_diff_appends_new_entry(tid_dir):
    _seed(tid_dir, "t02", entries=[])
    out = LearnConsolidateOutput(
        rule_content="Never hardcode SKUs from task_text",
        reasoning="prev hardcoded value",
        agents_md_anchor="#products > naming",
        deactivate_ids=[],
        skip=False,
    )
    learned_store.apply_learn_diff("t02", out)
    data = yaml.safe_load((tid_dir / "t02.yaml").read_text())
    assert data["entries"][0]["id"] == "r001"
    assert data["entries"][0]["status"] == "active"
    assert data["entries"][0]["agents_md_anchor"] == "#products > naming"
    assert data["entries"][0]["content"].startswith("Never hardcode")


def test_apply_learn_diff_deactivates_prior(tid_dir):
    _seed(tid_dir, "t03", entries=[
        {"id": "r001", "content": "Use exact eq on products.name", "status": "active"},
    ])
    out = LearnConsolidateOutput(
        rule_content="Use LIKE with token splits instead of exact eq on products.name",
        reasoning="exact eq missed multi-word names",
        deactivate_ids=["r001"],
        deactivate_reason="superseded by LIKE rule",
        skip=False,
    )
    learned_store.apply_learn_diff("t03", out)
    data = yaml.safe_load((tid_dir / "t03.yaml").read_text())
    ids = {e["id"]: e for e in data["entries"]}
    assert ids["r001"]["status"] == "inactive"
    assert ids["r001"]["deactivated_reason"] == "superseded by LIKE rule"
    assert ids["r002"]["status"] == "active"


def test_apply_learn_diff_skip_writes_nothing(tid_dir):
    _seed(tid_dir, "t04", entries=[{"id": "r001", "content": "rule", "status": "active"}])
    out = LearnConsolidateOutput(
        rule_content="",
        reasoning="duplicate",
        deactivate_ids=[],
        skip=True,
        skip_reason="r001",
    )
    learned_store.apply_learn_diff("t04", out)
    data = yaml.safe_load((tid_dir / "t04.yaml").read_text())
    assert [e["id"] for e in data["entries"]] == ["r001"]


def test_save_last_run_no_heuristic_valid_no_schema_hash(tid_dir):
    learned_store.save_last_run("t05", status="success", outcome="OUTCOME_OK", cycles_used=2)
    data = yaml.safe_load((tid_dir / "t05.yaml").read_text())
    lr = data["last_run"]
    assert lr["status"] == "success"
    assert lr["outcome"] == "OUTCOME_OK"
    assert lr["cycles_used"] == 2
    assert "heuristic_valid" not in lr
    assert "schema_hash" not in lr
    assert "date" in lr
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_learned_store.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'agent.learned_store'`.

- [ ] **Step 3: Create `agent/learned_store.py`**

```python
"""Per-task learned knowledge store. Replaces helpers from prompt_assembler."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from .models import LearnConsolidateOutput

_LEARNED_DIR = Path(__file__).parent.parent / "data" / "learned"

_MIN_CONTENT_LEN = 20
_VALID_RULE_STARTS = ("never", "always", "use", "do not", "when", "if", "prefer")


def _read(tid: str) -> dict:
    if not tid:
        return {}
    path = _LEARNED_DIR / f"{tid}.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write(tid: str, data: dict) -> None:
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    (_LEARNED_DIR / f"{tid}.yaml").write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def _next_entry_id(entries: list[dict]) -> str:
    used = {
        int(e["id"][1:])
        for e in entries
        if isinstance(e.get("id"), str) and e["id"].startswith("r") and e["id"][1:].isdigit()
    }
    return f"r{(max(used, default=0) + 1):03d}"


def load_entries(tid: str) -> list[dict]:
    """Return active entries only."""
    data = _read(tid)
    return [e for e in data.get("entries", []) if e.get("status") == "active"]


def apply_learn_diff(tid: str, out: LearnConsolidateOutput) -> None:
    """Append new rule + deactivate listed ids. Skip path writes nothing."""
    if not tid or out.skip:
        return

    content = (out.rule_content or "").strip()
    if len(content) < _MIN_CONTENT_LEN or not content.lower().startswith(_VALID_RULE_STARTS):
        return

    data = _read(tid)
    entries: list[dict] = list(data.get("entries", []))

    deact_ids = set(out.deactivate_ids or [])
    for e in entries:
        if e.get("id") in deact_ids:
            e["status"] = "inactive"
            e["deactivated_reason"] = out.deactivate_reason or "superseded"

    entries.append({
        "id": _next_entry_id(entries),
        "content": content,
        "agents_md_anchor": out.agents_md_anchor,
        "reasoning": (out.reasoning or "").strip(),
        "status": "active",
        "created": str(date.today()),
        "deactivated_reason": None,
    })

    data["task_id"] = tid
    data["entries"] = entries
    _write(tid, data)


def save_last_run(
    tid: str,
    status: str,
    outcome: str,
    cycles_used: int,
) -> None:
    """Persist last_run metadata. No heuristic_valid, no schema_hash."""
    if not tid:
        return
    data = _read(tid)
    data["task_id"] = tid
    data["last_run"] = {
        "status": status,
        "outcome": outcome,
        "cycles_used": cycles_used,
        "date": str(date.today()),
    }
    _write(tid, data)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_learned_store.py -v
```

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/learned_store.py tests/test_learned_store.py
git commit -m "feat(learned_store): per-task LearnConsolidate store; drop heuristic_valid/schema_hash"
```

---

## Task 3: Create `agent/mock_vm_spy.py`

**Files:**
- Create: `agent/mock_vm_spy.py`
- Create: `tests/test_mock_vm_spy.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mock_vm_spy.py`:

```python
import pytest

from agent.mock_vm_spy import MockVMSpy, fixture_key


def test_records_calls_in_order():
    vm = MockVMSpy(fixtures={})
    vm.exec(path="/bin/sql", args=[".schema baskets"])
    vm.read(path="/AGENTS.MD")
    assert vm.calls == [
        ("Exec", {"path": "/bin/sql", "args": [".schema baskets"]}),
        ("Read", {"path": "/AGENTS.MD"}),
    ]


def test_fixture_lookup_by_rpc_path_args():
    fx = {fixture_key("Exec", "/bin/sql", [".schema baskets"]): "schema-bytes"}
    vm = MockVMSpy(fixtures=fx)
    out = vm.exec(path="/bin/sql", args=[".schema baskets"])
    assert out == "schema-bytes"


def test_missing_fixture_returns_stub():
    vm = MockVMSpy(fixtures={})
    out = vm.exec(path="/bin/sql", args=["SELECT 1"])
    # stub is a deterministic empty-but-structured response
    assert out is not None


def test_answer_recorded_does_not_raise():
    vm = MockVMSpy(fixtures={})
    vm.answer(message="ok", outcome="OUTCOME_OK", refs=[])
    assert vm.calls[-1][0] == "Answer"


def test_all_rpcs_record():
    vm = MockVMSpy(fixtures={})
    vm.list(path="/proc")
    vm.tree(root="/", level=2)
    vm.find(root="/", name="*.json", limit=10)
    vm.search(root="/", pattern="foo", limit=5)
    vm.stat(path="/proc/x")
    vm.write(path="/tmp/x", content="data")
    vm.delete(path="/tmp/x")
    rpcs = [c[0] for c in vm.calls]
    assert rpcs == ["List", "Tree", "Find", "Search", "Stat", "Write", "Delete"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_mock_vm_spy.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create `agent/mock_vm_spy.py`**

```python
"""Recording mock VM used inside the fidelity gate."""
from __future__ import annotations

from typing import Any


def fixture_key(rpc: str, path: str, args: list[str] | None = None) -> str:
    arg_part = "|".join(args) if args else ""
    return f"{rpc}:{path}:{arg_part}"


_DEFAULT_STUB = {"stdout": "", "stderr": "", "content": "", "entries": [], "nodes": [], "matches": []}


class MockVMSpy:
    """Records every RPC call. Looks up canned responses from `fixtures`.

    Designed for use inside the deterministic fidelity test produced by
    `agent.fidelity.generate_fidelity_test`. NOT for production VM dispatch.
    """

    def __init__(self, fixtures: dict[str, Any]) -> None:
        self.fixtures = fixtures
        self.calls: list[tuple[str, dict]] = []

    def _record(self, rpc: str, **kwargs: Any) -> None:
        self.calls.append((rpc, kwargs))

    def _lookup(self, rpc: str, path: str, args: list[str] | None = None) -> Any:
        return self.fixtures.get(fixture_key(rpc, path, args), _DEFAULT_STUB)

    def read(self, path: str) -> Any:
        self._record("Read", path=path)
        return self._lookup("Read", path)

    def list(self, path: str) -> Any:
        self._record("List", path=path)
        return self._lookup("List", path)

    def tree(self, root: str, level: int = 0) -> Any:
        self._record("Tree", root=root, level=level)
        return self._lookup("Tree", root)

    def find(self, root: str, name: str = "", kind: str = "", limit: int = 0) -> Any:
        self._record("Find", root=root, name=name, kind=kind, limit=limit)
        return self._lookup("Find", root)

    def search(self, root: str, pattern: str = "", limit: int = 0) -> Any:
        self._record("Search", root=root, pattern=pattern, limit=limit)
        return self._lookup("Search", root)

    def exec(self, path: str, args: list[str] | None = None, stdin: str = "") -> Any:
        args_list = list(args or [])
        self._record("Exec", path=path, args=args_list)
        return self._lookup("Exec", path, args_list)

    def write(self, path: str, content: str = "", if_match_sha256: str = "") -> Any:
        self._record("Write", path=path, content=content, if_match_sha256=if_match_sha256)
        return self._lookup("Write", path)

    def delete(self, path: str) -> Any:
        self._record("Delete", path=path)
        return self._lookup("Delete", path)

    def stat(self, path: str) -> Any:
        self._record("Stat", path=path)
        return self._lookup("Stat", path)

    def answer(self, message: str, outcome: str, refs: list[str] | None = None) -> None:
        self._record("Answer", message=message, outcome=outcome, refs=list(refs or []))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_mock_vm_spy.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/mock_vm_spy.py tests/test_mock_vm_spy.py
git commit -m "feat(mock_vm_spy): recording spy for deterministic fidelity gate"
```

---

## Task 4: Create `agent/fidelity.py`

**Files:**
- Create: `agent/fidelity.py`
- Create: `tests/test_fidelity.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_fidelity.py`:

```python
import textwrap

import pytest

from agent.fidelity import (
    generate_fidelity_test,
    exec_fidelity_in_subprocess,
    FidelityResult,
)
from agent.models import (
    DesignOutput, ToolOp, AgentsMdRef, AnswerTemplate,
)


def _design():
    return DesignOutput(
        intent="count baskets",
        params={"store_id": "S001"},
        success_criteria=["cnt >= 0"],
        discovery=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": [".schema baskets"]}, bind="schema")],
        ops=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, bind="rows")],
        agents_md_constraints=[AgentsMdRef(anchor="#baskets > store_scope", rule="filter store_id")],
        answer_template=AnswerTemplate(message="{rows[0][cnt]} baskets", outcome="OUTCOME_OK", refs=[]),
        outcome_override=None,
    )


def test_generate_is_deterministic():
    d = _design()
    a = generate_fidelity_test(d, "t_fp")
    b = generate_fidelity_test(d, "t_fp")
    assert a == b


def test_generated_module_contains_expected_calls():
    d = _design()
    src = generate_fidelity_test(d, "t_fp")
    assert "EXPECTED_CALLS" in src
    assert "Exec" in src
    assert "/bin/sql" in src
    assert ".schema baskets" in src
    assert "Answer" in src


def test_subprocess_pass_path():
    """Script that emits EXPECTED_CALLS exactly → passes."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            vm.exec(path="/bin/sql", args=[".schema baskets"])
            vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
            vm.answer(message="0 baskets", outcome="OUTCOME_OK", refs=[])
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=30)
    assert isinstance(result, FidelityResult)
    assert result.passed, f"unexpected fail: {result.error}"


def test_subprocess_fail_extra_call():
    """Script that calls an extra RPC → fails the gate."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            vm.exec(path="/bin/sql", args=[".schema baskets"])
            vm.tree(root="/", level=1)
            vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
            vm.answer(message="0", outcome="OUTCOME_OK", refs=[])
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=30)
    assert not result.passed
    assert "Tree" in (result.error or "") or "drift" in (result.error or "")


def test_subprocess_fail_missing_discovery():
    """Skipped discovery op → fails the gate."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
            vm.answer(message="0", outcome="OUTCOME_OK", refs=[])
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=30)
    assert not result.passed


def test_subprocess_timeout():
    """Infinite loop → killed by timeout, reported as failure."""
    d = _design()
    test_src = generate_fidelity_test(d, "t_fp")
    script = textwrap.dedent('''
        def run(vm, params):
            while True:
                pass
    ''')
    result = exec_fidelity_in_subprocess(test_src, script, timeout_s=2)
    assert not result.passed
    assert "timeout" in (result.error or "").lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_fidelity.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create `agent/fidelity.py`**

```python
"""Deterministic fidelity gate.

Generates a Python test module from a DesignOutput tool_plan. Executes the
candidate script + test in a subprocess and asserts that the script's RPC
sequence matches the tool_plan exactly.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from typing import Any

from .models import DesignOutput, ToolOp


@dataclass
class FidelityResult:
    passed: bool
    error: str | None = None
    stdout: str = ""
    stderr: str = ""


def _serialize_expected(ops: list[ToolOp]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for op in ops:
        out.append((op.rpc, dict(op.args)))
    return out


def _expected_answer_call(d: DesignOutput) -> tuple[str, dict[str, Any]]:
    return (
        "Answer",
        {
            "message": d.answer_template.message,
            "outcome": d.answer_template.outcome,
            "refs": list(d.answer_template.refs),
        },
    )


def generate_fidelity_test(design: DesignOutput, tid: str) -> str:
    """Emit a Python module string. Deterministic — same input ⇒ byte-equal output."""
    expected: list[tuple[str, dict]] = []
    expected.extend(_serialize_expected(design.discovery))
    expected.extend(_serialize_expected(design.ops))
    expected.append(_expected_answer_call(design))

    expected_lit = json.dumps([list(item) for item in expected], sort_keys=False, indent=2)
    params_lit = json.dumps(design.params, sort_keys=True)
    template_msg = json.dumps(design.answer_template.message)
    template_outcome = json.dumps(design.answer_template.outcome)
    template_refs = json.dumps(list(design.answer_template.refs))

    return textwrap.dedent(f'''
        # auto-generated fidelity test for task {tid}
        from agent.mock_vm_spy import MockVMSpy

        EXPECTED_CALLS = [tuple([rpc, args]) for rpc, args in {expected_lit}]
        PARAMS = {params_lit}

        # Recognise the canned Answer call even if the script reuses the template literally
        EXPECTED_ANSWER = ("Answer", {{
            "message": {template_msg},
            "outcome": {template_outcome},
            "refs": {template_refs},
        }})


        def _normalise_calls(calls):
            return [(rpc, dict(args)) for rpc, args in calls]


        def test_fidelity():
            vm = MockVMSpy(fixtures={{}})
            run(vm, dict(PARAMS))   # noqa: F821 — `run` injected at exec time
            got = _normalise_calls(vm.calls)
            want = _normalise_calls(EXPECTED_CALLS)
            if got != want:
                raise AssertionError(
                    "fidelity drift\\nexpected: " + repr(want) + "\\ngot: " + repr(got)
                )
    ''')


def exec_fidelity_in_subprocess(
    test_src: str,
    script_code: str,
    timeout_s: int = 30,
) -> FidelityResult:
    """Combine script + test in a single source, exec in a subprocess, gate on test_fidelity()."""
    combined = (
        script_code
        + "\n\n"
        + test_src
        + "\n\nif __name__ == '__main__':\n"
        + "    test_fidelity()\n"
        + "    print('FIDELITY_OK')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", combined],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        return FidelityResult(passed=False, error=f"fidelity timeout after {timeout_s}s", stdout=e.stdout or "", stderr=e.stderr or "")

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if proc.returncode == 0 and "FIDELITY_OK" in stdout:
        return FidelityResult(passed=True, stdout=stdout, stderr=stderr)
    return FidelityResult(
        passed=False,
        error=(stderr or stdout).strip()[:2000],
        stdout=stdout,
        stderr=stderr,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_fidelity.py -v
```

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/fidelity.py tests/test_fidelity.py
git commit -m "feat(fidelity): deterministic tool-plan gate via subprocess + MockVMSpy"
```

---

## Task 5: Create `agent/design.py`

**Files:**
- Create: `agent/design.py`
- Create: `data/prompts/design.md` (minimal placeholder; final content in Task 7)
- Create: `tests/test_design.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_design.py`:

```python
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
    """F-001 regression guard: H2/H13/H15 forbid learn_ctx in DESIGN."""
    sig = inspect.signature(run_design)
    params = list(sig.parameters.keys())
    assert params == ["instruction", "agents_md_text"], params


def test_stray_learn_ctx_kwarg_raises_type_error():
    """F-001 regression guard."""
    with patch("agent.design.call_llm_raw", return_value=_GOOD_DESIGN_JSON):
        with pytest.raises(TypeError):
            run_design("hello", "AGENTS", learn_ctx=[])   # type: ignore[call-arg]


def test_happy_path_returns_design_output():
    with patch("agent.design.call_llm_raw", return_value=_GOOD_DESIGN_JSON):
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
    with patch("agent.design.call_llm_raw", return_value=blocked):
        out = run_design("dump all PII", "AGENTS")
    assert out.outcome_override == "OUTCOME_DENIED_SECURITY"


def test_unparseable_response_raises():
    from agent.design import DesignError
    with patch("agent.design.call_llm_raw", return_value="not json"):
        with pytest.raises(DesignError):
            run_design("x", "y")
```

Create `data/prompts/design.md` placeholder (full content in Task 7):

```bash
echo "# PHASE: DESIGN (placeholder — rewritten in Task 7)" > data/prompts/design.md
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_design.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create `agent/design.py`**

```python
"""DESIGN phase — single LLM call producing a tool_plan from instruction + AGENTS.MD.

Per H2/H13/H15: input strictly (instruction, agents_md_text). NO learn_ctx.
DESIGN is frozen per task run; LEARN feedback only feeds CODEGEN.
"""
from __future__ import annotations

import os
from pathlib import Path

from .json_extract import _extract_json_from_text
from .llm import call_llm_raw, _resolve_model_for_phase
from .models import DesignOutput
from .prompt import load_prompt


class DesignError(RuntimeError):
    pass


_PROTO_REF_PATH = Path(__file__).parent.parent / "docs" / "proto-api-reference.md"
_MAX_TOKENS_DESIGN = int(os.environ.get("MAX_TOKENS_DESIGN", "4096"))


def _proto_reference() -> str:
    try:
        return _PROTO_REF_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def run_design(instruction: str, agents_md_text: str) -> DesignOutput:
    """Run DESIGN phase. Returns DesignOutput or raises DesignError.

    H2/H13/H15: signature MUST NOT accept learn_ctx.
    """
    guide = load_prompt("design") or "# PHASE: DESIGN"
    proto_ref = _proto_reference()

    system: list[dict] = [
        {"type": "text", "text": proto_ref, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}},
    ]

    user_msg = (
        f"INSTRUCTION:\n{instruction}\n\n"
        f"AGENTS.MD:\n{agents_md_text}"
    )

    model = _resolve_model_for_phase("design", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_DESIGN)
    if not raw:
        raise DesignError("DESIGN LLM returned empty response")

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise DesignError(f"DESIGN: could not parse JSON; head: {raw[:200]!r}")

    try:
        return DesignOutput(**obj)
    except Exception as e:
        raise DesignError(f"DESIGN: pydantic validation failed: {e}; obj keys: {list(obj.keys())}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_design.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/design.py data/prompts/design.md tests/test_design.py
git commit -m "feat(design): single-call DESIGN phase grounded in proto-api-reference"
```

---

## Task 6: Create `agent/codegen_v2.py`

**Files:**
- Create: `agent/codegen_v2.py`
- Create: `tests/test_codegen_v2.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_codegen_v2.py`:

```python
import json
from unittest.mock import patch

import pytest

from agent.codegen_v2 import run_codegen, CodegenError
from agent.models import (
    DesignOutput, ToolOp, AgentsMdRef, AnswerTemplate, CodegenOutput,
)


def _design():
    return DesignOutput(
        intent="count baskets",
        params={"store_id": "$agent_store_id"},
        success_criteria=["rows non-empty"],
        discovery=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": [".schema baskets"]}, bind="schema")],
        ops=[ToolOp(rpc="Exec", args={"path": "/bin/sql", "args": ["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"]}, bind="rows")],
        agents_md_constraints=[AgentsMdRef(anchor="#baskets > store_scope", rule="filter store_id")],
        answer_template=AnswerTemplate(message="{rows[0][cnt]} baskets", outcome="OUTCOME_OK", refs=[]),
        outcome_override=None,
    )


_GOOD_SCRIPT = '''
def run(vm, params):
    vm.exec(path="/bin/sql", args=[".schema baskets"])
    rows = vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets WHERE store_id=:store_id"])
    vm.answer(message="0 baskets", outcome="OUTCOME_OK", refs=[])
'''


def test_happy_path_returns_codegen_output():
    payload = json.dumps({"script_code": _GOOD_SCRIPT})
    with patch("agent.codegen_v2.call_llm_raw", return_value=payload):
        out = run_codegen(_design(), learn_ctx=[], prev_error=None)
    assert isinstance(out, CodegenOutput)
    assert "def run(vm, params)" in out.script_code


def test_learn_ctx_passed_in_user_msg():
    captured = {}

    def _fake_llm(system, user_msg, *a, **kw):
        captured["user_msg"] = user_msg
        return json.dumps({"script_code": _GOOD_SCRIPT})

    with patch("agent.codegen_v2.call_llm_raw", side_effect=_fake_llm):
        run_codegen(_design(), learn_ctx=["Never hardcode SKUs"], prev_error=None)
    assert "Never hardcode SKUs" in captured["user_msg"]


def test_prev_error_appended():
    captured = {}

    def _fake_llm(system, user_msg, *a, **kw):
        captured["user_msg"] = user_msg
        return json.dumps({"script_code": _GOOD_SCRIPT})

    with patch("agent.codegen_v2.call_llm_raw", side_effect=_fake_llm):
        run_codegen(_design(), learn_ctx=[], prev_error="lint: invalid syntax")
    assert "lint: invalid syntax" in captured["user_msg"]


def test_unparseable_raises_codegen_error():
    with patch("agent.codegen_v2.call_llm_raw", return_value="<not json>"):
        with pytest.raises(CodegenError):
            run_codegen(_design(), learn_ctx=[], prev_error=None)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_codegen_v2.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create `agent/codegen_v2.py`**

```python
"""CODEGEN phase v2 — translates a tool_plan to a Python `run(vm, params)` module."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .json_extract import _extract_json_from_text
from .llm import call_llm_raw, _resolve_model_for_phase
from .models import CodegenOutput, DesignOutput
from .prompt import load_prompt


class CodegenError(RuntimeError):
    pass


_PROTO_REF_PATH = Path(__file__).parent.parent / "docs" / "proto-api-reference.md"
_MAX_TOKENS_CODEGEN = int(os.environ.get("MAX_TOKENS_CODEGEN", "8192"))


def _proto_reference() -> str:
    try:
        return _PROTO_REF_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _design_to_tool_plan_json(d: DesignOutput) -> str:
    return d.model_dump_json(indent=2)


def run_codegen(
    design: DesignOutput,
    learn_ctx: list[dict],
    prev_error: str | None,
) -> CodegenOutput:
    """Translate `design.tool_plan` into a Python module. Returns CodegenOutput or raises."""
    guide = load_prompt("codegen") or "# PHASE: CODEGEN"
    proto_ref = _proto_reference()

    system: list[dict] = [
        {"type": "text", "text": proto_ref, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}},
    ]

    parts = [
        f"TOOL_PLAN:\n{_design_to_tool_plan_json(design)}",
    ]
    if learn_ctx:
        rule_lines = "\n".join(
            f"  - [{e.get('id', '?')}] {e.get('content', '')}" for e in learn_ctx
        )
        parts.append(f"LEARNED_RULES (active):\n{rule_lines}")
    if prev_error:
        parts.append(f"PREVIOUS_ERROR:\n{prev_error}")

    user_msg = "\n\n".join(parts)

    model = _resolve_model_for_phase("codegen", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_CODEGEN)
    if not raw:
        raise CodegenError("CODEGEN LLM returned empty response")

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict) or "script_code" not in obj:
        raise CodegenError(f"CODEGEN: could not parse script_code from response; head: {raw[:200]!r}")

    return CodegenOutput(script_code=obj["script_code"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_codegen_v2.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/codegen_v2.py tests/test_codegen_v2.py
git commit -m "feat(codegen_v2): tool_plan → run(vm, params) translator with learn_ctx feedback"
```

---

## Task 7: Write DESIGN / CODEGEN / LEARN prompts

**Files:**
- Modify: `data/prompts/design.md`
- Modify: `data/prompts/codegen.md`
- Modify: `data/prompts/learn.md`

- [ ] **Step 1: Overwrite `data/prompts/design.md`**

```markdown
# PHASE: DESIGN

You receive an INSTRUCTION and the verbatim AGENTS.MD vault rules.
You produce a deterministic tool_plan — the smallest sequence of vm RPCs
that solves the instruction, grounded in `docs/proto-api-reference.md`
(already in your system prompt).

## Output format

Single JSON object — no prose, no markdown fences:

```json
{
  "intent": "<one-sentence summary>",
  "params": {"<name>": "<literal or $agent_var>"},
  "success_criteria": ["<observable condition>"],
  "discovery": [
    {"rpc": "Exec|Read|List|Tree|Find|Search|Stat", "args": {...}, "bind": "<name>"}
  ],
  "ops": [
    {"rpc": "Exec|Read|Write|Delete", "args": {...}, "bind": "<name>"}
  ],
  "agents_md_constraints": [
    {"anchor": "<#section > entry>", "rule": "<verbatim AGENTS.MD line>"}
  ],
  "answer_template": {
    "message": "<f-string-style template referencing bound vars>",
    "outcome": "OUTCOME_OK",
    "refs": ["<grounding path>"]
  },
  "outcome_override": null
}
```

Set `outcome_override` to `"OUTCOME_DENIED_SECURITY"` or `"OUTCOME_NONE_UNSUPPORTED"`
if the instruction itself violates AGENTS.MD policy or asks for an
operation not supported by the VM. In that case discovery/ops may be empty
and `answer_template.message` carries the human reason.

## Tool selection rules

- Prefer `Find` / `Search` / `Read` with `start_line` / `end_line` over
  `Tree` + manual parse.
- Use `Exec /bin/sql` with parameterised placeholders (`:name`) — never inline literals from `params`.
- Use `Stat` before `Read` when the path might not exist.
- Batch SQL with CTEs into a single `Exec /bin/sql` rather than multiple round-trips.
- `discovery` items must read-only.
- `ops` items perform the work that produces the answer.

## AGENTS.MD anchoring

For every constraint that applies (store scope, issuer_id, RBAC),
copy the verbatim AGENTS.MD line into `agents_md_constraints[*].rule`
and reference it by `#section > entry` anchor. The CODEGEN phase
will compile these into in-code fail-fast checks.
```

- [ ] **Step 2: Overwrite `data/prompts/codegen.md`**

```markdown
# PHASE: CODEGEN

You receive a TOOL_PLAN (JSON), optional LEARNED_RULES, and an optional PREVIOUS_ERROR.
You produce a single self-contained Python module that solves the task by
calling the VM exactly as TOOL_PLAN describes.

## Output format

Single JSON object — no prose, no markdown fences:

```json
{"script_code": "def run(vm, params):\n    ...\n"}
```

## Script requirements

- Top-level `def run(vm, params)`.
- `vm` exposes: `read`, `list`, `tree`, `find`, `search`, `exec`, `write`, `delete`, `stat`, `answer`.
  All take keyword args matching `proto-api-reference.md`.
- Execute every `discovery` op, in order, then every `ops` op, in order.
  Bind results to local variables named after `bind`.
- For each `agents_md_constraints` entry, emit an `assert` or `if … vm.answer(OUTCOME_DENIED_SECURITY)` guard
  before the related op runs.
- Format `answer_template.message` using the bound variables; call `vm.answer(message=..., outcome=..., refs=[...])` exactly once at the end.

## Forbidden

- Hardcoding values from the instruction.
- Calling RPCs not present in TOOL_PLAN.
- Skipping discovery ops.
- Computing SQL strings — emit them as written in TOOL_PLAN.
- Filesystem access outside `vm.*`.
- Network calls.

## Param substitution

`params` is a dict. Values starting with `$` (e.g. `$agent_store_id`) are pre-resolved by the caller —
read them directly: `store_id = params["store_id"]`. Pass them through `vm.exec(args=[":name"], ...)` style
parameterised SQL; do not interpolate into the SQL string.

## Outcome codes

`OUTCOME_OK | OUTCOME_DENIED_SECURITY | OUTCOME_NONE_UNSUPPORTED | OUTCOME_NONE_CLARIFICATION`.
```

- [ ] **Step 3: Overwrite `data/prompts/learn.md`**

```markdown
# PHASE: LEARN + CONSOLIDATE (merged)

You diagnose a failed CODEGEN cycle and either produce a new corrective rule
or skip if the failure is already covered. You may also deactivate stale rules
that contradict the new one — this replaces the standalone CONSOLIDATE phase.

## Inputs

- `TASK` — original instruction
- `TOOL_PLAN` — DesignOutput JSON for this run (frozen — do not propose tool_plan changes)
- `ERROR` — error string (`lint:`, `fidelity:`, `codegen_llm_fail:`)
- `SCRIPT_CODE` — the failing CODEGEN output
- `EXISTING_RULES` — active rules from prior cycles in this and earlier runs

## Output format

Single JSON object — no prose, no markdown fences:

```json
{
  "rule_content": "<starts with Never|Always|Use|Do not|When|If|Prefer>",
  "agents_md_anchor": "<#section > entry> or null",
  "reasoning": "<diagnosis: verbatim error, root cause, failing fragment, rule linkage>",
  "deactivate_ids": ["rXXX"],
  "deactivate_reason": "<why these become obsolete> or null",
  "skip": false,
  "skip_reason": null
}
```

## Rules

- `rule_content` must describe a CODEGEN technique — how to translate `tool_plan` to script — not domain conclusions.
- `rule_content` must be task-agnostic — never embed literal task params (SKUs, brand names, dates).
- Skip (`skip: true`) only if the new rule is semantically identical to an existing one.
- Use `deactivate_ids` when the new rule strictly supersedes prior rules — set `deactivate_reason`.
- Length: `rule_content` ≥ 20 chars; must start with one of the listed lead verbs.
```

- [ ] **Step 4: Verify prompts load**

```bash
uv run python -c "from agent.prompt import load_prompt; assert 'DESIGN' in load_prompt('design'); assert 'CODEGEN' in load_prompt('codegen'); assert 'LEARN' in load_prompt('learn'); print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add data/prompts/design.md data/prompts/codegen.md data/prompts/learn.md
git commit -m "feat(prompts): rewrite design/codegen/learn for tool_plan pipeline"
```

---

## Task 8: Rewrite `agent/pipeline.py`

**Files:**
- Modify: `agent/pipeline.py` (full rewrite)
- Create: `tests/test_pipeline_v2.py`
- Create: `tests/test_learn_consolidate.py`

- [ ] **Step 1: Write failing tests — fidelity / learn / loop / terminal**

Create `tests/test_learn_consolidate.py`:

```python
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
```

Create `tests/test_pipeline_v2.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.pipeline import run_pipeline, _extract_sql_literals, _identical_sql_set


_GOOD_DESIGN = {
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


_GOOD_SCRIPT = '''
def run(vm, params):
    rows = vm.exec(path="/bin/sql", args=["SELECT COUNT(*) AS cnt FROM baskets"])
    vm.answer(message="ok", outcome="OUTCOME_OK", refs=[])
'''


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError("LLM called more times than expected")
    return _next


def test_outcome_override_terminal(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)

    blocked = dict(_GOOD_DESIGN, outcome_override="OUTCOME_DENIED_SECURITY",
                   discovery=[], ops=[],
                   answer_template={"message": "denied", "outcome": "OUTCOME_DENIED_SECURITY", "refs": []})
    vm = MagicMock()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(json.dumps(blocked))):
        run_pipeline(vm, instruction="dump pii", task_id="t_block", agents_md_text="AGENTS")
    vm.answer.assert_called_once()
    args, kwargs = vm.answer.call_args
    assert kwargs.get("outcome") == "OUTCOME_DENIED_SECURITY" or "OUTCOME_DENIED_SECURITY" in str(args)


def test_happy_path_design_plus_one_codegen(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)

    vm = MagicMock()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(
        json.dumps(_GOOD_DESIGN),
        json.dumps({"script_code": _GOOD_SCRIPT}),
    )):
        run_pipeline(vm, instruction="how many baskets", task_id="t_hp", agents_md_text="AGENTS")
    vm.answer.assert_called_once()
    # learned/last_run persisted
    import yaml
    data = yaml.safe_load((tmp_path / "t_hp.yaml").read_text())
    assert data["last_run"]["outcome"] == "OUTCOME_OK"


def test_exhaust_path_terminates_clarification(tmp_path, monkeypatch):
    from agent import learned_store
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)

    bad_script = '{"script_code": "def run(vm, params):\\n    vm.tree(root=\\"/\\")\\n"}'
    learn_payload = json.dumps({
        "rule_content": "Always use Exec for SQL ops listed in tool_plan",
        "agents_md_anchor": None,
        "reasoning": "script called Tree not in plan",
        "deactivate_ids": [],
        "deactivate_reason": None,
        "skip": False,
        "skip_reason": None,
    })
    # 1 DESIGN + 3 × (CODEGEN + LearnConsolidate) = 7 calls
    seq = [
        json.dumps(_GOOD_DESIGN),
        bad_script, learn_payload,
        bad_script, learn_payload,
        bad_script, learn_payload,
    ]
    vm = MagicMock()
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(*seq)):
        run_pipeline(vm, instruction="how many baskets", task_id="t_ex", agents_md_text="AGENTS")
    vm.answer.assert_called_once()
    args, kwargs = vm.answer.call_args
    assert kwargs.get("outcome") == "OUTCOME_NONE_CLARIFICATION" or "OUTCOME_NONE_CLARIFICATION" in str(args)


def test_extract_sql_literals_basic():
    code = '''
def run(vm, params):
    vm.exec(path="/bin/sql", args=["SELECT   1"])
    vm.exec(path="/bin/sql", args=["select 1"])
    vm.exec(path="/bin/sh", args=["ls"])
'''
    sqls = _extract_sql_literals(code)
    assert "SELECT 1" in sqls
    assert "select 1" in sqls
    assert all("ls" not in s for s in sqls)


def test_extract_sql_literals_ignores_fstrings():
    code = '''
def run(vm, params):
    q = f"SELECT * FROM t WHERE id={params['id']}"
    vm.exec(path="/bin/sql", args=[q])
'''
    sqls = _extract_sql_literals(code)
    assert sqls == []


def test_identical_sql_set_normalises_whitespace():
    a = ["SELECT  1", "SELECT 2"]
    b = ["select 2", "SELECT 1"]   # different order, different case, extra ws
    # case-sensitive per F-005 ("no other casing or token rewrites")
    assert not _identical_sql_set(a, b)
    c = ["SELECT  1", "  SELECT 2  "]
    d = ["SELECT 1", "SELECT 2"]
    assert _identical_sql_set(c, d)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_learn_consolidate.py tests/test_pipeline_v2.py -v
```

Expected: FAIL — `ImportError` (`_learn_consolidate`, `_extract_sql_literals`, `_identical_sql_set` not yet defined; `run_pipeline` has old signature).

- [ ] **Step 3: Overwrite `agent/pipeline.py`**

```python
"""DESIGN → CODEGEN → fidelity → ANSWER pipeline (terminal one-shot ANSWER)."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from bitgn.vm.ecom.ecom_pb2 import AnswerRequest

from .codegen_v2 import CodegenError, run_codegen
from .design import DesignError, run_design
from .fidelity import exec_fidelity_in_subprocess, generate_fidelity_test
from .json_extract import _extract_json_from_text
from .learned_store import apply_learn_diff, load_entries, save_last_run
from .llm import (
    CLI_BLUE, CLI_CLR, CLI_GREEN, CLI_RED, CLI_YELLOW,
    OUTCOME_BY_NAME, _resolve_model_for_phase, call_llm_raw,
)
from .models import DesignOutput, LearnConsolidateOutput
from .prompt import load_prompt
from .sql_security import check_retry_loop
from .trace import get_trace

_MAX_STEPS = int(os.environ.get("MAX_STEPS", "3"))
_MAX_TOKENS_LEARN = int(os.environ.get("MAX_TOKENS_LEARN", "2048"))
_FIDELITY_TIMEOUT_S = int(os.environ.get("FIDELITY_TIMEOUT_S", "30"))

_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# SQL extraction for check_retry_loop (F-005)
# ---------------------------------------------------------------------------

def _extract_sql_literals(script_code: str) -> list[str]:
    """Return literal SQL strings passed to vm.exec(path='/bin/sql', args=[...]).

    Per F-005: walk ast.Constant nodes whose parent is a Call to vm.exec
    where args[0] == '/bin/sql'. Computed SQL (concat, f-strings) is ignored.
    """
    try:
        tree = ast.parse(script_code)
    except SyntaxError:
        return []

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_vm_exec = (
            isinstance(func, ast.Attribute)
            and func.attr == "exec"
            and isinstance(func.value, ast.Name)
            and func.value.id == "vm"
        )
        if not is_vm_exec:
            continue
        path_val = None
        args_node = None
        for kw in node.keywords:
            if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                path_val = kw.value.value
            if kw.arg == "args":
                args_node = kw.value
        if path_val != "/bin/sql" or not isinstance(args_node, (ast.List, ast.Tuple)):
            continue
        for elt in args_node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
    return out


def _normalise(sql: str) -> str:
    return _WHITESPACE_RE.sub(" ", sql).strip()


def _identical_sql_set(a: list[str], b: list[str]) -> bool:
    """Multiset equality after whitespace collapse + strip; case-sensitive."""
    return sorted(_normalise(s) for s in a) == sorted(_normalise(s) for s in b)


# ---------------------------------------------------------------------------
# Learn + consolidate (merged LLM call)
# ---------------------------------------------------------------------------

def _learn_consolidate(
    task_id: str,
    learn_ctx: list[dict],
    design: DesignOutput,
    error: str,
    script_code: str,
) -> None:
    """Single LLM call. Writes a diff to data/learned/{tid}.yaml and mutates learn_ctx."""
    guide = load_prompt("learn") or "# PHASE: LEARN"
    system = [{"type": "text", "text": guide, "cache_control": {"type": "ephemeral"}}]

    rules_lines = "\n".join(
        f"  - [{e.get('id', '?')}] {e.get('content', '')}" for e in learn_ctx
    ) or "(none)"
    user_msg = (
        f"TOOL_PLAN:\n{design.model_dump_json(indent=2)}\n\n"
        f"ERROR:\n{error}\n\n"
        f"SCRIPT_CODE:\n```python\n{script_code[:4000]}\n```\n\n"
        f"EXISTING_RULES:\n{rules_lines}"
    )

    model = _resolve_model_for_phase("learn", os.environ.get("MODEL", ""))
    raw = call_llm_raw(system, user_msg, model, {}, max_tokens=_MAX_TOKENS_LEARN)
    if not raw:
        print(f"{CLI_YELLOW}[pipeline] LEARN: empty response, skipping{CLI_CLR}")
        return

    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        print(f"{CLI_YELLOW}[pipeline] LEARN: unparseable response, skipping{CLI_CLR}")
        return

    try:
        out = LearnConsolidateOutput(**obj)
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] LEARN: validation failed: {e}{CLI_CLR}")
        return

    apply_learn_diff(task_id, out)

    if not out.skip:
        learn_ctx.append({
            "id": "in-session",
            "content": out.rule_content,
            "agents_md_anchor": out.agents_md_anchor,
        })


# ---------------------------------------------------------------------------
# Terminal exits — exactly one vm.answer() per task
# ---------------------------------------------------------------------------

def _terminal_clarification(vm, message: str) -> None:
    vm.answer(message=message[:800], outcome="OUTCOME_NONE_CLARIFICATION", refs=[])


def _terminal_outcome_override(vm, design: DesignOutput) -> None:
    vm.answer(
        message=design.answer_template.message,
        outcome=design.outcome_override,
        refs=list(design.answer_template.refs),
    )


# ---------------------------------------------------------------------------
# Real-VM exec
# ---------------------------------------------------------------------------

def _run_script_on_vm(script_code: str, vm, params: dict[str, str]) -> None:
    """Exec the script's top-level module; call its `run(vm, params)`."""
    ns: dict = {}
    exec(compile(script_code, "<heuristic>", "exec"), ns)
    fn = ns.get("run")
    if not callable(fn):
        raise RuntimeError("script does not define run(vm, params)")
    fn(vm, params)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_pipeline(
    vm,
    instruction: str,
    task_id: str,
    agents_md_text: str,
) -> None:
    """Per-task pipeline. Exactly one vm.answer() call before returning."""
    tlog = get_trace()
    if tlog:
        tlog.log_header(instruction, os.environ.get("MODEL", ""))
    learn_ctx = load_entries(task_id)
    print(f"{CLI_BLUE}[pipeline] task={task_id} active_rules={len(learn_ctx)}{CLI_CLR}")

    # ── DESIGN ──────────────────────────────────────────────────────────────
    try:
        design = run_design(instruction, agents_md_text)
    except DesignError as e:
        print(f"{CLI_RED}[pipeline] DESIGN failed: {e}{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=0)
        _terminal_clarification(vm, f"DESIGN failed: {e}")
        return

    if design.outcome_override:
        print(f"{CLI_YELLOW}[pipeline] outcome_override: {design.outcome_override}{CLI_CLR}")
        save_last_run(task_id, status="success", outcome=design.outcome_override, cycles_used=0)
        _terminal_outcome_override(vm, design)
        return

    # ── CODEGEN retry loop (unified MAX_STEPS counter, F-003) ──────────────
    last_error: str | None = None
    script_code: str | None = None
    prior_sql_sets: list[list[str]] = []

    for cycle in range(1, _MAX_STEPS + 1):
        print(f"{CLI_BLUE}[pipeline] cycle {cycle}/{_MAX_STEPS}{CLI_CLR}")

        try:
            cg = run_codegen(design, learn_ctx, last_error)
        except CodegenError as e:
            last_error = f"codegen_llm_fail: {e}"
            print(f"{CLI_YELLOW}[pipeline] CODEGEN llm fail: {e}{CLI_CLR}")
            continue   # no LEARN; just retry

        # Lint gate
        try:
            ast.parse(cg.script_code)
        except SyntaxError as e:
            last_error = f"lint: {e}"
            print(f"{CLI_YELLOW}[pipeline] lint fail: {e}{CLI_CLR}")
            _learn_consolidate(task_id, learn_ctx, design, last_error, cg.script_code)
            continue

        # check_retry_loop — anti-infinite-loop guard (HM4)
        sqls = _extract_sql_literals(cg.script_code)
        if prior_sql_sets and _identical_sql_set(sqls, prior_sql_sets[-1]):
            print(f"{CLI_RED}[pipeline] check_retry_loop: identical SQL set, breaking{CLI_CLR}")
            last_error = last_error or "identical SQL set across cycles"
            break
        loop_msg = check_retry_loop([_normalise(s) for s in sqls], [frozenset(_normalise(s) for s in p) for p in prior_sql_sets])
        if loop_msg:
            print(f"{CLI_RED}[pipeline] {loop_msg}{CLI_CLR}")
            last_error = loop_msg
            break
        prior_sql_sets.append(sqls)

        # Fidelity gate
        test_src = generate_fidelity_test(design, task_id)
        result = exec_fidelity_in_subprocess(test_src, cg.script_code, timeout_s=_FIDELITY_TIMEOUT_S)
        if not result.passed:
            last_error = f"fidelity: {result.error}"
            print(f"{CLI_YELLOW}[pipeline] fidelity fail: {result.error}{CLI_CLR}")
            _learn_consolidate(task_id, learn_ctx, design, last_error, cg.script_code)
            continue

        # Gate passed — break out of loop
        script_code = cg.script_code
        break

    if script_code is None:
        print(f"{CLI_RED}[pipeline] exhausted {_MAX_STEPS} cycles{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=_MAX_STEPS)
        _terminal_clarification(vm, last_error or "all cycles exhausted")
        return

    # ── Persist last-attempt script (reference for LEARN, not for re-exec) ─
    heur_dir = Path("data/heuristics")
    heur_dir.mkdir(parents=True, exist_ok=True)
    (heur_dir / f"{task_id}.py").write_text(script_code, encoding="utf-8")

    # ── ANSWER terminal one-shot (real VM) ──────────────────────────────────
    try:
        _run_script_on_vm(script_code, vm, design.params)
    except Exception as e:
        print(f"{CLI_RED}[pipeline] real-vm exec failed: {e}{CLI_CLR}")
        save_last_run(task_id, status="failure", outcome="OUTCOME_NONE_CLARIFICATION", cycles_used=cycle)
        _terminal_clarification(vm, f"real-vm exec: {e}")
        return

    print(f"{CLI_GREEN}[pipeline] success after {cycle} cycle(s){CLI_CLR}")
    save_last_run(task_id, status="success", outcome="OUTCOME_OK", cycles_used=cycle)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_learn_consolidate.py tests/test_pipeline_v2.py -v
```

Expected: PASS (8 tests). If `run_pipeline` test mocks fail because `vm.answer` is called with positional vs keyword args, inspect the call in `_terminal_*` and align — the implementation above uses kwargs throughout.

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_v2.py tests/test_learn_consolidate.py
git commit -m "feat(pipeline): unified MAX_STEPS loop, fidelity gate, terminal ANSWER, check_retry_loop via ast.walk"
```

---

## Task 9: Trim `agent/orchestrator.py`

**Files:**
- Modify: `agent/orchestrator.py`

- [ ] **Step 1: Overwrite `agent/orchestrator.py`**

```python
"""Minimal orchestrator — reads AGENTS.MD then dispatches the pipeline."""
from __future__ import annotations

import os

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import ReadRequest

from agent.pipeline import run_pipeline


def _read_agents_md(vm: EcomRuntimeClientSync) -> str:
    for candidate in ("/AGENTS.MD", "/AGENTS.md"):
        try:
            r = vm.read(ReadRequest(path=candidate))
            if r.content:
                return r.content
        except Exception:
            continue
    return ""


def run_agent(
    model_configs: dict,
    harness_url: str,
    task_text: str,
    task_id: str = "",
    injected_session_rules: list[str] | None = None,    # accepted for harness compat; unused
    injected_prompt_addendum: str = "",                  # accepted for harness compat; unused
) -> dict:
    vm = EcomRuntimeClientSync(harness_url)
    agents_md_text = _read_agents_md(vm)
    run_pipeline(vm, instruction=task_text, task_id=task_id, agents_md_text=agents_md_text)
    return {
        "model_used": os.environ.get("MODEL", ""),
        "task_type": "lookup",
    }
```

- [ ] **Step 2: Smoke-import**

```bash
uv run python -c "from agent.orchestrator import run_agent; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add agent/orchestrator.py
git commit -m "refactor(orchestrator): drop prephase; read AGENTS.MD inline"
```

---

## Task 10: Delete obsolete source / prompts / data

**Files:**
- Delete: `agent/prephase.py`, `agent/prompt_assembler.py`, `agent/evaluator.py`
- Delete: `data/prompts/idd.md`, `data/prompts/sdd.md`, `data/prompts/plan.md`, `data/prompts/assembler.md`, `data/prompts/tdd.md`, `data/prompts/answer.md`, `data/prompts/consolidate.md`
- Delete: `data/eval_log.jsonl`, `data/heuristics/t01.py`, `data/heuristics/t99.py`, `data/heuristics/*_test.py`
- Delete: obsolete tests (full list below)

- [ ] **Step 1: Delete source modules**

`agent/mock_vm.py` is intentionally NOT deleted — spec Delete-source lists only `prephase.py`, `prompt_assembler.py`, `evaluator.py`. If `mock_vm.py` later proves unused, remove in a follow-up.

```bash
git rm agent/prephase.py agent/prompt_assembler.py agent/evaluator.py
```

- [ ] **Step 2: Delete obsolete prompts**

```bash
git rm data/prompts/idd.md data/prompts/sdd.md data/prompts/plan.md data/prompts/assembler.md data/prompts/tdd.md data/prompts/answer.md data/prompts/consolidate.md
```

- [ ] **Step 3: Delete obsolete data**

```bash
git rm -f data/eval_log.jsonl data/heuristics/t01.py data/heuristics/t99.py
find data/heuristics -name '*_test.py' -print -delete
```

- [ ] **Step 4: Delete obsolete tests**

```bash
git rm tests/test_pipeline.py tests/test_prephase.py tests/test_prompt_assembler.py \
       tests/test_codegen.py tests/test_fast_path.py tests/test_orchestrator_pipeline.py \
       tests/test_sdd_action_fix.py tests/test_schema_gate.py tests/test_pipeline_models.py \
       tests/test_models_cleanup.py tests/test_models_consolidate.py tests/test_models_json_cleanup.py \
       tests/test_test_runner.py tests/test_trace_pipeline.py tests/test_ref_bugs.py \
       tests/test_answer.py
```

`tests/test_mock_vm.py` kept until `agent/mock_vm.py` is itself removed in a follow-up.

- [ ] **Step 5: Delete review-list tests now folded into new tests**

Folded coverage:
- `test_consolidate.py` → folded into `test_learn_consolidate.py`
- `test_learned_storage.py` → folded into `test_learned_store.py`
- `test_llm_phases.py` → reduced to `test_llm_module.py` (kept) — drop the phases test
- `test_prompt_loader.py` — keep only the assertion that DESIGN/CODEGEN/LEARN prompts exist (overwrite below)

```bash
git rm tests/test_consolidate.py tests/test_learned_storage.py tests/test_llm_phases.py
```

- [ ] **Step 6: Overwrite `tests/test_prompt_loader.py` to assert new prompts**

```python
from agent.prompt import load_prompt


def test_design_prompt_loaded():
    txt = load_prompt("design")
    assert "DESIGN" in txt
    assert "tool_plan" in txt or "tool plan" in txt.lower()


def test_codegen_prompt_loaded():
    txt = load_prompt("codegen")
    assert "CODEGEN" in txt
    assert "script_code" in txt


def test_learn_prompt_loaded():
    txt = load_prompt("learn")
    assert "LEARN" in txt
    assert "rule_content" in txt


def test_deleted_prompts_absent():
    for name in ("idd", "sdd", "plan", "assembler", "tdd", "answer", "consolidate"):
        assert load_prompt(name) == "", f"{name} prompt must be deleted"
```

- [ ] **Step 7: Run remaining tests to detect dangling imports**

```bash
uv run pytest tests/ -v --no-header
```

Expected: all previously created tests pass; no `ImportError` from deleted modules. If a kept test (e.g. `test_llm_module.py`, `test_trace_main.py`, `test_agents_md_parser.py`, `test_sql_security.py`, `test_json_extract_cleanup.py`, `test_trace.py`) imports a deleted module, surgically remove that import + any references — no logic changes.

- [ ] **Step 8: Commit**

```bash
git add -u
git commit -m "chore: delete prephase/prompt_assembler/evaluator/mock_vm + obsolete prompts/data/tests"
```

---

## Task 11: Reset `data/learned/t01.yaml` and `t99.yaml`

**Files:**
- Modify: `data/learned/t01.yaml`, `data/learned/t99.yaml`

- [ ] **Step 1: Reset both YAML files**

Overwrite `data/learned/t01.yaml`:

```yaml
task_id: t01
entries: []
last_run: null
```

Overwrite `data/learned/t99.yaml`:

```yaml
task_id: t99
entries: []
last_run: null
```

- [ ] **Step 2: Verify loadable**

```bash
uv run python -c "from agent.learned_store import load_entries; print(load_entries('t01'), load_entries('t99'))"
```

Expected: `[] []`.

- [ ] **Step 3: Commit**

```bash
git add data/learned/t01.yaml data/learned/t99.yaml
git commit -m "reset(learned): clear t01/t99 entries for fresh DESIGN+CODEGEN run"
```

---

## Task 12: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Replace the Models / Tokens block**

Read current `.env.example`. In the `# ─── Phase Models ───` section:

- Remove lines that set: `MODEL_IDD`, `MODEL_SDD`, `MODEL_PLAN`, `MODEL_ASSEMBLER`, `MODEL_CONSOLIDATE`, `MODEL_EXECUTOR` (keep `MODEL`, `MODEL_FALLBACK`, `MODEL_LEARN`, `MODEL_CODEGEN`)
- Do NOT add `MODEL_DESIGN` — `agent/llm.py:_PHASE_MODEL_MAP` lacks a `design` key and llm.py is in spec Keep / intent No-autonomy. The DESIGN phase reads `MODEL` directly via fallback. Adding the var would mislead.

In the `# ─── Phase Max Tokens ───` section:

- Add line: `MAX_TOKENS_DESIGN=4096               # DESIGN phase response limit`
- Add line: `FIDELITY_TIMEOUT_S=30                # subprocess timeout for fidelity gate`
- Remove lines that set: `MAX_TOKENS_IDD`, `MAX_TOKENS_SDD`, `MAX_TOKENS_PLAN`, `MAX_TOKENS_ANSWER`, `MAX_TOKENS_ASSEMBLER`, `MAX_TOKENS_CONSOLIDATE`, `CODEGEN_LINT_RETRIES`, `SDD_ENABLED`
- Keep `MAX_TOKENS_LEARN` and `MAX_TOKENS_CODEGEN`.

- [ ] **Step 2: Verify the diff is consistent**

```bash
grep -E '^(MODEL_IDD|MODEL_SDD|MODEL_PLAN|MODEL_ASSEMBLER|MODEL_CONSOLIDATE|MODEL_EXECUTOR|MODEL_DESIGN|MAX_TOKENS_IDD|MAX_TOKENS_SDD|MAX_TOKENS_PLAN|MAX_TOKENS_ANSWER|MAX_TOKENS_ASSEMBLER|MAX_TOKENS_CONSOLIDATE|CODEGEN_LINT_RETRIES|SDD_ENABLED)=' .env.example && echo FAIL || echo OK_NO_REMOVED_VARS
grep -E '^(MAX_TOKENS_DESIGN|FIDELITY_TIMEOUT_S)=' .env.example
grep -E '^(MODEL|MODEL_FALLBACK|MODEL_LEARN|MODEL_CODEGEN|MAX_TOKENS_LEARN|MAX_TOKENS_CODEGEN|MAX_STEPS)=' .env.example
```

Expected: first command prints `OK_NO_REMOVED_VARS`; second prints both new vars; third prints all six kept vars.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "chore(env): drop IDD/SDD/PLAN/Assembler/Consolidate vars; add MAX_TOKENS_DESIGN + FIDELITY_TIMEOUT_S"
```

---

## Task 13: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `agent/CLAUDE.md`

- [ ] **Step 1: Overwrite the "Architecture" section of `CLAUDE.md`**

Replace the existing "Architecture" block with:

```markdown
## Architecture

Entry point: `main.py` → BitGN harness → `agent/orchestrator.py:run_agent()`

**Execution flow per task:**
1. `orchestrator.py:run_agent()` — opens VM, reads `/AGENTS.MD` directly (no PREPHASE), calls `run_pipeline`
2. `pipeline.py:run_pipeline(vm, instruction, task_id, agents_md_text)`:
   - **DESIGN** (1 LLM call, frozen for the run) — system: `design.md` + `proto-api-reference.md`. Input strictly `[instruction, AGENTS.MD]`. Output: `DesignOutput` (`intent`, `params`, `success_criteria`, `discovery`, `ops`, `agents_md_constraints`, `answer_template`, `outcome_override?`).
   - If `outcome_override` set → `vm.answer(...)` → END.
   - **LOOP** — single counter `cycle = 1..MAX_STEPS`:
     - **CODEGEN** (LLM call) — input: `[tool_plan, learn_ctx, prev_error?]`. Output: `CodegenOutput.script_code` (a module exposing `run(vm, params)`).
     - **AST lint** — `ast.parse(script_code)`; on `SyntaxError` → LEARN+CONSOLIDATE → next cycle.
     - **check_retry_loop** — extract literal SQL via `ast.walk` over `vm.exec(path="/bin/sql", args=[...])`; compare normalised multiset to prior cycle; identical → break with CLARIFICATION.
     - **Fidelity gate** — `agent/fidelity.py:generate_fidelity_test(design, task_id)` emits a deterministic test; run in subprocess (`FIDELITY_TIMEOUT_S=30s`). Mismatch → LEARN+CONSOLIDATE → next cycle.
     - Pass → break.
   - **ANSWER terminal one-shot** — exec script on real VM (`run(vm, params)`); the script calls `vm.answer(...)` itself. On any real-VM exception → terminal `OUTCOME_NONE_CLARIFICATION`.
   - On loop exhaust → terminal `OUTCOME_NONE_CLARIFICATION`.
3. `learned_store.py` — `load_entries(tid)` (active only), `apply_learn_diff(tid, LearnConsolidateOutput)`, `save_last_run(tid, status, outcome, cycles_used)`.

**LLM call budget:** 1 (hard-stop) / 2 (best happy path) / 7 (worst, `MAX_STEPS=3`).
```

- [ ] **Step 2: Update the env-vars table in `CLAUDE.md`**

Remove rows for: `MODEL_ASSEMBLER`, `MODEL_SDD`, `MODEL_PLAN`, `MODEL_CONSOLIDATE`, `MAX_TOKENS_SDD`, `MAX_TOKENS_PLAN`, `MAX_TOKENS_CONSOLIDATE`, `MAX_TOKENS_ANSWER`, `MAX_TOKENS_ASSEMBLER`, `CODEGEN_LINT_RETRIES`.

Add rows:

```
| `MAX_TOKENS_DESIGN` | Max tokens for DESIGN phase response (default 4096) |
| `FIDELITY_TIMEOUT_S` | Subprocess timeout for fidelity gate (default 30) |
```

Keep: `MODEL`, `MODEL_FALLBACK`, `MODEL_LEARN`, `MODEL_CODEGEN`, `MAX_TOKENS_CODEGEN`, `MAX_TOKENS_LEARN`, `MAX_STEPS`, `LOG_LEVEL`, `OLLAMA_BASE_URL`, `CC_ENABLED`, `LLM_HTTP_READ_TIMEOUT_S`.

`MODEL_DESIGN` is intentionally NOT added — `agent/llm.py:_PHASE_MODEL_MAP` has no `design` key (llm.py in spec Keep / intent No-autonomy). Documenting the knob would mislead.

- [ ] **Step 3: Update the "Key Data Files" section**

Remove rows for `data/heuristics/{task_id}_test.py` (no longer written).
Update the row for `data/learned/{task_id}.yaml`:

```
| `data/learned/{task_id}.yaml` | Per-task active+inactive LearnConsolidate rules; `last_run` carries `status/outcome/cycles_used/date` only (no `heuristic_valid`, no `schema_hash`) |
```

Update the row for `data/heuristics/{task_id}.py`:

```
| `data/heuristics/{task_id}.py` | Last successful or last-attempted heuristic script. Reference only — pipeline always regenerates via DESIGN + CODEGEN (no fast path). |
```

Replace the `data/prompts/*.md` row with:

```
| `data/prompts/*.md` | Phase guides: `design`, `codegen`, `learn` only |
```

- [ ] **Step 4: Rewrite `agent/CLAUDE.md` to match**

Open `agent/CLAUDE.md` and replace the "Agent Package Architecture" + "Phase execution order" + "Pydantic models" sections with shortened descriptions mirroring the new flow above. Keep the LLM routing and prompt loading sections — they did not change.

- [ ] **Step 5: Verify the rewrite is consistent**

```bash
grep -nE 'IDD|SDD|PLAN phase|PREPHASE|ASSEMBLE|FAST PATH|fast path|CODEGEN_LINT_RETRIES|MODEL_DESIGN|MODEL_ASSEMBLER|MODEL_CONSOLIDATE|MAX_TOKENS_(IDD|SDD|PLAN|ANSWER|ASSEMBLER|CONSOLIDATE)' CLAUDE.md agent/CLAUDE.md && echo FAIL || echo OK_NO_LEGACY_REFS
grep -nE 'DESIGN|CODEGEN|fidelity|LearnConsolidate|MAX_TOKENS_DESIGN|FIDELITY_TIMEOUT_S' CLAUDE.md agent/CLAUDE.md | head
```

Expected: first command prints `OK_NO_LEGACY_REFS`; second lists the new phase + var refs.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md agent/CLAUDE.md
git commit -m "docs(claude): document DESIGN+CODEGEN pipeline; remove IDD/SDD/PLAN/Assembler refs"
```

---

## Task 14: Local verification + benchmark

**Files:**
- Create: `tests/test_benchmark_t01.py`, `tests/test_benchmark_t99.py`

- [ ] **Step 1: Create env-gated benchmark regression tests (HM1)**

Create `tests/test_benchmark_t01.py`:

```python
"""HM1 regression — t01 from empty learned state to OUTCOME_OK.

Env-gated. Set RUN_BENCHMARK=1 to enable (uses a real LLM tier).
"""
import os
import subprocess
import sys

import pytest
import yaml


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BENCHMARK") != "1",
    reason="RUN_BENCHMARK=1 not set",
)


def test_t01_runs_from_empty_to_outcome_ok(tmp_path, monkeypatch):
    learned = "data/learned/t01.yaml"
    monkeypatch.setenv("MAX_STEPS", "3")
    subprocess.run(["uv", "run", "python", "-m", "main", "--task", "t01"], check=True, timeout=600)
    data = yaml.safe_load(open(learned))
    assert data["last_run"]["status"] == "success"
    assert data["last_run"]["outcome"] == "OUTCOME_OK"
```

Create `tests/test_benchmark_t99.py` (same shape, replace `t01` with `t99`):

```python
"""HM1 regression — t99 from empty learned state to OUTCOME_OK.

Env-gated. Set RUN_BENCHMARK=1 to enable (uses a real LLM tier).
"""
import os
import subprocess
import sys

import pytest
import yaml


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BENCHMARK") != "1",
    reason="RUN_BENCHMARK=1 not set",
)


def test_t99_runs_from_empty_to_outcome_ok(tmp_path, monkeypatch):
    learned = "data/learned/t99.yaml"
    monkeypatch.setenv("MAX_STEPS", "3")
    subprocess.run(["uv", "run", "python", "-m", "main", "--task", "t99"], check=True, timeout=600)
    data = yaml.safe_load(open(learned))
    assert data["last_run"]["status"] == "success"
    assert data["last_run"]["outcome"] == "OUTCOME_OK"
```

- [ ] **Step 2: Full unit test pass (benchmark tests skipped)**

```bash
uv run pytest tests/ -v
```

Expected: ALL pass. `test_benchmark_t01` + `test_benchmark_t99` SKIPPED (gate off). New tests green. Kept tests (`test_llm_module.py`, `test_sql_security.py`, `test_json_extract_cleanup.py`, `test_agents_md_parser.py`, `test_trace_main.py`, `test_trace.py`, `test_prompt_loader.py`, `test_models.py`) green.

- [ ] **Step 3: Smoke-run `t01` + `t99` from empty learned state**

```bash
RUN_BENCHMARK=1 uv run pytest tests/test_benchmark_t01.py tests/test_benchmark_t99.py -v
```

Or, equivalently:

```bash
make task TASKS='t01,t99'
```

Expected: both report `OUTCOME_OK`. Verify:

```bash
uv run python -c "import yaml; print(yaml.safe_load(open('data/learned/t01.yaml'))['last_run']); print(yaml.safe_load(open('data/learned/t99.yaml'))['last_run'])"
```

Expected: both `last_run.outcome == 'OUTCOME_OK'`, `last_run.status == 'success'`.

- [ ] **Step 3: Full benchmark run with wall-clock check**

```bash
time uv run python main.py
```

Expected: completes under 1 hour. All task outcomes `OUTCOME_OK`. Note real numbers in the commit message for traceability.

- [ ] **Step 4: Verify HM metrics by inspection**
- HM1 — `t01.yaml.last_run.outcome == OUTCOME_OK` and `t99.yaml.last_run.outcome == OUTCOME_OK` after Step 2 from empty state.
- HM3 — `data/learned/{tid}.yaml` files exist for any failing tasks and have at least one entry written via `apply_learn_diff`.
- HM4 — `tests/test_sql_security.py` and `tests/test_json_extract_cleanup.py` still pass.
- HM5 — Worst-case LLM call count for a failing task ≤ 7; best-case ≤ 2. Inspect run log.
- HM6 — Switch `MODEL` between `anthropic/claude-sonnet-4-6`, `openrouter/...`, `ollama/...`, `claude-code` (with `CC_ENABLED=1`) and re-run one task per tier; each tier returns a `DesignOutput`. (Tier coverage check; one task per tier suffices.)
- HM7 — Inspect a successful `DesignOutput.ops[*].rpc` — should prefer `Find`/`Search`/`Read` for navigation and `Exec /bin/sql` with parameter placeholders for data ops; no `Tree` when a narrower tool fits.

- [ ] **Step 5: Final commit if any docs updated during verification**

```bash
git add -u
git commit -m "chore: verify pipeline redesign — t01/t99 OUTCOME_OK from empty learned state, benchmark < 1 h"
```

---

## Self-review notes (already applied in this plan)

- **F-001:** Task 5 includes `test_signature_accepts_only_two_args` + `test_stray_learn_ctx_kwarg_raises_type_error`. `run_design` signature is `(instruction, agents_md_text)`.
- **F-002:** Task 1 makes `success_criteria` a required `DesignOutput` field. Test `test_design_output_success_criteria_required` enforces.
- **F-003:** Task 8 implements a single `for cycle in range(1, _MAX_STEPS + 1):` loop. `CODEGEN_LINT_RETRIES` is removed in Task 12 (`.env.example`) and is never referenced in pipeline code.
- **F-005:** Task 8 provides `_extract_sql_literals` (ast.walk over `vm.exec(path="/bin/sql", args=[...])` `ast.Constant` strings; computed SQL ignored) and `_identical_sql_set` (regex `\s+` → single space, strip, multiset equality, case-sensitive). Tests `test_extract_sql_literals_*` + `test_identical_sql_set_normalises_whitespace` cover both.
- **F-006:** Subprocess fidelity overhead budget — `MAX_STEPS=3 × N_tasks × 30 ms ≈ 9 s` worst case for `N_tasks ≤ 100`. `FIDELITY_TIMEOUT_S` env knob lets ops cap individual gates.
