# Wiki Index

<!-- Этот файл обновляется автоматически при ingest/init/query --save -->

## Страницы по доменам

### документация

#### pipeline-phases
- `.wiki/документация/pipeline-phases/answer-phase.md` — Фаза ANSWER: финальный синтез JSON-ответа по результатам SQL
- `.wiki/документация/pipeline-phases/resolve-phase.md` — Фаза RESOLVE: value-resolution и генерация discovery SQL по идентификаторам задачи
- `.wiki/документация/pipeline-phases/sql-plan-phase.md` — Фаза SQL_PLAN (устаревшее): планирование SQL-запросов — см. sdd-phase
- `.wiki/документация/pipeline-phases/sdd-phase.md` — Фаза SDD: Spec-Driven Development — spec_goal + success_criteria + plan + actions кандидаты
- `.wiki/документация/pipeline-phases/plan-phase.md` — Фаза PLAN: выбор единственного action из SddOutput.actions → PlanOutput
- `.wiki/документация/pipeline-phases/assembler-phase.md` — Фаза ASSEMBLE: LLM-ассемблер unified_context из всех источников
- `.wiki/документация/pipeline-phases/test-generation-phase.md` — Фаза TDD: генерация acceptance-тестов test_sql/test_answer (всегда обязательна)
- `.wiki/документация/pipeline-phases/sql-pipeline-overview.md` — SQL Pipeline: детерминированный фазовый пайплайн (обзор)
- `.wiki/документация/pipeline-phases/mock-gen-phase.md` — Фаза Mock Gen: генерация синтетических CSV-данных и Python-assertions для офлайн-валидации
- `.wiki/документация/pipeline-phases/learn-phase.md` — Фаза LEARN: диагностика failure по SDD+PLAN+ANSWER выводам, обновление learn_ctx
- `.wiki/документация/pipeline-phases/consolidate-phase.md` — Фаза CONSOLIDATE: LLM-дедупликация active rules — устранение дублей, перекрытий, противоречий

#### design-decisions
- `.wiki/документация/design-decisions/grounding-refs.md` — Grounding Refs: механизм ссылок на SKU каталога через AUTO_REFS
- `.wiki/документация/design-decisions/eval-optimization-dedup.md` — Eval Optimization Deduplication: двухуровневая дедупликация (content-hash + LLM cluster + existing-content injection)
- `.wiki/документация/design-decisions/mock-validation-offline.md` — Офлайн-валидация пайплайна через синтетические моки (mock_results + answer_assertions без ECOM VM)
- `.wiki/документация/design-decisions/sgr-pattern.md` — SGR Pattern: Schema → Guide → Reasoning

#### specs
- `.wiki/документация/specs/active-eval-validation.md` — Active Eval Validation: переход от пассивного к активному eval с validate_recommendation()
- `.wiki/документация/specs/api-update-carts.md` — API Update + Shopping Carts: синхронизация с upstream API, /bin/date /bin/id, поддержка корзин
- `.wiki/документация/specs/prompt-architecture-redesign.md` — Спека: Редизайн промп-архитектуры (2026-05-17)
- `.wiki/документация/specs/prompt-rules-separation.md` — Спека: Prompt/Rules Separation — thin prompts, бизнес-правила в rules/ (2026-05-18)

#### plans
- `.wiki/документация/plans/prompt-architecture-redesign.md` — План реализации: редизайн промп-архитектуры (2026-05-17)
- `.wiki/документация/plans/learned-knowledge-redesign.md` — План: Learned Knowledge Redesign — постоянная per-task база знаний, удаление rules/security/eval_log (2026-05-19)

#### agent-modules
- `.wiki/документация/agent-modules/propose-optimizations.md` — propose_optimizations.py: синтез eval-рекомендаций в кандидат-файлы (rules, security, prompts)
- `.wiki/документация/agent-modules/pipeline-prompt-assembler.md` — agent/prompt_assembler.py: LLM-ассемблер unified_context с persist/load learn_ctx
