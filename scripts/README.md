# scripts/propose_optimizations.py

Синтезирует записи из `data/eval_log.jsonl` в файлы-кандидаты через LLM. Три канала: правила SQL, security-гейты, патчи промптов.

## Предварительные требования

```bash
cp .env.example .env        # добавить MODEL_EVALUATOR=anthropic/claude-...
uv sync                     # установить зависимости
```

`MODEL_EVALUATOR` — модель для синтеза (та же что в `.env`).

## Запуск

**Предварительный просмотр (без записи файлов):**

```bash
EVAL_ENABLED=1 uv run python main.py   # собрать eval_log
uv run python scripts/propose_optimizations.py --dry-run
```

**Запись кандидатов:**

```bash
uv run python scripts/propose_optimizations.py
```

## Результаты

| Канал | Куда пишет | Активация |
|-------|-----------|-----------|
| `rule_optimization` | `data/rules/sql-NNN.yaml` (`verified: false`) | Поставить `verified: true` |
| `security_optimization` | `data/security/sec-NNN.yaml` (`verified: false`) | Поставить `verified: true` |
| `prompt_optimization` | `data/prompts/optimized/YYYY-MM-DD-NN-file.md` | Скопировать секцию в `data/prompts/file.md` вручную |

## Проверка и применение

```bash
# Просмотреть предложенные правила
cat data/rules/sql-NNN.yaml

# Активировать правило
# Изменить verified: false → verified: true в файле

# Повторный запуск пропускает уже обработанные записи автоматически
uv run python scripts/propose_optimizations.py
```

Хеши обработанных записей хранятся в `data/.eval_optimizations_processed`.

---

# scripts/trace_view.py

Pretty-вьюер per-task трейса `logs/<run>/<task_id>.jsonl`. Разворачивает диалог в хронологическом порядке: system-промпт, user-сообщение каждой фазы/цикла и ответ модели (assistant). System-промпты в трейсе дедуплицируются (один `header_system` на sha256, на него ссылаются многие `llm_call`) — вьюер резолвит ссылку и печатает полный system один раз на sha, далее back-reference.

## Запуск

```bash
uv run python scripts/trace_view.py logs/<run>/t09.jsonl          # весь трейс
uv run python scripts/trace_view.py logs/<run>/                   # список трейсов в прогоне
uv run python scripts/trace_view.py logs/<run>/t09.jsonl --phase PLAN     # только фаза PLAN
uv run python scripts/trace_view.py logs/<run>/t09.jsonl --no-system      # скрыть system
uv run python scripts/trace_view.py logs/<run>/t09.jsonl --max-chars 2000 # обрезать тела до N символов
```

## Флаги

| Флаг | Действие |
|------|----------|
| `--phase X` | Только указанная фаза: `DESIGN`, `CODEGEN`, `INTENT`, `PLAN`, `LEARN`, `TESTGEN`, `COMPACTION` |
| `--no-system` | Не печатать system-промпты |
| `--full-system` | Печатать полный system на каждом вызове (без дедупа) |
| `--llm-only` | Скрыть не-LLM события таймлайна (gate/sql/test) |
| `--max-chars N` | Обрезать каждое тело до N символов (0 = без ограничения) |

Цвет включается автоматически при выводе в терминал; в pipe (`| less`, `> file`) — чистый текст. Источник записей `llm_call` — единый funnel `agent/llm.py:call_llm_raw` (фаза проставляется вызывающим, цикл — через `agent.trace.set_cycle`).
