# Harness effectiveness — research conclusions & recommendations (2026-06-25)

Branch `determinism`. Conclusions from a pattern-level review of the agent (schema-guided
reasoning, structured output, CoT, ReAct, self-learning, tool use, answer analysis, skill
accumulation, loops) against the 5-phase escape-bias roadmap. Grounded in `agent/*.py`,
`docs/wiki/*.md`, and `docs/superpowers/specs/2026-06-24-escape-bias-elimination-design.md`.

**STATUS (2026-06-25):** Phase 5 + Phase 1 LANDED on `determinism` (range `3378a61..846ea71`, SDD,
merge-ready). The "post-landing evidence" section below records what the full 55-task benchmark and
the t20 trace actually measured, and revises the recommendations against that evidence. The original
Conclusions/Recommendations are kept as-is; ✓/△ annotations mark what the data confirmed or revised.

---

## Post-landing evidence (2026-06-25)

**What shipped.** Phase 5: `main.py` per-task wall-clock deadline + `_collect_with_deadline` +
non-blocking pool teardown (`ECOM_TASK_TIMEOUT_S`); `agent/llm.py` bounded call budget (read 120s,
`ECOM_LLM_MAX_RETRIES`=2 ⇒ worst 360s < 600s cap). Phase 1: `agent/resolve.py`
(`normalize_value`/`relax_sql`/`literal_from_prose`/`resolve_product`); A-seat interpreter auto-relax
of a 0-row read-only `/bin/sql` discovery step; B-seat INVESTIGATE descriptor-probe binding the
resolved entity into `Brief.env`; `sufficient()` blocks on an unresolved key-entity `record_path`.

**Phase 5 — VALIDATED AT SCALE (the headline).** The full 55-task run COMPLETED (76 min,
deepseek-v4-flash) — prior full runs HUNG. The deadline-abandonment path fired in production:
`[run] 7 task(s) exceeded 3720s deadline — abandoned, submitting the rest` → 48 scored, `SubmitRun`
reached. The 7 abandoned were weak-model thrashers (cycles 8–10, 1748–2392s each), bounded by the
Task-1 cap and dropped cleanly instead of freezing the pass. `pass_deadline=3720=600·6+120` ⇒ lanes=10
(`ECOM_PARALLEL_TASKS=10`), confirming the lane-aware deadline formula. **This is the load-bearing
win: a clean scored run is now always possible, the precondition for every later phase's measurement.**

**Phase 1 — mechanisms fire; residual is beyond relax_sql.** On t20 (B1 product task) the trace shows
BOTH seats firing: the A-seat relaxed PLAN's own 0-row query
(`pv.brand='Dulux' AND pv.series='Quick Dry Weathershield' AND pv.model='2ZJ-R8R' …` →
`LOWER(TRIM(…))`), and the B-seat probe ran its exact→relaxed `_product_select` ladder. But every
query — exact and relaxed — returned EMPTY, so the entity genuinely did not resolve and the agent
honestly emitted `OUTCOME_NONE_UNSUPPORTED`. The miss is NOT case/unit/whitespace skew (relax_sql's
scope); it is a deeper descriptor↔stored-value mismatch (re-seed / schema / synonym). **This is exactly
the information-preserving boundary predicted in Conclusion 2 — confirmed by measurement, not theory.**

**A-seat vs B-seat (measured).** The A-seat (relax PLAN's own query) is load-bearing and correct: PLAN
wrote the right schema query. The B-seat probe's `descriptors_from_intent` heuristic is confirmed weak
— on t20 it mis-mapped the brand into a property filter (`property_key='lookup' AND
property_value_text='Dulux'`) instead of `pv.brand`. As designed this is non-load-bearing (the A-seat
covered the dominant case), but it is a concrete DETERMINISTIC improvement target (below), separate
from any embedding work.

**Full-run outcome distribution (the meaningful signal — score is model-floored).** FINAL 2.08%
(1/48 pass: t21), consistent with the prior ~3.64% weak-model floor; the matched-model control
([[project_ir_error_determinism_ab]] in repo memory) already proved the determinism changes carry
**0 benchmark delta**. Submitted outcomes (got): **28 `NONE_CLARIFICATION`, 22 `NONE_UNSUPPORTED`,
4 `DENIED_SECURITY`** (expected: 42 `OK`, 12 `DENIED_SECURITY`). Classified:
- **~22 UNSUPPORTED give-ups (expected OK)** = B1 resolve misses. Normalization-class now caught by
  relax_sql; the residual is synonym/schema/re-seed (beyond relax_sql) — see boundary above.
- **~28 CLARIFICATION (mostly expected OK)** = under-spec / non-convergence; several thrashed to
  cycles 8–10. Loop convergence, not entity resolution, is the lever here.
- **~6 wrong-refusal-type**: under-refuse (expected DENIED → CLARIFICATION/UNSUPPORTED: t24/t25/t28/
  t29/t34/t37) and over-refuse (expected OK → DENIED: t27/t33). Phase 2/4 territory, untouched here.

**Revised recommendations (against the evidence).**
1. **Phase 1 next lever is NOT embeddings yet — it is the descriptor map + the residual classifier.**
   The A-seat already relaxes PLAN's query; the measured residual is (a) the B-seat's weak
   `descriptors_from_intent` key→column mapping (deterministic fix: have INTENT emit structured
   descriptors, or strengthen the substring map / add a column-name probe), and (b) genuine
   beyond-normalization misses. Add a deterministic unit-conversion table next (still
   information-preserving). Only AFTER measuring what survives both should an embedding-match layer be
   considered — as a SEPARATE spec with a high floor + the ownership guard + its own A/B (Conclusion 4
   holds, now evidence-backed).
2. **Convergence guard belongs with Phase 5.** ~28 CLARIFICATION + the cycles-8–10 thrashers show the
   loop burns budget without converging on a weak model. The per-task cap bounds the damage; a
   convergence/early-give-up signal (or a stronger model) would reclaim those tasks. The deadline is a
   backstop, not a fix for non-convergence.
3. **Measurement discipline confirmed (Conclusion 6).** The absolute score is a weak-model floor;
   every phase claim needs a matched-model control, and a meaningful absolute number needs a stronger
   model. That model choice — not more determinism code — is the path to the 80–90% goal.

## Conclusions

1. **All named patterns are already built.** The spine is the **"muxx exoskeleton"**: every LLM
   judgment that maps to a grader-observable is wrapped in a deterministic code gate — LLM proposes
   (PLAN refs/outcome/format), code disposes (`grounding` / `decide` / `format_gate` / `verify`).
   The 5-phase escape-bias work is the **maturation roadmap of these patterns**, not a bug list.

2. **Exoskeleton ceiling.** Code gates are ideal for *enforcement* (refs/outcome/format). Phase 1 is
   the first *semantic* gate. The determinism boundary is **where a transform is
   information-PRESERVING** (case/whitespace/unit-strip/numeric-cast, and unit-conversion via a
   table). Synonym/category matching is information-ADDING — it needs an LLM/embedding and carries a
   false-cite risk the exoskeleton was built to avoid. ✓ CONFIRMED — t20's relaxed query still
   returned empty; the residual miss is information-adding, exactly this boundary.

3. **Phase 3 = the deepest shift.** An execution-grounded typed chain *is* ReAct with deterministic
   glue and Pydantic schemas — ReAct's flexibility moves from `investigate` into `plan`, constrained
   by schemas. It cures B1 blindness because each LLM step sees real rows, not a guess.

4. **Embedding-match for entity resolution is not yet justified.** False-cite is worse than
   UNSUPPORTED; the benchmark re-seeds (thresholds won't hold); most B1 is formatting skew that
   `relax_sql` should clear. Decide only on the measured residual. △ REVISED — residual now measured:
   relax_sql landed but the dominant survivor is descriptor↔column mismatch, not formatting; fix the
   descriptor map + add a unit-table BEFORE embeddings (post-landing §, rec 1).

5. **Contradiction ≠ duplication.** Embedding/cosine dedup collapses true duplicates but is wrong
   for contradictions — negation does not move embedding distance, so "do X on empty" and "do NOT X
   on empty" look near-identical. Contradiction detection needs the outcome semantics, not text
   similarity.

6. **Measurement discipline is mandatory.** Matched-model control only — deepseek-flash baseline is
   ~3.64%, not the 32% of a stronger model. Each phase gets an independent scored re-run on one
   model, or a model swap reads as signal. ✓ HELD — full run 2.08% (1/48) is a weak-model floor;
   matched-model control already showed 0 determinism delta, so the floor is the model, not the code.

7. **Phase dependencies fix the order (5→1→2→3→4).** Phase 1 feeds Phase 3 (resolve-spec consumes
   the resolved entity). Phase 4 protects Phase 1/2 (its tie-break locks in the anti-escape bias).

---

## Recommendations

**Phase 1 — boundary.** Land `relax_sql` (information-preserving normalization only). Then measure
the residual B1 misses and classify them: formatting (done), unit-conversion (add a deterministic
conversion table — still general), or genuine synonyms (only then an embedding-match layer, as a
*separate* spec with a high floor + the ownership guard + its own A/B). Never grow `relax_sql`
per-case. △ DONE/REVISED — relax_sql + both seats landed and measured; the next deterministic lever is
the descriptor map (B-seat mis-mapped on t20) + a unit-table, embeddings only after that (post-landing § rec 1).

**Phase 3 — chain (flag-gated).** Decompose only PLAN into resolve-spec → compute-spec →
answer-spec, interleaved with deterministic interpretation between stages; a thin assembler stitches
the sub-specs back into one `PlanIR` so `interpret → ground → decide → format → verify`,
`_plan_signature`, and iLEARN run unchanged. Keep INTENT a single frozen call. answer-spec collapses
to near-nothing (outcome/surface/refs are already exoskeleton-owned). Measure chain cost (calls,
tokens, cycles) **under** the Phase-5 task cap, A/B vs the monolith on a matched model.

**Phase 4 — contradiction-detector (option B).** Add optional `trigger_signature` +
`outcome_guidance` to `LearnConsolidateOutput`; have the already-running iLEARN call emit them.
Contradiction = same `trigger_signature` ∧ different `outcome_guidance` → deactivate the loser, with
an **anti-escape tie-break** (when a typed answer was computed, keep the OK-favoring rule). Run this
before the existing cap-trim (semantic before recency). Degrades safely to current behavior on a
normalization miss. Validate against t20's r001↔r006 oscillation.

**Phase 2 — proactive denial.** Move spurious-denial correction from reactive `verify`-reject to
proactive `decide`-rewrite: downgrade a PLAN-authored `OUTCOME_DENIED_SECURITY` with no holding
`deny_when` to the next ladder outcome; preserve denials backed by a holding predicate.

**Sequencing.** After Phase 5 + Phase 1 land: run a full matched-model pass, record the before/after
submitted-outcome distribution and the residual B1 classification — that measurement gates the
Phase-1 follow-up and the Phase-3 spike.
