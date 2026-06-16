# VM Protocol

The ECOM VM is accessed via Connect-RPC through `EcomRuntimeClientSync` (wrapped by `vm_adapter.py`). Protobuf stubs in `bitgn/` are generated from `proto/` with `make proto`.

## VM Operations

All VM operations available to the interpreter. `PlanIR` steps name the RPC (`Exec`, `Read`, `List`, …); `interpret()` dispatches via `getattr(vm, step.rpc.lower())(**kwargs)`.

| Operation | Request Type | Use |
|-----------|-------------|-----|
| `vm.exec()` | `ExecRequest(path, args)` | Run shell tools (`/bin/sql`, `/bin/discount`, `/bin/date`, `/bin/id`) |
| `vm.read()` | `ReadRequest(path)` | Read file content from VM filesystem |
| `vm.list()` | `ListRequest(path)` | List directory entries |
| `vm.search()` | `SearchRequest(root, pattern, limit)` | Grep-style search |
| `vm.find()` | `FindRequest(root, name, limit)` | Find files by name |
| `vm.tree()` | `TreeRequest(root, level)` | Directory tree |
| `vm.write()` / `vm.delete()` | mutation requests | Mutating ops — gated by `lint_security_first` |
| `vm.answer()` | `AnswerRequest(message, outcome, refs)` | Submit final answer (called exactly once) |

`_MUTATING = {"Write", "Delete"}`; a `/bin/` exec other than `/bin/sql` also counts as mutating. The pipeline only re-runs a failed plan when it is read-only. See [[pipeline-phases]].

## Result Extraction

`interpreter.py:_payload(result)` normalizes a VM response to text — reads `stdout` (attribute or dict key), falling back to `content`, stripped. Empty result is `""`; the interpreter distinguishes empty from error by exception vs. empty string.

## Outcome Codes

`AnswerRequest.outcome` must be a protobuf `Outcome` enum value. `OUTCOME_BY_NAME` in `llm.py` maps string names to enum values; the pipeline uses string names internally and converts at the call site. See [[security-lint]].

Emitted outcomes: `OUTCOME_OK`, `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED`, `OUTCOME_DENIED_SECURITY`.
