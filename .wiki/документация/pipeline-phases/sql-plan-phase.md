---
wiki_sources:
  - "[[data/prompts/sql_plan.md]]"
  - "[[docs/superpowers/specs/2026-05-14-api-update-carts-design.md]]"
  - "[[data/prompts/sdd.md]]"
wiki_updated: 2026-05-17
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/sdd-phase]]"
  - "[[pipeline-phases/answer-phase]]"
  - "[[design-decisions/grounding-refs]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "SQL_PLAN"
  - "SQL Plan Phase"
  - "Фаза планирования SQL"
---

> **Примечание (2026-05-17):** Фаза SQL_PLAN переименована в **SDD** (Spec-Driven Development) в рамках редизайна промп-архитектуры. Актуальная страница: [[pipeline-phases/sdd-phase]]. Данная страница сохранена для исторического контекста. CONFIRMED VALUES и RESOLVE phase — удалены из архитектуры.

# Фаза SQL_PLAN

Фаза планирования SQL-запросов в пайплайне агента. Получает описание задачи и схему базы данных, выдаёт упорядоченный список SQL-запросов для ответа на вопрос. Является ключевой фазой основного цикла пайплайна (max 3 цикла).

## Основные характеристики

- Выходной формат: чистый JSON (первый символ обязательно `{`)
- Поле `reasoning` — цепочка мышления: какие таблицы/колонки релевантны и почему
- Поле `queries` — упорядоченный список SQL-строк для последовательного выполнения
- Поле `agents_md_refs` — список всех секций AGENTS.MD, которые были использованы
- Каждый SELECT обязан содержать WHERE-клаузулу
- Финальные запросы обязаны проецировать `p.path` для заполнения `grounding_refs` фазой ANSWER

## Изоляция discovery-запросов (CRITICAL)

Discovery-запросы и зависимые filter-запросы **обязательно** выполняются в отдельных циклах:

1. **Цикл N:** только discovery-запросы (`SELECT DISTINCT model`, `SELECT DISTINCT key`, `SELECT DISTINCT value_text`) → ждать результатов
2. **Проверить** возвращённые значения
3. **Цикл N+1:** filter/aggregate-запрос, использующий только подтверждённые значения

Запрещено: батчить `SELECT DISTINCT model` вместе с `WHERE model = <что-либо>` в одном выводе.

## CONFIRMED VALUES

При наличии блока `# CONFIRMED VALUES` в контексте:
- Использовать эти значения как литералы в WHERE — без повторного запуска discovery
- `attr_value` подтверждён, `attr_key` нет → фильтровать только по `value_text`, не изобретать имя ключа

```sql
-- ПРАВИЛЬНО: attr_value подтверждён, ключ неизвестен
AND EXISTS (SELECT 1 FROM product_properties pp WHERE pp.sku = p.sku AND pp.value_text = 'facade paint')

-- НЕПРАВИЛЬНО: ключ не был в CONFIRMED VALUES
AND EXISTS (SELECT 1 FROM product_properties pp WHERE pp.sku = p.sku AND pp.key = 'product_type' AND pp.value_text = 'facade paint')
```

## Многоатрибутная фильтрация

При фильтрации по нескольким атрибутам `product_properties` использовать **отдельные EXISTS-подзапросы** — не JOIN с двумя условиями по ключу (одна строка содержит только один ключ).

## Числовые атрибуты с единицами измерения

Никогда не предполагать имя ключа или хранимую единицу из текста задачи:

1. Открыть ключ: `SELECT DISTINCT key FROM product_properties WHERE key LIKE '%<unit_stem>%' LIMIT 20`
2. Открыть домен значений: `SELECT DISTINCT value_text, value_number FROM product_properties WHERE key = '<confirmed_key>' LIMIT 20`
3. Только после этого — EXISTS-клаузула с подтверждёнными ключом и значением

## Pre-Output Query Checklist (обязательный)

Перед эмиссией каждого запроса проверить:
1. Нет DDL-ключевых слов: `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `RENAME`, `COMMENT`
2. Нет DML-записи: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `UPSERT`, `REPLACE`, `GRANT`, `REVOKE`
3. Запрос начинается с `SELECT` или `EXPLAIN SELECT`
4. Нет multi-statement через `;` с последующим кодом

При провале → не эмитировать план, эмитировать `{"reasoning":"...","error":"PLAN_ABORTED_NON_SELECT","queries":[],"agents_md_refs":[]}`.

## Запросы к корзине покупателя (Cart Queries)

При задачах, связанных с корзиной:

1. Использовать `customer_id` из блока `# AGENT CONTEXT` для привязки к текущему покупателю
2. Данные корзины в таблицах `carts` и `cart_items` (проверять через `.schema`)
3. Паттерн JOIN: `carts → cart_items → products`
4. `grounding_refs`: использовать `/proc/catalog/{sku}.json` для каждого SKU из корзины

```sql
SELECT ci.sku, ci.quantity, p.name, p.path
FROM carts c
JOIN cart_items ci ON ci.cart_id = c.cart_id
JOIN products p ON p.sku = ci.sku
WHERE c.customer_id = '<customer_id_из_agent_context>'
```

## /bin/checkout

`/bin/checkout` — runtime-инструмент, **не SQL-запрос**:
- Для задач checkout: использовать exec-инструмент с `path="/bin/checkout"`, передавать `cart_id` через `ExecRequest.args`
- Для preview: тот же exec-вызов возвращает preview без финализации
- Пайплайн не имеет фазы checkout — задачи обрабатываются согласно AGENTS.MD

## Инвентарные запросы

- Всегда проецировать `available_today` и `store_id` явно; `SELECT *` не допускается
- Перед суммированием инвентаря по городу — верифицировать все `store_id` через `proc/stores/`
- Никогда не использовать `WHERE store_id LIKE '%city%'` — store_id являются непрозрачными кодами

## История изменений

- **2026-05-14** (из [[docs/superpowers/specs/2026-05-14-api-update-carts-design.md]]): добавлены разделы "Cart and Basket Queries" и "/bin/checkout"; `carts`, `cart_items` добавлены в `_SCHEMA_TABLES` в `prephase.py`.
