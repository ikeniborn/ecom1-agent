---
wiki_sources:
  - "[[docs/superpowers/specs/2026-05-18-prompt-rules-separation-design.md]]"
wiki_updated: 2026-05-19
wiki_status: stub
wiki_outgoing_links:
  - "[[pipeline-phases/sdd-phase]]"
  - "[[pipeline-phases/learn-phase]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[plans/learned-knowledge-redesign]]"
tags:
  - ecom1-agent
  - documentation
aliases:
  - "Prompt/Rules Separation"
  - "prompt rules separation spec"
  - "thin prompts"
---

# Спека: Prompt / Rules Separation (2026-05-18)

**Статус:** Approved  
**Реализовано в:** [[plans/learned-knowledge-redesign]]

## Проблема

`data/prompts/*.md` содержали два класса контента:

1. **Structural** — роль, выходной формат, семантика фаз, коды ошибок
2. **Business rules** — SQL-паттерны, discovery-паттерны, column constraints

Смешение вызывало:
- **Противоречия**: `sec-write-detect-001` блокировал checkout, `sdd.md` разрешал basket discovery → t21 bug, score 0
- **Дивергенцию**: одно правило обновлялось в двух местах независимо
- **Мёртвый груз**: удалённые `data/rules/` файлы оставляли дубликаты в промтах

## Цель

- **Промты содержат только**: роль, выходной формат, workflow фазы, коды ошибок
- **`data/rules/`**: все SQL-планировочные ограничения, discovery-паттерны, формы запросов
- **`data/security/`**: detection gates и blocking rules

## Ключевые изменения промтов

| Файл | До | После |
|------|----|-------|
| `sdd.md` | ~215 строк (роль + 13 секций бизнес-правил) | ~55 строк (только структурное) |
| `learn.md` | ~92 строки | ~45 строк |
| `answer.md` | ~87 строк | ~40 строк |
| `tdd.md` | без изменений | без изменений |
| `assembler.md` | без изменений | без изменений |

## Что удалено из sdd.md

13 секций перенесены в `data/rules/` (впоследствии — в `data/learned/` через redesign):
- Table Name Resolution / Zero-Column Table Skip
- Discovery Steps patterns
- Multi-Attribute Filtering (EXISTS subqueries)
- SKU and Path Projection
- Store Name Discovery + Inventory Query Rules
- Count Questions / Cart Queries
- Column Existence Pre-Flight
- Retry Divergence / Identical Plan Guard
- Product Line Column Mapping
- NOT FOUND Rule

## Исправление sec-write-detect-001

Убрана инструкция: «For checkout tasks → respond OUTCOME_NONE_UNSUPPORTED without planning SQL.»  
Checkout exception живёт исключительно в `sdd.md`. Security gate блокирует только SQL-мутации (INSERT/UPDATE/DELETE/DROP).

## Статус в рамках learned knowledge redesign

Спека 2026-05-18 описывала перенос в `data/rules/*.yaml`. В рамках [[plans/learned-knowledge-redesign]] (2026-05-19) `data/rules/` сам удалён — правила теперь живут в `data/learned/{task_id}.yaml` как активные LEARNED-записи. Промпты остаются «тонкими» по тому же принципу.
