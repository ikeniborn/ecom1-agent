# Intent: Approach A — pre-phase grounding для качественного frozen INTENT

**Date:** 2026-06-15
**Status:** approved
**Источник:** `docs/superpowers/notes/2026-06-14-agent-debug-findings.md`

## Objective

Качество ответа агента (INTERPRETER path: INTENT→PLAN→interpret→verify) гейтится двумя
upstream-артефактами, которые цикл не может починить: **pre-phase fact set** и **frozen INTENT**.

Корень — pre-phase под-граундит INTENT (P1/P9): `docs_inventory` всегда пуст (`tree`.`stdout`
не существует в `TreeResponse`), policy-доки читаются только по path-имени, topic/entity-релевантные
доки (catalogue-addenda, counting policy) никогда не читаются. Frozen INTENT под-специфицирует
acceptance → verify false-green → отгружается неверный ответ. Эмпирически: **t09 = 0.00**
(grader требует `/docs`-путь как grounding ref; verify.py:27 считает `/docs` static-only).

Approach A чинит UPSTREAM: harden pre-phase так, чтобы он собрал *каждый артефакт для качественного
INTENT с первого раза*. Качественный frozen INTENT делает verify честным, а loop — сходящимся.
Доказано end-to-end на живом грейдере: цепочка discover-doc → read-rule → PLAN-applies-rule →
cite-doc-path превращает prod 0.00 в **1.0** (probe v4, `scripts/probe_t09_refs.py`).

Решено (2026-06-14): Approach B (re-ground INTENT post-discovery) **отклонён** — INTENT это контракт,
из которого деривируется весь прогон; мутировать его после цикла нелогично. Loop-фиксы (R1/R4/R5)
вторичны.

## Desired Outcomes

- **t09 0.00→1.0 в реальном prod benchmark-прогоне** (не только hand-probe): doc discovered → read →
  rule applied → doc cited.
- **Bucket-B задачи (policy/counting/grounding) растут; зелёные задачи остаются зелёными**; общий
  score ≥ baseline ~32%.
- **`docs_inventory` непустой**: discovery через Search/tree-walk (не `tree`.`stdout`) → INTENT реально
  видит кандидат-доки; `gather_status` показывает `ok`/`empty`/`error` на факт (нет silent `""`).
- **refs ПРОЕКТИРУЮТСЯ из INTENT.required_refs per-outcome**, PLAN поставляет только bindings →
  G1 (под-цитирование) и G2 (пере-цитирование) исчезают структурно.

## Health Metrics

- **Зелёные задачи остаются зелёными** — задачи со score 1.0 не регрессируют; baseline score ≥ ~32%.
- **Бюджет LLM-вызовов** — discovery детерминирована (Search, 0 LLM в типичном случае); DOC-SELECT
  fallback только когда Search пуст (cap 4). Не раздуваем 1/2/7 budget.
- **Время прогона** — ~3ч/прогон на 54 задачи не растёт значимо; pre-phase caps (≈4KB/doc, ≤3 hits)
  держат контекст.
- **Re-seed устойчивость** — INTENT не запекает literals (kind_id/city/doc-path); всё резолвится из
  текущего StartRun. Правила = методы, не значения.

## Strategic Context

- Взаимодействует с: `orchestrator.py` (pre-phase: `gather_prephase_facts`, discovery, `policies`),
  INTENT/PLAN/interpret/verify (`_run_interpreted`), `ir_models.py` (`IntentSpec.required_refs`),
  `intent.md` / `plan.md` (промпты), `verify.py` (I1, `/docs`-эвристика), живой грейдер (ref-контракт).
- **Приоритет trade-off: TRUST (корректность).** Честный verify и правильный ответ важнее лишнего
  LLM-вызова/времени. INTENT-quality превыше скорости и стоимости. Лучше +1 fallback-вызов, чем
  false-green.

## Constraints

### Steering (поведенческие ориентиры)

- **Recall/precision split:** discovery = recall (широко поднимает кандидат-доки); INTENT = precision
  (объявляет только load-bearing доки как `required_refs`). Чтение дока ≠ обязанность цитировать.
- **Читать CONTENT, не paths:** правило дока load-bearing для ВЫЧИСЛЕНИЯ (naive count=3, rule-correct=2).
  Содержимое дока читается в pre-phase (cap ≈4KB), не только путь.
- **gather_status сигнал (P6):** каждый факт → `ok`/`empty`/`error`, surfaced в `_facts_block`; INTENT
  различает "нет факта" и "fetch упал". Нет silent `""`.
- **Loop-фиксы вторичны:** R1 (load IR rules), R4 (identical-plan guard), R5 (MAX_STEPS↓), R2/R3
  (LEARN reframe + observations в PLAN) — дешёвые stop-the-bleed, желанны но ПОСЛЕ корня. Не блокируют
  Approach A.

### Hard (архитектурное принуждение)

- **INTENT остаётся frozen:** запускается раз, не мутирует после цикла. Approach B (re-ground
  post-discovery) ОТКЛОНЁН. Фикс только upstream (pre-phase).
- **IDD/SDD раздел:** INTENT = WHAT/why (objective, outcome_space, constraints, `required_refs` =
  цитировать governing doc + record, `success_criteria` = СТРУКТУРНЫЕ/grounding only). INTENT НЕ
  запекает SQL/join/kind_id/city. PLAN = HOW: читает eligibility-rule из `facts.policies` → строит
  rule-correct SQL.
- **Не патчить `data/prompts/`** для починки task-failure: task-specific знание только через LEARN в
  `data/learned/{tid}.yaml`. `data/prompts/*.md` — только общие структурные правила.
- **Discovery без `tree`.`stdout`:** инвентарь через `Search` (`SearchMatch.path`) и/или tree-walk
  (`TreeResponse.root` → `TreeNode{name,is_dir,children}`). НЕ `tree`.`stdout` (пуст), НЕ
  VMAdapter `Find(kind=…)` (`FindRequest.type` int32 → `kind=` kwarg даёт пусто).

## Autonomy Zones

- **Full autonomy (reversible, low risk):** ничего полностью без апрува — по решению пользователя
  всё proposal-first.
- **Guarded (log + confidence threshold):** —
- **Proposal-first (needs approval):** **ВСЕ суб-шаги** — discovery/pre-phase правки, `ir_models`
  schema change (`required_refs` per-outcome, drop `required_ref_kinds`), `verify.py` (I1 rewrite,
  удаление `/docs`-эвристики), `intent.md`/`plan.md` правки. Сначала план на апрув → потом код.
- **No autonomy (human only):** cutover флага в prod после A/B-замера.

> Эти зоны OVERRIDE дефолт subagent-driven-development "continuous execution, don't pause". Любой шаг,
> касающийся proposal-first / no-go решений, помечается **HUMAN CHECKPOINT** в плане.

## Stop Rules

- **Halt if:** A/B-прогон показывает регресс на зелёных задачах ИЛИ score < baseline ~32%.
- **Escalate if:** требуется изменить `ir_models` schema, удалить verify-эвристику, или тронуть
  `data/prompts/` (proposal-first → апрув человека).
- **Done when:** в реальном benchmark-прогоне **t09 = 1.0**, bucket-B растёт, общий score ≥ baseline
  ~32%, зелёные задачи не упали — **измерено** на живом грейдере, не «тесты зелёные».
