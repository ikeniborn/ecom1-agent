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
| `identity` | Output of `/bin/id` — caller role, store, issuer; includes a structural `kind`: `customer` \| `employee` \| `guest` |
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
  "success_criteria": {
    "OUTCOME_OK": [
      {"op": "<leaf or bool op>", "lhs": "$<ref>", "rhs": "<value>"}
    ]
  },
  "answer_shape": {
    "msg_skeleton": "<human-readable template, e.g. 'Processed {count} items'>"
  },
  "required_refs": {
    "OUTCOME_OK": [
      {"kind": "policy_doc", "path": "/docs/<governing-doc>.md"},
      {"kind": "record_path", "source": "$<row>.record_path"}
    ]
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
- `required_refs` — keyed by outcome. For each outcome the answer can take, list the
  evidence the grader requires: a `policy_doc` (literal `/docs/...md` `path` taken from
  THIS run's `docs_inventory`/`policies` — the governing rule/count/procedure the
  decision rests on) and/or a `record_path` (a `$ref` `source` bound at runtime to the
  reported row's path). Declare ONLY load-bearing refs (reading a doc ≠ obligation to
  cite it). Exactly one of `path`/`source` per RefSpec, matching its `kind`.
- `success_criteria` — a map keyed by outcome (same shape as `required_refs`).
  List STRUCTURAL / grounding checks only per outcome (e.g. `count ge 0`, a
  nonempty bound id). A negative outcome (e.g. `OUTCOME_NONE_UNSUPPORTED`)
  typically needs no criteria — it is gated by `outcome_space`. Do NOT bake a SQL
  recipe, join, `kind_id`, or `city` here — that is PLAN's job (HOW).

### Security scope — role-aware customer-ownership deny

`facts.identity.kind` is one of `customer`, `employee`, `guest` (structural,
derived from the `/bin/id` id-shape — not a role-name list). The `security.md`
customer-ownership clause binds **customers** acting on their own account — NOT
an employee operational read or action.

Apply a customer-ownership `deny_when` **only when** the caller is a customer:

```json
{"op":"and","args":[
  {"op":"eq","lhs":"$_facts.identity.kind","rhs":"customer"},
  {"op":"ne","lhs":"$record.customer_id","rhs":"$_facts.identity.customer_id"}]}
```

Do NOT emit an owner-mismatch deny for an `employee`/operational identity — an
employee reading or acting on a record they do not "own" is not a customer-scope
violation. Customer-only actions (account recovery, email change per the doc)
remain a separate class. Ground this in the `security.md` scope + `facts.identity`,
never a hardcoded role or id.

## IDD vs SDD (what belongs here)

INTENT is the IDD layer: WHAT must hold and WHY — `objective`, `outcome_space`,
`constraints`, `required_refs` (cite the governing doc + the reported record),
`success_criteria` (structural/grounding). INTENT NEVER specifies HOW: no SQL, joins,
column names, `kind_id`, or `city`. PLAN (the SDD layer) reads the eligibility rule
from `facts.policies` and builds the rule-correct SQL.

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
