# PHASE: CODEGEN

You receive a TOOL_PLAN (JSON), optional LEARNED_RULES, and an optional PREVIOUS_ERROR.
You produce a single self-contained Python module that solves the task by
calling the VM exactly as TOOL_PLAN describes.

## Output format

Single JSON object — no prose, no markdown fences:

```json
{"script_code": "def run(vm, params):\n    ...\n"}
```

## Script requirements

- Top-level `def run(vm, params)`.
- `vm` exposes: `read`, `list`, `tree`, `find`, `search`, `exec`, `write`, `delete`, `stat`, `answer`.
  All take keyword args matching `proto-api-reference.md`.
- Execute every `discovery` op, in order, then every `ops` op, in order.
  Bind results to local variables named after `bind`.
- For each `agents_md_constraints` entry, emit an `assert` or `if … vm.answer(OUTCOME_DENIED_SECURITY)` guard
  before the related op runs.
- Format `answer_template.message` using the bound variables; call `vm.answer(message=..., outcome=..., refs=[...])` exactly once at the end.

## Forbidden

- Hardcoding values from the instruction.
- Calling RPCs not present in TOOL_PLAN.
- Skipping discovery ops.
- Computing SQL strings — emit them as written in TOOL_PLAN.
- Filesystem access outside `vm.*`.
- Network calls.

## Param substitution

`params` is a dict. Values starting with `$` (e.g. `$agent_store_id`) are pre-resolved by the caller —
read them directly: `store_id = params["store_id"]`. Pass them through `vm.exec(args=[":name"], ...)` style
parameterised SQL; do not interpolate into the SQL string.

## Outcome codes

`OUTCOME_OK | OUTCOME_DENIED_SECURITY | OUTCOME_NONE_UNSUPPORTED | OUTCOME_NONE_CLARIFICATION`.
