# Agent debug — intermediate findings (2026-06-14)

Branch `heuristics`. Focus: low quality, deep recursion, repeated errors, weak tests.
**Primary mode under debug: INTERPRETER path (INTENT→PLAN→interpret→verify).** Legacy A/B'd alongside.

## 1. Pre-phase (input the agent receives)

Entry `orchestrator.py:run_agent()`. Inputs: `task_text` (instruction), `/AGENTS.MD`, VM + bin tools.
`gather_prephase_facts` collects 7 facts (all best-effort, error → `""`):
schema, sample_rows, identity (`/bin/id` regex), docs_inventory (`tree /docs level=2`),
policies (security.md always + only path-named `/docs/*.md`), target_records (baskets/payments only).

**Defect A — facts wasted in legacy.** `run_pipeline` receives `facts` but the legacy body
ignores it; only `_run_interpreted` consumes it. DESIGN sees just `instruction + agents_md(+schema+sample_rows)`.
→ A/B is unfair: legacy handicapped on input, not architecture.

**Defect B — no semantic doc discovery (hits both paths).** Pre-phase reads docs named by *path*;
docs named by *topic* (catalogue-addenda, counting policies) never read. t09 needs
`/docs/catalogue-addenda/2025-06-22-reporting-wood-drywall-screws.md`; instruction never names it.
Legacy: zero chance (no inventory). Interpreter: doc appears in `docs_inventory` tree, but relies on the
model spotting+reading it. → failure bucket B; **t09 = 0.00 (answer missing required reference).**

**Defect C — narrow probes.** target_records only baskets/payments (no stores/employees/returns/orders);
identity is a fragile regex.

## 2. Interpreter loop / recursion (`_run_interpreted`)

Loop: `for cycle in 1..MAX_STEPS: PLAN(LLM) → lint → interpret → verify → answer-once`, LEARN between.

**R1 — no cross-run learning.** `learn_ctx = []` at start (line ~302); never `load_entries`.
`_ilearn` writes rules to `data/learned/{tid}.yaml` (apply_learn_diff) that the interpreter path
**never re-reads**. → same mistakes repeat run after run. Write-only LEARN.

**R2 — LEARN prompt mismatched.** `learn.md` is CODEGEN-framed ("rule_content must describe a CODEGEN
technique… translate tool_plan to script"). Interpreter artifact is PlanIR JSON, no script. → distilled
rules low-value / skipped → weak corrective signal.

**R3 — PLAN regen blind to runtime data.** `run_plan(intent, facts, learn_ctx, prev_error)` gets no
`observed`. Runtime RPC stdouts (which explain the failure) feed LEARN only, reaching PLAN solely through
a distilled rule. If LEARN skips, PLAN re-plans with a one-line error string. → thrash.

**R4 — no identical-plan short-circuit.** Legacy has `check_retry_loop` (3 identical SQL → break).
`_run_interpreted` has no analog → burns all MAX_STEPS on identical-plan thrash.

**R5 — MAX_STEPS=10** (active env; code default 3) amplifies R1–R4. Each cycle = PLAN LLM + interpret +
verify + LEARN LLM.

**R6 — frozen INTENT is unrecoverable (structural).** INTENT runs once, frozen. VERIFY checks the answer
against the frozen `success_criteria` / `answer_shape`. If INTENT mis-specifies (e.g. `required_ref_kinds
=["runtime"]` for a pure-count task), **every** PLAN fails verify → deterministic recursion to exhaustion →
CLARIFICATION. No PLAN retry can fix a bad INTENT. INTENT quality gates everything downstream.

**R7 — verify treats `/docs/*` as static-only.** `verify.py:27` `non_static = [r for r in refs if not
str(r).startswith("/docs/")]`. Tasks whose required grounding ref IS a `/docs` path (t09 addenda) can't
satisfy I1's runtime-ref demand → verify/grader mismatch.

## 3. R6 deep-dive — INTENT is the root lever (real t09 artifacts)

Read persisted `data/heuristics/t09.{intent,plan}.json` (a different seed than the trace — intent
objective says "Nut Bolt and Washer", trace asked "Wood and Drywall Screw" — but the failure
STRUCTURE is seed-independent).

**INTENT froze:** `answer_shape.required_ref_kinds=["runtime"]`; `success_criteria = [kind_id nonempty,
product_count ge 0]`; `constraints` = two generic AGENTS.MD lines (`security:false, deny_when:null`).
**PLAN dutifully bound** `refs=["$sample_path"]` (a `product_variants.record_path` via `MIN(v.record_path)`).

**Smoking gun — verify green-lights a wrong answer:**
- I1 wants a non-`/docs` runtime ref → `$sample_path` satisfies it. ✅
- success_criteria: `kind_id nonempty` ✅; `product_count ge 0` is **always true** (tautology) ✅.
- → verify GREEN → submit → **grader REJECTS: missing `/docs/catalogue-addenda/…md` ref.**

The loop never even recursed here — it passed a bad gate on cycle 2. Same blind spot in legacy
(intent-tests green → 0.00). Neither gate knows the addenda doc is required.

**Why INTENT is the highest lever:**
1. INTENT is *frozen* and *upstream of every gate*. verify I1/I2/I3 + success_criteria are all DERIVED
   from it. Under-specify → verify too lenient → wrong answer shipped (t09 false-green). Over/mis-specify
   (e.g. `required_ref_kinds=["runtime"]` on a task whose real grounding is a `/docs` path, or an
   unsatisfiable criterion) → verify too strict → every PLAN fails → recursion to exhaustion. Both
   unrecoverable in-run (INTENT never re-runs; PLAN only reshapes HOW).
2. **success_criteria are weak/tautological** (`ge 0`) — near-zero acceptance signal; they can't encode
   the correct count (no oracle) nor the real grader requirement (cite the addenda).
3. **constraints are noise** — picked two inert generic lines, missed the actionable counting policy
   (which pre-phase never surfaced → Defect B).
4. **Architectural tension:** INTENT freezes acceptance BEFORE discovery runs. For bucket-B tasks
   (policy/counting/grounding) you cannot know the correct grounding until discovery reveals which doc/
   record applies — yet acceptance is already frozen. Frozen-INTENT assumes acceptance is knowable from
   `facts + instruction` alone; for a whole task class it is not. This undercuts the "VERIFY re-derives
   from the frozen fact-grounded IntentSpec" killer-property: re-derivation is only as strong as INTENT's
   grounding, and INTENT is under-grounded exactly where it matters.

## Through-line

Quality is gated by two upstream, frozen artifacts the loop cannot repair: the **pre-phase fact set**
(misses topic-relevant docs) and the **frozen INTENT** (one bad spec = full-budget recursion). The LEARN
feedback loop that is supposed to recover is write-only (R1) and mis-framed (R2), so recursion rarely
converges — it exhausts.

## 4. Decision (2026-06-14)

**Direction = Approach A.** INTENT is the execution base and MUST stay frozen — mutating it after a cycle
is illogical (it is the contract the whole run derives from). Therefore Approach B (re-grounding INTENT
post-discovery) is **rejected**. The fix is UPSTREAM: harden the pre-phase so it gathers *every artifact
needed to form a high-quality INTENT the first time*. A quality frozen INTENT then makes verify honest and
the loop convergent. Cheap "stop-the-bleed" loop fixes (R1/R4/R5) remain welcome but secondary.

## 5. Consolidated problem register (ALL findings)

Pre-phase (input → quality INTENT):
- **P1 / Defect B — `policies` path-named only** (`orchestrator.py:157-167`). Reads `/docs/security.md`
  always + only `/docs/*.md` whose path is literally in instruction/agents_md. Topic/entity-relevant docs
  (catalogue-addenda, counting/business policy) never read. **ROOT of t09 0.00 and failure-bucket B.**
- **P2 — `docs_inventory` shallow + unstructured** (`orchestrator.py:150-153`): `tree(/docs, level=2)`
  raw string. May miss deeper docs; INTENT must eyeball-match entity → filename.
- **P3 — `target_records` narrow** (`orchestrator.py:169-180`): only baskets/payments, regex over
  instruction. Misses stores/employees/returns/orders/product records and entity-named (non-ID) targets.
- **P4 — `identity` fragile regex** (`orchestrator.py:108,114-115`): `(\w+)=([^\s]+)` over `/bin/id`;
  format drift → silent empty → security constraints/outcome_space under-grounded.
- **P5 — schema/sample caps** (`orchestrator.py:27-29`): 12 tables / 3 rows / 400 chars. May truncate the
  exact table/columns INTENT needs.
- **P6 — silent-fail everywhere (`→ ""`)**: every gather step swallows exceptions. INTENT cannot tell
  "no such fact" from "fetch failed" → confident-wrong INTENT on a silently-missing fact. No missing-fact
  signal.
- **P7 / Defect A — legacy discards `facts`** (`pipeline.run_pipeline` ignores the `facts` param outside
  `_run_interpreted`). A/B is unfair; legacy DESIGN flies on instruction+agents_md+schema only.
- **P8 — no facts→INTENT sufficiency check** before the spec is frozen.
- **P9 / NEW (grader-oracle confirmed 2026-06-14) — `docs_inventory` is SILENTLY EMPTY.**
  `vm.tree` returns `TreeResponse { TreeNode root = 1; }` (proto/bitgn/vm/pcm.proto) — there is NO
  `.stdout` field. Orchestrator extracts `docs_inventory = _extract_text(t, "stdout")`
  (`orchestrator.py:150-153`) → always `""`. So the interpreter's claimed advantage ("INTENT sees
  docs_inventory") is **illusory** — INTENT receives an empty inventory; neither path can spot the
  topic-relevant doc. This compounds P1 and is a direct cause of t09 failing in BOTH paths.
  **Fix: build the inventory from `Search` (`SearchMatch.path`) or a recursion over `TreeResponse.root`
  (`TreeNode{name,is_dir,children}`), NOT `tree`.`stdout`.** Avoid VMAdapter `Find(kind=…)` — `FindRequest`
  field is `type` (int32), the `kind=` kwarg yields empty. (Read is fine: `ReadResponse { content }`,
  already used for `policies`.) See §7.1 for the chosen discovery design.

### Grader-oracle CONFIRMATION (probe run 2026-06-14, seed entity "Nut Bolt and Washer")
`scripts/probe_t09_refs.py`, one fresh StartRun. Answered `3` + `refs=[]` → **SCORE 0.0**, detail:
`answer missing required reference '/docs/current-updates/catalogue-counting-2025-06-22-nuts-bolts-washers-graz.md'`.
- **G1 EMPIRICALLY CONFIRMED:** the grader's required grounding ref is a **`/docs` path**. verify's
  "`/docs` = static, never the runtime ref" model (`verify.py:27`) is wrong → the projected-refs fix (7.4)
  must let a `policy_doc` literal satisfy the requirement.
- Required doc lives under **`/docs/current-updates/`** (not `catalogue-addenda/`), name re-seeded with a
  date + kind-slug + city token (`...-graz.md`). Entity is re-seeded too → DOC-SELECT must match by the
  CURRENT instruction's entity, never a remembered path.
- Grader complained ONLY about the missing ref (count `3` not flagged) — suggestive that a naive
  per-kind count may be correct, but the grader may short-circuit on the first failure; unconfirmed.
- Probe tree-empty was a probe bug (wrong field), but it surfaced the real P9 orchestrator bug above.

### Grader-oracle CONFIRMATION #2 (probe v3, seed "Nut Bolt and Washer", Vienna)
Cited the addenda doc + naive count `3` → **SCORE 0.0, detail `Answer should be "2"`**. The *missing-
reference* complaint VANISHED once the `/docs` path was in refs.
- **G1 FULLY CONFIRMED — a `/docs` path IS an accepted required ref.** The projected-refs design (7.4,
  `policy_doc` literal) is validated end-to-end on the live grader.
- **Discovery works two ways (both verified live):** `Search(root="/docs", pattern=<kind>)` →
  `SearchMatch.path` (absolute), and tree-walk of `TreeResponse.root` (TreeNode{name,is_dir,children})
  recursion. **Neither uses `.stdout`** — confirms P9. `/docs` had 12 files this seed; Search by the kind
  name pinned the exact addenda in one call. (`FindRequest` field is `type` int32, NOT `kind` — VMAdapter's
  `kind=` kwarg silently yields empty Find; prefer Search/tree-walk.)
- **NEW DEEP FINDING — the doc is load-bearing for COMPUTATION, not just citation.** The addenda's rule
  ("count only SKUs with ≥1 inventory row in an OPEN PowerTool store in Vienna, available_today_quantity>0,
  each SKU once") changes the answer: naive per-kind `COUNT(*)`=3, rule-correct=2. So Approach A must do
  MORE than cite the doc: **the doc CONTENT must be read in pre-phase and the doc's eligibility RULE must
  be APPLIED when computing the answer.** Citation alone fixes G1 (the ref) but not the value; the doc
  governs both. **Layering (corrected — see §8): pre-phase reads the doc → PLAN (SDD) applies the rule to
  build the SQL → INTENT (IDD) only requires the doc's citation + declares the outcome; INTENT does NOT
  bake the SQL recipe.** Reading doc CONTENT (not just paths) is mandatory.

### Grader-oracle CONFIRMATION #3 — END-TO-END 1.0 (probe v4, seed "Tool Box and Bag", Vienna)
The full Approach-A chain, executed by hand in the probe, scored **1.0** on a task that is 0.00 in prod:
1. `Search(/docs, "Tool Box and Bag")` → `/docs/current-updates/catalogue-counting-2025-06-22-tool-boxes-bags-vienna.md` (doc dir re-seeds: `current-updates` here vs `catalogue-addenda` earlier).
2. `Read` doc → parse `product_kind_id: tool_boxes_bags` + city `Vienna` from the rule text.
3. Rule SQL: `COUNT(DISTINCT v.product_sku) FROM product_variants v JOIN store_inventory si ON
   si.product_sku=v.product_sku JOIN stores s ON s.store_id=si.store_id WHERE v.product_kind_id='tool_boxes_bags'
   AND si.available_today_quantity>0 AND s.is_open=1 AND s.city='Vienna'` → **1**.
4. Answer `"1"` + `refs=['/docs/current-updates/...md']` → **SCORE 1.0**.

**Approach A is empirically validated end-to-end.** The chain pre-phase-discover-doc → read-rule →
PLAN-applies-rule-SQL (SDD) + INTENT-requires-citation (IDD) → cite-doc-path turns a production 0.00 into
1.0. Schema
(`product_variants`, `store_inventory{available_today_quantity}`, `stores{city,is_open}`) is seed-stable;
entity, city, doc dir/name, and answer format re-seed. Reproducible harness: `scripts/probe_t09_refs.py`.

### Net contract (proven)
1. Required ref = the applied policy/business `/docs` doc path (+ matched record path for record tasks).
   Citing it satisfies the grader (ref complaint disappears). ✅ live-confirmed.
2. Extra refs penalized (memory t29/t45) — not re-confirmed this session.
3. The doc's rule governs the COMPUTED answer; naive computation fails the value check even with the ref.
4. Discovery: Search-by-content or tree-walk; NOT `tree`.`stdout` (empty), NOT VMAdapter `Find(kind=...)`.
5. Entity, answer format string, and doc path/name ALL re-seed per StartRun → resolve from THIS run only.

INTENT quality (R6 cluster, gated by the above):
- **R6 — frozen INTENT unrecoverable**: under-spec → verify false-green (t09); over/mis-spec → recursion
  to exhaustion. PLAN reshapes HOW, never the WHAT/acceptance.
- success_criteria tautological (`ge 0`); constraints picked inert generic lines; required_ref_kinds wrong
  grounding (runtime record_path vs the real `/docs` addenda).

Loop / recursion / repeated errors (interpreter path):
- **R1 — `learn_ctx=[]` every run**, persisted IR rules never re-loaded (write-only LEARN).
- **R2 — LEARN prompt CODEGEN-framed**, mismatched to PlanIR artifact.
- **R3 — PLAN regen blind to runtime `observations`** (they feed LEARN only).
- **R4 — no identical-plan short-circuit** (legacy `check_retry_loop` has no interpreter analog).
- **R5 — MAX_STEPS=10** amplifies R1–R4.

verify / test quality:
- **R7 — verify treats `/docs/*` as static-only** (`verify.py:27`); tasks whose grounding ref is a
  `/docs` path can't satisfy I1's runtime-ref demand → verify/grader mismatch.

## 6. Pre-phase audit — what a quality INTENT needs vs what pre-phase delivers

| IntentSpec field | Grounding fact needed | Delivered? | Gap |
|---|---|---|---|
| `objective` | instruction | ✅ | — |
| `params` (methods) | schema, sample_rows | ✅ (capped) | P5 |
| `outcome_space` | applicable policy docs | ⚠️ partial | P1 |
| `constraints` + `deny_when` | AGENTS.MD + policy docs + identity | ⚠️ partial | P1, P4 |
| `success_criteria` | business/counting policy doc | ❌ | P1 |
| `answer_shape.required_ref_kinds` | which doc/record is the grounding | ❌ | P1, P3 — **t09 killer** |

Conclusion: the pre-phase reliably grounds only the *mechanical* half of INTENT (objective, params from
schema). The *acceptance* half (outcome_space, constraints, success_criteria, required grounding) depends
on policy/business docs and target records that the pre-phase gathers narrowly (path-named docs, ID-named
baskets/payments) and silently (P6). Approach A = close this gap.

## 7. Approach A — final design (agreed + corrected 2026-06-15)

> Sections 7.1–7.7 below supersede any earlier wording in this file. Earlier confirmation paragraphs
> (§5) that said "INTENT must translate the rule into params" are corrected by the IDD/SDD layering (§8).

### 7.1 Doc discovery — deterministic Search primary, LLM fallback (closes P1, P9)
Resolved (Detail #1): the doc echoes the task entity verbatim, so **deterministic content Search finds it
with 0 LLM** — proven live (`Search(/docs, "Tool Box and Bag")` → exact doc, one call).
- **Inventory / discovery via `Search` + tree-walk, NEVER `tree`.`stdout`** (P9: `TreeResponse{TreeNode
  root}` has no stdout → today's `docs_inventory` is always `""`). Build the candidate set from
  `SearchMatch.path` and/or a recursion over `TreeResponse.root` (`TreeNode{name,is_dir,children}`).
  Do NOT use VMAdapter `Find(kind=...)` — `FindRequest` field is `type` (int32), the `kind=` kwarg yields
  empty.
- **Primary:** extract salient entity tokens from the instruction → `Search(root="/docs", pattern=…)` →
  read top **≤3** hits' CONTENT into `policies` (+ `/docs/security.md` always + any path-named docs).
- **Fallback (only when Search is empty/thin):** one cheap LLM **DOC-SELECT** call (`MODEL_LEARN`,
  cap 4) — `instruction` + tree-walk inventory → `{"docs":[…]}`, filtered to paths that exist. Never
  fails the run. So the +1 LLM call does NOT happen in the typical case.
- Doc content stored with a size cap (≈4 KB/doc) to bound INTENT context.

### 7.2 recall / precision split
- **Discovery (Search/fallback) = recall**: surface candidate docs broadly.
- **INTENT = precision**: from the content, declare which docs are *load-bearing* → only those become
  `required_refs`. Reading a doc ≠ obligation to cite it.

### 7.3 verify ↔ grader ref contract (G1/G2) — CONFIRMED live
Old verify model is a wrong binary `static=/docs` vs `runtime=non-/docs` (`verify.py:27`); it hard-codes
"/docs is never the grounding" — false. **Grader contract confirmed live this session:** the required ref
is the applied policy/business `/docs` path (citing it removes the complaint); extra refs are penalized
(memory t29/t45, not re-confirmed this session).
- **G1 (under-citation / R7):** required `/docs` ref not credited → t09 false-green. → fixed by 7.4.
- **G2 (over-citation):** grader penalizes extras → fixed structurally by 7.4 (PLAN can't add refs).

### 7.4 refs are PROJECTED from INTENT.required_refs, per-outcome — NOT authored by PLAN
Dissolves the strict-`==` vs superset dilemma (superset ships penalized extras; strict `==` false-reds on
under-declaration).
- **INTENT** declares `required_refs`, **keyed by outcome** (Detail #2 — INTENT speaks outcomes, PLAN
  speaks labels; label→outcome via the answer template):
  ```json
  "required_refs": {
    "OUTCOME_OK":              [{"kind":"policy_doc","path":"/docs/…md"},
                                {"kind":"record_path","source":"$matched.record_path"}],
    "OUTCOME_DENIED_SECURITY": [{"kind":"policy_doc","path":"/docs/security.md"},
                                {"kind":"record_path","source":"$basket.record_path"}]
  }
  ```
  - `policy_doc.path` — literal, known at INTENT (from discovery).
  - `record_path.source` — a `$ref` binding; the literal `/proc/.../<id>.json` resolves at runtime.
  Replaces the flat `AnswerShape.required_ref_kinds`.
- **PLAN** supplies only the bindings (SQL, the record_path column) — does NOT author `answer.refs`.
- **Interpreter** assembles `answer.refs := [resolve(r) for r in required_refs[selected_outcome]]`.
- **verify** checks each required ref of the selected outcome resolved non-empty. `refs == required` holds
  by construction → G1 and G2 vanish structurally. The `/docs`=static heuristic is deleted.
- Residual risk = INTENT under-declaring → pure INTENT quality (where Approach A invests), not a verify
  heuristic.
- **Blast radius:** `ir_models.py` (`IntentSpec.required_refs` per-outcome; drop `required_ref_kinds`),
  `intent.md`, `plan.md` (drop PLAN-authored refs), `interpreter.py` (ref projection + refuse-invariant),
  `verify.py` (I1 rewrite, delete /docs heuristic). Medium but clean.

### 7.5 Secondary pre-phase hardening (fold in)
- P3 broaden `target_records` beyond baskets/payments (stores/employees/returns/orders/product records).
- P4 robust `/bin/id` parse (less regex-fragile).
- P6 missing-fact signal (Detail #4): add `gather_status: dict[str,str]` to `PrePhaseFacts`
  (fact → `ok`/`empty`/`error`), surfaced in `_facts_block`, so INTENT distinguishes "no fact" from
  "fetch failed" (no silent `""`).
- P7 Defect A (legacy discards `facts`) — pass facts to DESIGN too for a FAIR A/B (secondary; interpreter
  is primary mode).

### 7.6 Out of scope for Approach A (separate follow-up)
Loop mechanics R1 (load persisted IR rules), R4 (identical-plan guard), R5 (MAX_STEPS down), R2/R3 (LEARN
reframe + feed observations to PLAN). Cheap "stop-the-bleed" wins, but Approach A targets the root
(under-grounded acceptance), not the recursion symptom.

### 7.7 Validation gate
- Grader ref contract re-confirmed live this session (t09 0.00→1.0). A DENIED-task re-confirm still nice-
  to-have but lower priority.
- A/B on benchmark behind a flag; cutover only if score ≥ baseline (~32%) AND t09/bucket-B improve, no
  regression on green tasks.

## 8. IDD/SDD layering (authoritative — corrects the §5 "INTENT encodes the rule" drift)

Concern raised + accepted: making INTENT digest the counting recipe (kind_id/city/joins) turns INTENT into
an SDD/design step and blurs the IDD↔SDD boundary. Corrected, clean separation:

```
PRE-PHASE (inputs)      : discover (Search/tree-walk) + Read doc → policies.content (+ gather_status)
        │
INTENT (IDD: WHAT/why)  : objective, outcome_space, constraints, required_refs (cite the governing doc +
        │                 record), success_criteria = STRUCTURAL/grounding ONLY (e.g. count is a
        │                 non-negative integer; answer cites the doc). Does NOT bake SQL/join/kind_id/city.
        ▼
PLAN (SDD: HOW)         : reads the eligibility rule from facts.policies → builds the rule-correct
        │                 discovery/SQL (parse kind_id+city, join store_inventory/stores, filters).
        ▼
INTERPRET → VERIFY      : structural + grounding + outcome checks (NOT value-correctness).
```

Rationale:
- INTENT stays thin IDD ("what must hold + what it must be grounded in"), no recipe.
- PLAN already receives `facts` (policies in `_facts_block`) → it can read the rule. Data already flows
  to the right layer; no new plumbing.
- **Re-seed safety strengthens:** INTENT bakes no kind_id/city literals; PLAN parses them from the doc at
  runtime.
- VERIFY is not a value oracle — it guards structure/grounding/outcome; value-correctness comes from PLAN
  applying the rule, checked post-hoc by the grader. The killer-property (independent re-derivation of the
  security verdict from `constraints.deny_when`) is about DENIED, untouched.
- vs §5 confirmation language: the doc is still read in pre-phase and cited (G1 intact); the RULE is
  applied by PLAN, not digested by INTENT.
