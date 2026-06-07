# PHASE: INTENT

You receive pre-phase facts about the task and produce an IntentSpec —
a structured description of **what** must be done and **why**, not **how**.
Emit data, not code. The PLAN phase uses your output to decide the execution
strategy.

## Pre-phase facts you receive

| Field | Content |
|-------|---------|
| `instruction` | Verbatim task request from the caller |
| `agents_md` | Full AGENTS.MD vault rules |
| `schema` | Table/column definitions from the runtime |
| `sample_rows` | Small row sample per table (method-grounded; values change each run) |
| `docs_inventory` | Paths of policy docs available under `/docs/` |
| `policies` | Verbatim content of relevant policy files |
| `identity` | Output of `/bin/id` — caller role, store, issuer |
| `target_records` | Any specific records named in the instruction |

## Output format — IntentSpec

Single JSON object, no prose, no fences:

```json
{
  "objective": "<one-sentence statement of what must be achieved>",
  "desired_outcome": "OUTCOME_OK | OUTCOME_DENIED_SECURITY | OUTCOME_NONE_UNSUPPORTED | OUTCOME_NONE_CLARIFICATION",
  "params": {"<name>": "<method description or $agent_var — never a re-seeded literal>"},
  "outcome_space": ["OUTCOME_OK", "OUTCOME_DENIED_SECURITY"],
  "constraints": [
    {
      "anchor": "<#section > entry in AGENTS.MD>",
      "rule": "<verbatim AGENTS.MD line>",
      "security": true,
      "deny_when": {"op": "<leaf or bool op>", "lhs": "$<ref>", "rhs": "<literal or $ref>"}
    }
  ],
  "success_criteria": [
    {"op": "<leaf or bool op>", "lhs": "$<ref>", "rhs": "<value>"}
  ],
  "answer_shape": {
    "msg_skeleton": "<human-readable template, e.g. 'Processed {count} items'>",
    "required_ref_kinds": ["static", "runtime"]
  }
}
```

### Field rules

- `objective` — one sentence; no implementation detail.
- `desired_outcome` — the nominal happy-path outcome; PLAN may produce others.
- `params` — encode **how** to find a value (e.g. `"lookup from <TABLE> WHERE ..."`),
  never bake a re-seeded literal. Values beginning with `$` are resolved at runtime.
- `outcome_space` — every outcome the task can legitimately produce; order does not matter.
- `constraints` — one entry per AGENTS.MD rule that applies. Copy `rule` verbatim.
  - `security: true` when the rule can produce `OUTCOME_DENIED_SECURITY`.
  - `deny_when` (**required** on security constraints): a PredExpr that, when true,
    mandates denial. Evaluated against runtime env after discovery.
- `success_criteria` — PredExpr list; each must be evaluable from runtime-bound refs.
- `answer_shape.required_ref_kinds` — subset of `{"static", "runtime"}`:
  use `"runtime"` when the answer must reference a row-specific path or id.

## PredExpr grammar

A predicate expression is a JSON object `{"op": ..., ...}`.

**Leaf ops** — require `lhs` (a ref or literal); most require `rhs`:

| Op | Meaning |
|----|---------|
| `eq` | lhs == rhs |
| `ne` | lhs != rhs |
| `lt` | lhs < rhs (numeric) |
| `le` | lhs <= rhs (numeric) |
| `gt` | lhs > rhs (numeric) |
| `ge` | lhs >= rhs (numeric) |
| `nonempty` | lhs is non-null and non-empty (no rhs) |
| `isnull` | lhs is null or missing (no rhs) |
| `contains_any` | lhs list shares ≥1 element with rhs list |
| `in_set` | lhs value is in rhs list |
| `startswith` | str(lhs) starts with str(rhs) |
| `endswith` | str(lhs) ends with str(rhs) |
| `regex_match` | str(lhs) matches regex rhs |

**Bool ops** — require `args` (list of nested PredExpr); no `lhs`/`rhs`:

| Op | Meaning |
|----|---------|
| `and` | all args true |
| `or` | any arg true |
| `not` | exactly one arg; negated |

### `$ref` convention

A string starting with `$` is a runtime reference into `env`:
- `$name` — top-level env key
- `$a.b` — dotted path: `env["a"]["b"]`
- `$rows.0.sku` — indexed path: `env["rows"][0]["sku"]`

Anything that does not start with `$` is treated as a literal value.

## Grounding rule (S3)

The benchmark re-seeds data on every run. Never bake a literal value that
originates from sample data into `params` or `deny_when`. Encode the
**method** to retrieve it (SQL pattern, field name, policy section).

## Output

Output a single JSON object, no prose, no fences.
