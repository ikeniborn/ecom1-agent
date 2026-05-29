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
