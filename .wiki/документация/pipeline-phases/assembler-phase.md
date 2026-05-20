---
wiki_sources:
  - "[[data/prompts/assembler.md]]"
  - "[[docs/superpowers/plans/2026-05-19-learned-knowledge-redesign.md]]"
wiki_updated: 2026-05-19
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/sdd-phase]]"
  - "[[pipeline-phases/sql-pipeline-overview]]"
  - "[[pipeline-phases/consolidate-phase]]"
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

Первая фаза каждого цикла пайплайна. LLM-ассемблер собирает `unified_context` — единый контекстный документ. Каждая последующая фаза цикла (SDD, TDD, LEARN, ANSWER) получает `[unified_context] + [phase_guide]` вместо собственного system builder.

## Основные характеристики

- Вызывается в начале каждого цикла pipeline loop (до SDD), с актуальным `learn_ctx`
- Делает 1 LLM-вызов с инструкцией из `data/prompts/assembler.md`
- Возвращает: `unified_context: str`
- Разрешение противоречий: LEARNED > BASE
- Модель: `MODEL_ASSEMBLER` (по умолчанию — `MODEL`)

## Входы ассемблера (learned knowledge redesign, 2026-05-19)

| Источник | Приоритет | Секция в unified_context |
|----------|-----------|--------------------------|
| `learn_ctx` (активные записи из `data/learned/{task_id}.yaml`) | 1 (высший) | `# LEARNED` |
| VAULT (agents_md из prephase) | 2 | `# BASE` |
| schema_digest + db_schema | — | `# SCHEMA` |

`data/rules/*.yaml`, `data/security/*.yaml`, `data/config/task_blocks.yaml` — удалены. SQL-планировочные правила теперь живут исключительно в `data/learned/{task_id}.yaml` как LEARNED-записи.

## Структура unified_context

```
# LEARNED
<активные правила из learn_ctx, новейшие последними; пропустить если пусто>

# BASE
<domain rules из VAULT/AGENTS.MD, релевантные задаче>

# SCHEMA
<schema digest и db schema>
```

## `_build_sources` (новая реализация)

```python
def _build_sources(task_text, task_type, prephase_result, learn_ctx) -> str:
    parts = [f"TASK_TEXT: {task_text}", f"TASK_TYPE: {task_type}"]
    if learn_ctx:
        parts.append("## LEARNED (highest priority)\n" + "\n".join(f"- {r}" for r in learn_ctx))
    if pre.agents_md_content:
        parts.append(f"## VAULT\n{pre.agents_md_content}")
    if pre.schema_digest:
        parts.append(f"## SCHEMA_DIGEST\n{_format_schema_digest(pre.schema_digest)}")
    if pre.db_schema:
        parts.append(f"## DB_SCHEMA\n{pre.db_schema}")
    ...
```

Убраны: загрузка `RulesLoader`, `load_security_gates`, `load_task_blocks`, директории `_RULES_DIR`, `_SECURITY_DIR`.
