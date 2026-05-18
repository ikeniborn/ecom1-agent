---
wiki_sources:
  - "[[docs/superpowers/specs/2026-05-12-structured-sql-pipeline-design.md]]"
  - "[[docs/superpowers/specs/2026-05-12-eval-driven-rules-design.md]]"
  - "[[docs/superpowers/specs/2026-05-13-schema-gate-sku-fix-design.md]]"
  - "[[CLAUDE.md]]"
  - "[[agent/CLAUDE.md]]"
  - "[[docs/superpowers/specs/2026-05-17-prompt-architecture-design.md]]"
  - "[[docs/superpowers/specs/2026-05-17-learn-ctx-compaction-design.md]]"
wiki_updated: 2026-05-18
wiki_status: developing
wiki_outgoing_links:
  - "[[pipeline-phases/assembler-phase]]"
  - "[[pipeline-phases/sdd-phase]]"
  - "[[pipeline-phases/test-generation-phase]]"
  - "[[pipeline-phases/answer-phase]]"
  - "[[pipeline-phases/learn-phase]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
  - "[[design-decisions/sgr-pattern]]"
tags:
  - ecom1-agent
  - documentation
aliases:
  - "SQL Pipeline"
  - "phase pipeline"
  - "pipeline state machine"
---

# SQL Pipeline (детерминированный фазовый пайплайн)

Детерминированный pipeline для catalogue lookup задач. Каждая фаза выполняет строго определённую функцию; переходы между фазами жёстко заданы кодом, не LLM. Реализован в `agent/pipeline.py`.

## Архитектура (актуальная, 2026-05-17)

Entry point: `main.py` → BitGN harness → `orchestrator.py:run_agent()` → `prephase.py` → `pipeline.py`

### Фазы цикла (до MAX_STEPS циклов)

| Фаза | Тип | Назначение |
|------|-----|-----------|
| **ASSEMBLE** | LLM | `prompt_assembler.py:assemble_prompt()` — 1 LLM-вызов; собирает `unified_context` из learn_ctx + rules + security + vault + schema |
| **SDD** | LLM | Spec-Driven Development: `[unified_context, sdd.md]` → `SddOutput` (spec + plan + agents_md_refs) |
| **AGENTS.MD refs check** | детерминированная | Если `agents_md_refs` пусто, но index terms в задаче → LEARN |
| **SCHEMA** | детерминированная | `schema_gate.py:check_schema_compliance()` — unknown columns, unverified literals, double-key JOINs |
| **VALIDATE** | детерминированная | `EXPLAIN <query>` через VM exec — синтаксическая валидация SQL |
| **TDD** | LLM | `test_runner.py` — всегда запускается; генерирует SQL + answer тесты, выполняет их |
| **EXECUTE** | детерминированная | Исполнение запросов; пустой результат → LEARN |
| **ANSWER** | LLM | `[unified_context, answer.md]` → `AnswerOutput` → `vm.answer()` |
| **LEARN** (при любом failure) | LLM | `[unified_context, learn.md]` → `LearnOutput` → compaction или append → `learn_ctx` → next cycle |

### Принцип сборки промтов

Каждая LLM-фаза получает:
```
system: [unified_context (block 1), phase_guide (block 2, cache_control=ephemeral)]
```
`unified_context` — результат ASSEMBLE-фазы. `phase_guide` — файл `data/prompts/{phase}.md`.

### Управление learn_ctx

```
Старт задачи: load_learned_ctx(task_id) → начальный learn_ctx (из предыдущего FAILURE)
Каждый цикл: assemble_prompt(..., learn_ctx, ...)
LEARN (при failure):
    compacted_ctx валиден → learn_ctx[:] = compacted_ctx  (compaction)
    иначе             → learn_ctx.append(rule_content)   (fallback)
FAILURE (все циклы исчерпаны): save_learned_ctx(task_id, learn_ctx)
SUCCESS: eval_log write (с learn_ctx) + clear_learned_ctx(task_id)
```

**compacted_ctx** — поле `LearnOutput` (добавлено 2026-05-18). LLM возвращает дедуплицированный список всех правил; при валидном значении заменяет `learn_ctx` целиком вместо append. Предотвращает рост контекста при семантически дублирующихся ошибках. См. [[pipeline-phases/learn-phase]].

### Управление eval_log

- eval_log пишется **только при SUCCESS** (`outcome=ok`)
- Содержит поле `learn_ctx` — все правила накопленные в сессии
- Evaluator запускается async только при success (если `EVAL_ENABLED=1`)
- При FAILURE — eval_log не пишется

## Prephase (до запуска пайплайна)

`prephase.py:run_prephase()` выполняется один раз перед пайплайном:
1. Читает `/AGENTS.MD` с VM → `agents_md_content` + `agents_md_index`
2. Запускает `.schema` + PRAGMA → `schema_digest` + `db_schema`
3. Определяет `task_type`: `sql` | `compute` | `default` (legacy-типы удалены)

## LLM routing

`llm.py:call_llm_raw()`: провайдер определяется по префиксу модели:
- `anthropic/` → Anthropic SDK (prompt caching через `cache_control`)
- `openrouter/` → OpenRouter (OpenAI-compatible)
- bare name / `ollama/` → local Ollama
- `CC_ENABLED=1` → CC CLI subprocess

Поддерживаемые phase models: `sdd`, `tdd`, `learn`, `evaluator`, `assembler`, `executor` (через `_PHASE_MODEL_MAP`).

## Optimization loop

`scripts/propose_optimizations.py`:
- Читает `data/eval_log.jsonl` (только `outcome=ok` записи)
- Анализирует `learn_ctx` и evaluator recommendations
- **Автоматически** применяет оптимизации (все с `verified: true`):
  - `data/rules/sql-NNN.yaml`
  - `data/security/sec-NNN.yaml`
  - `data/prompts/<target>.md` (append)

## Rule Lifecycle (обновлённый)

```
LEARN phase → learn_ctx (in-session)
    ↓ (при SUCCESS)
eval_log (с полем learn_ctx)
    ↓
scripts/propose_optimizations.py → data/rules/sql-NNN.yaml (verified: true, auto-applied)
    ↓
Используется на следующих запусках через RulesLoader
```

## История изменений

- **2026-05-12/13** (ранние спеки): создан детерминированный пайплайн SQL_PLAN → VALIDATE → EXECUTE → LEARN → ANSWER
- **2026-05-17** ([[docs/superpowers/specs/2026-05-17-prompt-architecture-design.md]]): редизайн промп-архитектуры — добавлен ASSEMBLE, SQL_PLAN → SDD, TDD обязательна, learn_ctx persist, eval_log только на success, security check как отдельный шаг убран
