# Phase 1 — Deterministic Ref-Grounding

**Status:** Draft for review
**Date:** 2026-06-22
**Branch:** `determinism`
**Depends on:** Phase 0 (legacy removal). **Built first among the deterministic stages; measured before Phases 2–3.**

## Goal

Move grounding-ref production out of the LLM into a deterministic stage. Every required
`/proc/...` and `/docs/...` reference must appear in the answer, **re-derived from the VM +
task text + computed answer**, independent of what INTENT/PLAN declared. The model's refs
become hints; code produces the authoritative set (the `muxx` exoskeleton pattern:
`submission_refs` + `doc_autocite`).

## Motivating evidence (run `20260621_232850`)

11 tasks fail **purely** on a missing required reference. Three sub-types:

| Task | Agent refs | Grader wanted | Sub-type |
|---|---|---|---|
| t13 | `[]` | `/proc/catalog/STO-2R84BSHQ.json` | record-path not derived |
| t41 | `[]` | `/docs/payments/3ds.md` | doc-ref not attached |
| t26 | `[/docs/security.md]` | `+ /docs/checkout.md` | **outcome correct, doc-ref incomplete (pure win)** |

Full set: t13, t14, t15, t16, t26, t28, t41, t42, t45, t47, t50.

Current machinery and its gaps:
- `intent.required_refs[outcome]` holds `RefSpec`s: `policy_doc` (literal `path`) or
  `record_path` (resolved via `resolve(source, env)`).
- `interpreter._project_required_refs` projects them; an unresolved `record_path` is
  **dropped**.
- `verify.py` **I1 enforces refs only on `OUTCOME_OK` and only by count**
  (`len(refs) < n_required`).

→ Gaps: (a) refs depend on the LLM both *declaring* the spec and the env *resolving* the
value; (b) enforcement is OK-only and count-only (t26's correct denial passes verify but
fails the grader); (c) docs the investigator actually read are never auto-cited.

## Design

New module **`agent/grounding.py`**:

```
ground_refs(intent, answer, result, vm, task_text) -> list[str]
```

Called in `pipeline.py` **after `interpret`, before `verify`**. Returns the authoritative
ref list that **replaces** `answer.refs`. Hybrid re-derivation (per CQ2):

**1. Record refs (precise).**
- `extract_entity_tokens(task_text, answer.message)` — regex for entity IDs/SKUs
  (`[A-Z]{3}-[A-Z0-9]{8}`, `basket_\d+`, payment/return/customer ID shapes).
- For each token, `resolve_record_path(vm, token)` — find-by-id over the `/proc` tree, else
  `/bin/sql select record_path from <table> where <key>=…`.
- `stat`-validate against the live tree; drop tokens that don't resolve to a real path.
- **Ownership guard (conservative in Phase 1):** never auto-cite a record owned by another
  customer; cite only owned/public records. The full identity gate lands in Phase 2 — Phase
  1 errs toward dropping a doubtful record ref.

**2. Doc refs (from evidence).**
- INVESTIGATE accumulates the `/docs/*.md` paths it actually read into
  `env["docs_read"]` (small change to `investigate.py`).
- `canonical_doc_refs(env["docs_read"], intent, answer)` keeps the docs the answer relies on
  for the chosen outcome's policy area; case-corrects each against the tree.

**3. Merge.** Union with the enforced `intent.required_refs` projections (never lose an
enforced ref), dedup, stable order.

**`verify.py` I1 hardening:**
- Enforce required-ref **presence on all outcomes** (not only `OUTCOME_OK`) — fixes the
  t26-class.
- **Presence-based**, not count: every resolved `intent.required_refs[outcome]` value must
  be `⊆ answer.refs`.
- Keep the unresolved-`$ref` guard.

**Generic vs task-specific:** extraction patterns + SQL/find/stat are *mechanism* — no
per-task ref values in code. `intent.required_refs` still declares *what kinds* are required
(data, from INTENT/LEARN); grounding fills the *values* from the VM.

## Data flow

```
interpret → CapturedAnswer(refs = interpreter projection)
          → ground_refs(...)  # overwrites refs with VM-derived authoritative set
          → verify (hardened) → vm.answer
```

## Components touched

- **`agent/grounding.py`** (new): `ground_refs` + `extract_entity_tokens`,
  `resolve_record_path`, `canonical_doc_refs`, `ownership_safe`.
- **`agent/investigate.py`**: accumulate `env["docs_read"]`.
- **`agent/verify.py`**: I1 hardening (all outcomes, presence-based).
- **`agent/pipeline.py`**: invoke `ground_refs` between `interpret` and `verify`.

## Error handling

`ground_refs` is best-effort and **never raises**: any resolution failure drops that one
ref. A genuinely required ref that cannot be resolved → `verify` fails → existing
`_ilearn` → next cycle (loop semantics unchanged). Added/dropped refs are logged to the
trace for observability.

## Testing

- **Unit:** `extract_entity_tokens` patterns; `resolve_record_path` against `mock_vm`;
  canonical-case correction; ownership guard drops cross-customer records.
- **Integration:** replay subset {t13,t14,t15,t16,t26,t28,t41,t42,t45,t47,t50} →
  `missing required reference` disappears from `score_detail`.
- **Regression:** full retained suite green; confirm I1 hardening (refs now required on
  non-OK) does not newly-fail previously-passing tasks beyond the measured intent.

## Success criteria

- On the 11-task subset, `missing required reference` is eliminated from grader feedback.
- No regression on currently-passing tasks.
- (Final OUTCOME correctness for some of these tasks still depends on Phase 2 — Phase 1's
  contract is *refs only*.)

## Risks & mitigations

- **Over-citation penalty** (grader may dock extra refs on count-type tasks) → precise
  re-derivation, plus `align_count` of catalog refs to the numeric answer for count tasks;
  settle by subset measurement.
- **Hardened verify surfaces new failures** (refs now enforced on DENIED/UNSUPPORTED) — this
  is correct per the grader (t26) but must be measured, not assumed safe.
- **Cross-customer leak** via an auto-cited record → conservative ownership guard in Phase 1;
  full identity gate in Phase 2.

## Non-goals

- Outcome/security decisions (Phase 2). Output formatting (Phase 3).
- No prompt edits — `intent.required_refs` still flows from INTENT/LEARN as data.
