---
wiki_sources:
  - "[[data/prompts/consolidate.md]]"
  - "[[CLAUDE.md]]"
  - "[[.env.example]]"
wiki_updated: 2026-05-20
wiki_status: stub
wiki_outgoing_links:
  - "[[pipeline-phases/learn-phase]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "CONSOLIDATE"
  - "Consolidate Phase"
  - "ConsolidateOutput"
---

# Фаза CONSOLIDATE

Фаза постобработки learned rules — устраняет дублирование, перекрытие и противоречия в активных записях `data/learned/{task_id}.yaml`. Вызывается после LEARN как шаг дедупликации.

## Основные характеристики

- Входы: список активных rules `{id, content}` из `data/learned/{task_id}.yaml`
- Выходной формат: чистый JSON (первый символ обязательно `{`)
- Модель: `MODEL_CONSOLIDATE` (по умолчанию — `MODEL`)
- Max tokens: `MAX_TOKENS_CONSOLIDATE` (default 2048)
- Директива `\no_think` — выключает CoT для быстрого прохода

## Задача фазы

LLM получает `ACTIVE_RULES` и находит группы:

| Тип группы | Описание |
|------------|---------|
| Дубликат | Правила семантически идентичны — одна ошибка, одно исправление |
| Перекрытие | Правило A — строгое подмножество правила B |
| Противоречие | Правила требуют несовместимых действий в одной ситуации |

Для каждой группы — одно `merged_rule`. База — содержимое правила с наибольшим числовым id; расширяется до охвата всей группы.

При отсутствии избыточных правил — возвращает `skip: true`.

## Формат вывода ConsolidateOutput

**Когда нет избыточности:**
```json
{
  "skip": true,
  "skip_reason": "<почему консолидация не нужна>",
  "consolidations": []
}
```

**Когда есть группы для объединения:**
```json
{
  "skip": false,
  "skip_reason": null,
  "consolidations": [
    {
      "deactivate": ["r002", "r003"],
      "merged_rule": "<содержимое на основе правила с наибольшим id, расширенное>",
      "merged_reasoning": "<какие ids объединены, что было избыточным>"
    }
  ]
}
```

## Место в пайплайне

```
LEARN → CONSOLIDATE → (learn_ctx обновлён) → следующий цикл ASSEMBLE
```

CONSOLIDATE дополняет LLM-driven dedup внутри LEARN (поля `skip`/`deactivate`): LEARN устраняет очевидные дубликаты точечно, CONSOLIDATE — полная проверка всего корпуса active rules.

## Связанные компоненты

- `data/prompts/consolidate.md` — phase guide (prompt)
- `data/learned/{task_id}.yaml` — источник active rules и место записи результата
- `_apply_learn_diff()` в `agent/prompt_assembler.py` — механизм деактивации записей

## Переменные окружения

| Var | Default | Назначение |
|-----|---------|-----------|
| `MODEL_CONSOLIDATE` | `MODEL` | Модель для CONSOLIDATE-фазы |
| `MAX_TOKENS_CONSOLIDATE` | 2048 | Лимит токенов ответа |

## История изменений

- **2026-05-20** (из [[data/prompts/consolidate.md]], [[CLAUDE.md]]): страница создана; фаза CONSOLIDATE добавлена в пайплайн как шаг дедупликации active rules; устраняет дублирование/перекрытие/противоречия через LLM; не требует сложного CoT (\\no_think)
