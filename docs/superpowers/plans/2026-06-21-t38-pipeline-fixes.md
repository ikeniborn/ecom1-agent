---
review:
  plan_hash: d5fdb53756ec4f6e
  spec_hash: 868e0bd29e43056b
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
  spec: docs/superpowers/specs/2026-06-21-t38-pipeline-fixes-design.md
---
# t38 Pipeline Robustness & Correctness Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop t38-class tasks from failing mechanically (empty PLAN on the CC tier with no reachable per-model config / fallback) and let INVESTIGATE deterministically ground the governing policy doc.

**Architecture:** One config seam in `agent/llm.py` resolves per-model `models.json` config so every LLM call site (which all pass `cfg={}`) gets CC timeout/model/fallback; the existing FIX-417 cross-provider fallback is turned on by config. INVESTIGATE gets two small pure helpers (deterministic doc-grounding + forced governing-doc read) wired into its ReAct loop. Optional observability touch-ups and an optional INVESTIGATE step-merge follow.

**Tech Stack:** Python 3, pytest, pydantic v2, `uv` for env/deps.

**Source of truth:** `docs/superpowers/specs/2026-06-21-t38-pipeline-fixes-design.md`.

**Conventions (read once):**
- Run tests with `uv run python -m pytest ... -v` (uv loads `.env`).
- Test style: `monkeypatch` for env + `monkeypatch.setattr` to stub `_call_raw_single_model`; `MockVMSpy` + `fixture_key` from `agent.mock_vm_spy` for VM fakes; pydantic models (`Note`, `Brief`, `RefSpec`) constructed directly.
- Commit after each task. Branch is `heuristics` (already off `master`).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `agent/llm.py` | LLM dispatch funnel | Add `resolve_model_cfg`; default empty `cfg` from it in `call_llm_raw` (incl. the fallback retry) |
| `agent/investigate.py` | read-only ReAct investigator | Add `_ground_doc_refs` + `_forced_doc_read`; wire into `investigate()`; (opt) merged step |
| `.env.example` | config template | Document/enable `ECOM_MODEL_FALLBACK`, `ECOM_CC_MAX_RETRIES`, `ECOM_CC_DEFAULT_TIMEOUT_S` |
| `models.json` | per-model config | (opt) add `cc_fallback_model` to `claude-code/*` |
| `main.py` | run summary | (opt, C/M1) add cache-token columns |
| `agent/llm.py` + `agent/trace.py` | trace | (opt, C/M2) thread `parsed_output` for INTENT/PLAN |
| `tests/test_llm_cfg_resolution.py` | new | A1/A2 unit tests |
| `tests/test_investigate_doc_grounding.py` | new | H2 unit tests |

---

## Task 1: A1 — Resolve per-model `cfg` from `models.json` at the call seam

**Files:**
- Modify: `agent/llm.py` (add `resolve_model_cfg`; patch `call_llm_raw` near line 564–601)
- Test: `tests/test_llm_cfg_resolution.py` (create)

**Context:** Every call site passes `cfg={}` (`reason.py:133,169`, `investigate.py:186`, `orchestrator.py:474`, `pipeline.py:138`, `llm.py:708`), so `models.json` `cc_options` (`cc_timeout_s`, `cc_model`) never reaches `cc_complete`. `models.json` is at the repo root; entries look like `"claude-code/sonnet": {"provider":"claude-code","cc_model":"sonnet","cc_options":{"cc_effort":"medium","cc_timeout_s":180,"cc_exclude_dynamic":true}}`. Underscore-prefixed keys (`_fields`, `_comment`) are docs and must be skipped.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_cfg_resolution.py`:

```python
import agent.llm as llm


def test_resolve_model_cfg_returns_block_for_known_model():
    cfg = llm.resolve_model_cfg("claude-code/sonnet")
    assert cfg.get("cc_model") == "sonnet"
    assert cfg.get("cc_options", {}).get("cc_timeout_s") == 180


def test_resolve_model_cfg_empty_for_unknown_model():
    assert llm.resolve_model_cfg("no/such-model") == {}


def test_resolve_model_cfg_skips_underscore_docs():
    assert llm.resolve_model_cfg("_fields") == {}


def test_call_llm_raw_defaults_empty_cfg_from_models_json(monkeypatch):
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["cfg"] = cfg
        return "ok"

    monkeypatch.setattr(llm, "_call_raw_single_model", _fake_single)
    llm.call_llm_raw([], "u", "claude-code/sonnet", {}, max_tokens=8, phase="PLAN")
    assert captured["cfg"].get("cc_model") == "sonnet"
    assert captured["cfg"].get("cc_options", {}).get("cc_timeout_s") == 180


def test_call_llm_raw_keeps_explicit_cfg(monkeypatch):
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["cfg"] = cfg
        return "ok"

    monkeypatch.setattr(llm, "_call_raw_single_model", _fake_single)
    llm.call_llm_raw([], "u", "claude-code/sonnet", {"cc_model": "opus"},
                     max_tokens=8, phase="PLAN")
    assert captured["cfg"] == {"cc_model": "opus"}  # caller cfg wins, not overridden


def test_call_llm_raw_unknown_model_keeps_empty_cfg(monkeypatch):
    captured = {}

    def _fake_single(system, user, model, cfg, **kw):
        captured["cfg"] = cfg
        return "ok"

    monkeypatch.setattr(llm, "_call_raw_single_model", _fake_single)
    llm.call_llm_raw([], "u", "no/such-model", {}, max_tokens=8, phase="PLAN")
    assert captured["cfg"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_llm_cfg_resolution.py -v`
Expected: FAIL — `AttributeError: module 'agent.llm' has no attribute 'resolve_model_cfg'`.

- [ ] **Step 3: Add the loader + resolver**

In `agent/llm.py`, just after the `_FALLBACK_MODEL = os.environ.get("ECOM_MODEL_FALLBACK", "")` line (≈284), add:

```python
# Per-model config from models.json (repo root). Loaded once at import.
# Every LLM call site passes cfg={}; call_llm_raw() backfills from here so
# models.json cc_options (cc_timeout_s / cc_model / cc_fallback_model) actually
# reach cc_complete. Underscore-prefixed keys are docs, not models.
_MODELS_JSON_PATH = Path(__file__).resolve().parent.parent / "models.json"
try:
    _raw_model_cfgs = json.loads(_MODELS_JSON_PATH.read_text())
    _MODEL_CFGS: dict[str, dict] = {
        k: v for k, v in _raw_model_cfgs.items()
        if not k.startswith("_") and isinstance(v, dict)
    }
except (OSError, ValueError):
    _MODEL_CFGS = {}


def resolve_model_cfg(model: str) -> dict:
    """Per-model config block from models.json ({} when absent / docs key)."""
    return _MODEL_CFGS.get(model, {})
```

Confirm `import json` and `from pathlib import Path` are already present at the top of `agent/llm.py` (they are used elsewhere); if `Path` is not imported, add `from pathlib import Path`.

- [ ] **Step 4: Backfill empty cfg in `call_llm_raw`**

In `agent/llm.py`, inside `call_llm_raw` (def at ≈564), immediately after the `if think is None: think = _think_for_phase(phase)` block and before `_tok = ...`, add:

```python
    if not cfg:
        cfg = resolve_model_cfg(model)
```

Then in the same function, change the fallback retry (≈597–601) so the fallback model also resolves its cfg. Replace:

```python
        result = _call_raw_single_model(
            system, user_msg, _FALLBACK_MODEL, {},
            max_tokens=max_tokens, think=think, max_retries=1,
            plain_text=plain_text, token_out=_tok, logprobs=logprobs,
        )
```

with:

```python
        result = _call_raw_single_model(
            system, user_msg, _FALLBACK_MODEL, resolve_model_cfg(_FALLBACK_MODEL),
            max_tokens=max_tokens, think=think, max_retries=1,
            plain_text=plain_text, token_out=_tok, logprobs=logprobs,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_llm_cfg_resolution.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Regression — existing routing tests still green**

Run: `uv run python -m pytest tests/test_llm_routing.py tests/test_llm_module.py tests/test_trace_llm_funnel.py -v`
Expected: PASS (no regressions; the empty-cfg backfill must not change behavior for unknown/test models).

- [ ] **Step 7: Commit**

```bash
git add agent/llm.py tests/test_llm_cfg_resolution.py
git commit -m "fix(llm): resolve per-model cfg from models.json at call seam

Every call site passes cfg={}, leaving models.json cc_options dead.
call_llm_raw now backfills an empty cfg via resolve_model_cfg(model)
(and for the MODEL_FALLBACK retry), so cc_timeout_s/cc_model reach
cc_complete. Caller-supplied cfg still wins.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: A2 — Configure the already-wired fallback (config)

**Files:**
- Modify: `.env.example`
- Modify (optional): `models.json` (`claude-code/*` `cc_fallback_model`)
- Test: `tests/test_llm_cfg_resolution.py` (append one test for FIX-417)

**Context:** `call_llm_raw` already retries with `_FALLBACK_MODEL` when the primary returns `None` (`llm.py:595-601`, FIX-417). It is dormant because `ECOM_MODEL_FALLBACK` is unset. This task documents/enables it and guards it with a test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_cfg_resolution.py`:

```python
def test_fallback_model_dispatched_when_primary_returns_none(monkeypatch):
    monkeypatch.setattr(llm, "_FALLBACK_MODEL", "anthropic/claude-sonnet-4-6")
    seen = []

    def _fake_single(system, user, model, cfg, **kw):
        seen.append(model)
        return None if model == "claude-code/sonnet" else "recovered"

    monkeypatch.setattr(llm, "_call_raw_single_model", _fake_single)
    out = llm.call_llm_raw([], "u", "claude-code/sonnet", {}, max_tokens=8, phase="PLAN")
    assert out == "recovered"
    assert seen == ["claude-code/sonnet", "anthropic/claude-sonnet-4-6"]
```

- [ ] **Step 2: Run test to verify it passes (FIX-417 already exists)**

Run: `uv run python -m pytest tests/test_llm_cfg_resolution.py::test_fallback_model_dispatched_when_primary_returns_none -v`
Expected: PASS — this guards the existing path. (If it FAILS, the fallback wiring regressed and must be fixed before proceeding.)

- [ ] **Step 3: Document config in `.env.example`**

In `.env.example`, under the model section, add (do not duplicate existing keys — edit in place if present):

```bash
# Cross-provider safety net: used after the primary model exhausts all tiers
# (incl. an empty/None CC-tier response). Any provider id works.
ECOM_MODEL_FALLBACK=anthropic/claude-sonnet-4-6

# CC (claude-code) tier subprocess controls. Lower retries for PLAN-heavy runs
# so a timing-out subprocess fails fast instead of ~3x180s.
ECOM_CC_MAX_RETRIES=1
ECOM_CC_DEFAULT_TIMEOUT_S=180
```

- [ ] **Step 4: (Optional) add native CC fallback to `models.json`**

In `models.json`, add `"cc_fallback_model": "haiku"` inside the `cc_options` block of `claude-code/sonnet` (and `claude-code/opus` if desired) so the native `--fallback-model` engages now that Task 1 makes `cc_options` reachable:

```json
  "claude-code/sonnet": {
    "provider": "claude-code",
    "cc_model": "sonnet",
    "cc_options": {
      "cc_effort": "medium",
      "cc_timeout_s": 180,
      "cc_exclude_dynamic": true,
      "cc_fallback_model": "haiku"
    }
  }
```

Verify `models.json` still parses: `uv run python -c "import json; json.load(open('models.json'))"` (no output = OK).

- [ ] **Step 5: Commit**

```bash
git add .env.example models.json tests/test_llm_cfg_resolution.py
git commit -m "feat(config): enable MODEL_FALLBACK + CC fallback/retry knobs

Turn on the already-wired FIX-417 cross-provider fallback via .env, add a
guard test, and (now reachable via Task 1) a native cc_fallback_model for
claude-code/* in models.json.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: H2a — Deterministic governing-doc grounding

**Files:**
- Modify: `agent/investigate.py` (add `_ground_doc_refs`; wire into `investigate()`)
- Test: `tests/test_investigate_doc_grounding.py` (create)

**Context:** `sufficient()` (`investigate.py:159-176`) reads `env["policy_doc:<path>"]`, set only by the digest LLM. `run_tool`'s `read` sets no env key. A required `policy_doc` RefSpec is `RefSpec(kind="policy_doc", path="/docs/x.md")` (path required, no source). We ground it in code the moment its exact path is read.

- [ ] **Step 1: Write the failing test**

Create `tests/test_investigate_doc_grounding.py`:

```python
from agent.investigate import _ground_doc_refs
from agent.ir_models import RefSpec


def _policy_refs():
    return [RefSpec(kind="policy_doc", path="/docs/fraud.md")]


def test_ground_sets_env_on_matching_read():
    env = {}
    _ground_doc_refs(env, "read", {"path": "/docs/fraud.md"}, _policy_refs())
    assert env.get("policy_doc:/docs/fraud.md") is True


def test_ground_ignores_nonmatching_path():
    env = {}
    _ground_doc_refs(env, "read", {"path": "/docs/other.md"}, _policy_refs())
    assert env == {}


def test_ground_ignores_nonread_tool():
    env = {}
    _ground_doc_refs(env, "exec", {"path": "/bin/sql"}, _policy_refs())
    assert env == {}


def test_ground_noop_without_policy_refs():
    env = {}
    _ground_doc_refs(env, "read", {"path": "/docs/fraud.md"}, [])
    assert env == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_investigate_doc_grounding.py -v`
Expected: FAIL — `ImportError: cannot import name '_ground_doc_refs'`.

- [ ] **Step 3: Add the helper**

In `agent/investigate.py`, add after `sufficient(...)` (≈line 176):

```python
def _ground_doc_refs(env: dict, tool: str, args: dict, refs: list) -> None:
    """Deterministically ground a required policy_doc ref when its exact path was
    just read — independent of the digest LLM emitting the env key. Mutates env."""
    if (tool or "").lower() != "read":
        return
    path = args.get("path", "")
    for r in refs:
        if getattr(r, "kind", "") == "policy_doc" and r.path == path:
            env[f"policy_doc:{path}"] = True
```

- [ ] **Step 4: Wire into the loop**

In `agent/investigate.py` `investigate()`, compute the required refs once before the loop. After `brief = Brief()` (≈line 252), add:

```python
    req_refs = (intent.required_refs or {}).get(intent.desired_outcome, [])
```

Then ground after each successful digest. In the normal-path block (≈lines 290-293), change:

```python
                seen.add(sig)
                note, env_updates = digest(goal, tool, args, observation, escalate=escalate)
                brief.notes.append(note)
                brief.env.update(env_updates)
                if sufficient(intent, brief.env):
                    break
```

to:

```python
                seen.add(sig)
                note, env_updates = digest(goal, tool, args, observation, escalate=escalate)
                brief.notes.append(note)
                brief.env.update(env_updates)
                _ground_doc_refs(brief.env, tool, args, req_refs)
                if sufficient(intent, brief.env):
                    break
```

And in the escalated-stop block (≈lines 286-289), change:

```python
                    if is_stalled(observation, sig, seen):     # still stalled after escalation → stop
                        note, env_updates = digest(goal, tool, args, observation, escalate=True)
                        brief.notes.append(note); brief.env.update(env_updates)
                        break
```

to:

```python
                    if is_stalled(observation, sig, seen):     # still stalled after escalation → stop
                        note, env_updates = digest(goal, tool, args, observation, escalate=True)
                        brief.notes.append(note); brief.env.update(env_updates)
                        _ground_doc_refs(brief.env, tool, args, req_refs)
                        break
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_investigate_doc_grounding.py tests/test_investigate.py -v`
Expected: PASS (new grounding tests + existing investigate tests).

- [ ] **Step 6: Commit**

```bash
git add agent/investigate.py tests/test_investigate_doc_grounding.py
git commit -m "fix(investigate): deterministically ground governing policy_doc on read

sufficient() depended on the digest LLM emitting policy_doc:<path>; now a
read of a required policy_doc path grounds the env key in code, closing the
'read the doc but never recorded it' gap behind t38.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: H2b — Prioritize reading an ungrounded governing doc

**Files:**
- Modify: `agent/investigate.py` (add `_forced_doc_read`; use it at the top of the step)
- Test: `tests/test_investigate_doc_grounding.py` (append)

**Context:** Even with Task 3, the router may never choose to read the governing doc. Force it: if a required `policy_doc` is ungrounded, the step's action is a `read` of that path instead of free routing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_investigate_doc_grounding.py`:

```python
from agent.investigate import _forced_doc_read


def test_forced_read_targets_ungrounded_policy_doc():
    act = _forced_doc_read({}, _policy_refs())
    assert act == {"tool": "read", "args": {"path": "/docs/fraud.md"}}


def test_forced_read_none_when_already_grounded():
    assert _forced_doc_read({"policy_doc:/docs/fraud.md": True}, _policy_refs()) is None


def test_forced_read_none_without_policy_refs():
    assert _forced_doc_read({}, []) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_investigate_doc_grounding.py -k forced -v`
Expected: FAIL — `ImportError: cannot import name '_forced_doc_read'`.

- [ ] **Step 3: Add the helper**

In `agent/investigate.py`, add right after `_ground_doc_refs`:

```python
def _forced_doc_read(env: dict, refs: list) -> "dict | None":
    """If a required policy_doc ref is still ungrounded, return a forced read
    action for its path (prioritized over free routing); else None."""
    for r in refs:
        if getattr(r, "kind", "") == "policy_doc" and r.path:
            if not env.get(f"policy_doc:{r.path}"):
                return {"tool": "read", "args": {"path": r.path}}
    return None
```

- [ ] **Step 4: Wire into the loop**

In `investigate()`, replace the router call at the top of the step (≈line 262):

```python
                act = router(intent, brief, atoms, escalate=False)
```

with:

```python
                forced = _forced_doc_read(brief.env, req_refs)
                if forced is not None and tool_signature(
                        forced["tool"], forced["args"]) not in seen:
                    act = forced  # prioritize grounding the governing doc
                else:
                    act = router(intent, brief, atoms, escalate=False)
```

(The `not in seen` guard prevents re-forcing a read that already ran; once the read succeeds, Task 3 grounds the env key and `_forced_doc_read` returns None.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_investigate_doc_grounding.py tests/test_investigate.py tests/test_pipeline_investigate.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/investigate.py tests/test_investigate_doc_grounding.py
git commit -m "feat(investigate): force-read an ungrounded required governing doc first

If a required policy_doc ref is ungrounded, the step reads that path instead
of free routing, so the investigator can't exhaust its budget without reading
the governing doc (the t38 sufficiency gap).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: M3 (optional, flagged) — Merge digest + next action into one call

**Files:**
- Modify: `agent/investigate.py` (add `digest_and_route`; gate via `ECOM_INVESTIGATE_MERGE_STEPS`)
- Test: `tests/test_investigate_merge.py` (create)

**Context:** Per step the loop makes a `router` call (pre-tool) and a `digest` call (post-tool). Merging the post-tool digest with the next step's routing halves router calls. Medium risk — gate behind a flag defaulting OFF so current behavior is unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/test_investigate_merge.py`:

```python
import agent.investigate as inv


def test_digest_and_route_returns_note_env_and_next_action(monkeypatch):
    def _fake_call_json(system, user, phase, escalate):
        return {
            "observation_digest": "40 rows",
            "lesson": "doc still unread",
            "env_updates": {"rows_found": "40"},
            "next_action": {"tool": "read", "args": {"path": "/docs/fraud.md"}},
        }

    monkeypatch.setattr(inv, "_call_json", _fake_call_json)
    note, env_updates, next_action = inv.digest_and_route(
        goal="g", tool="exec", args={"path": "/bin/sql"}, observation="rows...",
        escalate=False)
    assert note.observation_digest == "40 rows"
    assert env_updates == {"rows_found": "40"}
    assert next_action == {"tool": "read", "args": {"path": "/docs/fraud.md"}}


def test_digest_and_route_done_when_no_next_action(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda *a, **k: {"observation_digest": "d", "lesson": "l"})
    note, env_updates, next_action = inv.digest_and_route(
        goal="g", tool="read", args={"path": "/x"}, observation="o", escalate=False)
    assert next_action is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_investigate_merge.py -v`
Expected: FAIL — `AttributeError: module 'agent.investigate' has no attribute 'digest_and_route'`.

- [ ] **Step 3: Add the merged function**

In `agent/investigate.py`, add after `digest(...)` (≈line 230):

```python
def digest_and_route(goal: str, tool: str, args: dict, observation: str,
                     escalate: bool):
    """Condense the observation AND choose the next action in one LLM call.
    Returns (Note, env_updates, next_action|None). next_action mirrors router()
    output: {"tool","args"} or None when the investigator is done."""
    guide = load_prompt("investigate") or "# PHASE: INVESTIGATE"
    user = (f"GOAL:\n{goal}\n\nTOOL: {tool} {args}\n\n"
            f"RAW_RESULT (condense this):\n{observation[:4000]}\n\n"
            "Return JSON: observation_digest, lesson, refs_found, env_updates, "
            "and next_action ({\"tool\":...,\"args\":...} or null when done).")
    obj = _call_json(guide, user, phase="INVESTIGATE", escalate=escalate)
    note = Note(goal=goal, tool=tool, args=args,
                observation_digest=str(obj.get("observation_digest", ""))[:200],
                lesson=str(obj.get("lesson", "")),
                refs_found=list(obj.get("refs_found", []) or []))
    env_updates = obj.get("env_updates", {}) if isinstance(obj.get("env_updates"), dict) else {}
    na = obj.get("next_action")
    next_action = na if isinstance(na, dict) and na.get("tool") else None
    return note, env_updates, next_action
```

- [ ] **Step 4: Gate the merged path in the loop**

In `agent/investigate.py`, add the flag near `_MAX_STEPS` (≈line 233):

```python
_MERGE_STEPS = os.environ.get("ECOM_INVESTIGATE_MERGE_STEPS", "0") == "1"
```

In `investigate()`, carry a pending action across steps. After `req_refs = ...`, add `pending_action = None`. At the top of the step, prefer (in order) a forced doc-read, then a merged pending action, else the router:

```python
                forced = _forced_doc_read(brief.env, req_refs)
                if forced is not None and tool_signature(
                        forced["tool"], forced["args"]) not in seen:
                    act = forced
                elif _MERGE_STEPS and pending_action is not None:
                    act = pending_action
                    pending_action = None
                else:
                    act = router(intent, brief, atoms, escalate=False)
```

In the normal-path digest block, when `_MERGE_STEPS` is on use the merged call and stash the next action:

```python
                seen.add(sig)
                if _MERGE_STEPS:
                    note, env_updates, pending_action = digest_and_route(
                        goal, tool, args, observation, escalate=escalate)
                else:
                    note, env_updates = digest(goal, tool, args, observation, escalate=escalate)
                brief.notes.append(note)
                brief.env.update(env_updates)
                _ground_doc_refs(brief.env, tool, args, req_refs)
                if sufficient(intent, brief.env):
                    break
```

(Leave the escalated-stop branch using plain `digest` — escalation already terminates the loop.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_investigate_merge.py tests/test_investigate.py tests/test_pipeline_investigate.py -v`
Expected: PASS. With the flag OFF (default), existing investigate behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
git add agent/investigate.py tests/test_investigate_merge.py
git commit -m "feat(investigate): optional merged digest+route step (flagged off)

ECOM_INVESTIGATE_MERGE_STEPS=1 condenses the observation and picks the next
action in one LLM call, cutting per-step router calls. Default off preserves
current behavior.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6 (optional, C/M1): Cache tokens in the run summary

**Files:**
- Modify: `main.py` (summary row ≈204, 219, 232)
- Test: manual (summary is integration-only)

**Context:** `token_stats` from the harness trial has no cache fields; surfacing cache cost means aggregating `cache_read`/`cache_creation` from the per-task trace. Low value — do only if cheap. If the trace object exposes per-call cache sums, add two columns; otherwise skip and note it. No unit test (formatting only); verify visually on a CC run that the summary prints non-zero cache columns. **If aggregation requires non-trivial trace plumbing, stop and leave M1 unimplemented (it is explicitly optional in the spec).**

- [ ] **Step 1:** Inspect whether `token_stats` / the trace exposes `cache_read`/`cache_creation` sums. Run: `grep -nE "cache_read|cache_creation|token_stats|input_tokens" main.py agent/trace.py`
- [ ] **Step 2:** If available with a one-line aggregation, add `Кэш(tok)` columns to the header (≈204), `_print_table_row` (≈219), and totals (≈232). If not, document the gap in a `# M1: cache not in summary — needs trace aggregation` comment and stop.
- [ ] **Step 3:** Verify on a CC run: `make task TASKS='t38'` and read the summary table.
- [ ] **Step 4:** Commit (only if implemented):

```bash
git add main.py
git commit -m "feat(report): add cache-token columns to run summary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7 (optional, C/M2): Thread parsed_output into the INTENT/PLAN trace

**Files:**
- Modify: `agent/trace.py` (a small post-write update keyed by seq) and/or `agent/reason.py`
- Test: `tests/test_trace_llm_funnel.py` (extend) — only if implemented

**Context:** `call_llm_raw` hardcodes `parsed_output=None` (`llm.py:621`) and logs before the caller parses. Threading it cleanly needs a post-hoc trace update. Low value — implement only if a `TraceLogger` method to patch the last `llm_call` record by seq already exists or is trivial. **If it requires reworking the trace write path, stop and leave M2 unimplemented (explicitly optional).**

- [ ] **Step 1:** Check for an existing "update last record" seam: `grep -nE "_last_llm_seq|def .*update|_write|_records" agent/trace.py`
- [ ] **Step 2:** If trivial, add `TraceLogger.set_last_parsed_output(obj)` that patches the most recent `llm_call` record, and call it from `run_intent`/`run_plan` after a successful parse. Otherwise document and stop.
- [ ] **Step 3:** If implemented, extend `tests/test_trace_llm_funnel.py` to assert a parsed object lands on the INTENT event; run `uv run python -m pytest tests/test_trace_llm_funnel.py -v` (PASS).
- [ ] **Step 4:** Commit (only if implemented):

```bash
git add agent/trace.py agent/reason.py tests/test_trace_llm_funnel.py
git commit -m "feat(trace): record parsed_output for INTENT/PLAN events

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Full suite + integration gate (verifies A1/A2/H2/H3)

**Files:** none (verification only)

**Context:** Cluster A unblocks PLAN (no more silent 732 s empties → CLARIFICATION); Cluster B makes the answer correct (governing doc grounded → confirmed signal, not 3DS proxy → satisfies `r015`/H3). The grader is the real gate.

- [ ] **Step 1: Full unit suite**

Run: `uv run python -m pytest tests/ -v`
Expected: PASS (or only the pre-existing known-red `test_t09_replay_matches_known_good`, which is an unrelated stale fixture — see project memory). No NEW failures.

- [ ] **Step 2: Check for a competing run before timing**

Run: `pgrep -af "python main.py" || echo "clear"`
Expected: `clear` (if another session is looping `main.py`, do not start a timed run and do not kill theirs — coordinate first).

- [ ] **Step 3: Integration re-run of t38 against the grader**

Ensure `.env` has `ECOM_MODEL_FALLBACK` set (Task 2). Run: `make task TASKS='t38'`
Expected: PLAN no longer returns empty twice; `t38` reaches `OUTCOME_OK` with `score 1.0`. Inspect the new trace under `logs/<ts>/t38.jsonl` — PLAN should produce a PlanIR, and the brief `env` should contain `policy_doc:<governing-doc>: True`.

- [ ] **Step 4: If t38 still < 1.0**, capture the new failure mode (PLAN built but wrong records? still empty?) and feed it back — this is the LEARN/iLEARN seam, not a prompt patch. Do not edit `data/prompts/`. Record findings; a residual semantic gap may need a learned rule, out of this plan's mechanical scope.

- [ ] **Step 5: Commit any config touch-ups** made to `.env.example` during verification, then summarize results (unit pass count, t38 score before→after).

---

## Self-Review notes (author)

- **Spec coverage:** A1→T1, A2→T2, H2→T3+T4, M3→T5, M1→T6, M2→T7, H3→T8 (verified via grader, no code), verification strategy→T8. All §4–§7 items mapped.
- **Type consistency:** `resolve_model_cfg(model)->dict`, `_ground_doc_refs(env,tool,args,refs)->None`, `_forced_doc_read(env,refs)->dict|None`, `digest_and_route(...)->(Note,dict,dict|None)` — names/signatures used consistently across tasks.
- **No placeholders:** every code step shows real code; optional Tasks 6/7 carry explicit stop-conditions rather than vague "implement later".
