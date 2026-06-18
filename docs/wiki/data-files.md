# Data Files

The `data/` tree and `models.json` hold every non-code input the pipeline reads at runtime: phase prompts, per-task learned rules, the knowledge-oracle store, persisted intent/plan artifacts, and per-model provider configs. Code lives elsewhere; this page documents the declarative surfaces. See [[architecture]] and [[pipeline]].

## Prompt Guides (`data/prompts/*.md`)

Five phase guides shape every LLM call: `intent`, `plan`, `ilearn`, `learn`, `compact`. Each defines a phase's input fields, a strict single-JSON-object output schema (no prose, no fences), and the structural rules that output must obey. See [[pipeline]].

The set: `intent.md` (the INTENT/IDD layer — emit an `IntentSpec` of WHAT/why, never SQL or column names; includes the PredExpr grammar, the `$ref` convention, and the keyed `success_criteria` shape — a map keyed by outcome); `plan.md` (the PLAN/SDD layer — emit a `PlanIR` of HOW, listing the EcomRuntime RPCs, the 13-name primitive registry, the `fuzzy_sku_receipt` parser, the exact allowed predicate-op spellings, and the `AnswerTemplateIR` keys); `ilearn.md` (diagnose a failed interpreter cycle, emit one corrective PLAN-shaping rule, optionally request `prephase_deep_read` paths/tables); `learn.md` (the merged LEARN+CONSOLIDATE rule for the CODEGEN-era flow); and `compact.md` (compress accumulated rules/verdicts into one dense paragraph). See [[learning]].

## Prompt Engineering Rule: General Structure Only

Prompts encode only general structural rules — action forms, output format, SQL constraints, generic decision patterns. Task-specific domain rules, per-task-type heuristics, and scenario-specific sequences are forbidden in `data/prompts/`. See [[learning]].

This is load-bearing: all task-specific knowledge must flow through the LEARN mechanism into `data/learned/{task_id}.yaml`, never into a prompt. A task failure is fixed by repairing the LEARN trigger or the learned rule — `data/prompts/` is never patched to fix a single task. Both `ilearn.md` and `learn.md` enforce this from the other side: an emitted `rule_content` must be task-agnostic and must never embed a re-seeded literal (SKU, id, city, date).

## Learned Rules (`data/learned/{task_id}.yaml`)

Per-task store of active and inactive LEARN rules plus a `last_run` block. Each rule the [[pipeline]] distils from a failed cycle or grader verdict is appended here; the active subset is loaded into the next PLAN call as `learn_ctx`. See [[learning]].

Top level is `entries: [...]`, `last_run: {...}`, and `task_id`. Each entry carries `id`, `created`, `status` (`active`|`inactive`), and `deactivated_reason`. Two entry shapes appear: a **rule** (`surface: ir`, `content`, `reasoning`, `agents_md_anchor`) emitted by the iLEARN phase, and a **verdict** (`source: verdict`, `score`, `score_detail`, `submitted_message`/`submitted_outcome`/`submitted_refs`) captured from the grader. Superseded entries are flipped to `inactive` rather than deleted. `last_run` carries only `status`/`outcome`/`cycles_used`/`date` — no `heuristic_valid`, no `schema_hash`.

## Knowledge-Oracle Store (`data/oracle/`)

Holds the validated general-knowledge atoms retrieved semantically into PLAN. `atoms.yaml` is the atom store — seeded with generic, re-seed-safe `method` atoms and grown at runtime; each atom carries a `polarity` (`method` | `anti_pattern`). `history.jsonl` is an append-only log of distillation snapshots. See [[oracle]].

Each `history.jsonl` line records a run's atom census: `date`, `total`, a `by_status` map (e.g. `{"candidate": 54}`), and `top_domains` as ranked `[domain, count]` pairs (sql, data-extraction, templating, …). Atoms reach `active` either by manual seed, by distill → validate → promote, or by end-of-run self-fill (`distill_from_grader` writes `active` atoms directly from the grader score). Retrieval uses cosine top-N then optional LLM re-rank, governed by the `ORACLE_*` env vars. See [[llm]].

## Persisted Heuristics (`data/heuristics/*.json`)

On a successful run the pipeline writes `{task_id}.intent.json` (the frozen `IntentSpec`) and `{task_id}.plan.json` (the working `PlanIR`). The directory is created on first success and may be absent on a fresh checkout. See [[pipeline]].

Both files are consumed by `pipeline.learn_from_grader` between training cycles (`TRAIN_MAX_CYCLES > 1`) and by `distill_from_grader` end-of-run self-fill: they let those seams distil grader feedback without re-running the INTENT and PLAN LLM calls. The `IntentSpec` is the WHAT/why layer (`objective`, `outcome_space`, `constraints`, `required_refs`, and `success_criteria` keyed by outcome); the `PlanIR` is the HOW layer (`discovery`, `rowsets`, `compute`, `decision`, `ops`, `answer`, `custom_extract`). A bare-list `success_criteria` in an older persisted `intent.json` is coerced to `{"OUTCOME_OK": [...]}` on load. See [[learning]] and [[pipeline#End-of-run self-fill]].

## Model Config (`models.json`)

Per-model provider hints and sampling options, keyed by the model ID used in env vars and loaded by `main.py` at startup. Supplies what cannot be inferred from a model name: explicit `provider`, Ollama options, embedding role, and Claude Code CLI flags. See [[llm]].

Recognised fields include `provider` (`anthropic`|`openrouter`|`ollama`|`claude-code`; inferred from the name when omitted), `response_format_hint` (OpenRouter `json_object`/`json_schema`), `ollama_think`, `ollama_options` (flattened sampling params like `num_ctx`, `temperature`, `seed`, `top_k`, `top_p`, `repeat_penalty`), and `kind: embedding` to mark an oracle embedding model (e.g. `nomic-embed-text`). Claude Code entries add `cc_model` (haiku/sonnet/opus alias) and a `cc_options` dict (`cc_effort`, `cc_timeout_s`, `cc_exclude_dynamic`, etc.). Per-phase model **tier** resolution is separate, handled in `llm.py`. See [[architecture]].
