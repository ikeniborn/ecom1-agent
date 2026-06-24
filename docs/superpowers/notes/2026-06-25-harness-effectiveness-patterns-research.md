# Harness effectiveness — research conclusions & recommendations (2026-06-25)

Branch `determinism`. Conclusions from a pattern-level review of the agent (schema-guided
reasoning, structured output, CoT, ReAct, self-learning, tool use, answer analysis, skill
accumulation, loops) against the 5-phase escape-bias roadmap. Frozen here; resume after Phase 5 +
Phase 1 land. Grounded in `agent/*.py`, `docs/wiki/*.md`, and
`docs/superpowers/specs/2026-06-24-escape-bias-elimination-design.md`.

---

## Conclusions

1. **All named patterns are already built.** The spine is the **"muxx exoskeleton"**: every LLM
   judgment that maps to a grader-observable is wrapped in a deterministic code gate — LLM proposes
   (PLAN refs/outcome/format), code disposes (`grounding` / `decide` / `format_gate` / `verify`).
   The 5-phase escape-bias work is the **maturation roadmap of these patterns**, not a bug list.

2. **Exoskeleton ceiling.** Code gates are ideal for *enforcement* (refs/outcome/format). Phase 1 is
   the first *semantic* gate. The determinism boundary is **where a transform is
   information-PRESERVING** (case/whitespace/unit-strip/numeric-cast, and unit-conversion via a
   table). Synonym/category matching is information-ADDING — it needs an LLM/embedding and carries a
   false-cite risk the exoskeleton was built to avoid.

3. **Phase 3 = the deepest shift.** An execution-grounded typed chain *is* ReAct with deterministic
   glue and Pydantic schemas — ReAct's flexibility moves from `investigate` into `plan`, constrained
   by schemas. It cures B1 blindness because each LLM step sees real rows, not a guess.

4. **Embedding-match for entity resolution is not yet justified.** False-cite is worse than
   UNSUPPORTED; the benchmark re-seeds (thresholds won't hold); most B1 is formatting skew that
   `relax_sql` should clear. Decide only on the measured residual.

5. **Contradiction ≠ duplication.** Embedding/cosine dedup collapses true duplicates but is wrong
   for contradictions — negation does not move embedding distance, so "do X on empty" and "do NOT X
   on empty" look near-identical. Contradiction detection needs the outcome semantics, not text
   similarity.

6. **Measurement discipline is mandatory.** Matched-model control only — deepseek-flash baseline is
   ~3.64%, not the 32% of a stronger model. Each phase gets an independent scored re-run on one
   model, or a model swap reads as signal.

7. **Phase dependencies fix the order (5→1→2→3→4).** Phase 1 feeds Phase 3 (resolve-spec consumes
   the resolved entity). Phase 4 protects Phase 1/2 (its tie-break locks in the anti-escape bias).

---

## Recommendations

**Phase 1 — boundary.** Land `relax_sql` (information-preserving normalization only). Then measure
the residual B1 misses and classify them: formatting (done), unit-conversion (add a deterministic
conversion table — still general), or genuine synonyms (only then an embedding-match layer, as a
*separate* spec with a high floor + the ownership guard + its own A/B). Never grow `relax_sql`
per-case.

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
