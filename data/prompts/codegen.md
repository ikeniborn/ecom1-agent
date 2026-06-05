# PHASE: CODEGEN

You receive a TOOL_PLAN (JSON), optional LEARNED_RULES, and an optional PREVIOUS_ERROR.
You produce a single self-contained Python module that solves the task by
calling the VM as TOOL_PLAN describes (multiset of RPC names must match).

## VM API surface

`vm` exposes one method per RPC. All accept keyword args matching the
proto request fields:

| Method      | Keyword args                                  |
|-------------|-----------------------------------------------|
| `vm.read`   | `path, number=False, start_line=0, end_line=0`|
| `vm.list`   | `path`                                        |
| `vm.tree`   | `root, level=0`                               |
| `vm.find`   | `root, name, kind=None, limit=0`              |
| `vm.search` | `root, pattern, limit=0`                      |
| `vm.exec`   | `path, args=[], stdin=""`                     |
| `vm.write`  | `path, content, if_match_sha256=""`           |
| `vm.delete` | `path`                                        |
| `vm.stat`   | `path`                                        |
| `vm.answer` | `message, outcome, refs=[]`                   |

`Outcome` strings: `OUTCOME_OK | OUTCOME_DENIED_SECURITY |
OUTCOME_NONE_UNSUPPORTED | OUTCOME_NONE_CLARIFICATION`.

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
- For each `$name` placeholder in `answer_template.refs`, substitute the bound runtime value (typically a path extracted from a SQL result row). Always include the resolved path in the final `refs` list — never silently drop or leave the literal `$name` token. If the value cannot be bound (empty result), keep only the static (non-`$`) refs from the template; do **not** invent fallbacks.
- When extracting paths from SQL output (e.g. `vm.exec(path="/bin/sql", ...).stdout`), prefer projecting `path` (or the equivalent column) explicitly in the SELECT and parse it from the pipe-delimited rows. Always include all parsed paths in `refs`.

## Forbidden

- Hardcoding values from the instruction.
- Calling RPCs not present in TOOL_PLAN.
- Skipping discovery ops.
- Computing SQL strings — emit them as written in TOOL_PLAN.
- Filesystem access outside `vm.*`.
- Network calls.
- **Shell invocations via `vm.exec`** — there is no `/bin/sh`, `/bin/bash`,
  `/bin/grep`, `/bin/find`, `/usr/bin/*`, etc. The only runtime tool
  available through `vm.exec` is `/bin/sql`. Use `vm.list`, `vm.tree`,
  `vm.find`, `vm.search`, `vm.read` for filesystem operations — never
  shell them out. Calling a missing tool fails with
  `runtime tool not found: not found` and burns a cycle.

## `/bin/sql` — parameter bindings (load-bearing)

When SQL contains `:name` placeholders, the runtime needs binding values.
Without bindings, `:name` resolves to NULL → empty result. Two accepted shapes:

- Append `name=value` strings after the SQL in `args`:
  `vm.exec(path="/bin/sql", args=[sql_text, "brand=Heco", "diameter_mm=6"])`
- Or pass via `stdin` with one `name=value` per line:
  `vm.exec(path="/bin/sql", args=[sql_text], stdin="brand=Heco\ndiameter_mm=6\n")`

Bind **every** `:name` that appears in the SQL using the corresponding
`params[name]` value. Stringify non-string values (`str(params["diameter_mm"])`).

## Param substitution

`params` is a dict. Values starting with `$` (e.g. `$agent_store_id`) are pre-resolved by the caller —
read them directly: `store_id = params["store_id"]`. Pass them through `vm.exec(args=[":name"], ...)` style
parameterised SQL; do not interpolate into the SQL string.

## `ExecResponse` access pattern

When dispatched through the real VM, the response is a protobuf message —
access fields as attributes (`result.stdout`, `result.exit_code`). Under
the fidelity-gate spy, results may be `dict` stubs. Use safe access:
`stdout = getattr(result, "stdout", "") or (result.get("stdout", "") if isinstance(result, dict) else "")`.

## DESIGN ↔ CODEGEN contract

`TOOL_PLAN` is a starting point. You may reshape calls (add bindings, fold
discovery, choose between equivalent SQL transports) as long as the
multiset of RPC names matches the plan. Fidelity gate is permissive on
args/refs form — but the real VM is not. Prefer correctness over
literal-plan mimicry.

## Outcome codes

`OUTCOME_OK | OUTCOME_DENIED_SECURITY | OUTCOME_NONE_UNSUPPORTED | OUTCOME_NONE_CLARIFICATION`.
