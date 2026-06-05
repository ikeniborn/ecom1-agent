# Intent: knowledge-oracle (validated knowledge bank with semantic retrieval)

**Date:** 2026-06-05
**Status:** approved

## Objective

The current per-task LEARN loop (`data/learned/{task_id}.yaml`) overfits to single-seed
values and gets stuck in local optima. Empirical proof from this session's t01/t38/t51 run:

- The benchmark **re-seeds data every StartRun** — fraud device `dev_CJvA3yBXfGY9mD` →
  `dev_7Uwmwp6ciMdDVu`; receipt VAT 20% → 10%; SKUs and totals all change. Rules that pin
  concrete ids/paths pass once, then break.
- t38 accumulated **35 rules around a wrong hypothesis** ("shared fingerprints") and could
  not escape: the sparse grader signal ("~0% EUR recovered") never reveals the real
  impossible-travel method. The LEARN loop lacks a data oracle.
- Knowledge is **fragmented and duplicated** across tasks ("never vm.read a directory" lives
  in both t38 and t51; "/bin/sql rejects :name binds" and "catalog price_cents is ex-VAT" are
  general but trapped in t51).
- **DESIGN never sees learned rules** (signature is strictly `(instruction, agents_md)`), so
  it keeps hallucinating (`customer_accounts.home_*` join, VAT doc in `/docs`).
- **Compaction** (`THRESHOLD=5/KEEP=3`) crushes 19 rules into one lossy summary, losing method
  precision.

Replace the per-task dump with a **general bank of validated knowledge-atoms** that the agent
queries **semantically, by analyzing the task** — so knowledge generalizes across seeds and
across tasks. "Like levels, but general": the agent keeps proven techniques and pulls the
relevant ones on demand instead of re-deriving every seed.

Why now: this session produced both the proof (re-seeding defeats per-task rules) and the
first validated atoms (a grader-oracle probe pinned the real fraud-detection method and the
t51 ex-VAT/bind facts) — the raw material for the bank already exists.

## Desired Outcomes

- At DESIGN/CODEGEN, the agent analyzes the task and retrieves the **top-k relevant
  knowledge-atoms** by semantic match (atom `description` ↔ task embedding), not a wholesale
  dump.
- Knowledge-atoms are **general** (not `task_id`-bound) and **reused across tasks**; current
  duplicates collapse into one atom.
- An atom enters the bank **only after validation** (confirmed by grader and/or fidelity on
  real data) — no unvalidated overfit.
- t38, t51 (and peers) converge to score **1.0 across re-seeded runs** via retrieved methods,
  not hardcoded values.
- Compaction becomes unnecessary for steering: retrieve k atoms, not the full history.

## Health Metrics

- **t01 stays 1.0** (must not regress).
- `pytest tests/` stays green (esp. `tests/test_design.py` F-001 DESIGN-signature guards).
- Per-task LLM-call budget not inflated (embedding/retrieval cost ≪ one LLM call).
- Existing pipeline phases (DESIGN → CODEGEN → fidelity → answer) keep functioning.
- No new task-specific content leaks into `data/prompts/`.

## Strategic Context

- Interacts with: `agent/pipeline.py` (codegen/learn), `agent/codegen_v2.py`,
  `agent/learned_store.py`, `agent/fidelity.py`, `agent/llm.py`, and a new vector index +
  atom store.
- Also interacts with: the **grader-oracle probe pattern** (StartRun→answer candidate→
  SubmitRun→read score) as the validation source for atoms.
- Priority trade-off: **trust** (only validated knowledge) > cost > speed.

## Constraints

### Steering (behavioral guidance)
- Atoms are **methods/facts** ("fraud archived = impossible-travel, compute geometrically";
  "catalog price_cents is ex-VAT"), never "fix error X seen in seed Y".
- Retrieval is **hybrid**: semantic vectors + domain tags/keywords, so a vector miss has a
  fallback.
- Atom granularity: one reusable technique or fact per atom; tag by domain
  (sql / payments / pricing / vm-io / fraud).

### Hard (architectural enforcement)
- An atom is admitted to the bank **only through a validation gate** (grader pass or fidelity
  on real data).
- **No hardcoded seed values** (device/customer ids, SKUs, paths, amounts) in any atom.
- Do **not** patch `data/prompts/` to fix a task (existing repo rule).
- Changing the **DESIGN signature** to consume the oracle is proposal-first (guarded by
  `tests/test_design.py` F-001); default is to feed the oracle to **CODEGEN only**.

## Autonomy Zones

- **Full autonomy** (reversible, low risk): atom schema, vector index build, retrieval wiring
  into CODEGEN, the grader-oracle validation harness.
- **Guarded** (log + threshold): migrating existing per-task `data/learned/*.yaml` rules into
  general atoms; deduping.
- **Proposal-first** (needs approval): feeding the oracle into DESIGN (signature change);
  removing/disabling the compaction path.
- **No autonomy** (human only): editing `data/prompts/`; deleting the per-task learned store
  before the oracle is proven.

## Stop Rules

- **Halt if:** retrieval regresses t01 below 1.0 or breaks `pytest`.
- **Escalate if:** correctness requires changing the DESIGN signature, or an atom cannot be
  validated without hardcoding seed values.
- **Done when:** the oracle retrieves validated atoms into CODEGEN and t01, t38, t51 each
  reach score 1.0 across **≥2 independently re-seeded runs**.
