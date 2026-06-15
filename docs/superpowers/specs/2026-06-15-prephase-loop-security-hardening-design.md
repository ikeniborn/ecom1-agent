# Pre-phase / loop / security hardening — design (2026-06-15)

Branch `heuristics`. Closes the gaps left open after Approach A (S1/S2 series) and
fixes the concrete t55 production failure surfaced in
`logs/20260615_140206_claude-code-sonnet/t55.detail.log`.

Source analysis: `docs/superpowers/notes/2026-06-14-agent-debug-findings.md`.

## Problem statement

Approach A (pre-phase doc-grounding + per-outcome projected refs) is implemented.
Remaining, confirmed-open gaps:

- **t55 literal-path discovery (NEW, run result).** Instruction names a literal
  directory `/proc/incoming/payments` (staging files `inpay_*.json`) that is **not**
  projected into SQL. The agent substituted the SQL `payment_transactions` table
  (`/proc/payments/pay_010.json`) → grader rejected: *answer missing required
  reference `/proc/incoming/payments/inpay_gFa1yFhy.json`*. The pre-phase
  `target_records` step matches only `<prefix>_<id>` ids → `/proc/<plural>/<id>.json`;
  a literal directory path is never enumerated.
- **P9-runtime.** `ListResponse`/`StatResponse`/`TreeResponse` carry **no `.stdout`**
  (proto: `ListResponse{entries[*].path}`, `StatResponse{kind}`,
  `TreeResponse{root}`). Any code reading `.stdout` on these gets `""` — the cause of
  the `[List …] -> <empty>` in the t55 trace. `_discover_docs` already walks the Tree
  entry; there is no reusable `List`/`Stat` entry-parser for runtime paths.
- **P5.** Static caps `_SAMPLE_TABLES_MAX=12 / _SAMPLE_ROWS_PER_TABLE=3 /
  _SAMPLE_ROW_MAX_CHARS=400` (schema has ~15 tables). Brittle; rot when inputs change.
- **P8.** `gather_status` exists (`ok|empty|error`) but nothing surfaces it to INTENT;
  a silently-missing fact reads as a confident-wrong spec.
- **R1–R5 (interpreter loop mechanics).** `learn_ctx=[]` every run (write-only LEARN),
  LEARN prompt CODEGEN-framed, PLAN blind to runtime observations, no identical-plan
  short-circuit, `MAX_STEPS=10`.
- **over-security (t55 v001).** A prior t55 run answered `OUTCOME_DENIED_SECURITY`
  (`emp_023` ≠ owning customer `cust_016`) where the grader expects `OUTCOME_OK`. The
  customer-ownership clause of `security.md` binds **customers**, not an employee
  operational read. INTENT emits an owner-mismatch `deny_when` that over-fires.

## Scope

In: the seven items above. Out: anything else in the findings register.

## Architecture — three phases

| Phase | Goal | Items | Primary files |
|---|---|---|---|
| **1. Pre-phase / discovery** | ground INTENT on real files + signal sufficiency | t55 literal-path, P9-runtime, P5, P8 | `agent/orchestrator.py`, `agent/reason.py` (`_facts_block`) |
| **2. Interpreter loop mechanics** | convergence, non-write-only LEARN | R1–R5 | `agent/pipeline.py` (`_run_interpreted`, `_ilearn`), `agent/reason.py` (`run_plan`), `agent/learned_store.py`, `data/prompts/ilearn.md` (new) |
| **3. Security-scope grounding** | remove over-DENIED | v001 | `data/prompts/intent.md`, `agent/orchestrator.py` (`identity.kind`), `agent/verify.py` (defense) |

Dependencies: Phase 1 is the foundation (gives t55 its required ref). Phase 3 is
parallel (gives t55 `OUTCOME_OK`); together they fix t55 end-to-end. Phase 2 is the
independent interpreter debt; its R2/`prephase_deep_read` hook depends on Phase 1's
tier split.

### Design principle — read by cost, not by fixed cap

Hardcoded caps rot and demand manual tuning. Split pre-phase reads into two tiers:

- **Tier-1 — metadata (cheap, naturally bounded): read eagerly, no count cap, only a
  byte-budget safety rail.** DDL schema, table names, directory listings (paths +
  kind), `Stat`.
- **Tier-2 — content (expensive, unbounded volume): read lazily, relevance-gated +
  learned-hint-driven, byte-budget bounded.** Table sample rows, file bodies.

The deep-read **set** is relevance + LEARN, never a magic N. This is the answer to
"what to read deeply" rotting: it self-tunes through the learning loop.

## Phase 1 — pre-phase / discovery

### 1.1 P9-runtime shared parsers (`orchestrator.py`)

Reusable by the interpreter. Proto/dict-tolerant wrappers (mirroring `_search_paths`):

```python
from bitgn.vm.ecom.ecom_pb2 import NodeKind

def _list_entries(vm, path):      # ListResponse.entries[*].path — NOT .stdout
    resp = vm.list(path=path)     # try/except -> []
    return [e.path for e in (resp.entries or []) if e.path]

def _stat_kind(vm, path):         # StatResponse.kind -> 'dir' | 'file' | ''
    k = vm.stat(path=path).kind
    return {NodeKind.NODE_KIND_DIR: "dir", NodeKind.NODE_KIND_FILE: "file"}.get(k, "")
```

### 1.2 Literal-path fact (listing only, no content slurp)

```python
_PROC_PATH_RE = re.compile(r"/proc/[\w./-]+")   # /docs literals already in policies
# byte-budget self-scales; no per-task count cap

def _extract_path_literals(instruction) -> list[str]:
    # findall, strip trailing punctuation, dedup, small cap
    ...

# in gather_prephase_facts:
for lit in _extract_path_literals(instruction):
    kind = _stat_kind(vm, lit)
    if kind == "dir":
        paths = _list_entries(vm, lit)                       # Tier-1, cheap
        path_listings[lit] = _render_budget(paths, BYTE_BUDGET)   # "+N more" tail
    elif kind == "file":
        path_listings[lit] = f"file {lit}"                   # existence; body NOT read
    # kind == "" -> missing path -> gather_status empty
_mark("path_listings", path_listings)
```

Boundary: pre-phase surfaces the **listing** (real record paths) — enough to route
INTENT/DESIGN away from the SQL table. The "last/newest" selection and the single
record body are read by **PLAN at runtime** (`vm.list` + read one file), not bounded
by any pre-phase cap. No sample-content slurp in pre-phase (content is Tier-2).

### 1.3 P5 — metadata uncapped, content relevance + learned

- Table names + DDL: drop `_SAMPLE_TABLES_MAX` from the names/DDL path (Tier-1, one
  query, small).
- Sample rows (Tier-2): table set = **relevant** (table name / entity token appears in
  the instruction, optionally FK-adjacent) **∪ learned `prephase_deep_read`** for this
  `tid`. Not "first 12 alphabetical".
- Each sample bounded by small `LIMIT` + byte-budget (safety rail, not the lever).
- **No silent truncation** (findings "no silent caps"): whatever drops past the
  byte-budget is logged (`… +N skipped`) so INTENT/LEARN see the omission.

### 1.4 P8 — sufficiency signal (deterministic, not a hard block)

- `_facts_sufficiency(facts)` → list of non-`ok` `gather_status` entries.
- Rendered in `_facts_block`: `FACT_STATUS (non-ok): identity=empty, target_records=empty`.
- One-line guidance in `intent.md`/`design.md`: *if a needed fact is empty/error,
  prefer a PLAN discovery step or CLARIFICATION; do not invent it.*
- Not a hard gate (blocking risks false negatives) — it distinguishes "no fact" from
  "fetch failed".

### 1.5 Surfacing (both paths)

- New field `PrePhaseFacts.path_listings: dict[str, str]` + `gather_status['path_listings']`.
- Interpreter: `reason.py:_facts_block` adds `path_listings` + sufficiency (flows to
  INTENT and PLAN).
- Legacy: extend the existing facts injection (S1-R8) with the same block.

## Phase 2 — interpreter loop mechanics

### R1 — cross-run IR learning (separate namespace)

- `surface: "ir" | "codegen"` field on each learned entry. `apply_learn_diff` stamps it;
  untagged legacy entries default to `"codegen"`.
- `load_entries(tid, surface=None)` gains an optional filter.
- `_run_interpreted` starts `learn_ctx = load_entries(tid, surface="ir")` (not `[]`).
  Codegen-era rules are excluded by tag, not by emptiness — honoring the existing
  warning at `pipeline.py:316-319`.

### R2 — LEARN reframed for PlanIR

- New `data/prompts/ilearn.md`: inputs `INTENT + PLAN_IR(JSON) + ERROR + OBSERVED`, no
  `SCRIPT_CODE`/`tool_plan`/fidelity framing. Output = `LearnConsolidateOutput` + optional
  `prephase_deep_read: list[str]`.
- `_ilearn` (`pipeline.py:283`) loads `ilearn.md`, stamps `surface="ir"`.

### R3 — observations → PLAN

- `reason.py:run_plan(..., observed: list[str] | None = None)` renders an
  `OBSERVED_RPC_OUTPUTS` block (mirror of `_ilearn`'s observed block, `pipeline.py:200-202`).
- `_run_interpreted` keeps `last_observed = result.observations` and passes it into the
  next `run_plan(... observed=last_observed)`. PLAN re-plans seeing actual RPC stdouts,
  not a one-line error.

### R4 — identical-plan short-circuit

- `_plan_signature(plan)` = (normalized SQL multiset, ops rpc multiset). Track `prev_sig`.
- Two identical consecutive signatures → break → terminal `OUTCOME_NONE_CLARIFICATION`
  (interpreter analog of legacy `check_retry_loop`; 2 not 3 because PLAN + observations
  must change something).

### R5 — interpreter cycle ceiling

- Separate `_IMAX_STEPS = env("INTERPRETER_MAX_STEPS", "6")` used by `_run_interpreted`;
  legacy keeps `MAX_STEPS`. `.env` `MAX_STEPS=10` no longer drives the interpreter.

### `prephase_deep_read` stitch (Phase 1 ↔ Phase 2)

```
fail -> _ilearn(ilearn.md) -> out.prephase_deep_read = ['payment_transaction_items',
                                                        '/proc/incoming/payments']
     -> apply_learn_diff (surface="ir", on entry)
     v  next run
gather_prephase_facts -> load_entries(tid, surface="ir") -> collect prephase_deep_read
     -> add to Tier-2 deep-read set -> pre-phase reads exactly those
```

Closed adaptive loop: the deep-read set self-tunes through LEARN, removing the need for
manual cap tuning (the objection that motivated the tier split).

## Phase 3 — security-scope grounding

Root: INTENT emits a customer-ownership `deny_when` that fires on any `/bin/id`-vs-owner
mismatch; for an employee operational read the customer-scope clause does not apply.

### D1 — derive `identity.kind` in pre-phase (deterministic)

From `/bin/id`, classify and store in `facts.identity["kind"]`:
- `customer_id` / `uid=cust_*` → `"customer"`
- employee roles (`employee`, `*_coordinator`, `*_viewer`, `store_manager`, …) / `emp_*`
  → `"employee"`
- empty → `"guest"`

No literal ids — only the kind. Re-seed safe.

### D2 — `intent.md` rule (general, not task-specific)

- "Apply a customer-ownership `deny_when` **only when** `$_facts.identity.kind ==
  "customer"`. An employee/operational identity is not bound by the `security.md`
  customer-scope clause — do not emit an owner-mismatch deny for it. Customer-only
  actions (account recovery, email-change per the doc) are a separate class."
- Grounded in `security.md` scope + `facts.identity`, never hardcoded.
- Predicate form INTENT authors (resolved at runtime):

```json
{"op":"and","args":[
  {"op":"eq","lhs":"$_facts.identity.kind","rhs":"customer"},
  {"op":"ne","lhs":"$record.customer_id","rhs":"$_facts.identity.customer_id"}]}
```

### D3 — env / defense

- Identity plumbing already exists: `interpret` sets `env["_facts"]` (`interpreter.py:212`)
  and verify carries it over (`env = dict(result.env)`). `_lookup_path`
  (`predicates.py:17-31`) supports dotted/attr access → `$_facts.identity.kind` resolves.
  No new plumbing — only ensure `identity.kind` is present (D1).
- verify I3 (`verify.py:33-38`) re-derives the same predicate on the same env → the
  killer-property (independent DENIED re-derivation) stays role-aware and consistent.

### D4 — validation

- `scripts/probe_t55_refs.py` (mirror `probe_t09_refs.py`): fresh StartRun, employee
  identity + literal path → assert `OUTCOME_OK` + ref `/proc/incoming/payments/inpay_*.json`.
- Phase 1 supplies the ref, Phase 3 supplies the outcome → t55 0.0 → 1.0.

Residual risk = INTENT quality (does it emit the role-aware predicate). This is the
findings lever (INTENT gates everything); defended by verify I3 re-derivation + the
grader-oracle gate.

## Testing

Unit (deterministic, `mock_vm` / `MockVMSpy`, proto + dict tolerant):

| Component | Assertion |
|---|---|
| `_list_entries` / `_stat_kind` | parse `entries[*].path`, `kind`→dir/file/''; no `.stdout` dependence |
| `_extract_path_literals` | `/proc/...` extraction, trailing-punct strip, dedup, cap |
| literal-path fact | dir → listing + byte-budget + "+N more"; file → existence; missing → status empty |
| tier split (1.3) | names+DDL uncapped; sample = relevant ∪ `prephase_deep_read`; skipped logged |
| `identity.kind` (D1) | cust_* → customer, emp_*/roles → employee, empty → guest |
| `_plan_signature` / R4 | two identical → break CLARIFICATION |
| R1 namespace | `load_entries(tid, surface="ir")` filters; untagged legacy → codegen |
| R3 | `run_plan(observed=)` renders `OBSERVED_RPC_OUTPUTS` |
| deny_when role-aware | employee → deny_when False (OK); customer mismatch → True (DENIED) |

Integration:
- `scripts/probe_t55_refs.py` as in D4.
- Existing suite stays green (note: `test_t09_replay_matches_known_good` is a known
  pre-existing stale-fixture red, not a regression).

## Validation gate (findings §7.7)

1. grader-oracle on t55: 0.0 → 1.0 (ref + outcome) — required before cutover.
2. A/B on the benchmark behind `INTERPRETER_ENABLED`; cut over only if score ≥ baseline
   (~32%) **and** t55 / bucket improve, with no regression on green tasks.

## Implementation order

```
Phase 1 (foundation): P9 parsers -> literal-path -> tier split -> P8
   +- Phase 3 (D1 + intent.md, light): supplies OUTCOME_OK
        v together -> t55 0.0 -> 1.0 -> grader-oracle gate
Phase 2 (interpreter debt, independent): R1 -> R2 -> R3 -> R4 -> R5
   +- R2 / prephase_deep_read depends on the Phase 1 tier split
```
