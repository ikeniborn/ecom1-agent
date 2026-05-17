# Prompt Architecture Redesign

**Date:** 2026-05-17  
**Status:** Approved for implementation

---

## Problem

1. Промты частично хардкодированы в Python-коде (`pipeline.py`, `evaluator.py`).
2. LEARN-правила живут только in-session, не агрегируются системно.
3. eval_log пишется на failed-задачи — нет сигнала «что реально сработало».
4. TDD — опциональный флаг (`TDD_ENABLED`), использует отдельную модель (`MODEL_TEST_GEN`).
5. SECURITY CHECK — отдельный программный шаг, дублирует то что уже в промте.

---

## Goals

- Все промты из `data/prompts/*.md` (ноль хардкода в коде).
- Unified prompt на задачу, собирается LLM task-aware (знает задачу + все источники).
- LEARN интегрируется в in-session `learn_ctx`, агрегируется в eval_log при success.
- eval_log только для успешных задач.
- TDD обязателен, модель SDD.
- `propose_optimizations.py` читает eval_log и автоматически обновляет файлы.

---

## Architecture

### New Pipeline Flow

```
prephase(task)
    → PrephaseResult (schema_digest, agents_md_index, task_type, date, ...)

learn_ctx: list[str] = []

pipeline_loop (up to MAX_STEPS):
    1. assemble_prompt(task_text, prephase_result, learn_ctx)
           ← data/prompts/ + data/rules/ + data/security/ + learn_ctx
           ← 1 LLM-вызов (task-aware)
           → unified_context: str

    2. SDD   → system: unified_context + sdd.md
               → SPEC (описание задачи) + PLAN (шаги выполнения)
               on failure → LEARN → next cycle

    3. TDD   → system: unified_context + tdd.md
               → тесты для всех шагов SDD PLAN
               on failure → LEARN → next cycle

    4. EXECUTE → выполнить все шаги PLAN (SQL, read, exec, compute)
                 on failure → LEARN → next cycle

    5. TESTING → запустить TDD-тесты против результатов EXECUTE
                 (покрывает все типы шагов из SDD)
                 on failure → LEARN → next cycle
                 *** ANSWER запускается ТОЛЬКО если TESTING прошёл ***

    6. ANSWER → system: unified_context + answer.md
                → AnswerOutput
                on failure (VERIFY_ANSWER не прошёл) → LEARN → next cycle
                *** SUCCESS только если VERIFY_ANSWER прошёл ***

    LEARN (при любом failure):
        → system: unified_context + learn.md
        → LLM extracts rule
        → проверяет дубли против текущего learn_ctx
        → если new: append learn_ctx
        → continue loop (с нового assemble_prompt на следующем цикле)

SUCCESS (VERIFY_ANSWER прошёл):
    eval_log write (task_id, task_text, task_type, trace, learn_ctx, outcome=ok)
    if EVAL_ENABLED: evaluator async → добавляет recommendations в eval_log entry

FAILURE (MAX_STEPS исчерпан без SUCCESS):
    eval_log НЕ пишется
    learn_ctx очищается (GC)
```

---

## New: `agent/prompt_assembler.py`

```python
@dataclass
class AssembledPrompt:
    unified_context: str

def assemble_prompt(
    task_text: str,
    task_type: str,
    prephase_result: PrephaseResult,
    learn_ctx: list[str],
    model: str,
) -> AssembledPrompt:
    ...
```

**Входы для LLM-ассемблера:**
| Источник | Приоритет | Порядок |
|---|---|---|
| `learn_ctx` (in-memory, текущая сессия) | 1 (высший) | Как добавлены (новейшие — последние, наивысший приоритет) |
| `data/rules/*.yaml` (`verified: true`) | 2 | По имени файла |
| `data/security/*.yaml` (`verified: true`) | 3 | ID + message (краткий) |
| `data/prompts/` базовые блоки + task-type блоки | 4 | По `task_blocks.yaml` |
| `prephase_result.schema_digest` + `db_schema` | metadata | Включается в секцию `# SCHEMA` unified_context |
| `prephase_result.agents_md_index` (vault rules) | metadata | Включается в секцию `# VAULT` unified_context |

**LLM-инструкция (assembler):**
- Дай задачу: `task_text`, `task_type`
- Дай все источники (выше)
- LLM: объедини без дублирования, разреши противоречия в пользу высшего приоритета
- Структура unified_context: `# LEARNED` → `# RULES` → `# SECURITY` → `# BASE`
- Убери нерелевантные для этой задачи правила

**Вызывается:** в начале каждого цикла pipeline loop (до SDD), передавая актуальный `learn_ctx`.

---

## Changes to Existing Modules

### `agent/pipeline.py`
- Убрать `_build_sdd_system`, `_build_learn_system`, `_build_answer_system` (заменить на `assemble_prompt` + append phase-guide)
- Убрать SECURITY CHECK как отдельный шаг (security gates в unified_context)
- TDD: всегда запускать (убрать `if TDD_ENABLED` проверку)
- `TEST_GEN` фаза → переименовать в `TDD`
- `VERIFY` фаза → переименовать в `TESTING`
- eval_log: писать только при `outcome=ok`
- Evaluator: запускать только при success (не failure)
- Schema gate: оставить (программная валидация column/table names)

### `agent/models.py`
- Убрать `MODEL_TEST_GEN` (тест-генерация использует модель SDD)

### `agent/prompt.py`
- Убрать `_TASK_BLOCKS` Python dict → заменить на `data/prompts/task_blocks.yaml`
- `build_system_prompt()` → упростить или удалить (логика переходит в `prompt_assembler.py`)

### `scripts/propose_optimizations.py`
- Читает `data/eval_log.jsonl` (только `outcome=ok` записи)
- LLM анализирует `learn_ctx` из записей + evaluator recommendations
- **Автоматически перезаписывает** целевые файлы:
  - `data/prompts/*.md` — обновить блоки
  - `data/rules/*.yaml` — добавить/обновить правила (с `verified: true`)
  - `data/security/*.yaml` — добавить/обновить gates (с `verified: true`)
- Логирует изменения
- Убрать `verified: true` gate как блокировку (оптимизации применяются автоматически)

### `agent/evaluator.py`
- Запускается только при success (убрать вызов на failure)
- Выход: recommendations поле в eval_log entry

---

## data/prompts/ Audit (Pre-implementation Task)

Перед имплементацией:

1. **Перенести хардкод из кода в файлы:**
   - Найти f-строки и строковые литералы с LLM-инструкциями в `pipeline.py`, `evaluator.py`, `prephase.py`
   - Вынести в соответствующие `data/prompts/*.md` блоки

2. **Ревизия существующих блоков:**
   - `test_gen.md` → переименовать в `tdd.md`
   - Обновить содержимое `sdd.md` (убрать ссылки на SECURITY CHECK, обновить фазы)
   - Проверить `learn.md`, `answer.md`, `pipeline_evaluator.md` — актуализировать
   - Удалить дублирующие/устаревшие секции

3. **`data/prompts/task_blocks.yaml`** — новый файл, заменяет `_TASK_BLOCKS` dict в `prompt.py`:
```yaml
lookup:   [core, lookup, catalogue]
temporal: [core, lookup]
capture:  [core]
crm:      [core, lookup]
distill:  [core, lookup]
preject:  [core]
default:  [core, lookup, catalogue]
```

4. **Добавить `data/prompts/assembler.md`** — системный промт для LLM-ассемблера (инструкции по сборке unified_context).

---

## eval_log Entry Format (Updated)

```json
{
  "task_id": "t42",
  "task_text": "...",
  "task_type": "lookup",
  "outcome": "ok",
  "cycles": 2,
  "trace": [...],
  "learn_ctx": ["правило 1 (цикл 1)", "правило 2 (цикл 2)"],
  "prephase": {
    "agents_md": "...",
    "schema_digest": {}
  },
  "evaluator": null
}
```

`evaluator` поле заполняется async если `EVAL_ENABLED=1` (только при success).

---

## Config Changes

### Removed env vars
- `TDD_ENABLED` — TDD всегда обязателен
- `MODEL_TEST_GEN` — используется `MODEL_SDD` (или `MODEL`)

### New env var
- `MODEL_ASSEMBLER` — модель для сборки unified prompt (defaults to `MODEL`)

### `.env.example` / `.secrets.example`
- Убрать `TDD_ENABLED`, `MODEL_TEST_GEN`
- Добавить `MODEL_ASSEMBLER` (optional, с комментарием)

---

## Files to Create / Modify / Delete

| Action | File |
|--------|------|
| CREATE | `agent/prompt_assembler.py` |
| CREATE | `data/prompts/task_blocks.yaml` |
| CREATE | `data/prompts/assembler.md` |
| RENAME | `data/prompts/test_gen.md` → `data/prompts/tdd.md` |
| MODIFY | `agent/pipeline.py` |
| MODIFY | `agent/prompt.py` |
| MODIFY | `agent/models.py` |
| MODIFY | `agent/evaluator.py` |
| MODIFY | `scripts/propose_optimizations.py` |
| MODIFY | `data/prompts/sdd.md` (аудит + актуализация) |
| MODIFY | `.env.example` |
| AUDIT  | `data/prompts/learn.md`, `answer.md`, `pipeline_evaluator.md` |

---

## Phase Names (Canonical)

| Old name | New name |
|---|---|
| `sql_plan` / SDD | `sdd` |
| `test_gen` / TEST_GEN | `tdd` |
| execute | `execute` |
| verify (sql tests) | `testing` |
| answer | `answer` |
| verify_answer | `verify_answer` |
| learn | `learn` |

---

## Non-Goals

- Не меняем протобуф/harness
- Не меняем schema_gate (программная валидация)
- Не добавляем новые типы задач
- Не делаем UI/API
