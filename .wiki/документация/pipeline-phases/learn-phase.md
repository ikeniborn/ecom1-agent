---
wiki_sources:
  - "[[data/prompts/learn.md]]"
  - "[[docs/superpowers/specs/2026-05-17-learn-ctx-compaction-design.md]]"
  - "[[docs/superpowers/plans/2026-05-19-learned-knowledge-redesign.md]]"
  - "[[agent/models.py]]"
  - "[[agent/pipeline.py]]"
wiki_updated: 2026-05-20
wiki_status: stable
wiki_outgoing_links:
  - "[[pipeline-phases/sql-pipeline-overview]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[pipeline-phases/consolidate-phase]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
tags:
  - ecom1-agent
  - documentation
aliases:
  - "LEARN phase"
  - "_run_learn"
  - "learn_ctx"
  - "compacted_ctx"
---

# Фаза LEARN

Фаза восстановления после failure. Вызывается из `agent/pipeline.py:_run_learn()` при любом сбое пайплайна (SDD-parse, schema gate, validate, execute, TDD, answer test). LLM диагностирует ошибку и добавляет правило в `learn_ctx` для следующего цикла.

## Когда вызывается

| Trigger | `error_type` |
|---------|-------------|
| SDD LLM parse fail | `llm_fail` |
| AGENTS.MD refs check fail | `semantic` |
| Schema gate blocked | `security` |
| TDD LLM parse fail | `llm_fail` |
| EXECUTE empty result / error | `empty` / `semantic` |
| Answer test fail | `test_fail` |

При `error_type=llm_fail` фаза **пропускает** добавление правила (LLM не вернул валидный JSON — нет чему учиться).

## Сигнатура `_run_learn` (learned knowledge redesign, 2026-05-19)

```python
def _run_learn(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    queries: list[str],
    error: str,
    sgr_trace: list[dict],
    learn_ctx: list[str],       # мутируется in-place
    agents_md_index: dict,
    error_type: str = "semantic",
    cycle: int = 0,
    task_id: str = "",
) -> None:
```

Параметр `prior_learn_hashes` удалён — дедупликация теперь через `skip` поле `LearnOutput` (LLM-driven).

## Модель вывода `LearnOutput`

```python
class LearnOutput(BaseModel):
    reasoning: str
    conclusion: str
    rule_content: str
    agents_md_anchor: str | None = None
    deactivate: list[str] = []
    deactivate_reason: str | None = None
    skip: bool = False
    skip_reason: str | None = None
```

Поля `compacted_ctx` и `PipelineEvalOutput` удалены в рамках redesign.

## Логика обновления learn_ctx (порядок проверок)

```
1. error_type == "llm_fail" → пропустить (return)
2. learn_out.skip == True → пропустить (return), вывести skip_reason
3. agents_md_anchor заполнен:
   → vault rule добавить в _apply_learn_diff(..., source="learn")
   → learn_ctx.append(vault_rule) → return
4. _apply_learn_diff(task_id, rule_content, reasoning, deactivate, deactivate_reason)
   → атомарно обновляет data/learned/{task_id}.yaml
5. Если deactivate непустой → удалить деактивированные записи из learn_ctx in-memory
6. learn_ctx.append(rule_content)
```

## Consolidation Logic (Deduplication via LLM)

После каждого LEARN LLM получает `EXISTING_RULES` — список активных записей из `data/learned/{task_id}.yaml`. LLM сравнивает новое правило с существующими и возвращает:

| Сценарий | Результат |
|----------|-----------|
| Дубликат (покрыто `rXXX`) | `skip=true`, `skip_reason="rXXX"`, правило не добавляется |
| Supersedes (делает `rXXX` устаревшим) | `deactivate=["rXXX"]`, `deactivate_reason="..."`, новое правило добавляется |
| Novel (новый паттерн ошибки) | `deactivate=[]`, правило добавляется |

Это заменяет старый `compacted_ctx` подход: вместо пересборки всего списка LLM точечно указывает что деактивировать.

После LEARN также может вызываться фаза [[pipeline-phases/consolidate-phase]] — полная проверка корпуса active rules на дублирование, перекрытие и противоречия.

## Входы LEARN (текущий формат)

LEARN теперь получает полный контекст всего цикла:

| Поле | Содержимое |
|------|-----------|
| `TASK` | Оригинальный текст задачи |
| `ERROR` + `ERROR_TYPE` | Что пошло не так |
| `SDD_OUTPUT` | Спецификация цикла: `spec_goal`, `success_criteria`, `plan`, `actions` |
| `PLAN_OUTPUT` | Декомпозиция: `approach`, `steps`, `action` — отсутствует если failure был в SDD |
| `ANSWER_OUTPUT` | Попытка ответа: `reasoning`, `message`, `outcome` — отсутствует если failure был до ANSWER |
| `EXISTING_RULES` | Активные правила из предыдущих циклов |

Правило нацелено на качество **spec или plan** — не на raw SQL паттерны. `rule_content` обязан ссылаться на идентификатор из `SDD_OUTPUT`, `PLAN_OUTPUT` или `ANSWER_OUTPUT`.

## Prompt-файл

`data/prompts/learn.md` — phase guide для LLM. Разделы:

- **Inputs** — задача + ошибка + SDD_OUTPUT + PLAN_OUTPUT + ANSWER_OUTPUT + EXISTING_RULES
- **Task** — диагноз: новое правило или skip
- **Output Rules** — pure JSON, concrete identifiers, ссылки на spec/plan
- **Output Format (JSON only)** — схема вывода с полями deactivate/skip
- **Field Definitions** — детальное описание каждого поля (4 обязательных компонента reasoning)
- **Consolidation Logic** — инструкции для dedup: Duplicate / Supersedes / Novel
- **Loop Prevention** — если исправленный action идентичен упавшему

## Файл хранилища знаний

`data/learned/{task_id}.yaml` — постоянная база знаний задачи. Структура:

```yaml
task_id: t01
entries:
  - id: r001
    content: "Always SELECT sku, path FROM products"
    status: active   # или inactive
    source: learn
    created: "2026-05-19"
    reasoning: "grounding_refs was empty without sku"
    deactivated_reason: null
  - id: r002
    content: "Old rule"
    status: inactive
    source: learn
    created: "2026-05-18"
    reasoning: "..."
    deactivated_reason: "Superseded by r003"
```

Файл **никогда не удаляется** при успехе задачи (в отличие от старого подхода). Записи накапливаются, деактивированные остаются для аудита.

## Тесты

`tests/test_learned_storage.py` (новый):
- `test_load_learned_ctx_returns_only_active` — только active записи попадают в learn_ctx
- `test_apply_learn_diff_adds_first_entry` — первая запись получает id r001
- `test_apply_learn_diff_deactivates_entries` — deactivate=[r001] → r001 status=inactive
- `test_apply_learn_diff_id_monotonic` — r001, r002, r003 — строго монотонно

## История изменений

- **2026-05-19** (из [[docs/superpowers/plans/2026-05-19-learned-knowledge-redesign.md]]): redesign learn_ctx — compacted_ctx и PipelineEvalOutput удалены; LLM-driven dedup через skip/deactivate; хранилище `data/learned/{task_id}.yaml`
- **2026-05-20** (из [[data/prompts/learn.md]]): расширены входы — LEARN теперь получает `SDD_OUTPUT` + `PLAN_OUTPUT` + `ANSWER_OUTPUT` (не только task+error); правила нацелены на spec/plan quality gaps, а не raw SQL паттерны; `rule_content` обязан цитировать идентификатор из одного из этих выводов
