---
wiki_sources:
  - "[[data/prompts/tdd.md]]"
wiki_updated: 2026-05-17
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/answer-phase]]"
  - "[[pipeline-phases/sdd-phase]]"
wiki_external_links: []
tags:
  - ecom1-agent
  - documentation
aliases:
  - "TDD phase"
  - "TDD Phase"
  - "test generation"
  - "tdd"
  - "test_gen"
---

# Фаза TDD

Фаза TDD-пайплайна агента, в которой LLM генерирует acceptance-тесты для задачи каталога до фазы ANSWER. Тесты запускаются в изолированном subprocess (только stdlib Python) и верифицируют корректность SQL-результатов и финального ответа агента. Начиная с редизайна промп-архитектуры (2026-05-17), TDD **всегда обязательна** — флаг `TDD_ENABLED` удалён.

## Основные характеристики

- Всегда активна (TDD_ENABLED удалён); выполняется до фазы ANSWER
- Принимает на вход: `TASK`, `TASK_TYPE`, `SDD_SPEC` — спецификация из SDD-фазы
- Генерирует две функции-теста: `test_sql` и `test_answer`
- Все тесты детерминированы, сигнализируют об ошибке через `assert` или `raise ValueError`
- Сбой TDD → LEARN-цикл (`error_type="llm_fail"`) → следующий цикл

## Поведение по task_type

| task_type | test_sql | test_answer |
|-----------|----------|-------------|
| `sql` | генерируется полноценно | генерируется полноценно |
| `compute` или `default` | `def test_sql(results): pass` (no-op) | генерируется полноценно |

## Генерируемые функции

**`test_sql(results: list[str]) -> None`**
Каждый элемент `results` — CSV-строка (первая строка = заголовки, остальные = данные).
Проверяет:
- Наличие обязательных колонок в заголовке (например, `sku`, `path`)
- Непустоту результатов, если задача предполагает наличие товаров (skip для zero-count задач)
- Для агрегатных запросов: результаты непусты, первая строка данных содержит parseable integer — конкретное имя колонки-алиаса не проверяется
- `results[-1]` используется как финальный результат; не предполагать что `results[0]` — data query

**`test_answer(sql_results: list[str], answer: dict) -> None`**
Ключи `answer`: `outcome`, `message`, `grounding_refs`, `reasoning`, `completed_steps`.
Проверяет:
- `answer['outcome']` равен ожидаемой строке outcome (например, `'OUTCOME_OK'`)
- `answer['message']` непуст
- `answer['grounding_refs']` непуст при `outcome == 'OUTCOME_OK'` и когда задача предполагает найденные товары (пустой допустим для zero-count / aggregate-only)
- `answer['message']` содержит ключевые факты из задачи (бренд, тип товара и т.п.) при OK-outcome

## Правила генерации тестов

- Одна функция на тест, без классов
- Только Python stdlib; импорты — внутри тела функции
- Пустой `results` допустим для zero-count задач — не утверждать непустоту безусловно
- Никогда не использовать `outcome != 'OUTCOME_OK'` проверки — «товар не найден», «атрибут отсутствует» → всегда `OUTCOME_OK` с `<NO>` в message

## Anti-patterns (запрещено)

- Никаких точных строк из текста TASK с учётом регистра: вместо `assert 'Cordless Drill Driver' in answer['message']` — проверка через `.lower()` с отдельными ключевыми словами
- Никакого хардкода конкретного алиаса колонки (`'count'`, `'total'`) в проверках заголовков SQL — для агрегатов: проверять что первая строка данных парсится как integer
- Для запросов с `COUNT(`, `SUM(`, `AVG(`, `MIN(`, `MAX(`: НИКОГДА не assert `len(rows) > 1` — data row count всегда равен 1
- Никакой проверки конкретного числового значения для COUNT-задач — только формат `<COUNT:`
- Не assert `outcome != 'OUTCOME_OK'` — проверять содержимое `message` для негативных результатов

## Формат вывода

Фаза возвращает чистый JSON (первый символ `{`) с полями:
- `reasoning` — анализ: ожидаемый outcome, обязательные колонки, правила непустоты
- `sql_tests` — строка с кодом функции `test_sql`
- `answer_tests` — строка с кодом функции `test_answer`

## История изменений

- **2026-05-15** (из [[data/prompts/test_gen.md]]): страница создана
- **2026-05-17** (из [[data/prompts/tdd.md]]): обновлено — TDD всегда обязательна (TDD_ENABLED удалён); task_type: sql/compute/default (legacy lookup/temporal/etc удалены); SDD_SPEC как вход; TDD failure → LEARN (не hard stop); anti-pattern `outcome != 'OUTCOME_OK'` добавлен
