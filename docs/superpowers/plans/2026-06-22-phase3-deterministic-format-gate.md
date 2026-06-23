---
review:
  plan_hash: 68ba0cdada031a49
  spec_hash: 66967c9869af9c8c
  last_run: 2026-06-23
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  findings:
    - id: F-001
      phase: coverage
      severity: INFO
      section: Task 1
      section_hash: 07539821eb5d9c09
      text: >-
        Plan adds agent/ir_models.py to "Components touched"; the spec listed only
        format_gate/pipeline/interpreter. Justified and self-disclosed (Self-Review
        "Deviation noted" + Global Constraints): the spec's "declares a typed shape"
        phrasing implies the AnswerShape declaration channel, and the additive
        optional fields are back-compatible. Acceptable scope extension.
      verdict: open
      verdict_at: null
    - id: F-002
      phase: coverage
      severity: INFO
      section: Task 4
      section_hash: 3c7f3a0b4bb74d93
      text: >-
        table/quote formatters are built and unit-tested though the spec flagged
        them untethered (spec finding F-003 WARNING). Plan resolves this by keeping
        them declaration-only (dormant until answer_shape.kind is set via
        INTENT/LEARN); no current intent triggers them. Consistent with the spec's
        own open finding, not a new gap.
      verdict: open
      verdict_at: null
    - id: F-003
      phase: consistency
      severity: INFO
      section: Key facts that shape the design
      section_hash: ""
      text: >-
        Spec motivating evidence shows the failing regex lhs as `$answer.msg`
        (legacy) while verify binds `$answer.message`; the plan's _outcome_regexes
        reads BOTH lhs forms, so the gate detection and verify path stay aligned.
        Noted for traceability; no defect.
      verdict: open
      verdict_at: null
chain:
  intent: null
  spec: docs/superpowers/specs/2026-06-22-phase3-deterministic-format-gate-design.md
---
# Phase 3 — Deterministic Output-Format Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `answer.message` surface-format contract out of the LLM into a deterministic gate (`agent/format_gate.py`) that renders the computed value into the exact required string — `EUR %d.%02d`, `<YES>`/`<NO>` (or the tenant's `/AGENTS.MD` tokens), the task's `count` format, and TSV for table/quote — so a weak model can never lose on the surface string while having the value right.

**Architecture:** A new best-effort `format_answer(...)` runs in `pipeline.py` **after** Phase-2 `decide_outcome` and **before** `verify` (it MUST precede verify — the motivating failure is a `verify fail` on a format `regex_match`, so reshaping after verify would never be reached). It reshapes `result.captured.message` per the typed shape declared/inferred from `intent.answer_shape`. The interpreter carries the typed computed value (`CapturedAnswer.value`/`.rows`) alongside the rendered message so the gate renders from the value, not by re-parsing a string. The model proposes content; code shapes the surface. Best-effort: any failure, a negative/terminal outcome, or a free-text shape returns the message unchanged.

**Tech Stack:** Python 3, Pydantic v2 (`agent/ir_models.py`, `agent/interpreter.py`), `decimal.Decimal` (half-up money rounding), pytest, `MockVMSpy` (`agent/mock_vm_spy.py`), the kwargs VM surface (`agent/vm_adapter.py`).

**Branch:** Builds on `determinism` (Phases 1–2 already merged). Implement on a `dev/*` branch cut from `determinism`; PR back into `determinism` (NOT `master`).

## Global Constraints

- **Branch workflow:** never commit to `master`/`determinism` directly. Cut `dev/phase3-format-gate` from `determinism`; open the PR into `determinism`.
- **Prompt-engineering rule:** NEVER add task-specific domain rules to `data/prompts/*.md`. This plan touches **NO** file under `data/prompts/`. The new `AnswerShape` fields (`kind`/`columns`/`rows_from`) are populated by INTENT/LEARN, not by a prompt patch — the gate works for all 56 existing intents (which carry only `msg_skeleton`) by **inference**; the explicit `kind` is the extensible precise path.
- **`vm.answer` is called exactly once per task** (the `answer_once` guard in `pipeline.py`). The gate only mutates `result.captured.message` in place; it never answers.
- **Deterministic, never-raise:** `format_answer` and every helper are best-effort — any exception, an unparseable value, or a shape it cannot confidently reshape returns the original message. The gate must never corrupt a message that was already correct.
- **Gate fires only for OK-like outcomes.** A denial / clarification / unsupported message (`OUTCOME_DENIED_*`, `OUTCOME_NONE_*`) passes through unchanged (spec: "Preserve non-OK messages").
- **Keep docs current (MANDATORY):** after the code lands, regenerate the affected `docs/wiki/` pages via `iwiki:iwiki-ingest` and run `/iwiki-lint`. Docs/comments/commits in English.
- **Surgical changes:** touch only `agent/format_gate.py` (new), `agent/ir_models.py`, `agent/interpreter.py`, `agent/pipeline.py`, their tests, and the wiki. Do not refactor adjacent code. Do not touch `agent/verify.py` (the gate makes the existing verify regex pass; verify is unchanged).

---

## Background the executor MUST read first

You know nothing about this codebase. Read these before Task 1:

- `docs/superpowers/specs/2026-06-22-phase3-deterministic-format-gate-design.md` — the spec this plan implements.
- `agent/ir_models.py` lines 62–65 (`AnswerShape`, the model you extend) and 106–139 (`IntentSpec`: `answer_shape`, `success_criteria` keyed by outcome, `outcome_space`).
- `agent/interpreter.py` lines 39–52 (`CapturedAnswer`, `InterpretResult` — the model you extend + the result it rides in), 106–129 (`_SLOT_RE`, `_BARE_REF_RE`, `_render_slot`, `_fill_slots` — how the message is rendered; note `_render_slot` drops an integral float's `.0` so `12.5` renders `"12.5"`, NOT `"12.50"` — this is exactly the money-surface bug), 366–396 (answer assembly: `message = _fill_slots(tmpl.message, env)`, then the `CapturedAnswer(...)` you will populate).
- `agent/predicates.py` lines 9–13 (`resolve("$name.path", env)` — used to resolve a skeleton slot against `env`).
- `agent/pipeline.py` lines 447–471 — the interpret → `ground_refs` (Phase 1) → `decide_outcome` (Phase 2) → `verify` → `answer_once` block. Your wiring site is **between** `decide_outcome` (ends line 459) and `verify` (line 460). `agents_md_text` is a `run_pipeline` parameter already in scope (line 276).
- `agent/verify.py` lines 13–16, 78–80 — `verify` binds `env["answer"] = {"message": ans.message, ...}` and the `success_criteria` loop evaluates a `regex_match` whose `lhs` is `$answer.message` against `ans.message`. The gate overwrites `ans.message` before this runs, so the reshaped surface is what the regex sees.
- `tests/test_pipeline_decide.py` (whole file) — the integration idiom you mirror in Task 8: `_seq(...)` side-effect for `call_llm_raw`, `monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")`, a `MagicMock` VM with `vm.exec.return_value`, the `_enabled` autouse fixture.
- `agent/mock_vm_spy.py` + `agent/vm_adapter.py` — VM call surface (kwargs-style) for the interpreter integration test in Task 7.

### Key facts that shape the design

1. **Where the gate runs is load-bearing.** The motivating evidence is `verify fail: success_criteria[...] failed: {'op':'regex_match', ... 'rhs':'^EUR \\d+\\.\\d{2}$'}`. If the gate ran *after* verify, that failing cycle never reaches `answer_once`. So the gate runs **after `decide_outcome`, before `verify`** — verify then validates the canonical surface and passes. The spec's prose "just before `vm.answer`" means "the last reshape before the answer is accepted"; functionally that is just before the verify gate.

2. **`AnswerShape` today carries only `msg_skeleton`.** All 56 persisted `data/heuristics/t*.intent.json` have `{"msg_skeleton": "..."}` and nothing else. The spec phrase "When `intent.answer_shape` **declares** a typed shape" implies a declaration channel, so `AnswerShape` gains optional `kind`/`columns`/`rows_from` (Task 1). Adding optional fields with defaults is back-compatible — `extra="forbid"` rejects only *unknown* keys, never *missing optional* ones (same back-compat property Phase 2 relied on for `Constraint`). The gate prefers an explicit `kind`; with `kind=""` (every current intent) it **infers** the shape from the skeleton + `success_criteria` regex.

3. **The interpreter renders the value lossily.** `_render_slot(12.5)` → `"12.5"` (drops the `.0` only for integral floats, but a non-integral float keeps single-digit cents). The gate must render `EUR 12.50` from the *number* `12.5`, not from the string `"12.5"`. So the interpreter carries the typed value on `CapturedAnswer.value` (Task 7); the gate falls back to parsing the message only when no value was carried.

4. **Money detection must be precise to avoid corruption.** Prose answers mention EUR without being a bare money surface — e.g. t51 `"The total price difference is {difference_euros} EUR, which is {comparison_result} the 1 EUR threshold."`. Reshaping that to `"EUR 0.50"` would destroy the answer. So the *money* shape fires ONLY when (a) the skeleton stripped matches `^EUR <amount>$` (bare, no prose — e.g. t48 `"EUR {total_euros}.{total_cents_two_digits}"`), or (b) a `success_criteria` regex for the outcome is the anchored EUR-cents pattern (`EUR \d…`). t51/t52/t53 prose → shape `free` → passthrough (their correctness is the numeric `le`/`gt` criterion, not the surface).

5. **Boolean reshape is additive, never destructive.** Motivating tasks (t04/t06/t07/t08) fail because the message lacks the canonical `<YES>`/`<NO>` token, not because the polarity is wrong. The gate prepends the canonical token when absent (polarity taken from the skeleton's literal token, else inferred from the message); it never strips the model's prose and never flips a token that is already present. Ambiguous polarity with no skeleton token → return unchanged.

6. **count format source (resolves spec finding F-001).** The count format string is `answer_shape.msg_skeleton` itself (it echoes the instruction's required clause — the same string the `success_criteria` regex validates), no other source. The gate substitutes the integer into the skeleton's `%d` (t13 `qty=%d`, t16 `Total: %d`, t12 `<COUNT:%d>`) or its single `{slot}` (t10 `<COUNT:{count}>`, t17 `count: {count}`).

7. **table/quote are declaration-only this phase (relates to spec finding F-003).** No current intent declares a tabular shape and the spec gives no TSV column contract, so the gate renders TSV from `CapturedAnswer.rows` + `answer_shape.columns` and fires only when `answer_shape.kind` is `"table"`/`"quote"` (set via INTENT/LEARN). The mechanism is built and unit-tested; it stays dormant until a `kind` is declared. `table` → header row + rows; `quote` → rows only (no header).

### Design decisions (read before coding)

- **`format_answer` signature.** The spec lists `format_answer(message, intent, answer_shape, agents_md) -> str`. Those four are kept positional; `outcome` (needed for the non-OK passthrough), `value`, and `rows` are keyword-only additions with defaults (`outcome="OUTCOME_OK"`, `value=None`, `rows=None`). `answer_shape` is `intent.answer_shape` passed explicitly for unit-test convenience.
- **Outcome passthrough set.** `_is_preserved_outcome(o)` is True for `o.startswith("OUTCOME_NONE")` or `"DENIED" in o`. OK and OK-like custom outcomes (e.g. `OUTCOME_DIFFERENCE_EXCEEDS`) are formatted; denials/clarifications/unsupported pass through.
- **`OUTCOME_*` prefix strip is a general normalize-only guard** applied to every formatted (OK-like) message before shape dispatch (spec: "a wrongly-prepended `OUTCOME_*` prefix is stripped").
- **No `verify.py` change.** The gate makes the *existing* verify regex pass; `verify` is out of scope (spec "Components touched" excludes it).
- **Inference is best-effort; explicit `kind` is precise.** Under-detecting a shape (→ `free` → passthrough) is always safe (no corruption); over-detecting money is the only dangerous case and is guarded by fact 4.

---

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `agent/ir_models.py` (modify) | Extend `AnswerShape` with optional `kind`/`columns`/`rows_from` (back-compatible). | 1 |
| `agent/format_gate.py` (new) | The whole deterministic gate: `format_eur`, `bool_tokens`, `_canonicalize_bool`, count/table/quote renderers, `detect_shape`, `already_exact`, `format_answer`. Best-effort, never raises. | 2–6 |
| `agent/interpreter.py` (modify) | `CapturedAnswer` gains `value`/`rows`; `interpret()` populates them via `_resolve_answer_value`/`_resolve_answer_rows`. | 7 |
| `agent/pipeline.py` (modify) | Invoke `format_answer` between `decide_outcome` and `verify`; pass `agents_md_text` + carried value/rows. | 8 |
| `tests/test_format_gate.py` (new) | Unit tests for every gate helper + `format_answer`. | 2–6 |
| `tests/test_interpreter_answer_value.py` (new) | Unit tests for `_resolve_answer_value`/`_resolve_answer_rows` + one `interpret()` carry assert. | 7 |
| `tests/test_pipeline_format.py` (new) | Integration: a money / boolean / count answer is reshaped before verify and accepted. | 8 |

---

## Task 1: Extend `AnswerShape` with the typed-shape declaration fields

**Files:**
- Modify: `agent/ir_models.py:62-65` (the `AnswerShape` class)
- Test: `tests/test_ir_models.py`

**Interfaces:**
- Produces: `AnswerShape(msg_skeleton="", kind="", columns=[], rows_from="")`. `format_gate.py` (Tasks 2–6) and `interpreter.py` (Task 7) consume `kind`/`columns`/`rows_from`/`msg_skeleton`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ir_models.py`:

```python
from agent.ir_models import AnswerShape, IntentSpec
import pytest
from pydantic import ValidationError


def test_answer_shape_accepts_typed_fields():
    s = AnswerShape(msg_skeleton="EUR {amt}", kind="money",
                    columns=["sku", "qty"], rows_from="rows")
    assert s.kind == "money"
    assert s.columns == ["sku", "qty"]
    assert s.rows_from == "rows"


def test_answer_shape_back_compatible_minimal_shape():
    # The legacy shape (only msg_skeleton) still validates with safe defaults.
    s = AnswerShape(msg_skeleton="count: {count}")
    assert s.kind == ""
    assert s.columns == []
    assert s.rows_from == ""


def test_answer_shape_default_empty():
    s = AnswerShape()
    assert s.msg_skeleton == "" and s.kind == "" and s.columns == [] and s.rows_from == ""


def test_answer_shape_rejects_unknown_key():
    with pytest.raises(ValidationError):
        AnswerShape(msg_skeleton="x", bogus=1)


def test_intent_with_persisted_answer_shape_still_loads():
    # A persisted intent.json carries only msg_skeleton — must still validate.
    intent = IntentSpec(objective="o", desired_outcome="OUTCOME_OK",
                        outcome_space=["OUTCOME_OK"], constraints=[],
                        success_criteria={}, answer_shape={"msg_skeleton": "qty=%d"},
                        required_refs={})
    assert intent.answer_shape.kind == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ir_models.py::test_answer_shape_accepts_typed_fields -v`
Expected: FAIL with `ValidationError` (extra fields `kind`, `columns`, `rows_from` forbidden).

- [ ] **Step 3: Extend the `AnswerShape` model**

Replace `agent/ir_models.py:62-65`:

```python
class AnswerShape(BaseModel):
    model_config = ConfigDict(extra="forbid")
    msg_skeleton: str = ""
    kind: str = ""            # "" -> format gate infers (money/boolean/count); else explicit
    columns: list[str] = []   # TSV column order for kind in {"table","quote"}
    rows_from: str = ""       # env binding name holding the row list for table/quote
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ir_models.py -v`
Expected: PASS (the 5 new tests + every pre-existing test).

- [ ] **Step 5: Run the IR-model regression to prove no break**

Run: `uv run pytest tests/test_ir_models.py tests/test_interpreter.py tests/test_verify.py -q`
Expected: PASS (persisted-intent shape and verify still validate unchanged).

- [ ] **Step 6: Commit**

```bash
git add agent/ir_models.py tests/test_ir_models.py
git commit -m "feat(ir): extend AnswerShape with typed-shape declaration fields"
```

---

## Task 2: `format_gate.py` — `format_eur`

**Files:**
- Create: `agent/format_gate.py`
- Test: `tests/test_format_gate.py`

**Interfaces:**
- Produces: `format_eur(value) -> str` — `"EUR <int>.<2 digits>"` (half-up to cents) or `""` on failure. Tasks 5–6 consume it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_format_gate.py`:

```python
from agent.format_gate import format_eur


def test_format_eur_pads_single_digit_cents():
    assert format_eur(12.5) == "EUR 12.50"


def test_format_eur_integer_value():
    assert format_eur(12) == "EUR 12.00"


def test_format_eur_string_value():
    assert format_eur("0.5") == "EUR 0.50"


def test_format_eur_half_up_rounding():
    # 1.005 -> 1.01 under half-up (the grader's expectation), not banker's rounding.
    assert format_eur("1.005") == "EUR 1.01"


def test_format_eur_already_two_digits():
    assert format_eur(1234.56) == "EUR 1234.56"


def test_format_eur_empty_on_unparseable():
    assert format_eur("twelve") == ""
    assert format_eur(None) == ""


def test_format_eur_empty_on_negative():
    # negative euros are unexpected -> caller keeps the original message.
    assert format_eur(-3.2) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_format_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.format_gate'`.

- [ ] **Step 3: Create `agent/format_gate.py`**

```python
"""Deterministic output-format gate (0 LLM): reshape answer.message into the exact
surface contract — EUR %d.%02d, <YES>/<NO> (or the tenant's /AGENTS.MD tokens), the
task's count format, or TSV for table/quote. The model proposes content; this code
shapes the surface.

Best-effort: format_answer and every helper never raise — any failure, a negative
outcome, or a shape it cannot confidently reshape returns the original message. The
gate never corrupts a message that was already correct (the muxx exoskeleton pattern,
mirroring agent/grounding.py and agent/decide.py).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_SLOT_RE = re.compile(r"\{([^{}]+)\}")   # mirrors interpreter._SLOT_RE


def format_eur(value) -> str:
    """Render a euro amount as 'EUR <int>.<2-digit cents>' (the grader's
    ^EUR \\d+\\.\\d{2}$). Half-up rounding to cents. Best-effort: '' on any failure
    (caller keeps the original message)."""
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return ""
    if d.is_nan() or d.is_infinite() or d < 0:
        return ""
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"EUR {d:.2f}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_format_gate.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/format_gate.py tests/test_format_gate.py
git commit -m "feat(format-gate): format_eur half-up money formatter"
```

---

## Task 3: `format_gate.py` — boolean tokens + canonicalisation

**Files:**
- Modify: `agent/format_gate.py` (append)
- Test: `tests/test_format_gate.py` (append)

**Interfaces:**
- Consumes: `AnswerShape` (Task 1).
- Produces: `bool_tokens(agents_md, answer_shape) -> tuple[str, str]`, `_canonicalize_bool(message, yes_tok, no_tok, skeleton) -> str`, `_strip_outcome_prefix(message) -> str`. Task 6 consumes them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_format_gate.py`:

```python
from agent.format_gate import bool_tokens, _canonicalize_bool, _strip_outcome_prefix
from agent.ir_models import AnswerShape


def test_bool_tokens_default():
    assert bool_tokens("", AnswerShape(msg_skeleton="<NO> (SKU: {sku})")) == ("<YES>", "<NO>")


def test_bool_tokens_custom_from_agents_md():
    md = "## Format\nyes_token: AFFIRM\nno_token: REJECT\n"
    assert bool_tokens(md, AnswerShape()) == ("AFFIRM", "REJECT")


def test_canonicalize_prepends_no_from_skeleton_polarity():
    # skeleton declares <NO>; message lacks any token -> prepend <NO>, keep the prose.
    out = _canonicalize_bool("SKU: ABC not found", "<YES>", "<NO>", "<NO> (SKU: {sku})")
    assert out == "<NO> SKU: ABC not found"


def test_canonicalize_prepends_yes_from_message_polarity():
    # no skeleton token; message reads affirmative -> prepend <YES>.
    out = _canonicalize_bool("yes it matches the spec", "<YES>", "<NO>", "{verdict} (SKU: {sku})")
    assert out.startswith("<YES> ")


def test_canonicalize_noop_when_token_already_present():
    # already carries a canonical token -> return "" (caller keeps the message as-is).
    assert _canonicalize_bool("<NO> (SKU: ABC)", "<YES>", "<NO>", "<NO> (SKU: {sku})") == ""


def test_canonicalize_noop_when_polarity_ambiguous():
    # no skeleton token AND no yes/no signal in the message -> "" (never fabricate).
    assert _canonicalize_bool("the product details follow", "<YES>", "<NO>", "{verdict}") == ""


def test_strip_outcome_prefix():
    assert _strip_outcome_prefix("OUTCOME_OK: 5 items") == "5 items"
    assert _strip_outcome_prefix("OUTCOME_NONE_UNSUPPORTED - nope") == "nope"
    assert _strip_outcome_prefix("plain message") == "plain message"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_format_gate.py -k "bool or canonical or strip_outcome" -v`
Expected: FAIL with `ImportError: cannot import name 'bool_tokens'`.

- [ ] **Step 3: Append the implementation to `agent/format_gate.py`**

```python
_BOOL_TOK_RE = re.compile(r"<\s*(?:YES|NO)\s*>", re.I)
_AGENTS_YES_RE = re.compile(r"(?im)^\s*(?:yes[_ ]?token|affirmative)\s*[:=]\s*(\S+)")
_AGENTS_NO_RE = re.compile(r"(?im)^\s*(?:no[_ ]?token|negative)\s*[:=]\s*(\S+)")
_OUTCOME_PREFIX_RE = re.compile(r"^\s*OUTCOME_[A-Z_]+\s*[:\-]?\s*")

# Polarity markers — conservative; ambiguous text yields no polarity (keep original).
_YES_RE = re.compile(r"<\s*yes\s*>|\byes\b|\bin the catalogue\b|\bmatches\b|\bconfirmed\b", re.I)
_NO_RE = re.compile(r"<\s*no\s*>|\bno\b|\bnot\b|\bcannot\b|\bno match\b|\bdenied\b|\bdoes not\b", re.I)


def _strip_outcome_prefix(message: str) -> str:
    """Strip a wrongly-prepended 'OUTCOME_*:' / 'OUTCOME_* -' prefix (normalize-only)."""
    return _OUTCOME_PREFIX_RE.sub("", message or "", count=1)


def bool_tokens(agents_md, answer_shape) -> tuple[str, str]:
    """The tenant's (yes, no) tokens. Default '<YES>'/'<NO>'; a custom pair declared in
    /AGENTS.MD ('yes_token: X' / 'no_token: Y') overrides. No per-task values."""
    yes_tok, no_tok = "<YES>", "<NO>"
    my = _AGENTS_YES_RE.search(agents_md or "")
    mn = _AGENTS_NO_RE.search(agents_md or "")
    if my:
        yes_tok = my.group(1)
    if mn:
        no_tok = mn.group(1)
    return yes_tok, no_tok


def _polarity_from(text: str):
    """True (affirmative) / False (negative) / None (ambiguous) from text markers."""
    t = text or ""
    yes, no = bool(_YES_RE.search(t)), bool(_NO_RE.search(t))
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


def _canonicalize_bool(message: str, yes_tok: str, no_tok: str, skeleton: str) -> str:
    """Ensure the canonical yes/no token is present (additive, never destructive).
    Returns '' when no change is warranted (token already present, or polarity cannot
    be determined) so the caller keeps the original message."""
    if yes_tok in (message or "") or no_tok in (message or ""):
        return ""
    polarity = _polarity_from(skeleton)
    if polarity is None:
        polarity = _polarity_from(message)
    if polarity is None:
        return ""
    tok = yes_tok if polarity else no_tok
    body = _strip_outcome_prefix(message).strip()
    return f"{tok} {body}".strip() if body else tok
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_format_gate.py -v`
Expected: PASS (Task 2 + Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/format_gate.py tests/test_format_gate.py
git commit -m "feat(format-gate): yes/no token resolution + additive canonicalisation"
```

---

## Task 4: `format_gate.py` — count / table / quote renderers + value extractors

**Files:**
- Modify: `agent/format_gate.py` (append)
- Test: `tests/test_format_gate.py` (append)

**Interfaces:**
- Produces: `_render_count(skeleton, n) -> str`, `_render_table(rows, columns) -> str`, `_render_quote(rows, columns) -> str`, `_extract_int(text) -> int | None`, `_extract_eur_number(text) -> float | None`, `_coerce_int(value, message) -> int | None`. Task 6 consumes them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_format_gate.py`:

```python
from agent.format_gate import (
    _render_count, _render_table, _render_quote,
    _extract_int, _extract_eur_number, _coerce_int,
)


def test_render_count_printf():
    assert _render_count("qty=%d", 5) == "qty=5"
    assert _render_count("<COUNT:%d>", 3) == "<COUNT:3>"
    assert _render_count("Total: %d", 12) == "Total: 12"


def test_render_count_single_slot():
    assert _render_count("<COUNT:{count}>", 7) == "<COUNT:7>"
    assert _render_count("count: {count}", 0) == "count: 0"


def test_render_count_empty_when_ambiguous_multi_slot():
    assert _render_count("{a} of {b}", 5) == ""


def test_render_table_header_then_rows():
    rows = [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 5}]
    assert _render_table(rows, ["sku", "qty"]) == "sku\tqty\nA\t2\nB\t5"


def test_render_table_empty_when_no_columns_or_rows():
    assert _render_table([{"a": 1}], []) == ""
    assert _render_table([], ["a"]) == ""


def test_render_quote_rows_only_no_header():
    rows = [{"sku": "A", "qty": 2}]
    assert _render_quote(rows, ["sku", "qty"]) == "A\t2"


def test_extract_int_first_integer():
    assert _extract_int("there are 5 items") == 5
    assert _extract_int("<COUNT:42>") == 42
    assert _extract_int("nothing here") is None


def test_extract_eur_number_prefers_eur_adjacent():
    assert _extract_eur_number("EUR 12.5") == 12.5


def test_coerce_int_prefers_value_then_message():
    assert _coerce_int(5, "ignored") == 5
    assert _coerce_int(5.0, "ignored") == 5
    assert _coerce_int(None, "qty=9") == 9
    assert _coerce_int(True, "qty=9") == 9   # bool is not a count value -> fall to message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_format_gate.py -k "render or extract or coerce" -v`
Expected: FAIL with `ImportError: cannot import name '_render_count'`.

- [ ] **Step 3: Append the implementation to `agent/format_gate.py`**

```python
_INT_RE = re.compile(r"-?\d+")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_EUR_NUM_RE = re.compile(r"EUR\s*(-?\d+(?:\.\d+)?)", re.I)


def _extract_int(text: str):
    """First integer in the text, else None."""
    m = _INT_RE.search(text or "")
    return int(m.group(0)) if m else None


def _extract_eur_number(text: str):
    """A euro amount parsed from a message: the number adjacent to 'EUR' if present,
    else the first number, else None."""
    m = _EUR_NUM_RE.search(text or "")
    if m:
        return float(m.group(1))
    m = _NUM_RE.search(text or "")
    return float(m.group(0)) if m else None


def _coerce_int(value, message: str):
    """The integer a count answer should render: a carried int/integral-float value
    (never a bool), else the first integer parsed from the message."""
    if isinstance(value, bool):
        value = None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return _extract_int(message)


def _render_count(skeleton: str, n: int) -> str:
    """Substitute the integer into the count contract (answer_shape.msg_skeleton): a
    printf '%d' or a single '{slot}'. Ambiguous (multi-slot, no %d) -> '' (caller keeps
    the original)."""
    s = skeleton or ""
    if "%d" in s:
        return s.replace("%d", str(int(n)), 1)
    slots = _SLOT_RE.findall(s)
    if len(slots) == 1:
        return s.replace("{" + slots[0] + "}", str(int(n)))
    return ""


def _cell(row, col: str) -> str:
    v = row.get(col, "") if isinstance(row, dict) else getattr(row, col, "")
    return "" if v is None else str(v)


def _render_table(rows, columns) -> str:
    """TSV with a header row. '' when rows or columns are empty (caller keeps original)."""
    if not rows or not columns:
        return ""
    out = ["\t".join(columns)]
    for r in rows:
        out.append("\t".join(_cell(r, c) for c in columns))
    return "\n".join(out)


def _render_quote(rows, columns) -> str:
    """TSV rows WITHOUT a header. '' when rows or columns are empty."""
    if not rows or not columns:
        return ""
    return "\n".join("\t".join(_cell(r, c) for c in columns) for r in rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_format_gate.py -v`
Expected: PASS (Tasks 2–4 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/format_gate.py tests/test_format_gate.py
git commit -m "feat(format-gate): count/table/quote renderers + value extractors"
```

---

## Task 5: `format_gate.py` — `detect_shape` + `already_exact`

**Files:**
- Modify: `agent/format_gate.py` (append)
- Test: `tests/test_format_gate.py` (append)

**Interfaces:**
- Consumes: `IntentSpec`/`AnswerShape` (Task 1), `_BOOL_TOK_RE` (Task 3).
- Produces: `_outcome_regexes(intent, outcome) -> list[str]`, `detect_shape(intent, answer_shape, outcome, value=None) -> str`, `already_exact(message, intent, answer_shape, outcome) -> bool`. Task 6 consumes them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_format_gate.py`:

```python
from agent.format_gate import detect_shape, already_exact, _outcome_regexes
from agent.ir_models import IntentSpec, AnswerShape


def _intent(skeleton="", criteria=None, kind="", columns=None, rows_from=""):
    return IntentSpec(
        objective="o", desired_outcome="OUTCOME_OK", outcome_space=["OUTCOME_OK"],
        constraints=[], success_criteria=criteria or {},
        answer_shape={"msg_skeleton": skeleton, "kind": kind,
                      "columns": columns or [], "rows_from": rows_from},
        required_refs={})


def test_detect_explicit_kind_wins():
    it = _intent(skeleton="anything", kind="table", columns=["a"])
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "table"


def test_detect_boolean_from_skeleton_token():
    it = _intent(skeleton="<NO> (SKU: {sku})")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "boolean"


def test_detect_money_from_bare_eur_skeleton():
    it = _intent(skeleton="EUR {total_euros}.{total_cents_two_digits}")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "money"


def test_detect_money_from_anchored_regex():
    it = _intent(skeleton="{amount}",
                 criteria={"OUTCOME_OK": [{"op": "regex_match", "lhs": "$answer.message",
                                           "rhs": r"^EUR \d+\.\d{2}$"}]})
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "money"


def test_detect_money_does_not_fire_on_eur_prose():
    # t51-class: EUR appears mid-prose -> NOT money (reshaping would corrupt the answer).
    it = _intent(skeleton="The total price difference is {d} EUR, which is {c} the threshold.")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "free"


def test_detect_count_printf_and_markers_and_count_slot():
    assert detect_shape(_intent("qty=%d"), AnswerShape(msg_skeleton="qty=%d"), "OUTCOME_OK") == "count"
    assert detect_shape(_intent("<COUNT:{count}>"), AnswerShape(msg_skeleton="<COUNT:{count}>"), "OUTCOME_OK") == "count"
    assert detect_shape(_intent("count: {count}"), AnswerShape(msg_skeleton="count: {count}"), "OUTCOME_OK") == "count"
    assert detect_shape(_intent("{count}"), AnswerShape(msg_skeleton="{count}"), "OUTCOME_OK") == "count"


def test_detect_free_for_plain_prose():
    it = _intent(skeleton="The product {name} (SKU: {sku}) is in the catalogue.")
    assert detect_shape(it, it.answer_shape, "OUTCOME_OK") == "free"


def test_already_exact_true_when_message_matches_required_regex():
    it = _intent(criteria={"OUTCOME_OK": [{"op": "regex_match", "lhs": "$answer.message",
                                           "rhs": r"^EUR \d+\.\d{2}$"}]})
    assert already_exact("EUR 12.50", it, it.answer_shape, "OUTCOME_OK") is True
    assert already_exact("EUR 12.5", it, it.answer_shape, "OUTCOME_OK") is False


def test_already_exact_false_when_no_regex_declared():
    it = _intent(skeleton="qty=%d")
    assert already_exact("qty=5", it, it.answer_shape, "OUTCOME_OK") is False


def test_outcome_regexes_reads_msg_and_message_lhs():
    it = _intent(criteria={"OUTCOME_OK": [
        {"op": "regex_match", "lhs": "$answer.msg", "rhs": "^<NO> .+$"},
        {"op": "nonempty", "lhs": "$answer.message"}]})
    assert _outcome_regexes(it, "OUTCOME_OK") == ["^<NO> .+$"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_format_gate.py -k "detect or already_exact or outcome_regexes" -v`
Expected: FAIL with `ImportError: cannot import name 'detect_shape'`.

- [ ] **Step 3: Append the implementation to `agent/format_gate.py`**

```python
_MONEY_SKELETON_RE = re.compile(r"^EUR\s+[\{\}\w.]+$")   # bare 'EUR <amount>' only
_MONEY_REGEX_RE = re.compile(r"EUR\s*\\d")               # anchored EUR-cents success regex
_COUNT_MARK_RE = re.compile(r"%d|<\s*COUNT|\[\s*QTY|<\s*QTY|qty\s*=|count\s*:", re.I)
_COUNT_SLOT_ONLY_RE = re.compile(r"^\s*\{([^{}]+)\}\s*$")


def _outcome_regexes(intent, outcome: str) -> list[str]:
    """The regex_match patterns a verify success_criterion applies to the answer message
    for `outcome` (lhs $answer.message or the legacy $answer.msg)."""
    out: list[str] = []
    for crit in (getattr(intent, "success_criteria", {}) or {}).get(outcome, []):
        op = getattr(crit, "op", None)
        lhs = getattr(crit, "lhs", None)
        rhs = getattr(crit, "rhs", None)
        if op == "regex_match" and lhs in ("$answer.message", "$answer.msg") and isinstance(rhs, str):
            out.append(rhs)
    return out


def _is_count_slot_only(skeleton: str) -> bool:
    m = _COUNT_SLOT_ONLY_RE.match(skeleton or "")
    return bool(m and re.search(r"count|qty|total|num", m.group(1), re.I))


def detect_shape(intent, answer_shape, outcome: str, value=None) -> str:
    """The typed shape to reshape into: explicit answer_shape.kind wins; otherwise infer
    from the skeleton + success_criteria regex. Returns one of
    money/boolean/count/table/quote/free. Conservative — anything unrecognised is 'free'
    (passthrough). Over-detecting money is the only unsafe case and is guarded by the
    bare-EUR / anchored-regex signals."""
    kind = (getattr(answer_shape, "kind", "") or "").strip().lower()
    if kind in {"money", "boolean", "count", "table", "quote", "free"}:
        return kind
    skel = (getattr(answer_shape, "msg_skeleton", "") or "").strip()
    rxs = _outcome_regexes(intent, outcome)
    if _BOOL_TOK_RE.search(skel) or any(_BOOL_TOK_RE.search(rx) for rx in rxs):
        return "boolean"
    if _MONEY_SKELETON_RE.match(skel) or any(_MONEY_REGEX_RE.search(rx) for rx in rxs):
        return "money"
    if _COUNT_MARK_RE.search(skel) or _is_count_slot_only(skel):
        return "count"
    return "free"


def already_exact(message: str, intent, answer_shape, outcome: str) -> bool:
    """True when the message already satisfies every declared answer-message regex for
    the outcome (short-circuit: leave a correct surface untouched)."""
    rxs = _outcome_regexes(intent, outcome)
    return bool(rxs) and all(re.search(rx, message or "") for rx in rxs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_format_gate.py -v`
Expected: PASS (Tasks 2–5 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/format_gate.py tests/test_format_gate.py
git commit -m "feat(format-gate): shape detection + already-exact short-circuit"
```

---

## Task 6: `format_gate.py` — `format_answer` orchestrator

**Files:**
- Modify: `agent/format_gate.py` (append)
- Test: `tests/test_format_gate.py` (append)

**Interfaces:**
- Consumes: every helper from Tasks 2–5.
- Produces: `format_answer(message, intent, answer_shape, agents_md, *, outcome="OUTCOME_OK", value=None, rows=None) -> str`. Task 8 (`pipeline.py`) consumes it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_format_gate.py`:

```python
from agent.format_gate import format_answer, _is_preserved_outcome


def _it(skeleton="", criteria=None, kind="", columns=None, rows_from=""):
    return IntentSpec(
        objective="o", desired_outcome="OUTCOME_OK", outcome_space=["OUTCOME_OK"],
        constraints=[], success_criteria=criteria or {},
        answer_shape={"msg_skeleton": skeleton, "kind": kind,
                      "columns": columns or [], "rows_from": rows_from},
        required_refs={})


def test_money_reshaped_from_carried_value():
    it = _it(skeleton="EUR {amt}")
    out = format_answer("EUR 12.5", it, it.answer_shape, "", outcome="OUTCOME_OK", value=12.5)
    assert out == "EUR 12.50"


def test_money_reshaped_from_message_when_no_value():
    it = _it(skeleton="EUR {amt}")
    out = format_answer("EUR 0.5", it, it.answer_shape, "", outcome="OUTCOME_OK", value=None)
    assert out == "EUR 0.50"


def test_boolean_prepends_canonical_token():
    it = _it(skeleton="<NO> (SKU: {sku})")
    out = format_answer("SKU: ABC not found", it, it.answer_shape, "", outcome="OUTCOME_OK")
    assert out == "<NO> SKU: ABC not found"


def test_count_substitutes_carried_int():
    it = _it(skeleton="qty=%d")
    out = format_answer("qty=5", it, it.answer_shape, "", outcome="OUTCOME_OK", value=5)
    assert out == "qty=5"
    out2 = format_answer("there are 9", it, it.answer_shape, "", outcome="OUTCOME_OK", value=9)
    assert out2 == "qty=9"


def test_table_renders_tsv_from_rows():
    it = _it(kind="table", columns=["sku", "qty"])
    rows = [{"sku": "A", "qty": 2}, {"sku": "B", "qty": 5}]
    out = format_answer("whatever the model said", it, it.answer_shape, "",
                        outcome="OUTCOME_OK", rows=rows)
    assert out == "sku\tqty\nA\t2\nB\t5"


def test_preserved_outcome_passes_through():
    it = _it(skeleton="EUR {amt}")
    msg = "Access denied: guests cannot view payments."
    assert format_answer(msg, it, it.answer_shape, "",
                         outcome="OUTCOME_DENIED_SECURITY", value=12.5) == msg
    assert format_answer(msg, it, it.answer_shape, "",
                         outcome="OUTCOME_NONE_UNSUPPORTED", value=12.5) == msg


def test_free_shape_passes_through_but_strips_outcome_prefix():
    it = _it(skeleton="The product {name} is in the catalogue.")
    assert format_answer("OUTCOME_OK: Product X is in the catalogue.", it, it.answer_shape, "",
                         outcome="OUTCOME_OK") == "Product X is in the catalogue."


def test_already_exact_left_untouched():
    it = _it(skeleton="EUR {amt}",
             criteria={"OUTCOME_OK": [{"op": "regex_match", "lhs": "$answer.message",
                                       "rhs": r"^EUR \d+\.\d{2}$"}]})
    assert format_answer("EUR 12.50", it, it.answer_shape, "",
                         outcome="OUTCOME_OK", value=12.5) == "EUR 12.50"


def test_failed_format_falls_back_to_original():
    # money shape but an unparseable value AND no number in the message -> keep original.
    it = _it(skeleton="EUR {amt}")
    assert format_answer("amount unavailable", it, it.answer_shape, "",
                         outcome="OUTCOME_OK", value="n/a") == "amount unavailable"


def test_never_raises_on_garbage_inputs():
    it = _it(skeleton="EUR {amt}")
    # answer_shape=None forces an attribute error inside -> swallowed, original returned.
    assert format_answer("EUR 1.5", it, None, "", outcome="OUTCOME_OK", value=1.5) == "EUR 1.5"


def test_is_preserved_outcome():
    assert _is_preserved_outcome("OUTCOME_DENIED_SECURITY") is True
    assert _is_preserved_outcome("OUTCOME_NONE_CLARIFICATION") is True
    assert _is_preserved_outcome("OUTCOME_OK") is False
    assert _is_preserved_outcome("OUTCOME_DIFFERENCE_EXCEEDS") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_format_gate.py -k "format_answer or preserved or free_shape or already_exact_left or fall_back or never_raises" -v`
Expected: FAIL with `ImportError: cannot import name 'format_answer'`.

- [ ] **Step 3: Append the implementation to `agent/format_gate.py`**

```python
def _is_preserved_outcome(outcome: str) -> bool:
    """Negative/terminal outcomes whose message is never reshaped (spec: 'preserve
    non-OK messages'). OK-like custom outcomes (e.g. OUTCOME_DIFFERENCE_EXCEEDS) are
    formatted."""
    o = outcome or ""
    return o.startswith("OUTCOME_NONE") or "DENIED" in o


def _format_for_shape(shape, message, intent, answer_shape, agents_md, value, rows) -> str:
    skel = getattr(answer_shape, "msg_skeleton", "") or ""
    if shape == "money":
        num = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else _extract_eur_number(message)
        return format_eur(num) if num is not None else ""
    if shape == "boolean":
        yes_tok, no_tok = bool_tokens(agents_md, answer_shape)
        return _canonicalize_bool(message, yes_tok, no_tok, skel)
    if shape == "count":
        n = _coerce_int(value, message)
        return _render_count(skel, n) if n is not None else ""
    if shape == "table":
        return _render_table(rows or [], list(getattr(answer_shape, "columns", []) or []))
    if shape == "quote":
        return _render_quote(rows or [], list(getattr(answer_shape, "columns", []) or []))
    return ""


def format_answer(message: str, intent, answer_shape, agents_md, *,
                  outcome: str = "OUTCOME_OK", value=None, rows=None) -> str:
    """Reshape an OK-like answer message into its exact surface contract. Best-effort:
    a preserved (negative) outcome, a free-text shape, an already-exact message, or any
    failure returns the message unchanged. Never raises.

    The 4 positional params are the spec's signature; outcome/value/rows are keyword-only
    additions (outcome gates the passthrough; value/rows are the interpreter-carried typed
    data the gate renders from)."""
    try:
        if _is_preserved_outcome(outcome):
            return message
        cleaned = _strip_outcome_prefix(message)
        if already_exact(cleaned, intent, answer_shape, outcome):
            return cleaned
        shape = detect_shape(intent, answer_shape, outcome, value)
        if shape == "free":
            return cleaned
        out = _format_for_shape(shape, cleaned, intent, answer_shape, agents_md, value, rows)
        return out or cleaned
    except Exception as e:                       # never corrupt the answer
        print(f"[format_gate] skipped ({e}); keeping original message")
        return message
```

- [ ] **Step 4: Run the full gate suite**

Run: `uv run pytest tests/test_format_gate.py -v`
Expected: PASS (all Tasks 2–6 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/format_gate.py tests/test_format_gate.py
git commit -m "feat(format-gate): format_answer orchestrator (dispatch + best-effort guards)"
```

---

## Task 7: interpreter carries the typed value/rows

**Files:**
- Modify: `agent/interpreter.py` — extend `CapturedAnswer` (lines 39–42), add two resolver helpers near the slot helpers (after line 129), populate them in `interpret()` answer assembly (line ~393)
- Test: `tests/test_interpreter_answer_value.py` (new)

**Interfaces:**
- Consumes: `AnswerShape` (Task 1), `predicates.resolve`, `_SLOT_RE` (interpreter).
- Produces: `CapturedAnswer(message, outcome, refs=[], value=None, rows=[])`, `_resolve_answer_value(shape, env) -> Any`, `_resolve_answer_rows(shape, env) -> list`. Task 8 reads `result.captured.value`/`.rows`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_interpreter_answer_value.py`:

```python
from agent.interpreter import _resolve_answer_value, _resolve_answer_rows, CapturedAnswer
from agent.ir_models import AnswerShape


def test_captured_answer_has_value_and_rows_defaults():
    cap = CapturedAnswer(message="m", outcome="OUTCOME_OK", refs=[])
    assert cap.value is None and cap.rows == []


def test_resolve_value_single_numeric_slot():
    shape = AnswerShape(msg_skeleton="EUR {amt}")
    assert _resolve_answer_value(shape, {"amt": 12.5}) == 12.5


def test_resolve_value_numeric_string_slot():
    shape = AnswerShape(msg_skeleton="qty={count}")
    assert _resolve_answer_value(shape, {"count": "9"}) == 9.0


def test_resolve_value_dotted_slot():
    shape = AnswerShape(msg_skeleton="EUR {row0.amt}")
    assert _resolve_answer_value(shape, {"row0": {"amt": "3.5"}}) == 3.5


def test_resolve_value_none_when_multiple_numeric_slots():
    # ambiguous (two numbers) -> None; the gate falls back to message-parse.
    shape = AnswerShape(msg_skeleton="EUR {euros}.{cents}")
    assert _resolve_answer_value(shape, {"euros": 12, "cents": 50}) is None


def test_resolve_value_none_when_non_numeric():
    shape = AnswerShape(msg_skeleton="Product {name}")
    assert _resolve_answer_value(shape, {"name": "Widget"}) is None


def test_resolve_value_never_raises():
    assert _resolve_answer_value(None, {}) is None


def test_resolve_rows_from_declared_binding():
    shape = AnswerShape(kind="table", rows_from="rows")
    rows = [{"a": 1}]
    assert _resolve_answer_rows(shape, {"rows": rows}) == rows


def test_resolve_rows_empty_when_not_declared_or_not_list():
    assert _resolve_answer_rows(AnswerShape(), {"rows": [{"a": 1}]}) == []
    assert _resolve_answer_rows(AnswerShape(rows_from="rows"), {"rows": "notalist"}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interpreter_answer_value.py -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_answer_value'`.

- [ ] **Step 3: Extend `CapturedAnswer`**

Replace `agent/interpreter.py:39-42`:

```python
class CapturedAnswer(BaseModel):
    message: str
    outcome: str
    refs: list[str] = []
    value: Any = None          # primary typed value the format gate renders (money/count)
    rows: list = []            # row list the format gate renders as TSV (table/quote)
```

- [ ] **Step 4: Add the resolver helpers**

In `agent/interpreter.py`, immediately AFTER `_fill_slots` (ends line 129, before `_project_required_refs` at line 132), add:

```python
def _as_number(v):
    """A number for v (int/float kept; numeric string parsed; bool/other -> None)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _resolve_answer_value(shape, env: dict):
    """The single typed value the format gate renders. Resolve each {slot} in the
    answer_shape skeleton against env; return the lone numeric one, else None (ambiguous
    multi-number or non-numeric -> the gate parses the message instead). Never raises."""
    try:
        skel = getattr(shape, "msg_skeleton", "") or ""
        nums = []
        for name in _SLOT_RE.findall(skel):
            n = _as_number(resolve("$" + name, env))
            if n is not None:
                nums.append(n)
        return nums[0] if len(nums) == 1 else None
    except Exception:
        return None


def _resolve_answer_rows(shape, env: dict) -> list:
    """The row list for a table/quote answer: the env binding named by
    answer_shape.rows_from, when it is a list. Empty otherwise. Never raises."""
    try:
        key = getattr(shape, "rows_from", "") or ""
        if not key:
            return []
        v = resolve("$" + key, env)
        return v if isinstance(v, list) else []
    except Exception:
        return []
```

- [ ] **Step 5: Populate value/rows in answer assembly**

In `agent/interpreter.py`, replace the `captured = CapturedAnswer(...)` line in `interpret()` (currently line 393):

```python
    captured = CapturedAnswer(message=message, outcome=outcome, refs=refs)
```

with:

```python
    _shape = getattr(intent, "answer_shape", None)
    captured = CapturedAnswer(
        message=message, outcome=outcome, refs=refs,
        value=_resolve_answer_value(_shape, env),
        rows=_resolve_answer_rows(_shape, env),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_interpreter_answer_value.py -v`
Expected: PASS (9 passed).

- [ ] **Step 7: Run the interpreter regression**

Run: `uv run pytest tests/test_interpreter.py tests/test_grounding.py tests/test_verify.py tests/test_decide.py -q`
Expected: PASS. (`CapturedAnswer` gained two defaulted fields — any test that asserts an exact `model_dump()` of a `CapturedAnswer` would now see `value`/`rows`; if one breaks, update that single assertion to include the new keys — it is a back-compat artifact, not a regression. None is expected in these files.)

- [ ] **Step 8: Commit**

```bash
git add agent/interpreter.py tests/test_interpreter_answer_value.py
git commit -m "feat(interpreter): carry typed answer value/rows for the format gate"
```

---

## Task 8: wire `format_answer` into the pipeline

**Files:**
- Modify: `agent/pipeline.py` — the local import block (lines 283–287) and the decide→verify block (between line 459 and line 460)
- Test: `tests/test_pipeline_format.py` (new)

**Interfaces:**
- Consumes: `format_answer` (Task 6), `result.captured.value`/`.rows` (Task 7), `agents_md_text` (run_pipeline param).
- Produces: the same `run_pipeline(...) -> dict` contract; the accepted `answer_message` is now the canonical surface.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_pipeline_format.py`:

```python
"""Phase 3 integration: format_answer reshapes the OK message BEFORE verify, so a
format-class success_criterion passes and the canonical surface is what vm.answer gets."""
import json
from unittest.mock import MagicMock, patch
import pytest

from agent.pipeline import run_pipeline


def _seq(*items):
    it = iter(items)
    def _next(*a, **kw):
        return next(it)
    return _next


@pytest.fixture(autouse=True)
def _enabled(monkeypatch, tmp_path):
    from agent import learned_store
    monkeypatch.setenv("ECOM_INVESTIGATE_ENABLED", "0")   # skip the ReAct phase in tests
    monkeypatch.setattr(learned_store, "_LEARNED_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "heuristics").mkdir(parents=True)


# A plan that reads a single value via SQL and authors a money message off the skeleton.
_PLAN_MONEY = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 12.5 AS amt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "EUR {row0.amt}", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})
_PLAN_COUNT = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 9 AS cnt"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "there are {row0.cnt}", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})
_PLAN_BOOL = json.dumps({
    "discovery": [{"rpc": "Exec", "args": {"path": "/bin/sql", "args": ["SELECT 'FK' AS sku"]}, "bind": "raw"}],
    "rowsets": [{"from": "raw", "format": "auto_delim", "into": "rows", "columns": []}],
    "compute": [{"prim": "first", "args": ["$rows"], "into": "row0"}],
    "decision": {"branches": [], "default_label": "ok"}, "ops": [],
    "answer": {"ok": {"message": "SKU: {row0.sku} not present", "outcome": "OUTCOME_OK", "refs": []}},
    "custom_extract": [],
})


def test_money_message_reshaped_before_verify():
    intent = json.dumps({
        "objective": "price diff", "desired_outcome": "money", "params": {},
        "outcome_space": ["OUTCOME_OK"], "constraints": [],
        "success_criteria": {"OUTCOME_OK": [
            {"op": "regex_match", "lhs": "$answer.message", "rhs": r"^EUR \d+\.\d{2}$"}]},
        "answer_shape": {"msg_skeleton": "EUR {row0.amt}"}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "amt\n12.5"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_MONEY)):
        m = run_pipeline(vm, instruction="price diff", task_id="t_money",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["outcome"] == "OUTCOME_OK"
    assert m["answer_message"] == "EUR 12.50"


def test_count_message_reshaped_to_skeleton_format():
    intent = json.dumps({
        "objective": "count", "desired_outcome": "count", "params": {},
        "outcome_space": ["OUTCOME_OK"], "constraints": [],
        "success_criteria": {"OUTCOME_OK": [
            {"op": "regex_match", "lhs": "$answer.message", "rhs": r"^qty=\d+$"}]},
        "answer_shape": {"msg_skeleton": "qty=%d"}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "cnt\n9"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_COUNT)):
        m = run_pipeline(vm, instruction="how many", task_id="t_count",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["answer_message"] == "qty=9"


def test_boolean_message_gets_canonical_token():
    intent = json.dumps({
        "objective": "exists", "desired_outcome": "boolean", "params": {},
        "outcome_space": ["OUTCOME_OK"], "constraints": [],
        "success_criteria": {"OUTCOME_OK": [{"op": "nonempty", "lhs": "$answer.message"}]},
        "answer_shape": {"msg_skeleton": "<NO> (SKU: {sku})"}, "required_refs": {},
    })
    vm = MagicMock()
    vm.exec.return_value = {"stdout": "sku\nFK"}
    with patch("agent.pipeline.call_llm_raw", side_effect=_seq(intent, _PLAN_BOOL)):
        m = run_pipeline(vm, instruction="does it exist", task_id="t_bool",
                         agents_md_text="A", facts={"identity": {"kind": "customer"}})
    vm.answer.assert_called_once()
    assert m["answer_message"].startswith("<NO> ")
    assert m["outcome"] == "OUTCOME_OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_format.py -v`
Expected: FAIL — `test_money_message_reshaped_before_verify` fails at `verify` (the message is `"EUR 12.5"`, which the regex `^EUR \d+\.\d{2}$` rejects), so the run ends `OUTCOME_NONE_CLARIFICATION` and `answer_message` is not `"EUR 12.50"`.

- [ ] **Step 3: Add the `format_answer` import**

In `agent/pipeline.py`, extend the local import block inside `run_pipeline` (currently lines 283–287) with:

```python
    from .format_gate import format_answer
```

- [ ] **Step 4: Wire the gate between `decide_outcome` and `verify`**

In `agent/pipeline.py`, locate (currently lines 457–460):

```python
        _decided_outcome, _decided_refs = decide_outcome(intent, result, vm, facts)
        result.captured.outcome = _decided_outcome
        result.captured.refs = _decided_refs
        ok, verr = verify(result, intent)
```

Insert the gate immediately before `verify`:

```python
        _decided_outcome, _decided_refs = decide_outcome(intent, result, vm, facts)
        result.captured.outcome = _decided_outcome
        result.captured.refs = _decided_refs
        # Phase 3: deterministic output-format gate reshapes the OK-like message to its
        # exact surface contract (EUR %d.%02d / <YES>|<NO> / count format / TSV) BEFORE
        # verify, so the format-class success_criteria/grader checks see the canonical
        # string. Best-effort: never raises; negative outcomes and free-text pass through.
        result.captured.message = format_answer(
            result.captured.message, intent, intent.answer_shape, agents_md_text,
            outcome=result.captured.outcome,
            value=result.captured.value, rows=result.captured.rows)
        ok, verr = verify(result, intent)
```

- [ ] **Step 5: Run the new integration tests**

Run: `uv run pytest tests/test_pipeline_format.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the pipeline regression suite**

Run: `uv run pytest tests/test_pipeline_interpreted.py tests/test_pipeline_decide.py tests/test_pipeline_grounding.py tests/test_pipeline_investigate.py tests/test_pipeline_v2.py -q`
Expected: PASS — happy-path, decide, grounding, and investigate integration tests are unaffected (the gate passes through `free`-shape and already-exact messages, and never reshapes negative outcomes).

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline.py tests/test_pipeline_format.py
git commit -m "feat(pipeline): apply format_answer gate before verify"
```

---

## Task 9: full regression, docs, and PR

**Files:**
- Read-only: whole `tests/` tree
- Modify: `docs/wiki/` pages for `agent/format_gate.py`, `agent/interpreter.py`, `agent/pipeline.py`, `agent/ir_models.py`; `CLAUDE.md` (repo root) + `agent/CLAUDE.md` (architecture flow)

**Interfaces:** none (verification + documentation only).

- [ ] **Step 1: Run the full test suite**

Run: `uv run python -m pytest tests/ -q`
Expected: PASS, except the one KNOWN pre-existing red `tests/test_corpus_replay.py::test_t09_replay_matches_known_good` (stale parity fixture — see project memory `t09 corpus stale`; NOT a regression). If ANY other test fails, fix it before continuing — do not mark this task complete with a new red. Pay special attention to any test asserting an exact `CapturedAnswer.model_dump()` (Task 7 added `value`/`rows` keys) — update that single assertion if it surfaces.

- [ ] **Step 2: Update the architecture sections**

Edit `CLAUDE.md` (repo root): in the per-task LOOP description, after the `decide-outcome` step and before `verify`, add one sentence:

```markdown
     - **format-gate** — `format_gate.format_answer(...)` (no LLM, best-effort) reshapes
       `result.captured.message` into the exact surface contract (`EUR %d.%02d` /
       `<YES>`/`<NO>` / count format / TSV) from `intent.answer_shape` + the
       interpreter-carried typed value, BEFORE verify. Negative outcomes and free-text
       pass through unchanged (`agent/format_gate.py`).
```

Edit `agent/CLAUDE.md`: in the LOOP section, after the `decide-outcome` bullet and before the `verify` bullet, add:

```markdown
   - **format-gate** (`format_gate.py:format_answer(message, intent, answer_shape, agents_md,
     *, outcome, value, rows)`) — no LLM, best-effort. Overwrites `result.captured.message`
     with the exact surface contract per `intent.answer_shape` (money → `format_eur`;
     boolean → `<YES>`/`<NO>` or `/AGENTS.MD` tokens; count → skeleton format; table/quote →
     TSV). Runs BEFORE verify so the format-class success_criteria regex passes on the
     canonical string. Non-OK outcomes and free-text shapes pass through unchanged.
```

Also extend the `ir_models.py` model list in `agent/CLAUDE.md` (the `AnswerShape` mention) to note the new `kind`/`columns`/`rows_from` fields, and the `interpreter.py` `CapturedAnswer` mention to note `value`/`rows`. One clause each; match surrounding style.

- [ ] **Step 3: Ingest the changed sources into the wiki**

Invoke the `iwiki:iwiki-ingest` skill (NOT a guessed engine subcommand) for each changed source — these alter behavior, so `CLAUDE.md` mandates the doc update:

```text
iwiki:iwiki-ingest agent/format_gate.py
iwiki:iwiki-ingest agent/interpreter.py
iwiki:iwiki-ingest agent/pipeline.py
iwiki:iwiki-ingest agent/ir_models.py
```

The new `format_gate.py` page documents the deterministic output-format gate; the others get the Phase-3 deltas (`CapturedAnswer.value/rows`, the gate wiring, `AnswerShape` fields).

- [ ] **Step 4: Verify the wiki pages exist and changed (measurable DoD)**

Run:

```bash
test -f docs/wiki/format_gate.md && echo "format_gate page OK" || echo "MISSING"
git status --porcelain docs/wiki/ | grep -E 'format_gate|interpreter|pipeline|ir_models'
```

Expected: `docs/wiki/format_gate.md` exists, and `git status` lists the four pages as added/modified (a non-empty diff confirms each ingest ran). An empty diff for a changed source means the ingest did not run — re-invoke before continuing.

- [ ] **Step 5: Lint the wiki graph**

Invoke the `/iwiki-lint` skill.
Expected: no broken `[[refs]]`, no orphan or stale pages introduced by the new `format_gate` page.

- [ ] **Step 6: Commit**

```bash
git add docs/wiki/ CLAUDE.md agent/CLAUDE.md
git commit -m "docs: Phase 3 deterministic output-format gate (wiki + architecture)"
```

- [ ] **Step 7: Open the PR into `determinism`**

```bash
git push -u origin dev/phase3-format-gate
gh pr create --base determinism --title "Phase 3: deterministic output-format gate" \
  --body "Implements docs/superpowers/specs/2026-06-22-phase3-deterministic-format-gate-design.md. answer.message surface (EUR %d.%02d / <YES>|<NO> / count format / TSV) shaped in code (agent/format_gate.py) from intent.answer_shape + the interpreter-carried typed value, applied after decide_outcome and before verify."
```

---

## Manual validation (after the suite is green)

The unit + integration tests prove the mechanism. Behavioral confirmation against the motivating tasks requires a benchmark run (out of band, ~costly) — per the spec's "Success criteria":

- Run the motivating subset `{the EUR-regex task, t04, t06, t07, t08}` and confirm the format-class feedback disappears: no `verify fail: ... regex_match ... ^EUR` and no grader `Answer should contain '<YES>'`/`'<NO>'`.
- Confirm no regression on tasks whose message already matched — especially the prose-with-EUR tasks (t51/t52/t53), which must remain untouched (they classify as `free`), and any count tasks (t09–t20, t33, t45, t49), which must keep their existing surface.
- Where a task still mismatches because INTENT did not declare a rich enough `answer_shape` (e.g. a `kind`/`columns` for a tabular answer), that is the **LEARN/INTENT channel's job** — feed the gap back through LEARN, NOT through a `data/prompts/` patch or a code special-case.

This is a measurement step, not a code gate — record results in a run report; do not gate the merge on a full benchmark inside the plan.

---

## Self-Review

**Spec coverage:**
- Typed formatters (money/boolean/count/table/quote) → Tasks 2 (`format_eur`), 3 (boolean), 4 (count/table/quote). Money/boolean/count + table/quote all implemented per the user's "all five" decision. ✓
- count format source (spec finding F-001) = `answer_shape.msg_skeleton`, no other source → Task 4 `_render_count`. ✓
- table/quote untethered in spec (finding F-003) → built as declaration-only via `answer_shape.kind`/`columns`/`rows_from`, fully unit-tested (Tasks 1, 4, 6); dormant until INTENT/LEARN declares a `kind`. ✓
- Gate guards: preserve non-OK (`_is_preserved_outcome`), already-exact short-circuit (`already_exact`), normalise-only with original-message fallback + `OUTCOME_*` prefix strip → Tasks 5, 6. ✓
- AGENTS.MD tokens honoured → Task 3 `bool_tokens`. ✓
- `format_gate.py` with `format_answer`, `format_eur`, `bool_tokens`, `already_exact` → Tasks 2–6. ✓
- `pipeline.py` applies the gate before `vm.answer` (specifically before verify, the last gate) → Task 8. ✓
- `interpreter.py` carries the typed value alongside the message slot → Task 7 (`CapturedAnswer.value`/`rows`, `_resolve_answer_value`/`_resolve_answer_rows`). ✓
- Error handling (best-effort, never raises, original message on failure) → Task 6 try/except + every helper returns `""`/`None` on failure. ✓
- Testing (unit, integration, regression) → Tasks 2–7 unit, Task 8 integration, Task 9 full-suite + measurement. ✓
- Risk: wrong-shape inference → money fires only on bare-EUR skeleton / anchored regex (Task 5), boolean is additive (Task 3), free passes through; locale/rounding → `format_eur` half-up, unit-tested (Task 2). ✓
- Deviation noted: `ir_models.py` is added to "Components touched" (spec listed only format_gate/pipeline/interpreter); the spec's "declares a typed shape" implies the `AnswerShape` field. No `data/prompts/` patch (inference covers all current intents; explicit `kind` flows via INTENT/LEARN).

**Placeholder scan:** every code step contains complete code; no TBD/TODO/"handle edge cases". ✓

**Type consistency:** `format_answer(message, intent, answer_shape, agents_md, *, outcome="OUTCOME_OK", value=None, rows=None)` used identically in Tasks 6 and 8. `format_eur(value)`, `bool_tokens(agents_md, answer_shape)`, `_canonicalize_bool(message, yes_tok, no_tok, skeleton)`, `detect_shape(intent, answer_shape, outcome, value=None)`, `already_exact(message, intent, answer_shape, outcome)`, `_render_count(skeleton, n)`, `_render_table/_render_quote(rows, columns)`, `_coerce_int(value, message)`, `_extract_int/_extract_eur_number(text)` consistent across Tasks 2–6. `_resolve_answer_value(shape, env)`/`_resolve_answer_rows(shape, env)` and `CapturedAnswer(..., value=None, rows=[])` consistent across Tasks 7–8. `AnswerShape(msg_skeleton, kind, columns, rows_from)` from Task 1 consumed by Tasks 5/6/7. ✓
