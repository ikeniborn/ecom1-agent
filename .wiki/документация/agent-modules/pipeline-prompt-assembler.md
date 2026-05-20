---
wiki_sources:
  - "[[CLAUDE.md]]"
  - "[[agent/CLAUDE.md]]"
  - "[[docs/superpowers/plans/2026-05-17-prompt-architecture-redesign.md]]"
  - "[[docs/superpowers/plans/2026-05-19-learned-knowledge-redesign.md]]"
wiki_updated: 2026-05-19
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/assembler-phase]]"
  - "[[pipeline-phases/sql-pipeline-overview]]"
  - "[[pipeline-phases/learn-phase]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "prompt_assembler.py"
  - "assemble_prompt"
  - "AssembledPrompt"
---

# agent/prompt_assembler.py

Модуль LLM-ассемблера unified_context. Вызывается в начале каждого цикла пайплайна — собирает все источники (learn_ctx, vault, schema) и делает 1 LLM-вызов для построения `unified_context: str`. Управляет постоянным per-task knowledge base в `data/learned/{task_id}.yaml`.

## Основные характеристики

- Создан в рамках редизайна промп-архитектуры (2026-05-17)
- Обновлён в рамках learned knowledge redesign (2026-05-19)
- Заменяет функции `_build_sdd_system`, `_build_learn_system`, `_build_answer_system` из pipeline.py

## Публичный API

**`assemble_prompt(task_text, task_type, prephase_result, learn_ctx, model, cfg, task_id="") → AssembledPrompt`**
Основная точка входа. Вызывает LLM-ассемблер с текущим `learn_ctx`, возвращает `AssembledPrompt(unified_context: str)`. Не загружает персистированный learn_ctx — он передаётся уже актуальным (обновляется инкрементально через `_apply_learn_diff`).

**`load_learned_ctx(task_id: str) → list[str]`**
Возвращает содержимое **активных** записей из `data/learned/{task_id}.yaml`. Возвращает `[]` если файл отсутствует.

**`load_learned_entries(task_id: str) → list[dict]`**
Возвращает **все** записи (active + inactive) из `data/learned/{task_id}.yaml` — для передачи как EXISTING_RULES в LEARN-фазу.

**`_apply_learn_diff(task_id, rule_content, reasoning, deactivate, deactivate_reason, source="learn") → None`**
Атомарно обновляет `data/learned/{task_id}.yaml`: деактивирует записи из `deactivate`, добавляет новую запись с монотонным id (`r001`, `r002`, ...).

**`_next_entry_id(entries) → str`**
Генерирует следующий монотонный id (`rNNN`) — никогда не повторяет существующие.

## Удалённые функции (redesign 2026-05-19)

- `save_learned_ctx` — теперь каждый LEARN пишет инкрементально через `_apply_learn_diff`
- `clear_learned_ctx` — файл **никогда не удаляется** при успехе, накапливается

## Dataclass AssembledPrompt

```python
@dataclass
class AssembledPrompt:
    unified_context: str
```

## Зависимости (после redesign)

Импортирует из: `llm.py` (call_llm_raw, _resolve_model_for_phase), `prompt.py` (load_prompt), `prephase.py` (PrephaseResult, _format_schema_digest).

Удалены зависимости: `rules_loader.RulesLoader`, `sql_security.load_security_gates`, `prompt.load_task_blocks`.

## Persist/Load цикл learn_ctx (новый)

```
Запуск задачи:
    load_learned_ctx(task_id) → начальный learn_ctx (активные записи)

Каждый цикл:
    assemble_prompt(..., learn_ctx, ...) → unified_context

Каждый LEARN:
    _apply_learn_diff(task_id, rule_content, ...) → атомарно пишет в YAML
    + обновляет learn_ctx in-memory

SUCCESS/FAILURE:
    Файл data/learned/{task_id}.yaml не удаляется — остаётся постоянным
```

## LearnOutput (новые поля)

`LearnOutput` (в `agent/models.py`) теперь содержит:
- `deactivate: list[str]` — ids записей для деактивации
- `deactivate_reason: str | None` — причина деактивации
- `skip: bool` — не добавлять новое правило (дубликат покрыт rXXX)
- `skip_reason: str | None` — id покрывающей записи

Поле `compacted_ctx` удалено. Подробнее: [[pipeline-phases/learn-phase]].
