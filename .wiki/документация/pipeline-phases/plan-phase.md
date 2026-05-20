---
wiki_sources:
  - "[[data/prompts/plan.md]]"
wiki_updated: 2026-05-20
wiki_status: stub
wiki_outgoing_links:
  - "[[pipeline-phases/sdd-phase]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[pipeline-phases/learn-phase]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "PLAN"
  - "Plan Phase"
  - "PlanOutput"
---

# Фаза PLAN

Третья фаза пайплайна агента — между SDD и EXECUTE. Получает `SddOutput` (результат SDD-фазы) и выбирает единственное действие для исполнения из списка кандидатов `actions`. Возвращает `PlanOutput`.

## Основные характеристики

- Входы: unified_context (из ASSEMBLE) + plan.md (phase guide) + SddOutput
- Выходной формат: чистый JSON (первый символ обязательно `{`)
- Поле `approach` — одно предложение: как будет разрешена спецификация
- Поле `steps` — 2–5 упорядоченных шагов выполнения (plain English)
- Поле `action` — единственное действие из `SddOutput.actions`, скопированное дословно
- Модель: `MODEL_SDD` (Override через `MODEL_SDD`, по умолчанию `MODEL`)

## Формат PlanOutput

```json
{
  "approach": "<one sentence: how the spec will be resolved>",
  "steps": [
    "step 1 description",
    "step 2 description"
  ],
  "action": "<exact action string from SddOutput.actions>"
}
```

## Правила выбора action

- Выбирать действие из `SddOutput.actions`, которое наиболее прямо удовлетворяет `spec_goal` и всем `success_criteria`
- Предпочитать точечное действие широкому discovery-запросу, если `spec_goal` специфичен
- Копировать строку действия дословно — не модифицировать
- Если `SddOutput.actions` пустой → `action: ""`

## Место в пайплайне

```
ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER
                  ↑
            Выбирает одно из actions SddOutput
```

До фазы PLAN существовал подход, при котором SDD возвращал типизированные шаги (`sql`/`read`/`compute`/`exec`), и исполнитель интерпретировал их напрямую. После редизайна (2026-05-20) SDD генерирует кандидатов `actions` как plain-string, PLAN выбирает один — разделение ответственности за планирование и выбор.

## История изменений

- **2026-05-20** (из [[data/prompts/plan.md]]): страница создана; фаза PLAN добавлена в пайплайн между SDD и EXECUTE; принимает SddOutput, возвращает PlanOutput с единственным action
