---
wiki_sources:
  - "[[CLAUDE.md]]"
  - "[[agent/CLAUDE.md]]"
  - "[[docs/superpowers/plans/2026-05-17-prompt-architecture-redesign.md]]"
wiki_updated: 2026-05-18
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/assembler-phase]]"
  - "[[pipeline-phases/sql-pipeline-overview]]"
wiki_external_links: []
tags:
  - ecom1-agent
aliases:
  - "prompt_assembler.py"
  - "assemble_prompt"
  - "AssembledPrompt"
---

# agent/prompt_assembler.py

Модуль LLM-ассемблера unified_context. Вызывается в начале каждого цикла пайплайна — собирает все источники (learn_ctx, rules, security, vault, schema) и делает 1 LLM-вызов для построения `unified_context: str`. Также управляет персистентностью `learn_ctx` между запусками задачи.

## Основные характеристики

- Создан в рамках редизайна промп-архитектуры (2026-05-17)
- Заменяет функции `_build_sdd_system`, `_build_learn_system`, `_build_answer_system` из pipeline.py
- Использует фазовую модель из `llm.py` через ключ `"assembler"`

## Публичный API

**`assemble_prompt(task_text, task_type, prephase_result, learn_ctx, model, cfg, task_id="") → AssembledPrompt`**
Основная точка входа. Загружает персистированный learn_ctx (если есть), объединяет с in-session learn_ctx, вызывает LLM-ассемблер, возвращает `AssembledPrompt(unified_context: str)`.

**`load_learned_ctx(task_id: str) → list[str]`**
Загружает `data/learned/{task_id}.yaml` — персистированный learn_ctx из предыдущего неуспешного запуска. Возвращает `[]` если файл отсутствует.

**`save_learned_ctx(task_id: str, learn_ctx: list[str]) → None`**
Персистирует learn_ctx в `data/learned/{task_id}.yaml` при исчерпании всех циклов без SUCCESS.

**`clear_learned_ctx(task_id: str) → None`**
Удаляет `data/learned/{task_id}.yaml` при SUCCESS — уроки агрегированы в eval_log.

## Dataclass AssembledPrompt

```python
@dataclass
class AssembledPrompt:
    unified_context: str
```

## Зависимости

Импортирует из: `llm.py` (call_llm_raw, _resolve_model_for_phase), `prompt.py` (load_prompt, load_task_blocks), `prephase.py` (PrephaseResult, _format_schema_digest), `rules_loader.py` (RulesLoader), `sql_security.py` (load_security_gates).

## Persist/Load цикл learn_ctx

```
Запуск задачи:
    load_learned_ctx(task_id) → начальный learn_ctx (если был предыдущий FAILURE)

Каждый цикл:
    assemble_prompt(..., learn_ctx, ...) → unified_context

FAILURE (все циклы исчерпаны):
    save_learned_ctx(task_id, learn_ctx) → data/learned/{task_id}.yaml

SUCCESS:
    clear_learned_ctx(task_id) → удалить data/learned/{task_id}.yaml
    _append_eval_log(..., learn_ctx=learn_ctx, ...) → в eval_log
```

## LearnOutput и compacted_ctx

`LearnOutput` (в `agent/models.py`) содержит поле `compacted_ctx: list[str] | None = None`. При LEARN-фазе LLM возвращает дедуплицированный список всех правил. `_run_learn` в `pipeline.py` заменяет `learn_ctx` целиком если `compacted_ctx` валиден, иначе делает append. Подробнее: [[pipeline-phases/learn-phase]].
