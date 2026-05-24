# ecom1-agent — lat.md Index

ecom1-agent is an LLM pipeline agent for an e-commerce benchmark. It receives natural language tasks, runs a multi-phase reasoning loop against a remote VM, and submits structured answers via Connect-RPC.

## Sections

Links to all documentation sections in this knowledge base.

- [[architecture]] — System overview, execution flow, component responsibilities
- [[pipeline-phases]] — Per-phase behavior: IDD, SDD, PLAN, EXECUTE, BATCH, ANSWER, LEARN, CONSOLIDATE
- [[data-models]] — Pydantic output models for every pipeline phase and learned YAML format
- [[prompt-assembly]] — How `unified_context` is built from learned rules, vault, schema, and agent context
- [[schema-validation]] — Schema gate checks and SQL security guards
- [[vm-protocol]] — ECOM VM operations, result extraction, action type routing, outcome codes
- [[constraints]] — Load-bearing invariants: JSON extraction priority, anti-loop guard, store filter injection, rule validation
