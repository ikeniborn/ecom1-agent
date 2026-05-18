---
wiki_sources:
  - "[[data/prompts/learn.md]]"
  - "[[docs/superpowers/specs/2026-05-17-learn-ctx-compaction-design.md]]"
  - "[[agent/models.py]]"
  - "[[agent/pipeline.py]]"
wiki_updated: 2026-05-18
wiki_status: stable
wiki_outgoing_links:
  - "[[pipeline-phases/sql-pipeline-overview]]"
  - "[[pipeline-phases/assembler-phase]]"
  - "[[agent-modules/pipeline-prompt-assembler]]"
tags:
  - ecom1-agent
  - documentation
aliases:
  - "LEARN phase"
  - "_run_learn"
  - "learn_ctx"
  - "compacted_ctx"
---

# Фаза LEARN

Фаза восстановления после failure. Вызывается из `agent/pipeline.py:_run_learn()` при любом сбое пайплайна (SDD-parse, schema gate, validate, execute, TDD, answer test). LLM диагностирует ошибку и добавляет правило в `learn_ctx` для следующего цикла.

## Когда вызывается

| Trigger | `error_type` |
|---------|-------------|
| SDD LLM parse fail | `llm_fail` |
| AGENTS.MD refs check fail | `semantic` |
| Schema gate blocked | `security` |
| TDD LLM parse fail | `llm_fail` |
| EXECUTE empty result / error | `empty` / `semantic` |
| Answer test fail | `test_fail` |

При `error_type=llm_fail` фаза **пропускает** добавление правила (LLM не вернул валидный JSON — нет чему учиться).

## Сигнатура `_run_learn`

```python
def _run_learn(
    unified_context: str,
    model: str,
    cfg: dict,
    task_text: str,
    queries: list[str],
    error: str,
    sgr_trace: list[dict],
    learn_ctx: list[str],       # мутируется in-place
    agents_md_index: dict,
    error_type: str = "semantic",
    cycle: int = 0,
    prior_learn_hashes: "set[str] | None" = None,
    task_id: str = "",
) -> None:
```

## Модель вывода `LearnOutput`

```python
class LearnOutput(BaseModel):
    reasoning: str
    conclusion: str
    rule_content: str
    agents_md_anchor: str | None = None
    compacted_ctx: list[str] | None = None   # добавлено 2026-05-18
```

## Логика обновления learn_ctx (порядок проверок)

```
1. error_type == "llm_fail" → пропустить (return)
2. prior_learn_hashes guard → дубликат правила → пропустить (return)
3. agents_md_anchor заполнен → vault rule в learn_ctx.append() → return
   # compacted_ctx игнорируется на anchor path
4. compacted_ctx валиден (non-None, non-empty, all strings) → learn_ctx[:] = compacted_ctx
5. иначе → learn_ctx.append(rule_content)
6. save_learned_ctx(task_id, learn_ctx)  # всегда, после ветки 4 или 5
```

## Context Compaction (2026-05-18)

После каждого LEARN LLM вместе с `rule_content` возвращает `compacted_ctx` — дедуплицированный и обобщённый список **всех** правил. Если валиден — заменяет `learn_ctx` целиком. Цель: предотвратить рост `learn_ctx` при повторяющихся семантически-близких ошибках.

### Правила слияния (из `data/prompts/learn.md`)

- Семантически похожие правила → объединить в одно каноническое
- Разные паттерны ошибок → оставить раздельно
- Конкретные ID (`basket_115`) → обобщить (`<basket_id>`)
- `compacted_ctx` обязан включать новый `rule_content`
- Если `EXISTING_RULES` пустой → `compacted_ctx = [rule_content]`

### Fallback

`compacted_ctx=None` или `compacted_ctx=[]` → обычный `learn_ctx.append(rule_content)`.

## Prompt-файл

`data/prompts/learn.md` — phase guide для LLM. Разделы:

- **Context** — задача + ошибка + существующие правила (`EXISTING_RULES`)
- **Diagnosis Rules** — как анализировать ошибку
- **Conclusion Specificity** — требования к rule_content
- **Context Compaction** — инструкции по compacted_ctx
- **Learn Loop Cap** — ограничение на дублирующиеся правила
- **Output format (JSON only)** — схема вывода

## Тесты

`tests/test_pipeline.py`:
- `test_learn_compaction_replaces_ctx` — integration через `run_pipeline`: compacted_ctx заменяет learn_ctx
- `test_learn_compaction_fallback_on_empty` — `_run_learn` с `compacted_ctx=[]` → append
- `test_learn_compaction_fallback_on_none` — `_run_learn` с `compacted_ctx=None` → append
