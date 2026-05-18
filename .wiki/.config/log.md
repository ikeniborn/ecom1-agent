# Wiki Log

<!-- Append-only лог. Новые записи добавляются в конец. -->

## 2026-05-14T00:00:00

**Операция:** ingest
**Источник:** data/prompts/answer.md
**Домен:** документация

**Затронуто страниц:** 2

- СОЗДАНА: `.wiki/документация/pipeline-phases/answer-phase.md` (stub)
- СОЗДАНА: `.wiki/документация/design-decisions/grounding-refs.md` (stub)

---

## 2026-05-14T00:01:00

**Операция:** ingest (batch)
**Источники:** data/prompts/resolve.md, data/prompts/sql_plan.md, docs/superpowers/specs/2026-05-14-active-eval-validation-design.md, docs/superpowers/specs/2026-05-14-api-update-carts-design.md, data/prompts/answer.md (update)
**Домен:** документация

**Затронуто страниц:** 6

- СОЗДАНА: `.wiki/документация/pipeline-phases/resolve-phase.md` (developing)
- СОЗДАНА: `.wiki/документация/pipeline-phases/sql-plan-phase.md` (developing)
- СОЗДАНА: `.wiki/документация/specs/active-eval-validation.md` (developing)
- СОЗДАНА: `.wiki/документация/specs/api-update-carts.md` (developing)
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/answer-phase.md` — добавлен раздел Cart Answers, статус stub→developing
- ОБНОВЛЕНА: `.wiki/документация/design-decisions/grounding-refs.md` — добавлен раздел cart grounding_refs, статус stub→developing

---

## 2026-05-14T00:02:00

**Операция:** ingest
**Источник:** scripts/CLAUDE.md
**Домен:** документация (определён по содержимому — файл вне `docs/`, но описывает agent-модуль)

**Затронуто страниц:** 2

- СОЗДАНА: `.wiki/документация/agent-modules/propose-optimizations.md` (developing) — entity_type: agent-module
- СОЗДАНА: `.wiki/документация/design-decisions/eval-optimization-dedup.md` (developing) — entity_type: design-decision

---

## 2026-05-15T00:00:00

**Операция:** ingest
**Источник:** data/prompts/test_gen.md
**Домен:** документация (определён по содержимому — файл вне `docs/`, но описывает pipeline-phase TDD)

**Затронуто страниц:** 1

- СОЗДАНА: `.wiki/документация/pipeline-phases/test-generation-phase.md` (stub) — entity_type: pipeline-phase

---

## 2026-05-16T00:00:00

**Операция:** ingest
**Источник:** .worktrees/mock-validation/data/prompts/mock_gen.md
**Домен:** документация (определён по содержимому — промпт-фаза офлайн-валидации пайплайна агента)

**Затронуто страниц:** 2

- СОЗДАНА: `.wiki/документация/pipeline-phases/mock-gen-phase.md` (stub) — entity_type: pipeline-phase
- СОЗДАНА: `.wiki/документация/design-decisions/mock-validation-offline.md` (stub) — entity_type: design-decision

---

## 2026-05-17T00:00:00

**Операция:** ingest (batch)
**Источники:** data/prompts/answer.md, data/prompts/assembler.md, data/prompts/sdd.md, data/prompts/tdd.md, CLAUDE.md, agent/CLAUDE.md, docs/superpowers/plans/2026-05-17-prompt-architecture-redesign.md, docs/superpowers/specs/2026-05-17-prompt-architecture-design.md
**Домен:** документация

**Затронуто страниц:** 9

- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/answer-phase.md` — добавлены разделы: точность названий моделей, отсутствующее числовое поле → LEARN, валидация области магазинов; обновлены wiki_outgoing_links
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/test-generation-phase.md` — TDD всегда обязательна (TDD_ENABLED удалён); task_type: sql/compute/default; SDD_SPEC как вход; failure → LEARN; новые anti-patterns; stub→developing
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/sql-plan-phase.md` — добавлена заметка об устаревании (переименована в SDD); CONFIRMED VALUES / RESOLVE удалены
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/sql-pipeline-overview.md` — полный редизайн архитектуры: ASSEMBLE фаза, SDD вместо SQL_PLAN, unified_context, learn_ctx persist, eval_log success-only, новая таблица фаз
- СОЗДАНА: `.wiki/документация/pipeline-phases/sdd-phase.md` (developing) — entity_type: pipeline-phase
- СОЗДАНА: `.wiki/документация/pipeline-phases/assembler-phase.md` (developing) — entity_type: pipeline-phase
- СОЗДАНА: `.wiki/документация/agent-modules/pipeline-prompt-assembler.md` (developing) — entity_type: agent-module
- СОЗДАНА: `.wiki/документация/specs/prompt-architecture-redesign.md` (developing) — entity_type: spec
- СОЗДАНА: `.wiki/документация/plans/prompt-architecture-redesign.md` (stub) — entity_type: plan

---

## 2026-05-17T12:00:00

**Операция:** ingest (batch)
**Источники:** data/prompts/answer.md, data/prompts/sdd.md, data/prompts/test_gen.md (→ tdd.md)
**Домен:** документация

**Затронуто страниц:** 2

- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/answer-phase.md` — добавлен раздел «Обработка checkout-задач» (OUTCOME_NONE_UNSUPPORTED + basket path в grounding_refs); добавлена «История изменений»
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/sdd-phase.md` — добавлено «Исключение для checkout-задач» (discovery-шаг перед UNSUPPORTED); уточнены ограничения exec-инструментов
- ПРОПУЩЕНА: `.wiki/документация/pipeline-phases/test-generation-phase.md` — уже актуальна (последнее обновление 2026-05-17 из tdd.md); data/prompts/test_gen.md не существует

**Примечание:** Файл data/prompts/test_gen.md не найден — соответствующий промпт находится по пути data/prompts/tdd.md и уже был ingested 2026-05-17.

---

## 2026-05-18T00:00:00

**Операция:** update-docs (graphify incremental + llm-wiki)
**Источники:** agent/models.py, agent/pipeline.py, tests/test_models.py, tests/test_pipeline.py, data/prompts/learn.md, docs/superpowers/specs/2026-05-17-learn-ctx-compaction-design.md, CLAUDE.md, agent/CLAUDE.md
**Домен:** код + документация

**Graphify:** incremental AST update — 4 changed code files; 1204 nodes / 2102 edges / 72 communities

**Затронуто страниц wiki:** 4

- СОЗДАНА: `.wiki/документация/pipeline-phases/learn-phase.md` (stable) — полная документация LEARN фазы: _run_learn, LearnOutput, compacted_ctx logic, fallback, тесты
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/sql-pipeline-overview.md` — LEARN фаза: compacted_ctx в таблице и в разделе learn_ctx management; ссылка на learn-phase
- ОБНОВЛЕНА: `.wiki/документация/agent-modules/pipeline-prompt-assembler.md` — добавлен раздел LearnOutput/compacted_ctx
- ОБНОВЛЕНА: `.wiki/.config/index.md` — добавлена запись learn-phase.md

---

