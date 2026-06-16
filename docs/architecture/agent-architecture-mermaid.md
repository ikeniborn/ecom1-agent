# Agent Architecture — Mermaid views

Clean, auto-routed companion to `agent-architecture.excalidraw` (same four diagrams +
legend). Mermaid's layered (dagre) layout removes the manual-placement crossings of the
Excalidraw canvas, so these blocks are the readable reference; the `.excalidraw` stays the
editable-in-app artifact. Renders on GitHub, Obsidian, and `mermaid.live`.

> **IR-only pipeline.** The legacy DESIGN→CODEGEN loop and the `INTERPRETER_ENABLED`
> fork were removed; `run_pipeline` is a single deterministic-interpreter path.

Shape/colour vocabulary (shared by every diagram):

| Glyph | Mermaid syntax | Meaning |
|-------|----------------|---------|
| Blue rectangle | `["…"]:::llm` | LLM call |
| Grey rectangle | `["…"]:::gate` | Deterministic step / gate |
| Green cylinder | `[("…")]:::store` | Storage (yaml / json / atoms) |
| Yellow diamond | `{"…"}:::branch` | Branch / condition |
| Red stadium | `(["…"]):::terminal` | Terminal outcome |
| `-->` | solid link | Control flow |
| `-.->` | dashed link | Feedback / learning |

## Diagram 1 — End-to-end flow (harness → pipeline)

```mermaid
flowchart TD
  classDef llm fill:#a5d8ff,stroke:#1e1e1e,color:#1e1e1e
  classDef gate fill:#e9ecef,stroke:#1e1e1e,color:#1e1e1e

  start["main.py: StartRun"]:::gate
  trial["StartTrial → run_agent"]:::gate
  open["open VM + read /AGENTS.MD"]:::gate
  subgraph prephase["gather_prephase_facts"]
    direction LR
    schema["schema discovery"]:::gate
    samples["sample rows"]:::gate
    docs["docs inventory"]:::gate
    deepread["prephase_deep_read"]:::gate
  end
  pipeline["run_pipeline (IR-only)"]:::gate
  endtrial["EndTrial (per trial)"]:::gate
  submit["SubmitRun (after pool)"]:::gate
  learn["learn_from_grader"]:::llm

  start --> trial --> open --> prephase --> pipeline
  pipeline --> endtrial --> submit --> learn
  learn -. "TRAIN_MAX_CYCLES" .-> start
```

## Diagram 2 — IR pipeline cycle + gates

```mermaid
flowchart TD
  classDef llm fill:#a5d8ff,stroke:#1e1e1e,color:#1e1e1e
  classDef gate fill:#e9ecef,stroke:#1e1e1e,color:#1e1e1e
  classDef branch fill:#ffec99,stroke:#1e1e1e,color:#1e1e1e
  classDef terminal fill:#ffc9c9,stroke:#1e1e1e,color:#1e1e1e

  intent["INTENT — run_intent (frozen, retried)"]:::llm
  plan["PLAN — run_plan (+learn_ctx +atoms +observed)"]:::llm
  lint["lint_security_first"]:::gate
  ident{"identical plan?"}:::branch
  interpret["interpret() — deterministic, no LLM"]:::gate
  verify["verify() — invariants + criteria"]:::gate
  answer["vm.answer once (+persist +distill)"]:::gate
  learn["_ilearn (LEARN between cycles)"]:::llm
  ok(["OUTCOME_OK"]):::terminal
  clar(["OUTCOME_NONE_CLARIFICATION"]):::terminal
  unsup(["OUTCOME_NONE_UNSUPPORTED"]):::terminal
  deny(["OUTCOME_DENIED_SECURITY"]):::terminal

  intent --> plan --> lint --> ident
  ident -- "new" --> interpret --> verify
  ident -- "identical" --> clar
  verify -- "ok" --> answer
  answer --> ok & clar & unsup & deny
  lint -. "plan/lint err" .-> learn
  interpret -. "interpret err" .-> learn
  verify -. "verify fail" .-> learn
  learn -. "re-plan next cycle" .-> plan
  learn -. "cycles exhausted" .-> clar
```

## Diagram 3 — `interpret()` + `verify()` internals

```mermaid
flowchart TD
  classDef gate fill:#e9ecef,stroke:#1e1e1e,color:#1e1e1e
  classDef terminal fill:#ffc9c9,stroke:#1e1e1e,color:#1e1e1e

  plan["PlanIR (ops, steps, answer)"]:::gate
  resolve["resolve columns (ColResolve)"]:::gate
  steps["run steps + RPC ops (RowSet / ComputeStep)"]:::gate
  classify["classify outcome (OutcomeFromExit)"]:::gate
  project["project required_refs[outcome]"]:::gate
  captured["CapturedAnswer (message, outcome, refs)"]:::gate
  verify["verify() — I1 refs / I3 security / criteria"]:::gate
  ok(["ok → vm.answer"]):::terminal
  refuse(["_refuse → InterpretError"]):::terminal

  plan --> resolve --> steps --> classify --> project --> captured --> verify
  verify -- "pass" --> ok
  verify -- "fail" --> refuse
  project -. "unresolved ref" .-> refuse
```

## Diagram 4 — Cross-cutting subsystems

```mermaid
flowchart TD
  classDef llm fill:#a5d8ff,stroke:#1e1e1e,color:#1e1e1e
  classDef gate fill:#e9ecef,stroke:#1e1e1e,color:#1e1e1e
  classDef store fill:#b2f2bb,stroke:#1e1e1e,color:#1e1e1e

  learn["LEARN _ilearn (pipeline.py)"]:::llm
  oracle["oracle.retrieve + distill"]:::llm
  route["LLM routing (llm.py)"]:::gate
  yaml[("data/learned/{tid}.yaml")]:::store
  atoms[("data/oracle/atoms.yaml")]:::store
  trace[("trace JSONL (trace.py)")]:::store
  plan["PLAN / interpret (run_pipeline)"]:::gate

  learn --> yaml
  oracle --> atoms
  route --> trace
  yaml -. "active rules" .-> plan
  atoms -. "K atoms" .-> plan
  route -- "tier + fallback" --> plan
  plan -. "on success: distill→validate→promote" .-> atoms
```

## Legend

```mermaid
flowchart LR
  classDef llm fill:#a5d8ff,stroke:#1e1e1e,color:#1e1e1e
  classDef gate fill:#e9ecef,stroke:#1e1e1e,color:#1e1e1e
  classDef store fill:#b2f2bb,stroke:#1e1e1e,color:#1e1e1e
  classDef branch fill:#ffec99,stroke:#1e1e1e,color:#1e1e1e
  classDef terminal fill:#ffc9c9,stroke:#1e1e1e,color:#1e1e1e

  l["LLM call"]:::llm
  g["Deterministic step / gate"]:::gate
  s[("Storage — yaml / json / atoms")]:::store
  b{"Branch / condition"}:::branch
  t(["Terminal outcome"]):::terminal
  c1["control flow"] --> c2["( solid arrow )"]
  f1["feedback / learning"] -.-> f2["( dashed arrow )"]
```
