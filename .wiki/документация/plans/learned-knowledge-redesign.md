---
wiki_sources:
  - "[[docs/superpowers/plans/2026-05-19-learned-knowledge-redesign.md]]"
  - "[[docs/superpowers/specs/2026-05-18-prompt-rules-separation-design.md]]"
wiki_updated: 2026-05-19
wiki_status: stub
wiki_outgoing_links:
  - "[[pipeline-phases/learn-phase]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
  - "[[specs/prompt-architecture-redesign]]"
tags:
  - ecom1-agent
  - documentation
aliases:
  - "Learned Knowledge Redesign"
  - "permanent per-task knowledge base"
  - "learned redesign"
---

# План: Learned Knowledge Redesign (2026-05-19)

**Цель:** Заменить `data/rules/` + `data/security/` + `eval_log` постоянной per-task базой знаний в `data/learned/{task_id}.yaml` с LLM-driven дедупликацией при каждом добавлении правила.

## Проблема

Две смешанные архитектуры:
1. `data/rules/*.yaml` + `data/security/*.yaml` — статические правила, обновляемые `propose_optimizations.py`
2. `data/learned/{task_id}.yaml` — динамические правила из LEARN-фазы

Проблемы: `sec-write-detect-001` + `sdd.md` давали противоречивые инструкции по checkout (t21 bug, score 0). Мёртвые правила в промтах после удаления yaml-файлов. Отсутствие единого источника истины.

## Архитектура после redesign

```
data/learned/{task_id}.yaml  ← постоянный (active/inactive entries)
      ↓
LEARN phase (_apply_learn_diff):
  - LLM получает EXISTING_RULES (активные записи)
  - Возвращает: skip | deactivate[] | rule_content
  - Атомарно обновляет YAML

assemble_prompt(_build_sources):
  - LEARNED секция из активных записей
  - BASE секция из VAULT/AGENTS.MD
  - SCHEMA секция из prephase
```

Удалены: `data/rules/`, `data/security/`, `data/eval_log.jsonl`, `scripts/propose_optimizations.py`, `agent/evaluator.py`, `agent/rules_loader.py`.

## Новый YAML-формат

```yaml
task_id: t01
entries:
  - id: r001
    content: "Always SELECT sku, path FROM products"
    status: active
    source: learn
    created: "2026-05-19"
    reasoning: "grounding_refs was empty without sku"
    deactivated_reason: null
  - id: r002
    content: "Old superseded rule"
    status: inactive
    source: learn
    created: "2026-05-18"
    reasoning: "..."
    deactivated_reason: "Superseded by r003"
```

Файл **никогда не удаляется** при SUCCESS — накапливается как аудит-трейл.

## Задачи плана (15 шагов)

| # | Задача | Файлы |
|---|--------|-------|
| 1 | Failing tests для новых storage-функций | `tests/test_learned_storage.py` (CREATE) |
| 2 | Реализация `load_learned_entries`, `_apply_learn_diff`, `_next_entry_id` | `agent/prompt_assembler.py` |
| 3 | Extend `LearnOutput`: `deactivate`, `skip`, `skip_reason`; удалить `compacted_ctx` | `agent/models.py` |
| 4 | Standalone `check_retry_loop` (убрать `security_gates` param) | `agent/sql_security.py` |
| 5 | Обновить `_run_learn` — использовать `_apply_learn_diff` и EXISTING_RULES | `agent/pipeline.py` |
| 6 | Удалить security gates, eval_log, evaluator из `run_pipeline` | `agent/pipeline.py` |
| 7 | Очистить `_build_sources` — удалить RULES/SECURITY/PROMPT_BLOCKS | `agent/prompt_assembler.py` |
| 8 | Исправить тесты — conftest, test_pipeline, test_prompt_assembler | тесты |
| 9 | Удалить неиспользуемые модули и тест-файлы | `agent/rules_loader.py`, `agent/evaluator.py`, etc. |
| 10 | Удалить data-артефакты | `data/rules/`, `data/security/`, `data/eval_log.jsonl` |
| 11 | Скрипт миграции плоских YAML → новый формат | `scripts/migrate_learned.py` |
| 12 | Обновить `learn.md` — добавить deactivate/skip поля | `data/prompts/learn.md` |
| 13 | Обновить `assembler.md`; очистить sdd/tdd/answer от domain-специфики | `data/prompts/*.md` |
| 14 | Обновить `.env.example` и `CLAUDE.md` | docs |
| 15 | Финальная верификация: тесты + migration + DoD checks | все |

## Проверки DoD (Definition of Done)

```bash
uv run python -m pytest tests/ -v           # all tests pass
grep -r "rules_loader|evaluator|eval_log" agent/ tests/  # no output
test -d data/rules && echo FAIL || echo PASS
grep -iE "sku|ecom" data/prompts/sdd.md && echo FAIL || echo PASS
```

## Связанные страницы

- [[pipeline-phases/learn-phase]] — детали LEARN фазы с новой схемой
- [[pipeline-phases/assembler-phase]] — новые входы ассемблера без RULES/SECURITY
- [[agent-modules/pipeline-prompt-assembler]] — новые API: `load_learned_entries`, `_apply_learn_diff`
- [[specs/prompt-architecture-redesign]] — исходный редизайн промп-архитектуры (2026-05-17)
