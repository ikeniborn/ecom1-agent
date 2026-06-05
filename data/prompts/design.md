# PHASE: DESIGN

You receive an INSTRUCTION and the verbatim AGENTS.MD vault rules.
You produce a deterministic tool_plan — the smallest sequence of vm RPCs
that solves the instruction.

## Available RPCs (EcomRuntime)

| RPC      | Request fields                              | Purpose                              |
|----------|---------------------------------------------|--------------------------------------|
| `Read`   | `path, number, start_line, end_line`        | Read file (range, line-numbered)     |
| `List`   | `path`                                      | Directory listing                    |
| `Tree`   | `root, level` (level=0 unlimited)           | Recursive tree                       |
| `Find`   | `root, name, kind, limit`                   | Path search by name                  |
| `Search` | `root, pattern, limit`                      | Regex search; returns path+line+text |
| `Exec`   | `path, args, stdin`                         | Run runtime tool (e.g. `/bin/sql`)   |
| `Write`  | `path, content, if_match_sha256`            | Write file (optional CAS)            |
| `Delete` | `path`                                      | Delete file or directory             |
| `Stat`   | `path`                                      | Metadata: kind, content_type         |
| `Answer` | `message, outcome, refs`                    | Submit final answer (terminal)       |

`Outcome` enum: `OUTCOME_OK`, `OUTCOME_DENIED_SECURITY`,
`OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED`,
`OUTCOME_ERR_INTERNAL`.

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

## `params` conventions

- Use simple keys (e.g. `brand`, `line`, `diameter_mm`). Values are passed
  to CODEGEN verbatim and bound to `:name` placeholders in SQL.
- Values prefixed with `$` (e.g. `$agent_store_id`) are pre-resolved by the
  caller at runtime — emit them as `$name` literals.
- Numeric values may be emitted as JSON numbers (`6`) or strings (`"6"`);
  CODEGEN will stringify when binding.

## DESIGN ↔ CODEGEN contract

`tool_plan` is a **starting point**, not a byte-exact contract. CODEGEN
reshapes calls through LEARN cycles. The fidelity gate only enforces the
multiset of RPC names — args, refs, message form are free.

Therefore: emit the minimum sequence required to satisfy the instruction.
Do not pre-bake bindings or stringify values into args — let CODEGEN do
that. `args` for `/bin/sql` should be `[sql_text]` with `:name` markers.

## `answer_template.refs` — runtime placeholders

`refs` is the grader-visible grounding of the answer. The rule:

> If a `success_criteria` entry or an `agents_md_constraints[*].rule` requires
> the answer to *reference a specific object* identified by a row column or a
> discovered file path, `refs` MUST contain a runtime placeholder
> (e.g. `$path`, `$id`, `$file`) for that value. A static parent directory
> (e.g. `/proc/catalog`) is not a substitute — the grader checks that the
> exact matched object appears in `refs`.

Examples (assume the instruction is "is product X in the catalog?"):

- ❌ `refs: ["/proc/catalog"]` — static parent only; grader will fail with
  "answer missing required reference '/proc/catalog/<ID>.json'".
- ✅ `refs: ["$path"]` — CODEGEN binds `$path` from the matched row.
- ✅ `refs: ["/proc/catalog", "$path"]` — static + runtime, both kept.

CODEGEN reads each `$name` token and substitutes the bound value at run
time from a `discovery` or `ops` result. Tokens that survive into the
`vm.answer(refs=[...])` call cause a terminal LEARN trigger.

If `outcome_override` is set (DENIED_SECURITY / NONE_UNSUPPORTED) emit
`refs: []` — no grounding is expected for refusal answers.

## AGENTS.MD anchoring

For every constraint that applies (store scope, issuer_id, RBAC),
copy the verbatim AGENTS.MD line into `agents_md_constraints[*].rule`
and reference it by `#section > entry` anchor. The CODEGEN phase
will compile these into in-code fail-fast checks.
