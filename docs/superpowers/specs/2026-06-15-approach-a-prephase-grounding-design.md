---
review:
  spec_hash: 0d9ba390c2b7a1c2
  last_run: 2026-06-15
  phases:
    structure:   { status: passed }
    coverage:    { status: passed }
    clarity:     { status: passed }
    consistency: { status: passed }
  findings:
    - { id: F-001, phase: clarity, severity: WARNING, section: "S1-R4", section_hash: a98471a9891e94bf, text: "vague 'тонкий' without threshold", verdict: fixed, verdict_at: 2026-06-15 }
    - { id: F-002, phase: clarity, severity: WARNING, section: "S1-R7", section_hash: f981214cc0c73312, text: "vague 'robust/менее хрупкий' without criterion", verdict: fixed, verdict_at: 2026-06-15 }
chain:
  intent: docs/superpowers/intents/2026-06-15-approach-a-prephase-grounding-intent.md
---

# Design: Approach A — pre-phase grounding для качественного frozen INTENT

**Date:** 2026-06-15
**Intent:** `docs/superpowers/intents/2026-06-15-approach-a-prephase-grounding-intent.md` (approved)
**Primary mode:** INTERPRETER path (`_run_interpreted`, за `INTERPRETER_ENABLED=1`)

## Acceptance (from intent)

Desired Outcomes (verbatim):
- **t09 0.00→1.0 в реальном prod benchmark-прогоне** (не только hand-probe): doc discovered → read →
  rule applied → doc cited.
- **Bucket-B задачи (policy/counting/grounding) растут; зелёные задачи остаются зелёными**; общий
  score ≥ baseline ~32%.
- **INTENT видит релевантные доки**: в pre-phase trace кандидат-доки непусты, нужный topic-док
  присутствует; каждый факт помечен `ok`/`empty`/`error` (нет silent `""`).
- **Грейдер не жалуется на refs**: `answer.refs` точно совпадает с required для выбранного outcome —
  ни missing ref (G1), ни extra ref (G2).

**Done when:** в реальном benchmark-прогоне **t09 = 1.0**, bucket-B растёт, общий score ≥ baseline
~32%, зелёные задачи не упали — **измерено** на живом грейдере, не «тесты зелёные».

## Overview

Качество гейтится двумя upstream frozen-артефактами: pre-phase fact set и frozen INTENT. Корень —
pre-phase под-граундит INTENT: `docs_inventory` всегда пуст (`TreeResponse` не имеет `stdout`),
policy-доки читаются только по path-имени, topic-релевантные доки не читаются. Approach A чинит
upstream: pre-phase собирает каждый артефакт для качественного INTENT с первого раза, а refs
проектируются из INTENT per-outcome (PLAN их не авторит).

Один design doc; implementation plan режет на **две slice-фазы**. Без runtime-флага: меняем
interpreter path напрямую. A/B-замер = прогон ветки `heuristics` vs `master` baseline; merge в master
= human-checkpoint cutover.

## Architecture / data flow

```
PRE-PHASE (orchestrator.py)              [SLICE 1]
  gather_prephase_facts:
    discover docs (Entry-walk TreeResponse.root + Search, НЕ tree.stdout)
    policies += Read CONTENT топ-≤3 Search-hits (cap ~4KB/doc)
    gather_status: dict[fact → ok|empty|error]
    P3 target_records шире, P4 robust identity
        │ facts (прокинуть и в legacy DESIGN — P7)
        ▼
INTENT (reason.run_intent, intent.md)    [SLICE 2]
  required_refs: dict[outcome → list[RefSpec]]   (drop required_ref_kinds)
  success_criteria = structural/grounding only (НЕ SQL recipe)
        ▼
PLAN (reason.run_plan, plan.md)          [SLICE 2]
  читает eligibility-rule из facts.policies → rule-correct SQL
  НЕ авторит answer.refs (только bindings)
        ▼
INTERPRET (interpreter.py)               [SLICE 2]
  answer.refs := [resolve(r) for r in required_refs[selected_outcome]]
        ▼
VERIFY (verify.py)                        [SLICE 2]
  I1: каждый required ref выбранного outcome резолвится non-empty
  удалить /docs-static эвристику
```

Изоляция ответственностей: discovery = recall (широко поднимает кандидат-доки); INTENT = precision
(объявляет только load-bearing доки как required_refs). Slice 1 тестируется независимо (доки читаются
в facts); Slice 2 — независимо (проекция refs на mock IntentSpec). t09=1.0 — после обеих фаз.

## Slice 1 — pre-phase discovery + facts (`orchestrator.py`)

### S1-R1: doc discovery без `tree.stdout`
`_discover_docs(vm) -> list[str]`: рекурсия по `TreeResponse.root` (ecom `Entry{name, content_type,
children}`) → список абсолютных путей под `/docs/**`. НЕ использует `tree.stdout` (его нет в proto).
НЕ использует VMAdapter `Find(kind=…)` (`FindRequest.type` int32 → `kind=` kwarg даёт пусто).
`docs_inventory` = собранный список путей (непустой при наличии доков).

### S1-R2: entity-token extraction (0 LLM)
`_extract_entity_tokens(instruction) -> list[str]`: детерминированно — quoted-строки
(`"Tool Box and Bag"`) + последовательности Capitalized-слов длиной ≥2. Каждый токен → отдельный
Search-pattern.

### S1-R3: policies обогащение через Search
`/docs/security.md` всегда + path-named доки (текущее поведение) +=:
для каждого entity-токена `Search(root="/docs", pattern=token)` → `SearchMatch.path` → Read CONTENT
топ-≤3 уникальных hits, cap ~4KB/doc. Читается CONTENT (не только путь) — правило дока load-bearing
для вычисления (naive count=3, rule-correct=2).

### S1-R4: LLM DOC-SELECT fallback
Триггер строго: Search вернул 0 hits по всем entity-токенам (после S1-R3). Тогда один cheap LLM-вызов
(`MODEL_LEARN`, cap 4) над inventory → `{"docs":[…]}`, фильтр по существующим путям. Не валит run. В
типичном случае не вызывается (детерминированный Search находит doc — proven live).

### S1-R5: gather_status (P6)
Новое поле `PrePhaseFacts.gather_status: dict[str, str]`. Каждый gather-шаг пишет `ok`/`empty`/
`error`. Surfaced в `_facts_block`. INTENT различает «нет факта» и «fetch упал»; нет silent `""`.

### S1-R6: P3 — target_records шире
Расширить с baskets/payments до stores/employees/returns/orders/product + entity-named (не только
ID-named) records.

### S1-R7: P4 — robust identity parse
Парсить `/bin/id` как набор `key=value` пар, толерантно к whitespace и порядку полей (не полагаться
на единый `(\w+)=([^\s]+)` proximto regex). Критерий: пустой `identity` только когда `/bin/id`
действительно пуст/ошибка — и тогда зафиксировано в `gather_status` (`empty`/`error`), не silent `{}`.

### S1-R8: P7 — facts в legacy DESIGN
`run_pipeline` прокидывает `facts` в legacy DESIGN-путь тоже (сейчас legacy игнорирует `facts`) —
для честного A/B. Legacy не primary mode, но fair-сравнение требует равного входа.

## Slice 2 — required_refs projection

### S2-R1: `ir_models.py` schema
```python
class RefSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str                  # "policy_doc" | "record_path"
    path: str | None = None    # literal /docs/…md, известен на INTENT (из discovery)
    source: str | None = None  # $ref binding, резолвится в runtime (record_path)
```
`IntentSpec`: добавить `required_refs: dict[str, list[RefSpec]] = {}` (keyed by outcome); удалить
`AnswerShape.required_ref_kinds`. `AnswerShape.msg_skeleton` остаётся. model_validator: RefSpec
обязан иметь ровно один из `path`/`source` под свой `kind`.

### S2-R2: `intent.md`
INTENT декларирует `required_refs` per-outcome: cite governing `/docs` doc (literal `path`) + record
(`record_path` с `$ref` source). `success_criteria` — структурные/grounding only (напр. `count ge 0`,
nonempty kind_id); INTENT НЕ запекает SQL/join/kind_id/city. IDD/SDD раздел явно в промпте.

### S2-R3: `plan.md`
Убрать инструкцию PLAN-authored refs (текущие строки ~99–115 «ALWAYS cite both»). PLAN читает
eligibility-rule из `facts.policies` → строит rule-correct SQL и bindings (record_path колонка);
`answer[*].refs` PLAN больше не заполняет.

### S2-R4: `interpreter.py` ref-projection
После выбора `label`→`outcome` (шаг 7 answer assembly): `refs := [_resolve_refspec(r, env) for r in
intent.required_refs.get(outcome, [])]`. `policy_doc.path` → literal; `record_path.source` →
`resolve($ref, env)`. Refuse-invariant: OUTCOME_OK с нерезолвленным required ref → `_refuse(...)`
(несёт `mutation_landed`). Удалить старую `required_ref_kinds`-ветку (строки ~243–247).

### S2-R5: `verify.py` I1 rewrite
Для `selected_outcome` каждый required ref резолвится non-empty. Удалить `/docs`-static эвристику
(строки ~26–29). `refs == required` держится by construction → G1 (под-цитирование) и G2
(пере-цитирование) исчезают структурно.

## Error handling

- Каждый pre-phase gather в try → `gather_status` пишет `ok`/`empty`/`error(<msg>)`; run не валится
  на pre-phase.
- Search пуст → LLM DOC-SELECT fallback → если и он пуст, `policies` = security.md + path-named
  (graceful degrade, не raise).
- cap ~4KB/doc bound'ит INTENT-контекст (health-метрика «время прогона ≤10%»).
- required_ref нерезолвлен на OUTCOME_OK → `_refuse` → InterpretError → LEARN → следующий cycle.
- RefSpec невалидный → pydantic `extra="forbid"` + model_validator → IntentError → retry.
- Re-seed: никаких literal kind_id/city в INTENT; doc-path literal резолвится из THIS run discovery,
  не из памяти.

## Testing

### Unit
- `_discover_docs` — mock `TreeResponse.root` Entry-дерево → ожидаемый список путей; `tree.stdout` не
  читается.
- `_extract_entity_tokens` — quoted + Capitalized n-grams из sample instruction.
- `policies` Search-обогащение — MockVMSpy: Search→path→Read CONTENT; cap соблюдён; ≤3 hits.
- `gather_status` — каждый fact помечен корректно (ok/empty/error).
- `RefSpec`/`required_refs` pydantic — валидные/невалидные shapes; ровно один из path/source.
- `interpreter` ref-projection — mock IntentSpec.required_refs → refs резолвятся per-outcome.
- `verify` I1 — required ref non-empty pass; missing → fail; regression guard на удаление
  `/docs`-эвристики.

### Integration (gated, как t09/t27/t51)
- t09 на живом грейдере через pipeline (не вручную): discover→read→rule→cite → score 1.0.
  Reproducible harness: `scripts/probe_t09_refs.py`.

### Outcome verification (после impl, до merge)
Прогон benchmark на `heuristics` vs `master`: t09=1.0, bucket-B↑, score ≥ ~32%, зелёные не упали.
Измерено на грейдере — green unit-тесты НЕ являются доказательством outcome.

## Out of scope (follow-up)

Loop mechanics: R1 (load persisted IR rules в learn_ctx), R2 (LEARN prompt reframe под PlanIR), R3
(observations в PLAN), R4 (identical-plan short-circuit), R5 (MAX_STEPS↓). Cheap stop-the-bleed, но
Approach A целит корень (под-граундленный acceptance), не симптом рекурсии.

## Blast radius

| Файл | Slice | Изменение |
|------|-------|-----------|
| `agent/orchestrator.py` | 1 | `_discover_docs`, `_extract_entity_tokens`, policies Search, gather_status, P3, P4 |
| `agent/pipeline.py` | 1 | P7: facts в legacy DESIGN |
| `agent/ir_models.py` | 2 | `RefSpec`, `IntentSpec.required_refs`, drop `required_ref_kinds` |
| `data/prompts/intent.md` | 2 | required_refs per-outcome; structural success_criteria |
| `data/prompts/plan.md` | 2 | drop PLAN-authored refs; read rule from policies |
| `agent/interpreter.py` | 2 | ref-projection; refuse-invariant |
| `agent/verify.py` | 2 | I1 rewrite; delete /docs heuristic |
