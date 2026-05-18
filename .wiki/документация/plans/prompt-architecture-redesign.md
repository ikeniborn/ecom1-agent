---
wiki_sources:
  - "[[docs/superpowers/plans/2026-05-17-prompt-architecture-redesign.md]]"
wiki_updated: 2026-05-17
wiki_status: stub
wiki_outgoing_links:
  - "[[specs/prompt-architecture-redesign]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "prompt architecture implementation plan"
  - "2026-05-17 redesign plan"
---

# План реализации: редизайн промп-архитектуры (2026-05-17)

Реализационный план для [[specs/prompt-architecture-redesign]]. 11 задач от аудита legacy промтов до финального прогона тестов.

## Основные характеристики

**Цель:** Централизовать все промты в `data/prompts/`, добавить LLM-ассемблер unified_context, сделать TDD обязательным, persist learn_ctx при failures, писать eval_log только при success.

**Статус проверки (check-plan):** Все 4 критических и warning находки (F-001–F-004) — исправлены до начала имплементации.

## Структура задач

| Задача | Файлы | Суть |
|--------|-------|------|
| Task 1 | `data/prompts/core/lookup/catalogue → sdd/answer/tdd` | Аудит legacy блоков, перенос, удаление |
| Task 2 | `assembler.md`, `task_blocks.yaml`, `data/learned/` | Создание инфраструктурных файлов |
| Task 3 | `agent/llm.py` | MODEL_ASSEMBLER + убрать MODEL_TEST_GEN |
| Task 4 | `agent/prephase.py` | task_type: sql/compute/default |
| Task 5 | `agent/prompt.py` | _TASK_BLOCKS → yaml loader |
| Task 6 | `agent/prompt_assembler.py` | Создать модуль + тесты |
| Task 7 | `agent/pipeline.py` | Major rewrite: assemble_prompt, faz renames, eval_log, evaluator |
| Task 8 | `agent/evaluator.py` | Убрать _append_log |
| Task 9 | `scripts/propose_optimizations.py` | auto-apply (verified:true) |
| Task 10 | `.env.example` | Убрать TDD_ENABLED/MODEL_TEST_GEN, добавить MODEL_ASSEMBLER |
| Task 11 | Все файлы | Final test run и cleanup |

## Ключевые находки check-plan (все исправлены)

- **F-001 (CRITICAL):** SDD failure → hard stop вместо LEARN — исправлено: SDD failure → LEARN (error_type="llm_fail")
- **F-002 (CRITICAL):** TDD failure → hard stop вместо LEARN — исправлено: TDD failure → LEARN (error_type="llm_fail")
- **F-003 (WARNING):** Нет шага добавления learn_ctx в eval_log entry — исправлено в Task 7.6
- **F-004 (WARNING):** Расхождение имени файла (llm.py vs models.py для MODEL_TEST_GEN) — исправлено

## File Map

```
CREATE  agent/prompt_assembler.py
CREATE  data/config/task_blocks.yaml
CREATE  data/prompts/assembler.md
CREATE  data/learned/.gitkeep
RENAME  data/prompts/test_gen.md → data/prompts/tdd.md
MODIFY  agent/llm.py
MODIFY  agent/models.py
MODIFY  agent/prephase.py
MODIFY  agent/prompt.py
MODIFY  agent/pipeline.py
MODIFY  agent/evaluator.py
MODIFY  scripts/propose_optimizations.py
MODIFY  .env.example
AUDIT   data/prompts/core.md, lookup.md, catalogue.md → extract + delete
DELETE  data/prompts/core.md
```
