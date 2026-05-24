# VM Protocol

The ECOM VM is accessed via Connect-RPC through `EcomRuntimeClientSync`. Protobuf stubs in `bitgn/` are generated from `proto/` with `make proto`.

## VM Operations

All VM operations available to the pipeline.

| Operation | Request Type | Use |
|-----------|-------------|-----|
| `vm.exec()` | `ExecRequest(path, args)` | Run shell tools (`/bin/sql`, `/bin/discount`, `/bin/date`, `/bin/id`) |
| `vm.read()` | `ReadRequest(path)` | Read file content from VM filesystem |
| `vm.list()` | `ListRequest(path)` | List directory entries |
| `vm.search()` | `SearchRequest(root, pattern, limit)` | Grep-style search |
| `vm.find()` | `FindRequest(root, name, limit)` | Find files by name |
| `vm.tree()` | `TreeRequest(root, level)` | Directory tree (level=2) |
| `vm.answer()` | `AnswerRequest(message, outcome, refs)` | Submit final answer |

## Result Extraction

`_exec_result_text()` extracts text from protobuf Message — `stdout`/`output`/`stderr` via `MessageToDict`, with attribute fallback.

Empty result is `""` — pipeline distinguishes empty from error by checking return value type.

## Outcome Codes

`AnswerRequest.outcome` must be a protobuf `Outcome` enum value.

`OUTCOME_BY_NAME` dict in `llm.py` maps string names to enum values. Pipeline uses string names internally and converts at call site.

## Action Type Inference

`_infer_action_type()` determines VM call from action string prefix.

- `SELECT` prefix → sql (EXPLAIN first, then query)
- `/path` not in `/bin/` or `/usr/` → read
- `list:path` → list
- `search:pattern /root` → search
- `find:name /root` → find
- `tree:path` → tree
- `/bin/...` or `/usr/...` → exec
- anything else → exec
