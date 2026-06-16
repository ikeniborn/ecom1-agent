# ecom1-agent — lat.md Index

ecom1-agent is an LLM pipeline agent for an e-commerce benchmark. It receives natural language tasks, runs a deterministic Plan-IR interpreter loop against a remote VM, and submits one structured answer via Connect-RPC.

## Sections

Links to all documentation sections in this knowledge base.

- [[architecture]] — System overview, IR-only execution flow, component responsibilities
- [[pipeline-phases]] — Per-phase behavior: INTENT, PLAN, lint, interpret, verify, LEARN
- [[data-models]] — Pydantic models: IntentSpec, PlanIR, LearnConsolidateOutput, AnswerOutput
- [[prephase]] — Best-effort facts gathered before the loop (schema, samples, identity, docs)
- [[security-lint]] — Security-first lint, verify invariants (I1/I3), anti-loop plan signature
- [[vm-protocol]] — ECOM VM operations, result extraction, outcome codes
- [[constraints]] — Load-bearing invariants: JSON extraction priority, frozen INTENT, single answer
