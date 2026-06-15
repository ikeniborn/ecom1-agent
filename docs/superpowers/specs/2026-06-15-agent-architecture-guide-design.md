---
review:
  spec_hash: efdb8ce5d2e45fc4
  last_run: 2026-06-15
  phases:
    structure:    { status: passed }
    coverage:     { status: passed }
    clarity:      { status: passed }
    consistency:  { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: INFO
      section: Production approach
      section_hash: 76a2a7b229458a8f
      text: >-
        Layout quality ("красиво" / "clean") has no measurable DoD. Inherently
        subjective; structural validity is covered by the Verification section.
      verdict: fixed
      verdict_at: 2026-06-15
chain:
  intent: null
---

# Agent Architecture Guide — Design Spec

**Date:** 2026-06-15
**Topic:** Visual architecture guide for the ecom1-agent pipeline, authored in Excalidraw format.
**Status:** Approved — ready for implementation plan.

## Goal

Produce a dense, accurate visual reference of the agent's runtime architecture for the
project's own developers (who already know the domain). The deliverable is an Excalidraw
canvas plus a Markdown companion guide. Both live under `docs/architecture/`.

Non-goals: onboarding-level explanation, external-stakeholder polish, exhaustive
per-function coverage. Focus is correctness of the control/data flow and pointers into the code.

## Deliverables

| File | Purpose |
|------|---------|
| `docs/architecture/agent-architecture.excalidraw` | One canvas, four diagram regions (frames) + a legend strip |
| `docs/architecture/agent-architecture-guide.md` | Markdown guide: one section per diagram, `file:line` references |
| `tools/gen_excalidraw.py` | Generator that emits the `.excalidraw` JSON deterministically (re-runnable when architecture changes) |

The canvas is a single Excalidraw file. The four diagrams are laid out as four named
`frame` regions stacked vertically, with a legend region. The generator owns all coordinate
math and arrow bindings so layout stays clean and reproducible.

## Production approach

Hand-author the `.excalidraw` JSON via a Python generator script (`tools/gen_excalidraw.py`).

Rationale: full control over layout (against the measurable layout rules in the
Verification section), deterministic output, no browser/node
tooling (the project avoids browser tools), and the resulting file remains editable in
excalidraw.app afterward. Rejected alternatives: `@excalidraw/mermaid-to-excalidraw`
(needs node/jsdom, rougher auto-layout, less control) and mermaid-in-markdown-only
(demotes the Excalidraw deliverable the user asked for).

The generator must emit schema-valid Excalidraw: each element has a unique `id`,
arrows carry `startBinding`/`endBinding` referencing element ids, and the top-level
document has `type: "excalidraw"`, `version: 2`, `elements`, and `appState`.

## Diagrams

### Diagram 1 — End-to-end flow (harness → pipeline)

Chain: `main.py` harness `[StartRun → trials-loop → SubmitRun → EndTrial]`, with the outer
`TRAIN_MAX_CYCLES` training loop drawn as a dashed feedback edge through `learn_from_grader`
→ `orchestrator.run_agent` `[open VM, read /AGENTS.MD, gather_prephase_facts]`
→ `pipeline.run_pipeline` → branch split on `INTERPRETER_ENABLED`.

`gather_prephase_facts` is expanded into its sub-steps: schema discovery, sample rows,
docs inventory, and learned `prephase_deep_read`.

### Diagram 2 — Pipeline loop + gates (legacy, default branch)

`DESIGN` (1 LLM call, frozen for the run) → `outcome_override?` (early exit) → **LOOP**
`cycle = 1..MAX_STEPS`: `CODEGEN` (LLM) → `AST lint` → `check_retry_loop` → `fidelity gate`
(subprocess) → pass → break. Then `ANSWER` one-shot via the `_AnswerGuard` proxy → terminal
outcomes: `OUTCOME_OK` / `OUTCOME_NONE_CLARIFICATION` / `OUTCOME_DENIED_SECURITY`.

Dashed feedback edges run from each gate → `LEARN+CONSOLIDATE` → next cycle.

### Diagram 3 — Deterministic interpreter (INTERPRETER_ENABLED branch)

Plan-IR path: `ir_models.PlanIR` (built from DESIGN/plan) → `lint_security_first`
→ `interpret()` (deterministic, no LLM inside the loop) → `CapturedAnswer` → outcome.
Show the `prephase_deep_read` input and contrast with the legacy branch (no free-form
CODEGEN retry loop).

### Diagram 4 — Cross-cutting subsystems

Three blocks with edges into the pipeline:
- **LEARN / learned_store** → `data/learned/{tid}.yaml` (active rules + `prephase_deep_read` + `last_run`)
- **Knowledge oracle** (`oracle.py`): cosine top-N → LLM re-rank → K atoms → injected into CODEGEN; bank at `data/oracle/atoms.yaml`
- **LLM routing** (`llm.py`): tiers anthropic / openrouter / ollama / cc + `MODEL_FALLBACK`, driven by `models.json`; trace JSONL via `trace.py`

## Legend (shared shape/color vocabulary across all diagrams)

| Shape / color | Meaning |
|---------------|---------|
| Blue rectangle | LLM call (DESIGN / CODEGEN / LEARN / oracle re-rank) |
| Grey rectangle | Deterministic step / gate (AST lint, retry-guard, fidelity, interpret) |
| Green cylinder | Storage (yaml / json / atoms) |
| Yellow diamond | Branch / condition |
| Red rounded rectangle | Terminal outcome |
| Solid arrow | Control flow |
| Dashed arrow | Feedback / learning (LEARN, training loop) |

## Markdown guide structure

1. Overview (one paragraph + LLM-call budget 1 / 2 / 7).
2. One section per diagram: what it shows + key `file:line` references.
3. Legend (same table as above).
4. "Where to change what" — a short module → responsibility map.

Tone: dense, reference-style; technical terms used without expansion.

## Verification

- `tools/gen_excalidraw.py` runs without error and writes the `.excalidraw` file.
- The emitted JSON parses as valid JSON and opens in excalidraw.app without errors
  (schema check: `type`, `version`, `elements[]` with unique ids, valid arrow bindings).
- Every `file:line` reference in the Markdown guide resolves to a real location at write time.
- All four diagrams + legend are present on the canvas.
- Layout quality is measurable (not subjective):
  - no two element bounding boxes overlap within a frame;
  - adjacent boxes keep a gap of at least 40px and snap to a shared grid step;
  - every diagram's elements fit inside their frame (no element extends past frame bounds);
  - an arrow crosses a frame boundary only when it is an explicitly labeled cross-diagram reference.
