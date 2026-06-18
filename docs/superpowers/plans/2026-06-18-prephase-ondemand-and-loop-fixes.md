---
review:
  plan_hash: 8fd374c1e32773eb
  spec_hash: 34f0b1003895d215
  last_run: 2026-06-18
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: WARNING
      status: open
      location: "Task 1 (Block A) Step 4"
      note: "Spec Block A prescribes a compact summary of security deny-rules for the INTENT tier ('verbose policy glossary is no longer injected wholesale'), but the plan injects full policies text via _INTENT_KEYS without compaction; verify assert only checks 'policies' in intent_block, not compaction."
chain:
  intent: docs/superpowers/intents/2026-06-16-prephase-ondemand-and-loop-fixes-intent.md
  spec:   docs/superpowers/specs/2026-06-17-prephase-ondemand-and-loop-fixes-design.md
result_check:
  verdict: OK
  plan_hash: 8fd374c1e32773eb
  last_run: 2026-06-18
---
# Prephase On-Demand + Loop/Oracle Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `t01` ("do you carry product X?") return `OUTCOME_OK` on a real `make task TASKS='t01'` run by splitting prephase facts per phase, fetching heavy data on-demand via PLAN `discovery`, seeding + self-filling the oracle with polarity, accepting valid negative outcomes in `verify`, and auto-repairing common IR-syntax slips.

**Architecture:** INTENT receives full facts on one frozen call; PLAN receives a thin fact block (tool/catalog inventory + schema + identity + docs paths) plus retrieved oracle atoms, and pulls real data portionally through existing IR `discovery` steps. The oracle self-fills from the grader score at end-of-run with `method`/`anti_pattern` polarity. `verify` applies only the criteria keyed to the chosen outcome. A deterministic pre-lint normalizer maps op synonyms before pydantic validation.

**Tech Stack:** Python 3, pydantic v2, PyYAML, `uv` for deps/test, deterministic Plan-IR interpreter (no LLM in lint/interpret/verify).

---

## Constraints that override the default skill workflow

This project's `CLAUDE.md` and the approved intent impose **hard rules** that take precedence over the writing-plans skill's default TDD shape:

- **No functional tests.** Do **not** write new test files to prove a task fix. Verify by running real code (`make task TASKS='t01'`, inline `uv run python -c …` smoke checks, and the existing `uv run pytest tests/ -q` suite staying green).
- **Never patch `data/prompts/` for task-specific fixes.** Only generic *structural* rules (allowed op lists, output shapes) may be added to prompts. Task knowledge flows through LEARN / the oracle.
- `verify()` stays deterministic (no LLM answer-grading). `vm.answer` is called exactly once per task.
- No re-seed-fragile hardcoded values in rules or atoms (the benchmark re-randomizes data each `StartRun`).
- **HUMAN CHECKPOINT (from intent):** all code changes are proposal-first. This plan is the proposal; execution begins only after approval.

Because of the "no new functional tests" rule, each task below verifies via **running real code**, not via new test files. The single exception is **migrating one existing unit test** (`tests/test_ir_models.py`) that the Block D schema change breaks — updating a pre-existing test to match a schema change is required maintenance, not a new functional test.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `agent/agents_md_parser.py` | Parse AGENTS.MD into sections; render a compact tool/catalog inventory | Add `render_inventory()` |
| `agent/orchestrator.py` | Gather prephase facts; hold `PrePhaseFacts` | Add `agents_md_inventory` field + compute it |
| `agent/reason.py` | INTENT/PLAN LLM phases; `_facts_block` | Add `tier` param (intent/plan key sets); add IR auto-repair normalizer in `run_plan` |
| `agent/oracle_atoms.py` | `Atom` model + YAML I/O + `build_oracle_block` | Add `polarity`; render methods/anti-patterns under separate headings |
| `agent/oracle.py` | Atom bank + retrieval + `distill` | Add `polarity`/`status` params to `distill` |
| `agent/pipeline.py` | Pipeline + grader-feedback seam | Add `distill_from_grader()` end-of-run self-fill |
| `main.py` | Benchmark run loop | Call `distill_from_grader` on both pass and fail |
| `agent/ir_models.py` | Plan-IR pydantic models | `IntentSpec.success_criteria` → keyed dict + back-compat coercion |
| `agent/verify.py` | Deterministic verify gate | Apply only the chosen outcome's criteria |
| `data/oracle/atoms.yaml` | Validated knowledge atoms | Seed probe-then-refine + generic methods |
| `data/prompts/intent.md` | INTENT phase guide (structural) | Document keyed `success_criteria` shape |
| `data/prompts/plan.md` | PLAN phase guide (structural) | List allowed predicate ops + `AnswerTemplateIR` shape |
| `tests/test_ir_models.py` | Existing unit test of golden IntentSpec | Migrate `success_criteria[0]` → `success_criteria["OUTCOME_OK"][0]` |

Tasks land in dependency order: **A** (thin prephase) → **C-models** (Atom polarity, needed before seeding) → **B** (seed atoms) → **C-seam** (distill polarity + self-fill) → **D** (verify keyed) → **E** (IR auto-repair) → **Acceptance**.

---

### Task 1 (Block A): Thin prephase + AGENTS.MD tool/catalog inventory

**Files:**
- Modify: `agent/agents_md_parser.py` (add `render_inventory`)
- Modify: `agent/orchestrator.py:230-239` (`PrePhaseFacts`), `agent/orchestrator.py:393-545` (`gather_prephase_facts`)
- Modify: `agent/reason.py:40-57` (`_facts_block`), `agent/reason.py:60-105` (`run_intent`, `run_plan`)

- [ ] **Step 1: Add `render_inventory` to `agents_md_parser.py`**

Append below the existing `parse_agents_md` (keep `parse_agents_md` unchanged):

```python
import re

_PATH_RE = re.compile(r"/[\w][\w./-]*")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_INVENTORY_CAP = 40


def render_inventory(content: str) -> str:
    """Compact, deterministic (0 LLM) tool/catalog inventory from AGENTS.MD.

    Collects backtick-quoted single tokens (tools/RPCs) and absolute path
    literals (catalog/dir paths). Used as a thin stand-in for the full document
    in both fact tiers so the verbose AGENTS.MD prose is not re-injected.
    """
    if not content:
        return ""
    tools: list[str] = []
    paths: list[str] = []
    for m in _CODE_RE.findall(content):
        t = m.strip()
        if t and " " not in t and "/" not in t and t not in tools:
            tools.append(t)
    for m in _PATH_RE.findall(content):
        p = m.rstrip(".,;:)'\"")
        if p and p not in paths:
            paths.append(p)
    lines: list[str] = []
    if tools:
        lines.append("tools/rpcs: " + ", ".join(tools[:_INVENTORY_CAP]))
    if paths:
        lines.append("catalog/paths: " + ", ".join(paths[:_INVENTORY_CAP]))
    return "\n".join(lines)
```

- [ ] **Step 2: Add `agents_md_inventory` to `PrePhaseFacts`**

In `agent/orchestrator.py`, add the field to the model (keep all existing fields):

```python
class PrePhaseFacts(BaseModel):
    agents_md: str = ""
    agents_md_inventory: str = ""
    schema: str = ""
    sample_rows: str = ""
    docs_inventory: str = ""
    policies: dict[str, str] = {}
    identity: dict = {}
    target_records: dict[str, str] = {}
    path_listings: dict[str, str] = {}   # instruction-named dir -> rendered listing (Tier-1)
    gather_status: dict[str, str] = {}   # fact -> ok|empty|error(<msg>)
```

- [ ] **Step 3: Compute the inventory in `gather_prephase_facts`**

In `agent/orchestrator.py`, add the import at the top with the other `agent.*` imports:

```python
from agent.agents_md_parser import render_inventory
```

Then in the `return PrePhaseFacts(...)` at the end of `gather_prephase_facts`, add the inventory (the rest of the call is unchanged):

```python
    return PrePhaseFacts(
        agents_md=agents_md_text,
        agents_md_inventory=render_inventory(agents_md_text),
        schema=schema, sample_rows=samples,
        docs_inventory=docs_inventory, policies=policies, identity=identity,
        target_records=target_records, path_listings=path_listings, gather_status=status,
    )
```

- [ ] **Step 4: Make `_facts_block` tier-aware in `reason.py`**

Replace the existing `_facts_block` (lines 40–57) with a tiered version. INTENT gets the inventory + schema + identity + docs paths **plus** the security policy text (the only place policies are still injected). PLAN gets the thin set only — `sample_rows`, full `policies`, `target_records`, `path_listings`, and the full `agents_md` are **dropped from upfront injection** and fetched on-demand by PLAN `discovery`:

```python
_PLAN_KEYS = ("agents_md_inventory", "schema", "identity", "docs_inventory")
_INTENT_KEYS = _PLAN_KEYS + ("policies",)


def _facts_block(facts: Any, tier: str = "plan") -> str:
    if facts is None:
        return ""
    if hasattr(facts, "model_dump"):
        facts = facts.model_dump()
    keys = _INTENT_KEYS if tier == "intent" else _PLAN_KEYS
    parts = []
    for key in keys:
        val = facts.get(key) if isinstance(facts, dict) else None
        if val:
            parts.append(f"## {key}\n{val if isinstance(val, str) else val}")
    block = "PRE-PHASE FACTS:\n" + "\n\n".join(str(p) for p in parts)
    nonok = _facts_sufficiency(facts)
    if nonok:
        status = facts.get("gather_status", {}) if isinstance(facts, dict) else {}
        block += "\n\nFACT_STATUS (non-ok): " + ", ".join(f"{k}={status.get(k)}" for k in nonok)
    return block
```

- [ ] **Step 5: Pass the tier from `run_intent` / `run_plan`**

In `run_intent` (reason.py), change the `user` line to request the intent tier:

```python
    user = "\n\n".join(p for p in [_facts_block(facts, tier="intent"), f"INSTRUCTION:\n{instruction}"] if p)
```

In `run_plan`, change the facts append to the plan tier and add a DEBUG prompt-size print (the size metric the intent's Health Metric asks for) just before the LLM call:

```python
    parts.append(_facts_block(facts, tier="plan"))
```

…and after `user = "\n\n".join(p for p in parts if p)`:

```python
    if os.environ.get("LOG_LEVEL") == "DEBUG":
        print(f"[plan] user prompt chars={len(user)}")
```

- [ ] **Step 6: Verify the renderer + tiers by running real code**

Run:
```bash
uv run python -c "
from agent.agents_md_parser import render_inventory
from agent.orchestrator import PrePhaseFacts
from agent.reason import _facts_block
inv = render_inventory('# A\n\nUse \`Read\` and \`Exec\`.\nCatalog at /proc/catalog and /docs.')
print('INVENTORY:', repr(inv))
f = PrePhaseFacts(agents_md='FULL DOC '*500, agents_md_inventory=inv, schema='CREATE TABLE t(x)',
                  docs_inventory='/docs/security.md', identity={'kind':'guest'},
                  policies={'/docs/security.md':'SEC '*1000}, sample_rows='ROWS '*500,
                  target_records={'/proc/x':'BODY '*500})
plan_block = _facts_block(f, tier='plan')
intent_block = _facts_block(f, tier='intent')
print('PLAN chars=', len(plan_block), 'INTENT chars=', len(intent_block))
assert 'agents_md_inventory' in plan_block
assert 'sample_rows' not in plan_block and 'target_records' not in plan_block
assert 'policies' not in plan_block and 'FULL DOC' not in plan_block
assert 'policies' in intent_block
assert len(plan_block) < len(intent_block)
print('OK')
"
```
Expected: prints `INVENTORY:` with `tools/rpcs:` + `catalog/paths:`, `PLAN chars=` much smaller than `INTENT chars=`, then `OK`.

- [ ] **Step 7: Confirm the existing suite stays green**

Run: `uv run pytest tests/ -q`
Expected: PASS (no failures introduced by the tier change).

- [ ] **Step 8: Commit**

```bash
git add agent/agents_md_parser.py agent/orchestrator.py agent/reason.py
git commit -m "feat(prephase): tier facts per phase + AGENTS.MD tool/catalog inventory

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2 (Block C-models): Atom polarity + polarity-aware oracle block

**Files:**
- Modify: `agent/oracle_atoms.py:11-23` (`Atom`), `:30-44` (`load_atoms`), `:59-66` (`build_oracle_block`)

- [ ] **Step 1: Add `polarity` to the `Atom` dataclass**

Add the field (default keeps existing/seed atoms back-compatible):

```python
@dataclass
class Atom:
    id: str
    description: str
    domain: list[str]
    content: str
    source: str            # investigation | distilled | verdict
    validated_by: str      # manual | grader | grader-oracle
    validated_at: str
    status: str            # active | candidate
    embedding_hash: str = ""
    source_task: str = ""   # task_id the candidate was distilled from (promote gate)
    polarity: str = "method"   # method | anti_pattern
    extra: dict = field(default_factory=dict)
```

- [ ] **Step 2: Read `polarity` in `load_atoms`**

In `load_atoms`, add the polarity read alongside the other `.get` lines:

```python
        known["embedding_hash"] = d.get("embedding_hash") or ""
        known["source_task"] = d.get("source_task") or ""
        known["polarity"] = d.get("polarity") or "method"
        atoms.append(Atom(**known))
```

(`save_atoms` uses `asdict(a)` so the new field is persisted automatically.)

- [ ] **Step 3: Render polarity in `build_oracle_block`**

Replace `build_oracle_block` so methods render under an "apply" heading and anti-patterns under an "avoid" heading:

```python
def build_oracle_block(oracle_atoms) -> str:
    """Render retrieved knowledge atoms for the PLAN prompt, split by polarity."""
    if not oracle_atoms:
        return ""
    methods = [a for a in oracle_atoms if getattr(a, "polarity", "method") != "anti_pattern"]
    antis = [a for a in oracle_atoms if getattr(a, "polarity", "method") == "anti_pattern"]
    lines: list[str] = []
    if methods:
        lines.append("## VALIDATED KNOWLEDGE — APPLY (verified methods)")
        for a in methods:
            lines.append(f"- ({', '.join(a.domain)}) {a.content.strip()}")
    if antis:
        lines.append("## ANTI-PATTERNS — AVOID (known failure causes)")
        for a in antis:
            lines.append(f"- ({', '.join(a.domain)}) {a.content.strip()}")
    return "\n".join(lines)
```

- [ ] **Step 4: Verify by running real code**

Run:
```bash
uv run python -c "
from agent.oracle_atoms import Atom, build_oracle_block
m = Atom(id='m1', description='', domain=['sql'], content='probe distinct then refine',
         source='investigation', validated_by='manual', validated_at='', status='active')
a = Atom(id='a1', description='', domain=['sql'], content='do not use strict equality on free text',
         source='distilled', validated_by='grader', validated_at='', status='active', polarity='anti_pattern')
blk = build_oracle_block([m, a])
print(blk)
assert 'APPLY' in blk and 'AVOID' in blk
assert m.polarity == 'method'
print('OK')
"
```
Expected: prints both headings, then `OK`.

- [ ] **Step 5: Confirm the suite stays green**

Run: `uv run pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/oracle_atoms.py
git commit -m "feat(oracle): add atom polarity (method|anti_pattern) + split rendering

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3 (Block B): Seed `atoms.yaml` with probe-then-refine + generic methods

**Files:**
- Modify: `data/oracle/atoms.yaml` (currently empty)

- [ ] **Step 1: Write the seed atoms**

Overwrite `data/oracle/atoms.yaml` with hand-authored, re-seed-safe **method** atoms (generic methods, no run-specific literals). These are trusted by authorship (`validated_by: manual`, `status: active`):

```yaml
- id: probe_then_refine_lookup
  description: Exact-equality lookup returning 0 rows usually means a format mismatch, not absence
  domain: [sql, lookup, discovery]
  content: >-
    An exact-equality lookup that returns 0 rows usually means the literal does
    not match the stored format, not that the entity is absent. Probe DISTINCT
    column values or sample the target table first, then refine with a
    normalized or case-insensitive comparison before concluding the item is not
    carried.
  source: investigation
  validated_by: manual
  validated_at: '2026-06-18'
  status: active
  polarity: method
- id: normalize_free_text_filter
  description: Prefer normalized/LIKE comparison over strict equality on free-text columns
  domain: [sql, normalization]
  content: >-
    When a SQL filter on a free-text attribute returns nothing, prefer a
    normalized comparison (trim + lower, or LIKE) over strict equality, because
    stored values often carry units, casing, or spacing variations the literal
    does not reproduce.
  source: investigation
  validated_by: manual
  validated_at: '2026-06-18'
  status: active
  polarity: method
- id: read_governing_doc_before_filter
  description: Read the governing /docs policy before encoding a count/eligibility filter
  domain: [docs, eligibility]
  content: >-
    Before encoding a count or eligibility filter, read the governing /docs
    policy surfaced in pre-phase; the documented rule, not a naive WHERE clause,
    defines correctness.
  source: investigation
  validated_by: manual
  validated_at: '2026-06-18'
  status: active
  polarity: method
```

- [ ] **Step 2: Verify the bank loads and renders**

Run:
```bash
uv run python -c "
from agent.oracle_atoms import load_atoms, build_oracle_block
atoms = load_atoms('data/oracle/atoms.yaml')
print('loaded', len(atoms), 'atoms')
assert len(atoms) >= 3
assert all(a.status == 'active' and a.polarity == 'method' for a in atoms)
print(build_oracle_block(atoms)[:200])
print('OK')
"
```
Expected: `loaded 3 atoms`, then the APPLY block head, then `OK`.

- [ ] **Step 3: Verify retrieval injects ≥1 atom (tag fallback if embeddings offline)**

Run:
```bash
uv run python -c "
from agent.oracle import KnowledgeOracle
atoms = KnowledgeOracle().retrieve('do you carry the Heco zinc plated product')
print('retrieved', len(atoms), 'atoms:', [a.id for a in atoms])
assert len(atoms) >= 1
print('OK')
"
```
Expected: ≥1 atom id printed, then `OK`. (If the embeddings endpoint is unreachable, `_cosine_topn` raises and `_tag_fallback` keyword-matches — retrieval still returns atoms.)

- [ ] **Step 4: Commit**

```bash
git add data/oracle/atoms.yaml
git commit -m "feat(oracle): seed bank with probe-then-refine + generic method atoms

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4 (Block C-seam): Distill polarity/status + end-of-run self-fill

**Files:**
- Modify: `agent/oracle.py:122-135` (`distill`)
- Modify: `agent/pipeline.py` (add `distill_from_grader` near `_maybe_distill_and_validate`)
- Modify: `main.py:100` (import), `main.py:319-329` (score loop)

- [ ] **Step 1: Add `polarity` + `status` params to `oracle.distill`**

Replace the `distill` method signature and the `Atom(...)` construction (keep `_DISTILL_SYS`, `add_candidate`, `promote` unchanged):

```python
    def distill(self, design_intent, error, script_code, source_task="",
                polarity="method", status="candidate"):
        user = (f"INTENT:\n{design_intent}\n\nERROR:\n{error}\n\n"
                f"SCRIPT:\n{(script_code or '')[:4000]}\n\nReturn the atom JSON.")
        from .llm import _resolve_model_for_phase
        out = call_llm_json(self._DISTILL_SYS, user,
                            _resolve_model_for_phase("distill", os.environ.get("MODEL", "")))
        if not isinstance(out, dict) or not out.get("content"):
            return None
        atom = Atom(id=out["id"], description=out.get("description", ""),
                    domain=list(out.get("domain") or []), content=out["content"],
                    source="distilled", validated_by="", validated_at="",
                    status=status, embedding_hash=content_hash(out["content"]),
                    source_task=source_task, polarity=polarity)
        return self.add_candidate(atom)
```

(The existing in-pipeline `_maybe_distill_and_validate` calls `distill(...)` without the new kwargs, so it keeps the default `candidate` status + `method` polarity — back-compatible.)

- [ ] **Step 2: Add `distill_from_grader` to `pipeline.py`**

Add this function directly below `_maybe_distill_and_validate` (it reuses `_new_oracle`, `Path`, `CLI_YELLOW`, `CLI_CLR`, all already imported in pipeline.py):

```python
def distill_from_grader(task_id: str, score: float, score_detail: list[str]) -> None:
    """End-of-run self-fill: distill an ACTIVE polarity atom from the grader score.

    pass (score >= 1.0) -> 'method' atom (effective knowledge);
    fail (score < 1.0)  -> 'anti_pattern' atom (failure cause, steers away next run).

    Uses the score already returned by SubmitRun — NOT a live grader round-trip
    (ORACLE_VALIDATE_INLINE stays 0 by default). Never raises; the run result is
    unchanged if distill yields nothing. Reads the persisted IntentSpec + PlanIR.
    """
    if os.environ.get("ORACLE_ENABLED", "1") == "0":
        return
    heur = Path("data/heuristics")
    ip, pp = heur / f"{task_id}.intent.json", heur / f"{task_id}.plan.json"
    if not (ip.exists() and pp.exists()):
        return
    try:
        from .ir_models import IntentSpec, PlanIR
        intent = IntentSpec.model_validate_json(ip.read_text(encoding="utf-8"))
        plan = PlanIR.model_validate_json(pp.read_text(encoding="utf-8"))
        if score >= 1.0:
            note, polarity = "effective method (grader score 1.0)", "method"
        else:
            detail = " | ".join(s.strip() for s in score_detail if s.strip())
            note, polarity = f"failure to avoid; grader: {detail}", "anti_pattern"
        oracle = _new_oracle()
        oracle.distill(design_intent=intent.objective, error=note,
                       script_code=plan.model_dump_json(), source_task=task_id,
                       polarity=polarity, status="active")
    except Exception as e:
        print(f"{CLI_YELLOW}[pipeline] distill_from_grader skipped: {e}{CLI_CLR}")
```

- [ ] **Step 3: Wire `distill_from_grader` into the `main.py` score loop**

Change the import on `main.py:100`:

```python
from agent.pipeline import learn_from_grader, distill_from_grader
```

In the per-row score loop (`main.py:319-329`), call the self-fill for **every** task (both pass and fail), then keep the existing fail-only `learn_from_grader` block:

```python
            next_filter: list[str] = []
            for row in scores:
                task_id, score, detail, elapsed, token_stats = row
                final_state[task_id] = (score, detail, elapsed, token_stats)
                distill_from_grader(task_id, float(score), list(detail))
                if score < 1.0:
                    next_filter.append(task_id)
                    if cycle < TRAIN_MAX_CYCLES:
                        if learn_from_grader(task_id, list(detail)):
                            print(
                                f"{CLI_BLUE}[{task_id}] LEARN distilled from grader feedback{CLI_CLR}"
                            )
```

- [ ] **Step 4: Verify `distill_from_grader` is import-safe and no-ops cleanly without artifacts**

Run (uses a task id with no persisted artifacts → must return silently, no raise):
```bash
uv run python -c "
from agent.pipeline import distill_from_grader
distill_from_grader('__no_such_task__', 1.0, [])
distill_from_grader('__no_such_task__', 0.0, ['missing ref'])
print('OK')
"
```
Expected: `OK` (no exception, no output — artifacts absent so it returns early).

- [ ] **Step 5: Confirm the suite stays green**

Run: `uv run pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/oracle.py agent/pipeline.py main.py
git commit -m "feat(oracle): self-fill bank from grader score with method/anti-pattern polarity

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5 (Block D): `verify` keyed by outcome

**Files:**
- Modify: `agent/ir_models.py:81-90` (`IntentSpec`)
- Modify: `agent/verify.py:40-43`
- Modify: `data/prompts/intent.md:39-41`, `:71-73` (structural shape — allowed)
- Modify: `tests/test_ir_models.py:74` (migrate existing assertion)

- [ ] **Step 1: Make `IntentSpec.success_criteria` a keyed dict with back-compat coercion**

In `agent/ir_models.py`, change the field and add a `mode="before"` validator so persisted `intent.json` files (and existing call sites) that carry a bare list still parse — a bare list is treated as `{"OUTCOME_OK": [...]}`:

```python
class IntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str
    desired_outcome: str
    params: dict[str, Any] = {}
    outcome_space: list[str]
    constraints: list[Constraint] = []
    success_criteria: dict[str, list[PredExpr]] = {}   # keyed by outcome
    answer_shape: AnswerShape
    required_refs: dict[str, list[RefSpec]] = {}   # keyed by outcome

    @model_validator(mode="before")
    @classmethod
    def _coerce_success_criteria(cls, data):
        # Migration: a bare list (legacy shape / persisted intent.json) means
        # criteria for the positive outcome.
        if isinstance(data, dict) and isinstance(data.get("success_criteria"), list):
            data["success_criteria"] = {"OUTCOME_OK": data["success_criteria"]}
        return data
```

(`model_validator` is already imported at the top of `ir_models.py`.)

- [ ] **Step 2: Apply only the chosen outcome's criteria in `verify`**

In `agent/verify.py`, replace the `success_criteria` loop (lines 40–43):

```python
    # success_criteria: only the criteria for the chosen outcome must hold.
    # A valid negative outcome (e.g. OUTCOME_NONE_UNSUPPORTED) with no criteria
    # passes here; it is still gated by I2 (outcome_space) above.
    for i, crit in enumerate(intent.success_criteria.get(ans.outcome, [])):
        if not evaluate(crit, env):
            return False, f"success_criteria[{ans.outcome}][{i}] failed: {crit.model_dump()!r}"
```

- [ ] **Step 3: Document the keyed shape in `intent.md` (structural rule — allowed)**

In `data/prompts/intent.md`, replace the `success_criteria` block in the JSON example (currently lines 39–41):

```json
  "success_criteria": {
    "OUTCOME_OK": [
      {"op": "<leaf or bool op>", "lhs": "$<ref>", "rhs": "<value>"}
    ]
  },
```

And replace the `success_criteria` field-rule bullet (currently lines 71–73):

```markdown
- `success_criteria` — a map keyed by outcome (same shape as `required_refs`).
  List STRUCTURAL / grounding checks only per outcome (e.g. `count ge 0`, a
  nonempty bound id). A negative outcome (e.g. `OUTCOME_NONE_UNSUPPORTED`)
  typically needs no criteria — it is gated by `outcome_space`. Do NOT bake a SQL
  recipe, join, `kind_id`, or `city` here — that is PLAN's job (HOW).
```

- [ ] **Step 4: Migrate the existing unit test that indexes the old shape**

In `tests/test_ir_models.py`, the golden `_GOLDEN_INTENT` keeps `success_criteria` as a list (the coercion handles it), but the assertion at line 74 must read through the key. Change:

```python
def test_intentspec_parses_golden():
    spec = IntentSpec(**_GOLDEN_INTENT)
    assert spec.success_criteria["OUTCOME_OK"][0].op == "nonempty"
    assert spec.answer_shape.msg_skeleton == "{cnt}"
```

- [ ] **Step 5: Verify negative-outcome verify by running real code**

Confirm a valid `OUTCOME_NONE_UNSUPPORTED` answer with no criteria for that outcome passes, while an `OUTCOME_OK` answer is still gated by its criteria:

```bash
uv run python -c "
from agent.ir_models import IntentSpec
from agent.verify import verify
from agent.interpreter import InterpretResult
from types import SimpleNamespace

spec = IntentSpec(
    objective='x', desired_outcome='OUTCOME_OK',
    outcome_space=['OUTCOME_OK', 'OUTCOME_NONE_UNSUPPORTED'],
    success_criteria={'OUTCOME_OK': [{'op':'nonempty','lhs':'\$row.sku'}]},
    answer_shape={'msg_skeleton':'{m}'})

def res(outcome, env):
    ans = SimpleNamespace(message='m', outcome=outcome, refs=[])
    return InterpretResult(captured=ans, env=env, observations=[], mutation_landed=False)

# negative outcome, no criteria -> passes
ok, err = verify(res('OUTCOME_NONE_UNSUPPORTED', {}), spec)
print('NEG', ok, err); assert ok, err
# positive outcome, criteria unmet -> fails
ok, err = verify(res('OUTCOME_OK', {'row': {}}), spec)
print('POS-FAIL', ok, err); assert not ok
# positive outcome, criteria met -> passes
ok, err = verify(res('OUTCOME_OK', {'row': {'sku':'X1'}}), spec)
print('POS-OK', ok, err); assert ok, err
print('OK')
"
```
Expected: `NEG True`, `POS-FAIL False …`, `POS-OK True`, then `OK`. (If `InterpretResult` requires different kwargs, adapt the constructor call to its actual signature — it is a dataclass in `agent/interpreter.py`.)

- [ ] **Step 6: Confirm the full suite stays green**

Run: `uv run pytest tests/ -q`
Expected: PASS (verify/pipeline tests using bare-list `success_criteria` still pass via coercion; `test_ir_models.py` updated).

- [ ] **Step 7: Commit**

```bash
git add agent/ir_models.py agent/verify.py data/prompts/intent.md tests/test_ir_models.py
git commit -m "feat(verify): key success_criteria by outcome so valid negatives pass

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6 (Block E): IR-syntax — `plan.md` op list + deterministic auto-repair

**Files:**
- Modify: `data/prompts/plan.md` (structural op/shape list — allowed)
- Modify: `agent/reason.py` (auto-repair in `run_plan`, before `PlanIR(**obj)`)

- [ ] **Step 1: List allowed ops + `AnswerTemplateIR` shape in `plan.md`**

In `data/prompts/plan.md`, append a new section after the "## `$ref` / `{slot}` convention" section (these are generic structural rules, not task knowledge):

```markdown
## Predicate ops (exact spellings)

`decision.branches[*].when` accepts ONLY these ops — use the exact spelling:

- Leaf: `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `nonempty`, `isnull`,
  `contains_any`, `in_set`, `startswith`, `endswith`, `regex_match`
- Bool: `and`, `or`, `not` (each takes `args`: a list of nested predicates)

Do NOT use `neq`, `!=`, `==`, `gte`, or `lte` — they are not valid op names.

## AnswerTemplateIR shape (exact keys)

Each `answer[<label>]` object has ONLY these keys: `message`, `outcome`, `refs`.
Add no other keys. Message `{slot}` placeholders resolve from `env`, never from
extra fields on the answer object.
```

- [ ] **Step 2: Add the deterministic normalizer to `reason.py`**

Add module-level helpers near the top of `agent/reason.py` (after the imports / `_MAX_TOKENS_*` constants):

```python
_OP_SYNONYMS = {"neq": "ne", "!=": "ne", "==": "eq", "gte": "ge", "lte": "le",
                "=>": "ge", "=<": "le"}
_ANSWER_KEYS = {"message", "outcome", "refs"}


def _repair_ops(node) -> None:
    """Map common predicate-op synonyms to canonical names, in place, recursively."""
    if isinstance(node, dict):
        op = node.get("op")
        if isinstance(op, str) and op in _OP_SYNONYMS:
            node["op"] = _OP_SYNONYMS[op]
        for v in node.values():
            _repair_ops(v)
    elif isinstance(node, list):
        for v in node:
            _repair_ops(v)


def _repair_plan_dict(obj: dict) -> dict:
    """Best-effort pre-lint repair of common IR slips, BEFORE pydantic validation.

    1. Normalize predicate-op synonyms (neq->ne, !=->ne, ==->eq, gte->ge, lte->le).
    2. Strip unknown keys from each answer branch (extra='forbid' would reject them).

    Unmappable ops are left untouched and still raise at PlanIR construction
    (-> PlanError -> iLEARN), so invalid IR is never silently accepted.
    """
    _repair_ops(obj)
    ans = obj.get("answer")
    if isinstance(ans, dict):
        for tmpl in ans.values():
            if isinstance(tmpl, dict):
                for k in list(tmpl.keys()):
                    if k not in _ANSWER_KEYS:
                        tmpl.pop(k)
    return obj
```

- [ ] **Step 3: Call the normalizer in `run_plan` before `PlanIR(**obj)`**

In `run_plan`, between the `isinstance(obj, dict)` check and `PlanIR(**obj)`:

```python
    obj = _extract_json_from_text(raw)
    if not isinstance(obj, dict):
        raise PlanError(f"PLAN: could not parse JSON; head: {raw[:200]!r}")
    obj = _repair_plan_dict(obj)
    try:
        return PlanIR(**obj)
    except Exception as e:
        raise PlanError(f"PLAN: validation failed: {e}") from e
```

- [ ] **Step 4: Verify auto-repair by running real code**

Run (a plan dict with `neq` in a branch + an extra answer key — both must be repaired and the plan must validate):
```bash
uv run python -c "
from agent.reason import _repair_plan_dict
from agent.ir_models import PlanIR
obj = {
  'discovery': [], 'rowsets': [], 'compute': [],
  'decision': {'branches': [{'when': {'op':'neq','lhs':'\$x','rhs':'1'}, 'label':'ok'}],
               'default_label': 'ok'},
  'ops': [],
  'answer': {'ok': {'message':'m','outcome':'OUTCOME_OK','refs':[],'extra_bogus':123}},
  'custom_extract': [],
}
obj = _repair_plan_dict(obj)
assert obj['decision']['branches'][0]['when']['op'] == 'ne'
assert 'extra_bogus' not in obj['answer']['ok']
plan = PlanIR(**obj)   # must not raise
print('op=', plan.decision.branches[0].when.op, '-> OK')
"
```
Expected: `op= ne -> OK`.

- [ ] **Step 5: Confirm the suite stays green**

Run: `uv run pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add data/prompts/plan.md agent/reason.py
git commit -m "feat(plan): list allowed IR ops + deterministic pre-lint op/answer repair

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7 (Acceptance): Real `t01` run, regression spot-check, prompt-size, docs

This is the intent's "Done when" gate. It runs the live benchmark — it needs the harness reachable and LLM creds configured (`.env` + `.secrets`).

- [ ] **Step 1: Run `t01` and confirm `OUTCOME_OK`**

Run:
```bash
LOG_LEVEL=DEBUG make task TASKS='t01' 2>&1 | tee /tmp/t01_after.log
```
Expected: the final table row for `t01` shows score `1.00` and `outcome=OUTCOME_OK`. In the log, confirm a `discovery` probe (e.g. `SELECT DISTINCT …` or a sample) precedes the format-correct filter (probe-then-refine).

- [ ] **Step 2: Confirm the PLAN prompt shrank below the 27–29 K baseline**

Run:
```bash
grep "\[plan\] user prompt chars=" /tmp/t01_after.log
```
Expected: every printed `chars=` value is well under the 27–29 K baseline (target < ~10 K). Record the numbers in the run notes.

- [ ] **Step 3: Confirm ≥1 oracle atom was injected into PLAN**

Run:
```bash
grep -iE "VALIDATED KNOWLEDGE|ANTI-PATTERNS|\[oracle\]" /tmp/t01_after.log || \
  echo "check the trace JSONL under logs/ for the oracle block in the PLAN user message"
```
Expected: evidence that the oracle block (APPLY/AVOID heading) entered the PLAN prompt; the bank is non-empty (Task 3 seeded it).

- [ ] **Step 4: Regression spot-check on ≥2 previously-passing tasks**

Pick two tasks that scored `1.00` on the last full baseline run (the intent's stop rule: halt if a prephase change regresses a passing task — include at least one security/`OUTCOME_DENIED_SECURITY` task to exercise the thinned INTENT policies path). Run:
```bash
make task TASKS='t<A>,t<B>' 2>&1 | tee /tmp/spotcheck_after.log
```
Expected: both still score `1.00`. If either regresses, STOP — do not proceed; investigate the thinned-facts path (likely a fact PLAN now needs via `discovery` but isn't fetching, or a constraint INTENT can no longer derive without full AGENTS.MD).

- [ ] **Step 5: Capture the LLM-call count delta (tracked, not gated)**

From `/tmp/t01_after.log`, note the per-cycle PLAN/iLEARN call count for `t01` (the intent tracks this; it is explicitly not a gate). Record before/after in the run notes.

- [ ] **Step 6: Update project docs (MANDATORY per CLAUDE.md)**

The change alters prephase fact flow, the oracle lifecycle, verify semantics, and PLAN IR handling. Regenerate the affected wiki pages and lint:

Invoke the iwiki skills (not raw engine subcommands):
- `iwiki:iwiki-ingest agent/reason.py agent/orchestrator.py agent/oracle.py agent/oracle_atoms.py agent/verify.py agent/ir_models.py agent/pipeline.py`
- `/iwiki-lint` — confirm no broken `[[refs]]`, orphans, or stale pages.

- [ ] **Step 7: Commit any doc updates**

```bash
git add docs/wiki/
git commit -m "docs(wiki): regenerate pages for prephase tiering + oracle polarity + keyed verify

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (run after writing, before execution)

- **Spec coverage:** Block A → Task 1; Block B → Task 3; Block C (model + render) → Task 2, Block C (distill + self-fill) → Task 4; Block D → Task 5; Block E → Task 6; acceptance/verification plan → Task 7. All five blocks + the verification plan have tasks.
- **Type consistency:** `success_criteria` is `dict[str, list[PredExpr]]` in Task 5 and is read as `.get(ans.outcome, [])` in `verify` (Task 5) — consistent. `Atom.polarity` added in Task 2 is set by `distill(..., polarity=...)` in Task 4 and read by `build_oracle_block` in Task 2 — consistent. `render_inventory` (Task 1) is called in `gather_prephase_facts` (Task 1) and feeds `_facts_block` via the `agents_md_inventory` fact key (Task 1) — consistent. `distill_from_grader(task_id, score, score_detail)` (Task 4) matches the `main.py` call site (Task 4).
- **No placeholders:** every code step shows complete code; every verify step shows the exact command + expected output.
- **Constraint adherence:** no new functional test files; prompt edits are structural (op lists, output shapes, keyed-criteria shape) — no task-specific domain rules; `verify` stays deterministic; `vm.answer` call sites untouched; seed atoms are generic methods (re-seed-safe).
