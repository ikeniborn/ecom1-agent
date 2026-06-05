# Proto API Reference

---

## HarnessService (`proto/bitgn/harness.proto`)

Controls benchmark lifecycle — runs, trials, scoring. Proto package: `bitgn.harness`.

Import: `from bitgn.harness_connect import HarnessServiceClientSync`

| RPC | Request | Response | Purpose |
|-----|---------|----------|---------|
| `Status` | `StatusRequest` | `StatusResponse` | Health check; returns status string + version |
| `GetBenchmark` | `GetBenchmarkRequest(benchmark_id)` | `GetBenchmarkResponse` | Fetch benchmark metadata + task list + links |
| `StartRun` | `StartRunRequest(benchmark_id, name, api_key)` | `StartRunResponse(run_id, benchmark_id, trial_ids)` | Start scored run; allocates trial IDs |
| `GetRun` | `GetRunRequest(run_id)` | `GetRunResponse` | Inspect run state, stats, aggregate score |
| `StartTrial` | `StartTrialRequest(trial_id)` | `StartTrialResponse` | Activate single trial; returns `harness_url` + `instruction` |
| `GetTrial` | `GetTrialRequest(trial_id, cursor)` | `GetTrialResponse` | Fetch trial logs + state; cursor for pagination |
| `EndTrial` | `EndTrialRequest(trial_id)` | `EndTrialResponse(trial_id, state)` | Lifecycle-only; **scores no longer here** — see `SubmitRun` |
| `SubmitRun` | `SubmitRunRequest(run_id, force)` | `SubmitRunResponse` | Submit; **returns per-trial scores** when policy permits |
| `StartPlayground` | `StartPlaygroundRequest` | `StartPlaygroundResponse` | **Deprecated** — always errors; use `StartRun` + `StartTrial` |

### Key Messages

```protobuf
GetBenchmarkResponse {
  benchmark_id, description, harness_id
  policy: EvalPolicy
  links: repeated Link { url, kind: LinkKind }
  tasks: repeated Task { task_id, preview, hint }   // hint empty for BLIND
}

StartTrialResponse {
  trial_id, benchmark_id, task_id, run_id
  instruction
  harness_url        // per-trial agent runtime endpoint (NOT control plane)
}

EndTrialResponse {
  trial_id
  state: TrialState
  // score, score_detail, score_available — all deprecated; use SubmitRun
}

SubmitRunResponse {
  run_id
  state: RunState              // EVALUATED (public) | PENDING_EVAL (sealed)
  score: optional float        // aggregate; present only if public
  score_available: bool        // mirrors score presence
  trials: repeated ScoredTrialResult
}

ScoredTrialResult {
  trial_id, task_id, num
  state: TrialState
  score: optional float        // present only when score_available
  score_available: bool
  score_detail: repeated string
  error                        // set if trial failed at runtime
}

GetTrialResponse {
  trial_id, instruction, benchmark_id, task_id
  state: TrialState
  error
  score: optional float, score_available, score_detail
  logs: repeated LogLine, next_cursor
  duration_sec, api_calls, api_errors, event_count
}

GetRunResponse {
  run_id, benchmark_id, name, policy
  state: RunState
  score: optional float, score_available
  stats: TrialStats { new_count, running_count, done_count, error_count }
  trials: repeated TrialHead
}
```

### Enums

#### `EvalPolicy`
| Value | Meaning |
|-------|---------|
| `EVAL_POLICY_UNSPECIFIED` | Default zero — invalid |
| `EVAL_POLICY_BLIND` | Hints hidden; scores sealed until reveal |
| `EVAL_POLICY_OPEN` | Public benchmark; scores at end of run |
| `EVAL_POLICY_PRIVATE` | Private run; not on leaderboards |

#### `TrialState`
`TRIAL_STATE_NEW | TRIAL_STATE_RUNNING | TRIAL_STATE_DONE | TRIAL_STATE_ERROR`

#### `RunState`
`RUN_STATE_RUNNING | RUN_STATE_PENDING_EVAL | RUN_STATE_EVALUATED`

### Scoring Flow

1. `StartRun` → allocate `trial_ids`
2. For each trial: `StartTrial` → run agent → `EndTrial` (lifecycle close, no score)
3. `SubmitRun(force=True)` → iterate `response.trials` for per-task `score` + `score_detail`
4. If `response.score_available=False` — policy is BLIND, scores sealed until reveal

---

## EcomRuntime (`proto/bitgn/vm/ecom/ecom.proto`)

Source: `proto/bitgn/vm/ecom/ecom.proto`
Import: `from bitgn.vm.ecom.ecom_connect import EcomRuntimeClient`

---

## RPC Methods

| RPC | Request | Response | Purpose |
|-----|---------|----------|---------|
| `Read` | `ReadRequest` | `ReadResponse` | Read file content; supports line ranges + numbering |
| `List` | `ListRequest(path)` | `ListResponse` | Directory listing with kind + content_type |
| `Tree` | `TreeRequest(root, level)` | `TreeResponse` | Recursive tree; `level=0` = unlimited |
| `Find` | `FindRequest(root, name, kind, limit)` | `FindResponse` | Path search by name/kind |
| `Search` | `SearchRequest(root, pattern, limit)` | `SearchResponse` | Regex search; returns path+line+text |
| `Exec` | `ExecRequest(path, args, stdin)` | `ExecResponse` | Run in-runtime tool (e.g. `/bin/sql`) |
| `Write` | `WriteRequest(path, content, if_match_sha256)` | `WriteResponse` | Write file; optional SHA-256 precondition |
| `Delete` | `DeleteRequest(path)` | `DeleteResponse` | Delete file or directory |
| `Stat` | `StatRequest(path)` | `StatResponse` | File metadata: kind, content_type, writable |
| `Answer` | `AnswerRequest(message, outcome, refs)` | `AnswerResponse` | Submit final answer to harness |
| `Context` | `ContextRequest` | `ContextResponse` | **Deprecated** — use `Exec /bin/date` instead |

---

## Messages

```protobuf
ReadRequest {
  path: string
  number: bool       // prefix lines with line numbers (cat -n style)
  start_line: int32  // 1-based inclusive, 0 = from first line
  end_line: int32    // 1-based inclusive, 0 = through last line
}

ReadResponse {
  path: string
  content_type: string
  content: string
  sha256: string     // SHA-256 of full file (not just returned range)
  truncated: bool
}

ListRequest  { path: string }
ListResponse {
  path: string
  entries: repeated Entry { name, path, kind: NodeKind, content_type }
}

TreeRequest  { root: string, level: int32 }  // level=0 unlimited
TreeResponse {
  root: Entry { name, kind, content_type, children: repeated Entry }
  truncated: bool
}

FindRequest  { root, name, kind: NodeKind, limit: int32 }
FindResponse { paths: repeated string, truncated: bool }

SearchRequest  { root, pattern, limit: int32 }
SearchResponse {
  matches: repeated Match { path, line: int32, line_text }
  truncated: bool
}

ExecRequest  { path, args: repeated string, stdin }
ExecResponse { exit_code: int32, stdout, stderr, truncated: bool }

WriteRequest {
  path: string
  content: string
  if_match_sha256: string  // CAS precondition; empty = no check
}
WriteResponse { path: string }

DeleteRequest { path: string }
DeleteResponse {}

StatRequest  { path: string }
StatResponse { path, kind: NodeKind, content_type, writable: bool }

AnswerRequest {
  message: string
  outcome: Outcome
  refs: repeated string  // supporting file paths
}
AnswerResponse {}
```

---

## Enums

### `Outcome`
| Value | Meaning |
|-------|---------|
| `OUTCOME_OK` | Task completed successfully |
| `OUTCOME_DENIED_SECURITY` | Blocked by security policy |
| `OUTCOME_NONE_CLARIFICATION` | Need clarification |
| `OUTCOME_NONE_UNSUPPORTED` | Unsupported operation |
| `OUTCOME_ERR_INTERNAL` | Internal runtime error |

### `NodeKind`
| Value | Meaning |
|-------|---------|
| `NODE_KIND_FILE` | Regular file |
| `NODE_KIND_DIR` | Directory |

---

## Generated Stubs

```
bitgn/vm/ecom/
├── ecom_pb2.py      # message definitions
└── ecom_connect.py  # EcomRuntimeClient
```
