---
review:
  spec_hash: d78b9dd0c845db29
  last_run: 2026-06-15
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - id: F-001
      phase: clarity
      severity: WARNING
      section: "1.2 / 1.3"
      section_hash: 9642d365f2de3de7
      text: "Numeric constants (literal-path cap, sample LIMIT, byte-budget) lack explicit default values / DoD. Intentionally deferred per the 'no magic N' principle, but a reader cannot verify a concrete acceptance criterion from the spec body."
      verdict: fixed
      verdict_at: 2026-06-15
chain:
  intent: null
---

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

In: the seven items above, **plus two cross-cutting cleanups they expose**:

- **De-hardcoding (H).** Remove the static domain lists in `orchestrator.py` that cause
  t55 and its class (`_RECORD_ID_RE` entity-prefix list, `_PROC_DIR` singular→plural map,
  any role allowlist in D1). Domain knowledge moves to the **oracle** (general atoms) or
  the **LEARN** loop (`prephase_deep_read`); structure stays in code. See "De-hardcoding".
- **Legacy cleanup (L).** Audit `.env.example` and the agent code for vars/functions that
  only served the deleted CODEGEN/fidelity path; plan their removal **gated behind the
  cutover** (validation gate §2). See "Legacy cleanup".

Out: anything else in the findings register.

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

**No root allowlist (de-hardcode).** Extract ANY absolute-path literal from the
instruction; the **VM is the filter**, not a static `/proc,/docs` prefix list. `Stat`
returns `''` for a non-existent or non-data path, which drops it. There is no hardcoded
root set to rot — a future `/data/incoming/…` or `/mnt/…` literal is grounded by the
same code with no edit.

```python
# Any absolute path; Stat() decides existence. No /proc allowlist, no hardcoded roots.
_PATH_LITERAL_RE = re.compile(r"/[\w./-]+")
# byte-budget self-scales; no per-task count cap

def _extract_path_literals(instruction) -> list[str]:
    # findall, strip trailing punctuation, dedup, small cap (_PATH_LITERAL_CAP)
    ...

# in gather_prephase_facts:
for lit in _extract_path_literals(instruction):
    kind = _stat_kind(vm, lit)               # VM ground truth — the only filter
    if kind == "dir":
        paths = _list_entries(vm, lit)                       # Tier-1, cheap
        path_listings[lit] = _render_budget(paths, BYTE_BUDGET)   # "+N more" tail
    elif kind == "file":
        path_listings[lit] = f"file {lit}"                   # existence; body NOT read
    # kind == "" -> non-existent / non-data path -> skipped; if NONE resolved,
    #               gather_status['path_listings'] = empty
_mark("path_listings", path_listings)
```

The `_PATH_LITERAL_CAP` (default 3) bounds Stat-probe cost only — a safety rail, not
domain knowledge. Over-matching tokens (`/bin/sql`, `/AGENTS.MD`) are harmless: `Stat`
classifies them (`/bin/sql` is a file → existence only; a non-path token → dropped),
so no denylist is needed either.

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

### D1 — derive `identity.kind` in pre-phase (deterministic, structural — no role list)

From `/bin/id`, classify by **id-shape only** (see H3 — no role allowlist) and store in
`facts.identity["kind"]`:
- a `customer_id` field / `cust_*` id present → `"customer"`
- any other non-empty authenticated id → `"employee"` (operational; the safe default —
  a *new* employee role classifies as `employee`, never silently as `guest`)
- empty → `"guest"`

No literal ids, no role-name list — only the kind. Re-seed safe. Finer role semantics, if
ever required, are an oracle atom, not a code constant.

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

## De-hardcoding — oracle or LEARN, no static domain lists

Governing rule (mirrors `CLAUDE.md` "Prompt Engineering Rules"): **code holds structure,
never domain facts.** Any per-domain knowledge flows through the **oracle** (validated
*general* atoms, semantically retrieved) or the **LEARN** loop (per-`tid`
`prephase_deep_read` / learned rules). The three generality gaps below are all the same
defect — a static list baked into `orchestrator.py` — and all resolve the same way.

### H1 — `_PROC_DIR` map + `_RECORD_ID_RE` prefix list (the t55 root cause)

Today `_proc_candidates` maps `<prefix>_<id>` → `/proc/<plural>/<id>.json` via a frozen
`{basket:baskets, payment:payments, …}` dict, and `_RECORD_ID_RE` only matches that same
seven-prefix set. A literal dir (`/proc/incoming/payments`) or any unlisted entity is
invisible — exactly t55.

De-hardcode (no list):
- **Plural/dir is discovered, not mapped.** `/proc` is itself a directory: `_list_entries(vm, "/proc")`
  (Tier-1, cheap) returns the *actual* subdirs. Match a record-id prefix to a real subdir
  by listing, never by a static singular→plural dict. The VM is ground truth.
- **Literal paths bypass the map entirely** via 1.2 (`_PATH_LITERAL_RE` + `Stat`), which
  already grounds `/proc/incoming/payments` with zero domain knowledge.
- **Entity tokens come from the DDL, not a regex allowlist.** Table names (Tier-1, already
  read) ∪ instruction tokens define the entity vocabulary; `_RECORD_ID_RE` collapses to a
  structural `\b\w+_\w+\b` id-shape, with the DDL/`/proc` listing deciding which prefixes
  are real. Drop the seven-word alternation.
- **Residual domain nuance** (e.g. "staging records live under `inpay_*`") is a *general*
  oracle atom or a learned `prephase_deep_read` hint — never a code constant.

### H2 — table relevance misses indirect references

Relevance = exact table-name/entity token in the instruction ∪ FK-one-hop. A table named
only by synonym is missed on the first run.

De-hardcode (already two-layered, made explicit):
- **General layer = oracle.** "Questions about X read tables Y/Z" is exactly a validated
  general atom; oracle retrieval (already wired into the pipeline) widens the relevance set
  semantically, before any failure. This is the first-run backstop the bare lexical match
  lacks.
- **Per-task layer = LEARN.** A miss that survives the oracle and fails grading emits
  `prephase_deep_read[tid]`, read eagerly next run. Convergence in ≤1 extra cycle.
- Accepted residual: a *novel* synonym with no oracle atom and no prior run costs one
  cycle. That is the LEARN design, not a hardcode — and it is logged (no silent miss).

### H3 — D1 identity role list

A role allowlist (`*_coordinator`, `store_manager`, …) → a new role falls through to
`guest`, silently mis-scoping security.

De-hardcode (structural classification only):
- `identity.kind` is decided by **id-shape**, not a role-name list:
  `customer_id` / `cust_*` present → `"customer"`; any other non-empty authenticated id →
  `"employee"` (operational); empty → `"guest"`. A new employee role is `employee` by
  default — the safe direction (does not silently relax customer-scope).
- Finer role semantics, if ever needed, are an oracle atom keyed on `security.md` scope —
  not a code list. D1 emits only the three structural kinds.

**Net:** after H1–H3, `orchestrator.py` carries no domain list. t55 and its whole class
(any entity, any `/proc` layout, any role) are covered by VM-discovery + oracle + LEARN.

## Legacy cleanup (`.env.example` + agent code)

The interpreter cutover (validation gate §2) deletes the CODEGEN/fidelity path; its
config and helpers become dead noise. **Plan now, delete only post-cutover** (gate §2
must pass first — premature deletion would regress the legacy A/B arm).

`.env.example` audit — vars that serve only the legacy path (remove on cutover), vs vars
that stay:

| Var | Disposition |
|---|---|
| `MAX_STEPS` | **legacy-only** after R5 (interpreter uses `INTERPRETER_MAX_STEPS`); keep for legacy arm until cutover, then drop |
| `FIDELITY_TIMEOUT_S` | **drop** — fidelity gate is CODEGEN-only |
| `MAX_TOKENS_CODEGEN`, `MODEL_CODEGEN` | **drop** — no CODEGEN phase |
| `MAX_TOKENS_TEST`, `MODEL_TEST`, `TDD_ENABLED`, `TDD_MOCK_ENABLED`, `TDD_FORCE_SUBMIT_AFTER` | **drop** — TDD gate rode the CODEGEN answer path |
| `MAX_TOKENS_DESIGN`, `MODEL_DESIGN` | **review** — DESIGN survives only if the interpreter keeps a DESIGN call; else drop |
| `COMPACTION_THRESHOLD`, `COMPACTION_KEEP_RECENT` | **keep** — `_compact_learn_ctx` is retained (interpreter LEARN still compacts) |
| `MODEL`, `MODEL_FALLBACK`, `MODEL_LEARN`, oracle `*`, HTTP timeouts | **keep** |
| `INTERPRETER_ENABLED`, `INTERPRETER_MAX_STEPS`, `PREPHASE_*` | **add** (see "Env documentation" under Constants & budgets) |

Code audit — already enumerated by the interpreter plan's cutover step (delete:
`_AnswerGuard`, `_AnswerRefsError`, `_extract_sql_literals`, `_retry_guard_applies`,
`_detect_zero_row_miss`, `_run_intent_tests`, `_mock_run`, `_RETRYABLE_VM_ERROR_PATTERNS`,
`generate_fidelity_test`/`exec_fidelity_in_subprocess`; keep `_is_retryable_vm_error`,
`_ground_security_refs`, `_terminal_clarification`, `_learn_consolidate_text`,
`learn_from_grader`, `_compact_learn_ctx`). This spec only **adds the `.env.example` +
`CLAUDE.md` doc-sync to that same cutover commit** so config and code die together.

DoD: a post-cutover checklist asserts every "drop" var is absent from `.env.example`,
`CLAUDE.md`, and `os.environ.get` call-sites; every "keep" var still resolves.

## Testing

Unit (deterministic, `mock_vm` / `MockVMSpy`, proto + dict tolerant):

| Component | Assertion |
|---|---|
| `_list_entries` / `_stat_kind` | parse `entries[*].path`, `kind`→dir/file/''; no `.stdout` dependence |
| `_extract_path_literals` | any-`/`-path extraction, trailing-punct strip, dedup, cap; non-`/proc` root (`/data/…`) extracted same |
| literal-path fact | dir → listing + byte-budget + "+N more"; file → existence; non-existent (Stat='') → skipped, status empty |
| H1 dir discovery | `/proc` subdir matched by `_list_entries`, NOT `_PROC_DIR` map; unlisted entity still resolves; no prefix allowlist |
| tier split (1.3) | names+DDL uncapped; sample = relevant ∪ `prephase_deep_read`; skipped logged |
| H2 relevance | oracle atom widens set pre-failure; LEARN `prephase_deep_read` covers post-failure miss |
| `identity.kind` (D1/H3) | cust_* → customer; any other non-empty id → employee (incl. unknown role); empty → guest |
| `_plan_signature` / R4 | two identical → break CLARIFICATION |
| R1 namespace | `load_entries(tid, surface="ir")` filters; untagged legacy → codegen |
| R3 | `run_plan(observed=)` renders `OBSERVED_RPC_OUTPUTS` |
| deny_when role-aware | employee → deny_when False (OK); customer mismatch → True (DENIED) |

Integration:
- `scripts/probe_t55_refs.py` as in D4.
- Existing suite stays green (note: `test_t09_replay_matches_known_good` is a known
  pre-existing stale-fixture red, not a regression).

## Constants & budgets

All numeric knobs have a default and an env override (`PREPHASE_*`); none is a
load-bearing magic number — behavior is gated by relevance + LEARN (see "Design
principle" and `prephase_deep_read`). Defaults:

Every knob below is a **cost safety rail** (Stat-probe count, byte budget, cycle
ceiling) — none encodes domain knowledge. There is no path-root list, no entity-prefix
list, no plural map, no role list among them (see "De-hardcoding").

| Constant | Default | Env | Role |
|---|---|---|---|
| `_PATH_LITERAL_CAP` | 3 | `PREPHASE_PATH_LITERALS` | max literal paths Stat-probed per instruction (cost rail) |
| `_PATH_LISTING_BUDGET` | 4096 (bytes) | `PREPHASE_LISTING_BYTES` | byte cap on a rendered dir listing; overflow → `… +N skipped` |
| `_SAMPLE_ROWS_PER_TABLE` | 3 | `PREPHASE_SAMPLE_ROWS` | `LIMIT` per sampled table |
| `_SAMPLE_ROW_MAX_CHARS` | 400 | `PREPHASE_SAMPLE_ROW_CHARS` | per-row byte cap (safety rail) |
| `_INTERPRETER_MAX_STEPS` | 6 | `INTERPRETER_MAX_STEPS` | interpreter cycle ceiling (R5) |
| `INTERPRETER_ENABLED` | `0` | `INTERPRETER_ENABLED` | feature flag selecting the interpreted pipeline branch (already in `pipeline.py:45`; documented here as the cutover gate var) |

Table names + DDL: uncapped (Tier-1). `_SAMPLE_TABLES_MAX` is removed; the sampled
**set** = relevance (table name / entity token present in the instruction, ∪ FK-adjacent
one hop) ∪ learned `prephase_deep_read[tid]`. When relevance yields nothing, pre-phase
stays metadata-only and logs the omission (no silent truncation).

DoD: each constant is read via `os.environ.get(...)` with the default above; a unit
test asserts both the default and one override per constant; every overflow path emits
the documented skip marker.

### Env documentation (user-facing)

The spec previously documented these knobs only in the table above; the runtime vars
were never surfaced to operators. Implementation MUST also:

- Add every row above to **`.env.example`** with its default and a one-line comment
  (currently `.env.example` carries only `MAX_STEPS=5` and nothing for `INTERPRETER_*`
  / `PREPHASE_*`).
- Add an **`INTERPRETER_ENABLED`** + **`PREPHASE_*`** block to the env-var table in
  **`CLAUDE.md`** (the existing table stops at the oracle vars; neither the interpreter
  flag nor any pre-phase knob is listed).
- Note in `CLAUDE.md` that `MAX_STEPS` no longer drives the interpreter loop (R5):
  the interpreter ceiling is `INTERPRETER_MAX_STEPS` (default 6); `MAX_STEPS` is
  legacy-path only.

DoD: `.env.example` and the `CLAUDE.md` env table each list `INTERPRETER_ENABLED`,
`INTERPRETER_MAX_STEPS`, and all four `PREPHASE_*` vars (`PREPHASE_PATH_LITERALS`,
`PREPHASE_LISTING_BYTES`, `PREPHASE_SAMPLE_ROWS`, `PREPHASE_SAMPLE_ROW_CHARS`) with
matching defaults.

## Validation gate (findings §7.7)

1. grader-oracle on t55: 0.0 → 1.0 (ref + outcome) — required before cutover.
2. A/B on the benchmark behind `INTERPRETER_ENABLED`; cut over only if score ≥ baseline
   (~32%) **and** t55 / bucket improve, with no regression on green tasks.

## Implementation order

```
Phase 1 (foundation): P9 parsers -> literal-path -> tier split -> P8
   +- H1 de-hardcode (drop _PROC_DIR/_RECORD_ID_RE -> VM-discovery) rides Phase 1
   +- Phase 3 (D1/H3 structural identity + intent.md, light): supplies OUTCOME_OK
        v together -> t55 0.0 -> 1.0 -> grader-oracle gate
Phase 2 (interpreter debt, independent): R1 -> R2 -> R3 -> R4 -> R5
   +- R2 / prephase_deep_read depends on the Phase 1 tier split
   +- H2 relevance: oracle atom (pre-failure) + LEARN hint (post-failure)
Cutover (gate §2 passes): delete legacy CODEGEN/fidelity code + drop legacy vars (L)
   +- same commit syncs .env.example + CLAUDE.md (Env documentation)
```
