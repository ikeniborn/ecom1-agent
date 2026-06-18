# Proto API

The benchmark harness and trial VM speak Connect RPC over JSON. Proto sources live in `proto/bitgn/`; `make proto` (buf) regenerates the Python stubs into `bitgn/`. This page is a navigable overview — see `docs/proto-api-reference.md` for the field-level reference.

## Layers

Two distinct service planes. The **control plane** (`HarnessService`) manages runs, trials, and scoring on the BitGN platform. The **trial plane** (the VM runtime) is a per-trial workspace the agent reads and mutates, reached via a trial-local `harness_url`.

The agent never talks to the VM through the control-plane API path; `StartTrial` hands back a separate `harness_url`, and runtime calls go there. See [[architecture]] for how the orchestrator threads these together.

## Proto sources

All `.proto` definitions live under `proto/bitgn/`. There are three: `harness.proto` (control plane), `vm/ecom/ecom.proto` (the active ECOM runtime), and `vm/pcm.proto` (legacy flat VM ABI).

```
proto/bitgn/
├── harness.proto            # bitgn.harness — control plane
├── vm/ecom/ecom.proto       # bitgn.vm.ecom — current VM runtime
└── vm/pcm.proto             # bitgn.vm.pcm — legacy VM
```

ECOM deliberately lives in its own `vm/ecom/` folder to avoid the legacy flat `vm/*.proto` ABI while keeping the import path simple (`bitgn.vm.ecom.ecom_pb2`).

## Generated stubs

`bitgn/` holds the generated, checked-in stubs: `*_pb2.py` (message classes) plus hand-thin `*_connect.py` Connect clients. Regenerate with `make proto` (requires `buf`). Do not hand-edit generated files; change the `.proto` and rerun.

```
bitgn/
├── _connect.py              # ConnectClient: JSON-over-httpx transport
├── harness_pb2.py / harness_connect.py
└── vm/
    ├── ecom/ecom_pb2.py / ecom_connect.py
    └── pcm_pb2.py / pcm_connect.py
```

`_connect.py` is the shared transport: `ConnectClient.call()` POSTs `MessageToJson` bodies to `{base_url}/{service}/{method}` and maps non-200 Connect errors to `ConnectError`. See [[tooling]].

## HarnessService

The control-plane service (`bitgn.harness`), driven via `HarnessServiceClientSync`. It exposes the run/trial lifecycle plus benchmark metadata: `Status`, `GetBenchmark`, `StartRun`, `GetRun`, `SubmitRun`, `StartTrial`, `GetTrial`, `EndTrial`.

`StartPlayground` is deprecated and always errors — use `StartRun` + `StartTrial`. Most methods require a BitGN API key. Field-level message shapes are in `docs/proto-api-reference.md`.

## Run and trial lifecycle

A run owns a set of trials. `StartRun(benchmark_id, name, api_key)` allocates `trial_ids`; each is activated with `StartTrial`, which returns the task `instruction` and the trial-local `harness_url`. `EndTrial` is lifecycle-only and no longer carries scores.

States are tracked by `RunState` (`RUNNING → PENDING_EVAL → EVALUATED`) and `TrialState` (`NEW → RUNNING → DONE | ERROR`). `GetRun`/`GetTrial` poll state, `TrialStats`, and paginated `LogLine` feeds.

## Scoring (StartRun / SubmitRun)

Scoring is decoupled from `EndTrial`. After all trials finish, `SubmitRun(run_id, force)` triggers evaluation and returns per-trial `ScoredTrialResult` entries (`score`, `score_detail`) plus an aggregate.

Visibility depends on `EvalPolicy`. Under `OPEN`, scores are public at submit; under `BLIND` the run seals (`PENDING_EVAL`) and `score_available=false` until reveal; `PRIVATE` stays off leaderboards. The training loop reads `score_detail` to drive LEARN — see [[architecture]].

## VM runtime service

The per-trial VM is the agent's workspace. The active runtime is **ECOM** (`bitgn.vm.ecom`, `EcomRuntimeClientSync`), constructed from the trial's `harness_url`. It offers filesystem-style reads, search, in-runtime `Exec`, mutations, and the terminal `Answer`.

ECOM RPCs: `Read`, `List`, `Tree`, `Find`, `Search`, `Exec`, `Write` (with optional SHA-256 CAS), `Delete`, `Stat`, `Answer`, and a deprecated `Context`. `NodeKind` tags entries file/dir. The orchestrator wraps this client in a kwargs adapter — see [[vm]].

## Answer and outcomes

`Answer(message, outcome, refs)` submits the trial's final result and is the single terminal call per task. `outcome` is an `Outcome` enum: `OUTCOME_OK`, `OUTCOME_DENIED_SECURITY`, `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED`, `OUTCOME_ERR_INTERNAL`.

The pipeline calls `Answer` exactly once — on the verified success path or one terminal clarification. `refs` lists supporting file paths backing the answer. See [[vm]] and [[architecture]].

## PCM (legacy VM)

`vm/pcm.proto` (`bitgn.vm.pcm`, `PcmRuntimeClientSync`) is the older flat VM ABI, retained alongside ECOM. It overlaps in spirit but differs in shape: it adds `MkDir`/`Move`, uses `is_dir` booleans instead of `NodeKind`, and its `Read`/`Write` omit ECOM's `content_type`/`sha256`/CAS fields.

Its `Outcome` enum matches ECOM's. New work targets ECOM; PCM is documented here only so the generated `bitgn/vm/pcm_*.py` stubs are accounted for. See [[tooling]].
