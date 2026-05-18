---
wiki_sources:
  - "[[data/prompts/assembler.md]]"
wiki_updated: 2026-05-17
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/sdd-phase]]"
  - "[[pipeline-phases/sql-pipeline-overview]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "ASSEMBLE"
  - "Assembler Phase"
  - "unified_context assembler"
  - "prompt assembler"
---

# Фаза ASSEMBLE

Первая фаза каждого цикла пайплайна. LLM-ассемблер собирает `unified_context` — единый контекстный документ из всех источников (learn_ctx, rules, security gates, prompt blocks). Каждая последующая фаза цикла (SDD, TDD, LEARN, ANSWER) получает `[unified_context] + [phase_guide]` вместо собственного system builder.

## Основные характеристики

- Вызывается в начале каждого цикла pipeline loop (до SDD), с актуальным `learn_ctx`
- Делает 1 LLM-вызов с инструкцией из `data/prompts/assembler.md`
- Возвращает: `unified_context: str`
- Разрешение противоречий: LEARNED > RULES > SECURITY > BASE
- Модель: `MODEL_ASSEMBLER` (по умолчанию — `MODEL`)

## Входы ассемблера

| Источник | Приоритет | Секция в unified_context |
|----------|-----------|--------------------------|
| `learn_ctx` (in-memory, текущая сессия) + `data/learned/{task_id}.yaml` | 1 (высший) | `# LEARNED` |
| `data/rules/*.yaml` (`verified: true`) | 2 | `# RULES` |
| `data/security/*.yaml` (`verified: true`) | 3 | `# SECURITY` |
| `data/prompts/` базовые блоки по `data/config/task_blocks.yaml` | 4 | `# BASE` |

Дополнительно включаются: schema_digest, db_schema, agents_md_index (vault rules), AGENT CONTEXT (customer_id, date).

## Структура unified_context

```
# LEARNED
<правила из learn_ctx, новейшие последними; пропустить если пусто>

# RULES
<релевантные правила из data/rules/; исключить с нулевым пересечением с task_text>

# SECURITY
<сводки security gates из data/security/>

# BASE
<объединённый domain context из PROMPT_BLOCKS; дедуплицировать>
```

## Фильтр релевантности для RULES

Правило остаётся если хотя бы одно из следующих совпадает с task_text:
- тип сущности (product, cart, inventory, store, kind, sku, brand, model)
- тип операции (count, find, list, sum, check, verify, compare)
- domain-ключевое слово (любое существительное или глагол из task_text длиннее 3 символов)

Правило исключается только при нулевом пересечении. При сомнении — оставить.

## task_blocks.yaml

Файл `data/config/task_blocks.yaml` определяет, какие дополнительные блоки из `data/prompts/*.md` включать по типу задачи:

```yaml
sql: []
compute: []
default: []
```

Поддерживаемые типы задач: `sql`, `compute`, `default`. Legacy-типы (lookup, temporal, capture, crm, distill, preject) — удалены.
