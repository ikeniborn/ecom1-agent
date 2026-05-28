# Intent: Knowledge Lifecycle & Pipeline Speed

**Date:** 2026-05-28
**Status:** draft

## Objective

Тестирование выявило два критических сбоя: (1) эвристика решает задачу в первом прогоне, но падает при следующем — условия задачи и данные меняются, накопленные знания устаревают; (2) пайплайн слишком медленный, агент не укладывается в приемлемое время. Агент не выполняет свои задачи в текущем состоянии.

## Desired Outcomes

- Задача решается корректно при каждом запуске независимо от входных данных
- Пайплайн укладывается в 300–600 секунд на задачу

## Health Metrics

- Точность LEARN-правил не деградирует (правила остаются применимыми)
- Качество CODEGEN не деградирует (AST lint проходит, MockVM выполняет)
- Совместимость с MockVM сохраняется

## Strategic Context

- Interacts with: `data/learned/`, `data/heuristics/`, `pipeline.py`, `prompt_assembler.py`
- Priority trade-off: **скорость** (300–600с) = **доверие** (корректность при смене данных); стоимость (LLM-вызовы) — вторична

## Constraints

### Steering (behavioral guidance)
- Формат `data/learned/` можно менять
- Схему `last_run` / `heuristic_valid` можно менять
- Добавление и удаление фаз (IDD/SDD/PLAN) разрешено

### Hard (architectural enforcement)
- MockVM API не меняется
- Protobuf/harness слой (`bitgn/`) не трогать
- LEARN-правила должны оставаться читаемыми и применимыми

## Autonomy Zones

- **Full autonomy** (reversible, low risk): оптимизация prompt'ов внутри фаз, рефакторинг вспомогательных функций без смены поведения
- **Guarded** (log + confidence threshold): рефакторинг `pipeline.py` без смены внешнего поведения
- **Proposal-first** (needs approval): удаление/сброс `data/learned/` между запусками; инвалидация `heuristic_valid`; добавление новых фаз или удаление IDD/SDD/PLAN
- **No autonomy** (human only): изменения в `bitgn/`, `proto/`, harness-интеграции

## Stop Rules

- **Halt if:** точность LEARN-правил или качество CODEGEN деградирует после изменений
- **Escalate if:** невозможно уложиться в 300–600с без удаления критических фаз — нужно согласование
- **Done when:** все задачи бенчмарка решаются корректно при повторных запусках с разными данными и укладываются в 300–600с
