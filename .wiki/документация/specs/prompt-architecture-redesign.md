---
wiki_sources:
  - "[[docs/superpowers/specs/2026-05-17-prompt-architecture-design.md]]"
wiki_updated: 2026-05-17
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/sql-pipeline-overview]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[pipeline-phases/sdd-phase]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "Prompt Architecture Redesign"
  - "prompt architecture spec"
  - "unified_context spec"
---

# Спека: Редизайн промп-архитектуры

**Дата:** 2026-05-17  
**Статус:** Approved for implementation

Спецификация централизации промтов, добавления LLM-ассемблера unified_context, обязательного TDD и персистентности learn_ctx.

## Проблемы (до редизайна)

1. Промты частично хардкодированы в Python-коде (`pipeline.py`, `evaluator.py`)
2. LEARN-правила живут только in-session, не агрегируются системно
3. eval_log писался на failed-задачи — нет сигнала «что реально сработало»
4. TDD — опциональный флаг (`TDD_ENABLED`), использует отдельную модель (`MODEL_TEST_GEN`)
5. SECURITY CHECK — отдельный программный шаг, дублирует то что уже в промте

## Цели

- Все промты из `data/prompts/*.md` (ноль хардкода в коде)
- Unified prompt на задачу, собирается LLM task-aware (знает задачу + все источники)
- LEARN интегрируется в in-session `learn_ctx`, агрегируется в eval_log при success
- eval_log только для успешных задач
- TDD обязателен, использует основную модель SDD
- `propose_optimizations.py` читает eval_log и автоматически обновляет файлы

## Новый пайплайн

```
prephase(task) → PrephaseResult

learn_ctx: list[str] = []

pipeline_loop (до MAX_STEPS):
    1. ASSEMBLE: assemble_prompt(task, prephase, learn_ctx) → unified_context
    2. SDD:      [unified_context + sdd.md] → spec + plan
    3. TDD:      [unified_context + tdd.md] → sql_tests + answer_tests
    4. EXECUTE:  выполнить все шаги PLAN
    5. TESTING:  запустить TDD-тесты
    6. ANSWER:   [unified_context + answer.md] → AnswerOutput
    LEARN (при любом failure): [unified_context + learn.md] → rule → learn_ctx
```

## Ключевые изменения файлов

| Действие | Файл |
|----------|------|
| CREATE | `agent/prompt_assembler.py` |
| CREATE | `data/config/task_blocks.yaml` |
| CREATE | `data/prompts/assembler.md` |
| CREATE | `data/learned/` (директория) |
| RENAME | `data/prompts/test_gen.md` → `data/prompts/tdd.md` |
| MODIFY | `agent/pipeline.py` (ASSEMBLE, SDD, eval_log, evaluator) |
| MODIFY | `agent/llm.py` (MODEL_ASSEMBLER, убрать MODEL_TEST_GEN) |
| MODIFY | `agent/models.py` (убрать MODEL_TEST_GEN) |
| MODIFY | `agent/prephase.py` (task_type: sql/compute/default) |
| MODIFY | `agent/prompt.py` (убрать _TASK_BLOCKS, загружать из yaml) |
| MODIFY | `agent/evaluator.py` (убрать _append_log, success-only) |
| MODIFY | `scripts/propose_optimizations.py` (auto-apply, verified:true) |
| DELETE | `data/prompts/core.md`, `lookup.md`, `catalogue.md` (legacy) |

## eval_log — новый формат

```json
{
  "task_id": "t42",
  "task_text": "...",
  "task_type": "sql",
  "outcome": "ok",
  "cycles": 2,
  "trace": [...],
  "learn_ctx": ["правило 1", "правило 2"],
  "prephase": {"agents_md": "...", "schema_digest": {}},
  "evaluator": null
}
```

`evaluator` поле заполняется async если `EVAL_ENABLED=1` (только при success).

## Изменения env vars

- Удалены: `TDD_ENABLED`, `MODEL_TEST_GEN`
- Добавлен: `MODEL_ASSEMBLER` (модель для ASSEMBLE-фазы; defaults to `MODEL`)

## Канонические имена фаз

| Старое | Новое |
|--------|-------|
| `sql_plan` / SQL_PLAN | `sdd` / SDD |
| `test_gen` / TEST_GEN | `tdd` / TDD |
| verify (sql tests) | `testing` / TESTING |
| answer | `answer` / ANSWER |
| learn | `learn` / LEARN |
