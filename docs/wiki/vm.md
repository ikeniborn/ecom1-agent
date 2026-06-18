# VM

The VM interface layer is the boundary between the agent pipeline and the BitGN VM service. It exposes one uniform kwargs-style RPC surface (`read/list/tree/find/search/exec/write/delete/stat/answer`) backed by either a real gRPC client or one of two test doubles, plus a parser for the `/AGENTS.MD` task brief. See [[architecture]] for the surrounding flow.

## VMAdapter — real VM RPC wrapper

`VMAdapter` (`agent/vm_adapter.py:49`) bridges the kwargs-style calls emitted by the interpreter and pipeline terminals to the protobuf-request API of the real `EcomRuntimeClientSync`. Each method wraps kwargs in the matching `*Request` message and dispatches.

The adapter holds a single client (`self._c`, `agent/vm_adapter.py:50`) and defines one thin method per RPC: `read`→`ReadRequest`, `list`→`ListRequest`, `tree`→`TreeRequest`, `find`→`FindRequest`, `search`→`SearchRequest`, `exec`→`ExecRequest`, `write`→`WriteRequest`, `delete`→`DeleteRequest`, `stat`→`StatRequest`, `answer`→`AnswerRequest` (`agent/vm_adapter.py:53`). The request types are imported from `bitgn.vm.ecom.ecom_pb2`; see [[proto-api]]. The interpreter that drives these calls is documented in [[interpreter]].

## NodeKind normalisation

`tree` and `find` pass kwargs through `_normalise_kind` (`agent/vm_adapter.py:33`) before building the request, because LLM-generated scripts emit free-form `kind` strings ('file', 'dir') that protobuf rejects with `unknown enum label`.

`_NODE_KIND_ALIASES` (`agent/vm_adapter.py:18`) maps lower-cased, stripped strings to `NodeKind` enum values: `""`/`"any"`/`"all"`/`"unspecified"` → `NODE_KIND_UNSPECIFIED`, `"file"` → `NODE_KIND_FILE`, and `"dir"`/`"directory"`/`"folder"` → `NODE_KIND_DIR`. A non-string or unrecognised value is left untouched so protobuf can still accept a raw enum int. Only `tree` and `find` invoke it.

## MockVM — synthesizing stub

`MockVM` (`agent/mock_vm.py:52`) is a stub for `EcomRuntimeClientSync` used in mock tests. It never raises on read paths and always returns a structurally valid dataclass response synthesized from the constructor's `extracted_params` and `schema_digest` (`agent/mock_vm.py:59`).

Each RPC returns a small dataclass: `exec` → `_ExecResult` with `stdout` as JSON rows (the params dict, or a default `{"id": "mock_001", ...}` when empty); `read` → `_ReadResult` echoing params plus `_mock_path`; `search`/`find`/`list` → canned single-element results; `tree` → a fixed two-line string. Crucially, `answer` does **not** answer — it raises `RuntimeError("vm.answer() must not be called from heuristic script")` (`agent/mock_vm.py:87`), enforcing that mock-driven heuristic scripts never terminate the task themselves.

## MockVMSpy — recording fixture replay

`MockVMSpy` (`agent/mock_vm_spy.py:15`) is a recording double for the deterministic interpreter and replay tests. It replays canned RPC fixtures keyed by call, records every call, and is explicitly not for production dispatch.

It is constructed with a `fixtures` dict and an empty `calls` list. Every RPC calls `_record(rpc, **kwargs)` (appending to `self.calls`) then `_lookup` (`agent/mock_vm_spy.py:26`), which resolves via `fixture_key(rpc, path, args)` and falls back to `_DEFAULT_STUB` — a dict carrying empty `stdout/stderr/content/entries/nodes/matches`. Only the RPC name plus key args (`path`, and `args` for `exec`) drive lookup; every signature accepts `**kwargs` so valid-but-undeclared proto fields (e.g. `read(number=True)`, `find(limit=20)`) don't get rejected. `answer` records `message/outcome/refs` and returns `None` (`agent/mock_vm_spy.py:73`), so the spy lets `answer` be observed by replay tests.

## agents_md_parser — parsing /AGENTS.MD

`parse_agents_md(content)` (`agent/agents_md_parser.py:1`) splits the `/AGENTS.MD` brief into `{section_name: [lines]}`, one entry per `##` heading. The orchestrator reads `/AGENTS.MD` inline at task start before gathering pre-phase facts (see [[architecture]]).

The parser walks lines: a line beginning `## ` starts a new section whose key is the heading text lower-cased with spaces replaced by underscores; subsequent lines accumulate under the current section. Lines before the first `## ` are dropped, and the heading line itself is excluded from its section's body.

## vm.answer-called-exactly-once contract

`vm.answer` is invoked **exactly once** per task — on the single success path or one terminal CLARIFICATION — and the test doubles encode this invariant. The quality gate before answering is the deterministic `verify()`, not an LLM check (see [[pipeline]]).

`MockVM.answer` hard-fails to guarantee heuristic scripts never answer on their own (`agent/mock_vm.py:87`), while `MockVMSpy.answer` merely records the call so replay tests can assert it fired once with the right `message/outcome/refs`. On the real path, `VMAdapter.answer` forwards an `AnswerRequest` to the client; the once-only discipline is enforced by the pipeline loop, which calls it only after `verify()` passes or at a terminal `OUTCOME_NONE_CLARIFICATION` (see [[pipeline]]).

## Retryable VM-error handling

Retryable-error classification lives in the pipeline, not the VM layer: `_is_retryable_vm_error(msg)` (`agent/pipeline.py:73`) lower-cases a real-VM exception string and tests it against `_RETRYABLE_VM_ERROR_PATTERNS`. A retryable error makes the loop LEARN-and-retry instead of dead-ending at clarification.

The patterns (`agent/pipeline.py:53`) cover deterministic input faults — `"not found"`, `"is a directory"`, `"does not exist"`, `"no such file"`, `"not a file"` — and network/VM transients — read/write operation timeouts, `"connection reset"`, `"remote disconnected"`, `"connection aborted"`. The retry is gated read-only at the call site (`agent/pipeline.py:303`): retry fires only when `_is_retryable_vm_error(str(e))` **and** the plan does not mutate; a mutating plan breaks rather than risk re-applying a side effect (see [[pipeline]] and [[interpreter]]).
