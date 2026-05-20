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

## 2026-05-19T00:00:00

**Операция:** ingest (batch)
**Источники:** CLAUDE.md, agent/CLAUDE.md, data/prompts/learn.md, data/prompts/assembler.md, data/prompts/sdd.md, data/prompts/tdd.md, data/prompts/answer.md, docs/superpowers/specs/2026-05-18-prompt-rules-separation-design.md, docs/superpowers/plans/2026-05-19-learned-knowledge-redesign.md
**Домен:** документация

**Затронуто страниц:** 6

- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/learn-phase.md` — learned knowledge redesign (2026-05-19): новая сигнатура _run_learn (удалён prior_learn_hashes), новые поля LearnOutput (deactivate/skip вместо compacted_ctx), постоянный YAML-формат, consolidation logic через LLM, ссылки на test_learned_storage.py
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/assembler-phase.md` — новые входы: LEARNED из data/learned/; удалены RULES/SECURITY/PROMPT_BLOCKS секции; новый _build_sources
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/sdd-phase.md` — история изменений 2026-05-19: sdd.md очищается от domain-специфики; wiki_sources обновлены
- ОБНОВЛЕНА: `.wiki/документация/agent-modules/pipeline-prompt-assembler.md` — новые API (load_learned_entries, _apply_learn_diff, _next_entry_id); удалены save/clear_learned_ctx; новый persist/load цикл без eval_log
- СОЗДАНА: `.wiki/документация/plans/learned-knowledge-redesign.md` (stub) — план 15 задач: замена rules/security/eval_log постоянной per-task YAML базой
- СОЗДАНА: `.wiki/документация/specs/prompt-rules-separation.md` (stub) — спека 2026-05-18: thin prompts, исправление sec-write-detect-001

---

## 2026-05-20T00:00:00

**Операция:** ingest
**Источники:** data/prompts/plan.md (NEW), data/prompts/sdd.md (UPDATED), data/prompts/learn.md (UPDATED)
**Домен:** документация

**Контекст:** Редизайн пайплайна ASSEMBLE→SDD→PLAN→EXECUTE→ANSWER. SddOutput переработан на spec_goal+success_criteria+plan+actions+error_code. Добавлена фаза PLAN. LEARN получает полный контекст цикла (SDD+PLAN+ANSWER outputs).

**Затронуто страниц:** 4

- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/sdd-phase.md` — SddOutput: spec_goal + success_criteria + plan (рассуждения) + actions (кандидаты) + error_code; убраны типизированные шаги и agents_md_refs; добавлена ссылка на plan-phase
- СОЗДАНА: `.wiki/документация/pipeline-phases/plan-phase.md` (stub) — фаза PLAN: PlanOutput с approach+steps+action (выбор единственного из SddOutput.actions)
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/learn-phase.md` — расширены входы: SDD_OUTPUT + PLAN_OUTPUT + ANSWER_OUTPUT; правила нацелены на spec/plan quality, не raw SQL; добавлен раздел «Входы LEARN»
- ОБНОВЛЕНА: `.wiki/.config/index.md` — добавлена запись plan-phase.md; обновлены описания sdd-phase и learn-phase

---

## 2026-05-20T01:00:00

**Операция:** ingest
**Источники:** CLAUDE.md, .env.example, data/prompts/consolidate.md, data/prompts/sdd.md
**Домен:** документация

**Контекст:** Новая фаза CONSOLIDATE — LLM-постобработка active rules для устранения дублей, перекрытий и противоречий. Добавлены переменные MODEL_CONSOLIDATE и MAX_TOKENS_CONSOLIDATE. SDD-фаза — без изменений (актуальна).

**Затронуто страниц:** 4

- СОЗДАНА: `.wiki/документация/pipeline-phases/consolidate-phase.md` (stub) — фаза CONSOLIDATE: ConsolidateOutput с skip/consolidations; устраняет дублирование в active rules; MODEL_CONSOLIDATE + MAX_TOKENS_CONSOLIDATE=2048
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/learn-phase.md` — добавлена ссылка на consolidate-phase; уточнена связь LEARN+CONSOLIDATE в consolidation logic
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/assembler-phase.md` — добавлена ссылка на consolidate-phase в wiki_outgoing_links
- ОБНОВЛЕНА: `.wiki/.config/index.md` — добавлена запись consolidate-phase.md

---

## 2026-05-20T02:00:00

**Операция:** ingest (batch)
**Источники:** data/prompts/answer.md, data/prompts/assembler.md, data/prompts/learn.md, data/prompts/plan.md, data/prompts/sdd.md
**Домен:** документация

**Затронуто страниц:** 5

- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/answer-phase.md` — синхронизация с актуальным промптом: удалены устаревшие разделы (OUTCOME_NEED_MORE_DATA, Cart Answers, checkout, inventory validation); добавлены clarification guard и таблица источников grounding_refs по типу execute-результата
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/assembler-phase.md` — добавлены LAST_RUN handling (suspect-state при failure/empty-grounding_refs, WARNING-преамбула) и раздел «Разрешение противоречий» (LEARNED > BASE)
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/learn-phase.md` — добавлены Repeated Failure Protocol (деактивация виновных правил при WARNING) и Loop Prevention (детали)
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/plan-phase.md` — исправлена env var модели с MODEL_SDD на MODEL_PLAN
- ОБНОВЛЕНА: `.wiki/документация/pipeline-phases/sdd-phase.md` — добавлен раздел ACCUMULATED RULES (hard-constraint блок от LEARN-фазы)

---

