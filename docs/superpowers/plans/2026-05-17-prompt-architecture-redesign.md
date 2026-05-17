---
review:
  plan_hash: d4906be568c975cb
  spec_hash: 244311d70d76d4db
  last_run: "2026-05-17"
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: skipped }
    verifiability: { status: skipped }
    consistency:   { status: skipped }
  findings:
    - id: F-001
      phase: coverage
      severity: CRITICAL
      section: "## Task 7: agent/pipeline.py — major rewrite"
      section_hash: 5b5b54c0be59fd41
      text: >
        Task 7 Step 5a: SDD failure → hard stop (не LEARN). Спека §Architecture §New Pipeline Flow
        явно указывает "on failure → LEARN → next cycle" для SDD-фазы.
        "LEARN (при любом failure)" — без исключений для SDD.
      verdict: fixed
      verdict_at: "2026-05-17"
    - id: F-002
      phase: coverage
      severity: CRITICAL
      section: "## Task 7: agent/pipeline.py — major rewrite"
      section_hash: 5b5b54c0be59fd41
      text: >
        Task 7 Step 6: TDD failure → hard stop (план говорит "поведение не меняется"). Спека
        §Architecture §New Pipeline Flow явно указывает "on failure → LEARN → next cycle"
        для TDD-фазы. Поведение hard-stop не покрыто спекой.
      verdict: fixed
      verdict_at: "2026-05-17"
    - id: F-003
      phase: coverage
      severity: WARNING
      section: "## Task 7: agent/pipeline.py — major rewrite"
      section_hash: 5b5b54c0be59fd41
      text: >
        Task 7.6 Steps 12-13: нет шага, добавляющего поле learn_ctx в eval_log entry.
        Спека требует "eval_log write (task_id, ..., learn_ctx, outcome=ok)" и JSON-пример
        содержит "learn_ctx": [...]. _append_eval_log должен быть обновлён для включения поля.
      verdict: fixed
      verdict_at: "2026-05-17"
    - id: F-004
      phase: coverage
      severity: WARNING
      section: "## File Map"
      section_hash: 325edf11b3586b35
      text: >
        File Map: MODIFY agent/llm.py для MODEL_TEST_GEN. Спека §agent/models.py
        явно указывает "MODIFY | agent/models.py" и "Убрать MODEL_TEST_GEN".
        Расхождение по имени файла — план верен технически (llm.py содержит _PHASE_MODEL_MAP),
        но спека называет models.py.
      verdict: fixed
      verdict_at: "2026-05-17"
---
# Prompt Architecture Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Централизовать все промты в `data/prompts/`, добавить LLM-ассемблер unified_context, сделать TDD обязательным, persist learn_ctx при failures, писать eval_log только при success.

**Architecture:** LLM-ассемблер (`prompt_assembler.py`) собирает `unified_context` из всех источников (learn_ctx, rules, security, prompt blocks) на каждом цикле пайплайна. Каждая фаза (SDD/TDD/LEARN/ANSWER) получает `[unified_context] + [phase_guide]` вместо собственного system builder. Security gates идут в `# SECURITY` unified_context, убираются как отдельный программный шаг.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML (уже в зависимостях), Anthropic SDK

---

## File Map

| Action | File |
|--------|------|
| CREATE | `agent/prompt_assembler.py` |
| CREATE | `data/config/task_blocks.yaml` |
| CREATE | `data/prompts/assembler.md` |
| CREATE | `data/learned/.gitkeep` |
| RENAME | `data/prompts/test_gen.md` → `data/prompts/tdd.md` |
| MODIFY | `agent/llm.py` (add MODEL_ASSEMBLER, remove MODEL_TEST_GEN `_PHASE_MODEL_MAP` entry) |
| MODIFY | `agent/models.py` (remove MODEL_TEST_GEN env var constant if defined there) |
| MODIFY | `agent/prephase.py` (_determine_task_type: sql\|compute\|default) |
| MODIFY | `agent/prompt.py` (remove _TASK_BLOCKS, load from yaml) |
| MODIFY | `agent/pipeline.py` (major: assembler, phase renames, eval_log, evaluator) |
| MODIFY | `agent/evaluator.py` (remove _append_log, success-only) |
| MODIFY | `scripts/propose_optimizations.py` (auto-apply, verified:true) |
| MODIFY | `.env.example` (remove TDD_ENABLED/MODEL_TEST_GEN, add MODEL_ASSEMBLER) |
| AUDIT  | `data/prompts/core.md`, `lookup.md`, `catalogue.md` → extract + delete |
| AUDIT  | `data/prompts/sdd.md`, `learn.md`, `answer.md`, `pipeline_evaluator.md` |
| DELETE | `data/prompts/core.md` (entirely legacy tool-calling format) |

---

## Task 1: Prompts Audit — читаем, извлекаем, удаляем legacy

**Files:**
- Read: `data/prompts/core.md`, `data/prompts/lookup.md`, `data/prompts/catalogue.md`
- Modify: `data/prompts/sdd.md`, `data/prompts/answer.md`, `data/prompts/learn.md`, `data/prompts/pipeline_evaluator.md`
- Rename: `data/prompts/test_gen.md` → `data/prompts/tdd.md`
- Delete: `data/prompts/core.md`, `data/prompts/lookup.md`, `data/prompts/catalogue.md`

### 1.1 Прочитай legacy блоки

- [ ] **Step 1: Прочитай core.md**

```bash
cat data/prompts/core.md
```

`core.md` — полностью legacy: определяет инструменты `exec/read/report_completion` старого tool-calling loop. SQL-правила уже перенесены в `sdd.md`. Удалить полностью — не переносить.

- [ ] **Step 2: Прочитай lookup.md и catalogue.md**

```bash
cat data/prompts/lookup.md
cat data/prompts/catalogue.md
```

Для каждого файла определи:
- Контент про SQL/domain (правила про JOIN, SKU, грounding_refs, стратегии поиска) → переноси в `sdd.md` если там нет, или в `answer.md` если про формат ответа.
- Tool-calling инструкции (`exec`, `read`, `report_completion`, `function` field) → удалить.
- Дублирующее содержимое (уже есть в sdd.md/answer.md) → удалить.

### 1.2 Обнови sdd.md

- [ ] **Step 3: Перенеси релевантный контент lookup.md/catalogue.md в sdd.md**

Добавь в конец `data/prompts/sdd.md` любые non-duplicate SQL/domain правила из lookup.md и catalogue.md.
Заодно в sdd.md:
- Убери любые ссылки на "SECURITY CHECK как отдельный шаг" (security gates теперь в unified_context, не отдельная программная проверка)
- Убери упоминания `CONFIRMED VALUES` (блок убран — RESOLVE phase удалена)
- Обнови раздел про фазы если есть: `TEST_GEN` → `TDD`, `VERIFY` → `TESTING`

- [ ] **Step 4: Проверь что sdd.md не упоминает tool-calling формат**

```bash
grep -n "report_completion\|\"tool\"\|\"function\"\|done_operations\|task_completed" data/prompts/sdd.md
```

Expected: пустой вывод. Если что-то нашлось — удали эти строки.

### 1.3 Обнови answer.md и learn.md

- [ ] **Step 5: Проверь answer.md на legacy**

```bash
grep -n "report_completion\|CONFIRMED VALUES\|TEST_GEN\|VERIFY\b" data/prompts/answer.md
```

Если есть ссылки — исправь: `TEST_GEN` → `TDD`, `VERIFY` → `TESTING`, удали tool-calling мусор.

- [ ] **Step 6: Проверь learn.md на legacy**

```bash
grep -n "report_completion\|CONFIRMED VALUES\|TEST_GEN\|VERIFY\b" data/prompts/learn.md
```

Аналогично исправь.

### 1.4 Обнови pipeline_evaluator.md

- [ ] **Step 7: Прочитай pipeline_evaluator.md**

```bash
cat data/prompts/pipeline_evaluator.md
```

Обнови если там есть: `task_type=lookup|temporal|capture|crm|distill|preject` → заменить на `sql|compute|default`. `TEST_GEN` → `TDD`. `VERIFY` → `TESTING`. `outcome=fail` → только `outcome=ok` записывается в eval_log.

### 1.5 Переименуй test_gen.md → tdd.md

- [ ] **Step 8: Rename файл**

```bash
mv data/prompts/test_gen.md data/prompts/tdd.md
```

- [ ] **Step 9: Обнови заголовок в tdd.md**

В начале файла измени `# Test Generation Phase` → `# TDD Phase` (первая строка файла).

```bash
sed -i '1s/.*/# TDD Phase/' data/prompts/tdd.md
```

- [ ] **Step 10: Убедись что task_type список актуален в tdd.md**

```bash
grep -n "task_type" data/prompts/tdd.md
```

Найди строку вида `- task_type=sql — generate both...` и обнови список типов: `sql`, `compute`, `default` (убери упоминания lookup/temporal/capture/etc).

### 1.6 Удали legacy файлы

- [ ] **Step 11: Удали core.md, lookup.md, catalogue.md**

```bash
rm data/prompts/core.md data/prompts/lookup.md data/prompts/catalogue.md
```

- [ ] **Step 12: Verify**

```bash
ls data/prompts/
```

Expected: `sdd.md tdd.md learn.md answer.md pipeline_evaluator.md` (без core/lookup/catalogue).

- [ ] **Step 13: Commit**

```bash
git add data/prompts/
git commit -m "refactor(prompts): audit legacy blocks, rename test_gen→tdd, remove core/lookup/catalogue"
```

---

## Task 2: Создай инфраструктурные файлы (assembler.md, task_blocks.yaml, learned/)

**Files:**
- Create: `data/prompts/assembler.md`
- Create: `data/config/task_blocks.yaml`
- Create: `data/learned/.gitkeep`

### 2.1 Создай assembler.md — системный промт для LLM-ассемблера

- [ ] **Step 1: Создай data/prompts/assembler.md**

```markdown
# Assembler Phase

You assemble a unified context document for a pipeline task.

/no_think

## Input

You receive:
- TASK_TEXT and TASK_TYPE
- LEARNED — in-session rules from prior failure cycles (highest priority)
- RULES — verified SQL planning rules from data/rules/
- SECURITY — verified security gates (summaries only)
- PROMPT_BLOCKS — base domain context blocks for this task_type

## Output

Return a single markdown document with exactly these sections in order:

```
# LEARNED
<rules from LEARNED, newest last; omit if empty>

# RULES
<relevant rules from RULES; omit rules with zero overlap with task_text entities/operations>

# SECURITY
<security gate summaries from SECURITY; include all>

# BASE
<combined domain context from PROMPT_BLOCKS; deduplicate; resolve contradictions in favor of higher priority>
```

## Relevance filter for RULES

Keep a rule if ANY of these match against task_text:
- entity type (product, cart, inventory, store, kind, sku, brand, model)
- operation type (count, find, list, sum, check, verify, compare)
- domain keyword (any noun or verb from task_text longer than 3 chars)

Drop a rule only if it has zero such overlaps. When in doubt, keep it.

## Contradiction resolution

Priority (highest → lowest): LEARNED > RULES > SECURITY > BASE

If two items contradict (opposite instructions for same scenario), keep the higher-priority item and omit the lower.

## Deduplication

Merge semantically equivalent items into one. Keep the most specific wording.

## Output format

Return the document as plain text. Start with `# LEARNED` header. No JSON, no preamble.
```

Сохрани точно этот контент в файл. В реальный файл убери внешние тройные backtick.

- [ ] **Step 2: Verify**

```bash
head -3 data/prompts/assembler.md
```

Expected: `# Assembler Phase`

### 2.2 Создай data/config/task_blocks.yaml

После аудита Task 1 ты знаешь какие блоки остались. Блоки — это stem-имена файлов в `data/prompts/`. После удаления core/lookup/catalogue остаётся только domain-контент в sdd.md (уже включается как phase guide). 

Если при аудите ты создал отдельный `domain.md` с extracted контентом — используй его. Если нет (весь контент уже в sdd.md) — используй пустые списки (ассемблер всё равно получает правила из rules/ и security/).

- [ ] **Step 3: Создай data/config/task_blocks.yaml**

```yaml
# Blocks loaded per task_type for the assembler's PROMPT_BLOCKS section.
# Each entry is a stem name from data/prompts/*.md (phase guides excluded).
# Phase guides (sdd, tdd, learn, answer, assembler) are loaded separately.
sql:
  - domain        # если domain.md создан при аудите; иначе оставь список пустым []
compute:
  - domain        # аналогично
default:
  - domain        # аналогично
```

Если `domain.md` не создавался (весь контент уже в sdd.md и нет отдельного domain-блока), укажи пустые списки:

```yaml
sql: []
compute: []
default: []
```

Правило: не фантазируй — вписывай только файлы которые реально существуют в `data/prompts/`.

- [ ] **Step 4: Verify**

```bash
python3 -c "import yaml; d = yaml.safe_load(open('data/config/task_blocks.yaml')); assert set(d.keys()) == {'sql','compute','default'}, d.keys(); print('ok')"
```

Expected: `ok`

### 2.3 Создай data/learned/.gitkeep

- [ ] **Step 5: Создай директорию и .gitkeep**

```bash
mkdir -p data/learned
touch data/learned/.gitkeep
```

- [ ] **Step 6: Добавь data/learned/ в .gitignore исключение (не игнорировать .gitkeep)**

```bash
grep -n "learned" .gitignore 2>/dev/null || echo "not in .gitignore"
```

Если `data/learned/` не упомянута в .gitignore — ничего делать не нужно. Если упомянута как игнорируемая — добавь исключение:
```
!data/learned/.gitkeep
```

- [ ] **Step 7: Commit**

```bash
git add data/prompts/assembler.md data/config/task_blocks.yaml data/learned/.gitkeep
git commit -m "feat(prompts): add assembler.md, task_blocks.yaml, data/learned/ dir"
```

---

## Task 3: agent/llm.py — добавь MODEL_ASSEMBLER, убери MODEL_TEST_GEN

**Files:**
- Modify: `agent/llm.py:67-73`

- [ ] **Step 1: Прочитай текущий _PHASE_MODEL_MAP (строки 67-73)**

```python
_PHASE_MODEL_MAP: dict[str, str | None] = {
    "sdd":      os.environ.get("MODEL_SDD") or None,
    "test_gen": os.environ.get("MODEL_TEST_GEN") or None,
    "executor": os.environ.get("MODEL_EXECUTOR") or None,
    "learn":    os.environ.get("MODEL_LEARN") or None,
    "evaluator": os.environ.get("MODEL_EVALUATOR") or None,
}
```

- [ ] **Step 2: Замени на новый вариант**

```python
_PHASE_MODEL_MAP: dict[str, str | None] = {
    "sdd":       os.environ.get("MODEL_SDD") or None,
    "tdd":       None,  # TDD uses MODEL (same as SDD)
    "executor":  os.environ.get("MODEL_EXECUTOR") or None,
    "learn":     os.environ.get("MODEL_LEARN") or None,
    "evaluator": os.environ.get("MODEL_EVALUATOR") or None,
    "assembler": os.environ.get("MODEL_ASSEMBLER") or None,
}
```

Убери строку `"test_gen": os.environ.get("MODEL_TEST_GEN") or None`.

- [ ] **Step 3: Verify**

```bash
uv run python -c "from agent.llm import _resolve_model_for_phase; print(_resolve_model_for_phase('assembler', 'fallback'))"
```

Expected: `fallback` (MODEL_ASSEMBLER не задан → используется default)

- [ ] **Step 4: Verify — test_gen убран**

```bash
python3 -c "from agent.llm import _PHASE_MODEL_MAP; assert 'test_gen' not in _PHASE_MODEL_MAP, 'test_gen still there'; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add agent/llm.py
git commit -m "feat(llm): add MODEL_ASSEMBLER phase, remove MODEL_TEST_GEN"
```

---

## Task 4: agent/prephase.py — обнови _determine_task_type

**Files:**
- Modify: `agent/prephase.py:151-158`

- [ ] **Step 1: Прочитай текущую функцию**

```python
def _determine_task_type(task_text: str, pre: "PrephaseResult") -> str:
    """Heuristic task_type detection. Default 'sql' for backward compat."""
    lower = task_text.lower()
    if any(kw in lower for kw in _READ_KEYWORDS):
        return "read"
    if any(kw in lower for kw in _COMPUTE_KEYWORDS) and not pre.schema_digest.get("tables"):
        return "compute"
    return "sql"
```

- [ ] **Step 2: Замени функцию**

`read` тип больше не существует — read steps обрабатываются внутри SDD PLAN. Задачи с read-ключевыми словами но обращением к БД → `sql`.

```python
def _determine_task_type(task_text: str, pre: "PrephaseResult") -> str:
    """Detect task type: sql | compute | default."""
    lower = task_text.lower()
    if any(kw in lower for kw in _COMPUTE_KEYWORDS) and not pre.schema_digest.get("tables"):
        return "compute"
    return "sql"
```

- [ ] **Step 3: Проверь что _READ_KEYWORDS константа всё ещё используется**

```bash
grep -n "_READ_KEYWORDS" agent/prephase.py
```

Если `_READ_KEYWORDS` используется только в `_determine_task_type` и больше нигде — удали её определение (строка 18: `_READ_KEYWORDS = ...`). Если используется в других местах — оставь.

- [ ] **Step 4: Run tests**

```bash
uv run python -m pytest tests/ -v -x -q 2>&1 | head -40
```

Expected: все тесты проходят (или те же что и раньше не проходили — не вводим новых поломок).

- [ ] **Step 5: Commit**

```bash
git add agent/prephase.py
git commit -m "refactor(prephase): task_type returns sql|compute|default, drop legacy 'read' type"
```

---

## Task 5: agent/prompt.py — убери _TASK_BLOCKS, загружай из yaml

**Files:**
- Modify: `agent/prompt.py`

- [ ] **Step 1: Прочитай текущий prompt.py**

```python
# Текущее содержимое уже известно — _TASK_BLOCKS dict с legacy типами,
# build_system_prompt() собирает строку из блоков.
```

- [ ] **Step 2: Перепиши prompt.py**

```python
"""Prompt loading utilities."""
from __future__ import annotations

from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent.parent / "data" / "prompts"
_CONFIG_DIR = Path(__file__).parent.parent / "data" / "config"

_BLOCKS: dict[str, str] = {}
_warned_missing_blocks: set[str] = set()


def _load_all() -> None:
    if not _PROMPTS_DIR.exists():
        return
    for f in _PROMPTS_DIR.glob("*.md"):
        _BLOCKS[f.stem] = f.read_text(encoding="utf-8")


_load_all()


def load_prompt(name: str) -> str:
    """Return prompt block by file stem name. Returns '' if not found."""
    return _BLOCKS.get(name, "")


def load_task_blocks(task_type: str) -> list[str]:
    """Return list of prompt block stems for given task_type from data/config/task_blocks.yaml."""
    cfg_file = _CONFIG_DIR / "task_blocks.yaml"
    if not cfg_file.exists():
        return []
    try:
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        return list(cfg.get(task_type, cfg.get("default", [])))
    except Exception:
        return []
```

Убери `_TASK_BLOCKS` dict, `build_system_prompt()`, `system_prompt`, `SYSTEM_PROMPT` (backward-compat aliases).

- [ ] **Step 3: Проверь что build_system_prompt не импортируется нигде**

```bash
grep -rn "build_system_prompt\|from .prompt import.*system_prompt\|SYSTEM_PROMPT" agent/ tests/ scripts/
```

Expected: пустой вывод. Если что нашлось — найди и убери импорты.

- [ ] **Step 4: Проверь что load_prompt всё ещё работает**

```bash
uv run python -c "from agent.prompt import load_prompt; r = load_prompt('sdd'); print('ok, len=', len(r))"
```

Expected: `ok, len=<число > 0>`

- [ ] **Step 5: Run tests**

```bash
uv run python -m pytest tests/ -v -x -q 2>&1 | head -40
```

- [ ] **Step 6: Commit**

```bash
git add agent/prompt.py
git commit -m "refactor(prompt): replace _TASK_BLOCKS dict with yaml loader, remove build_system_prompt"
```

---

## Task 6: Создай agent/prompt_assembler.py

**Files:**
- Create: `agent/prompt_assembler.py`
- Test: `tests/test_prompt_assembler.py`

Ассемблер делает 1 LLM-вызов, получает `unified_context: str`. Вызывается в начале каждого цикла с актуальным `learn_ctx`.

- [ ] **Step 1: Напиши failing test**

Создай `tests/test_prompt_assembler.py`:

```python
import pytest
from unittest.mock import patch
from agent.prompt_assembler import assemble_prompt, AssembledPrompt
from agent.prephase import PrephaseResult


def _make_pre():
    return PrephaseResult(
        agents_md_content="## vault\nsome rules",
        agents_md_index={"vault": ["some rules"]},
        schema_digest={"tables": {"products": {"columns": [{"name": "sku", "type": "TEXT"}], "fk": [], "role": "products"}}},
        db_schema="CREATE TABLE products (sku TEXT)",
        task_type="sql",
    )


def test_assemble_returns_assembled_prompt(tmp_path):
    pre = _make_pre()
    fake_unified = "# LEARNED\n\n# RULES\nrule1\n\n# SECURITY\nsec1\n\n# BASE\nbase"

    with patch("agent.prompt_assembler.call_llm_raw", return_value=fake_unified), \
         patch("agent.prompt_assembler._RULES_DIR", tmp_path / "rules"), \
         patch("agent.prompt_assembler._SECURITY_DIR", tmp_path / "security"), \
         patch("agent.prompt_assembler._LEARNED_DIR", tmp_path / "learned"):
        (tmp_path / "rules").mkdir()
        (tmp_path / "security").mkdir()
        (tmp_path / "learned").mkdir()
        result = assemble_prompt(
            task_text="find products with sku ABC",
            task_type="sql",
            prephase_result=pre,
            learn_ctx=["Never use ILIKE"],
            model="test-model",
            cfg={},
        )

    assert isinstance(result, AssembledPrompt)
    assert result.unified_context == fake_unified


def test_assemble_loads_learned_ctx_from_file(tmp_path):
    pre = _make_pre()
    learned_dir = tmp_path / "learned"
    learned_dir.mkdir()
    import yaml
    (learned_dir / "t99.yaml").write_text(
        yaml.dump({"task_id": "t99", "learn_ctx": ["persisted rule"]}),
        encoding="utf-8",
    )

    calls = []
    def fake_llm(system, user_msg, model, cfg, **kw):
        calls.append(user_msg)
        return "# LEARNED\npersisted rule\n\n# RULES\n\n# SECURITY\n\n# BASE\n"

    with patch("agent.prompt_assembler.call_llm_raw", side_effect=fake_llm), \
         patch("agent.prompt_assembler._RULES_DIR", tmp_path / "rules"), \
         patch("agent.prompt_assembler._SECURITY_DIR", tmp_path / "security"), \
         patch("agent.prompt_assembler._LEARNED_DIR", learned_dir):
        (tmp_path / "rules").mkdir()
        (tmp_path / "security").mkdir()
        result = assemble_prompt(
            task_text="test task",
            task_type="sql",
            prephase_result=pre,
            learn_ctx=[],
            model="test-model",
            cfg={},
            task_id="t99",
        )

    assert "persisted rule" in calls[0]
```

- [ ] **Step 2: Запусти — убедись что падает**

```bash
uv run python -m pytest tests/test_prompt_assembler.py -v 2>&1 | tail -10
```

Expected: `ImportError` или `ModuleNotFoundError` (модуль не существует).

- [ ] **Step 3: Создай agent/prompt_assembler.py**

```python
"""LLM-assembler: builds unified_context from all prompt sources per pipeline cycle."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .llm import call_llm_raw, _resolve_model_for_phase
from .prompt import load_prompt, load_task_blocks
from .prephase import PrephaseResult, _format_schema_digest
from .rules_loader import RulesLoader
from .sql_security import load_security_gates

_RULES_DIR = Path(__file__).parent.parent / "data" / "rules"
_SECURITY_DIR = Path(__file__).parent.parent / "data" / "security"
_LEARNED_DIR = Path(__file__).parent.parent / "data" / "learned"


@dataclass
class AssembledPrompt:
    unified_context: str


def load_learned_ctx(task_id: str) -> list[str]:
    """Load persisted learn_ctx from prior failed run, or [] if none."""
    if not task_id:
        return []
    path = _LEARNED_DIR / f"{task_id}.yaml"
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return list(data.get("learn_ctx", []))
    except Exception:
        return []


def save_learned_ctx(task_id: str, learn_ctx: list[str]) -> None:
    """Persist learn_ctx to data/learned/{task_id}.yaml on pipeline failure."""
    if not task_id or not learn_ctx:
        return
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    path = _LEARNED_DIR / f"{task_id}.yaml"
    path.write_text(
        yaml.dump({"task_id": task_id, "learn_ctx": learn_ctx}, allow_unicode=True),
        encoding="utf-8",
    )


def clear_learned_ctx(task_id: str) -> None:
    """Delete data/learned/{task_id}.yaml on pipeline success."""
    if not task_id:
        return
    path = _LEARNED_DIR / f"{task_id}.yaml"
    path.unlink(missing_ok=True)


def _build_sources(
    task_text: str,
    task_type: str,
    prephase_result: PrephaseResult,
    learn_ctx: list[str],
) -> str:
    parts: list[str] = []

    parts.append(f"TASK_TEXT: {task_text}")
    parts.append(f"TASK_TYPE: {task_type}")

    if learn_ctx:
        parts.append("## LEARNED (highest priority)\n" + "\n".join(f"- {r}" for r in learn_ctx))

    rules_loader = RulesLoader(_RULES_DIR)
    rules_md = rules_loader.get_rules_markdown(phase="sql_plan", verified_only=True)
    if rules_md:
        parts.append(f"## RULES\n{rules_md}")

    security_gates = load_security_gates()
    if security_gates:
        gate_lines = "\n".join(f"- [{g['id']}] {g.get('message', '')}" for g in security_gates)
        parts.append(f"## SECURITY\n{gate_lines}")

    block_names = load_task_blocks(task_type)
    block_texts = [load_prompt(name) for name in block_names if load_prompt(name)]
    if block_texts:
        parts.append("## PROMPT_BLOCKS\n" + "\n\n".join(block_texts))

    pre = prephase_result
    if pre.agents_md_content:
        parts.append(f"## VAULT\n{pre.agents_md_content}")

    if pre.schema_digest:
        parts.append(f"## SCHEMA_DIGEST\n{_format_schema_digest(pre.schema_digest)}")
    if pre.db_schema:
        parts.append(f"## DB_SCHEMA\n{pre.db_schema}")

    meta: list[str] = []
    if pre.current_date:
        meta.append(f"date: {pre.current_date}")
    if pre.agent_id:
        meta.append(f"customer_id: {pre.agent_id}")
    if meta:
        parts.append("## AGENT_CONTEXT\n" + "\n".join(meta))

    return "\n\n".join(parts)


def assemble_prompt(
    task_text: str,
    task_type: str,
    prephase_result: PrephaseResult,
    learn_ctx: list[str],
    model: str,
    cfg: dict,
    task_id: str = "",
) -> AssembledPrompt:
    """Call LLM assembler to produce unified_context from all sources."""
    persisted = load_learned_ctx(task_id)
    merged_ctx = list(dict.fromkeys(persisted + learn_ctx))

    assembler_guide = load_prompt("assembler")
    sources = _build_sources(task_text, task_type, prephase_result, merged_ctx)
    assembler_model = _resolve_model_for_phase("assembler", model)

    raw = call_llm_raw(
        assembler_guide or "Assemble unified context from sources.",
        sources,
        assembler_model,
        cfg,
        max_tokens=4096,
        plain_text=True,
    )

    unified = raw or sources
    return AssembledPrompt(unified_context=unified)
```

- [ ] **Step 4: Запусти тесты**

```bash
uv run python -m pytest tests/test_prompt_assembler.py -v
```

Expected: оба теста `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add agent/prompt_assembler.py tests/test_prompt_assembler.py
git commit -m "feat(assembler): add prompt_assembler.py with LLM-based unified_context assembly"
```

---

## Task 7: agent/pipeline.py — major rewrite

**Files:**
- Modify: `agent/pipeline.py`
- Test: `tests/test_pipeline_tdd.py`, `tests/test_pipeline.py` (обнови патчи)

Это самый большой таск. Разбит на под-шаги.

### 7.1 Замени system builders на assemble_prompt

- [ ] **Step 1: Добавь импорты в pipeline.py**

В секцию импортов добавь:

```python
from .prompt_assembler import assemble_prompt, save_learned_ctx, clear_learned_ctx
```

Убери импорт `from .prompt import load_prompt` — он больше не используется напрямую в pipeline.py (используется внутри prompt_assembler.py).

- [ ] **Step 2: Удали _build_sdd_system, _build_learn_system, _build_answer_system**

Удали три функции целиком (строки 173–301 в текущем pipeline.py):
- `_build_sdd_system()`
- `_build_learn_system()`
- `_build_answer_system()`

Также удали вспомогательную `_gates_summary()` — больше не нужна в pipeline.py (security gates идут через assembler).

- [ ] **Step 3: Verify imports компилируются**

```bash
uv run python -c "import agent.pipeline; print('ok')"
```

Expected: `ok` (или предупреждения — не ошибки).

### 7.2 Перепиши run_pipeline — начало цикла

- [ ] **Step 4: В run_pipeline замени статическую сборку system на assemble_prompt в цикле**

Найди в `run_pipeline` блок (строки ~433-443):

```python
static_learn = _build_learn_system(...)
static_answer = _build_answer_system(...)
static_sdd = _build_sdd_system(...)
```

Удали эти три строки. Переменные `static_learn`, `static_answer`, `static_sdd` больше не используются.

В начале `for cycle in range(_MAX_CYCLES):` добавь первым действием:

```python
for cycle in range(_MAX_CYCLES):
    cycles_used = cycle + 1
    print(f"\n{CLI_BLUE}[pipeline] cycle={cycle + 1}/{_MAX_CYCLES}{CLI_CLR}")

    # ── ASSEMBLE PROMPT ───────────────────────────────────────────────────
    assembled = assemble_prompt(
        task_text=task_text,
        task_type=task_type,
        prephase_result=pre,
        learn_ctx=learn_ctx,
        model=model,
        cfg=cfg,
        task_id=task_id,
    )
    unified_context = assembled.unified_context
```

### 7.3 Замени system в _call_llm_phase вызовах + исправь failure handling

> **Ключевое архитектурное правило (по спеке):**
> Все фазы (SDD, TDD, EXECUTE, TESTING, VERIFY_ANSWER) при failure → **LEARN → next cycle**.
> "LEARN (при любом failure)" — без исключений по типу фазы.

- [ ] **Step 5: Замени static_sdd → unified_ctx + sdd guide в SDD фазе**

Найди SDD вызов (~строка 460):

```python
sdd_out, sgr_entry, tok = _call_llm_phase(
    static_sdd, user_msg, sdd_model, cfg, SddOutput,
    phase="sdd", cycle=cycle + 1,
)
```

Замени на:

```python
sdd_guide = load_prompt("sdd") or "# PHASE: sdd"
sdd_system: list[dict] = [
    {"type": "text", "text": unified_context},
    {"type": "text", "text": sdd_guide, "cache_control": {"type": "ephemeral"}},
]
sdd_out, sgr_entry, tok = _call_llm_phase(
    sdd_system, user_msg, sdd_model, cfg, SddOutput,
    phase="sdd", cycle=cycle + 1,
)
```

Добавь `from .prompt import load_prompt` обратно в импорты (нужен для phase guide загрузки).

- [ ] **Step 5a: SDD failure → LEARN (убедись что error_type правильный)**

Найди блок обработки SDD failure (~строка 469). Убедись что передаётся `error_type="llm_fail"` (чтобы LEARN знал что это parse-fail, а не семантика):

```python
if not sdd_out:
    print(f"{CLI_RED}[pipeline] SDD LLM parse failed — running LEARN{CLI_CLR}")
    last_error = "SDD phase: failed to parse LLM output"
    _run_learn(unified_context, model, cfg, task_text, [], last_error,
               sgr_trace, learn_ctx, pre.agents_md_index,
               error_type="llm_fail", cycle=cycle + 1,
               prior_learn_hashes=prior_learn_hashes)
    continue
```

Текущий `_run_learn` уже пропускает добавление правила при `error_type="llm_fail"` (строка `if learn_out and error_type != "llm_fail"`). Цикл просто перезапустится с тем же промтом — что и является поведением спеки.

- [ ] **Step 6: Замени system в _run_test_gen → TDD фазе**

Найди `_run_test_gen()` функцию. Перепиши чтобы принимала `unified_context`:

```python
def _run_test_gen(
    model: str,
    cfg: dict,
    task_text: str,
    sdd_spec: str,
    task_type: str,
    unified_context: str = "",
) -> "TestOutput | None":
    tdd_model = _resolve_model_for_phase("tdd", model)
    tdd_guide = load_prompt("tdd") or "# PHASE: tdd\nGenerate sql_tests and answer_tests as JSON."
    system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": tdd_guide, "cache_control": {"type": "ephemeral"}},
    ]
    user_msg = f"TASK: {task_text}\n\nTASK_TYPE: {task_type}\n\nSDD_SPEC:\n{sdd_spec}"
    out, _, _ = _call_llm_phase(
        system, user_msg, tdd_model, cfg, TestOutput,
        phase="tdd", cycle=0,
    )
    if out:
        if t := get_trace():
            t.log_test_gen(out.sql_tests, out.answer_tests)
    return out
```

В вызове `_run_test_gen` в `run_pipeline` передай `unified_context=unified_context`.

**TDD failure → LEARN (по спеке):** Найди блок `if test_gen_out is None:` в `run_pipeline`. Замени `break` на LEARN + continue:

```python
if test_gen_out is None:
    print(f"{CLI_RED}[pipeline] TDD LLM parse failed — running LEARN{CLI_CLR}")
    last_error = "TDD phase: failed to parse test output"
    _run_learn(unified_context, model, cfg, task_text, [], last_error,
               sgr_trace, learn_ctx, pre.agents_md_index,
               error_type="llm_fail", cycle=cycle + 1,
               prior_learn_hashes=prior_learn_hashes)
    continue
```

- [ ] **Step 7: Замени static_learn → unified_ctx + learn guide в _run_learn**

Перепиши `_run_learn()` чтобы принимала `unified_context: str` вместо `static_learn: str | list[dict]`:

```python
def _run_learn(
    unified_context: str,      # ← заменяет static_learn
    model: str,
    cfg: dict,
    task_text: str,
    queries: list[str],
    error: str,
    sgr_trace: list[dict],
    learn_ctx: list[str],
    agents_md_index: dict,
    error_type: str = "semantic",
    cycle: int = 0,
    prior_learn_hashes: "set[str] | None" = None,
) -> None:
    learn_model = _resolve_model_for_phase("learn", model)
    learn_guide = load_prompt("learn") or "# PHASE: learn"
    learn_system: list[dict] = [
        {"type": "text", "text": unified_context},
        {"type": "text", "text": learn_guide, "cache_control": {"type": "ephemeral"}},
    ]
    learn_user = _build_learn_user_msg(task_text, queries, error, error_type)
    learn_out, sgr_learn, _ = _call_llm_phase(
        learn_system, learn_user, learn_model, cfg, LearnOutput,
        max_tokens=2048, phase="learn", cycle=cycle,
    )
    # остальное тело без изменений — только убери ссылку на agents_md_index
    # (vault rules уже в unified_context, anchor логика остаётся):
    sgr_learn["error_type"] = error_type
    sgr_trace.append(sgr_learn)
    if learn_out and error_type != "llm_fail":
        if prior_learn_hashes is not None:
            learn_hash = make_json_hash(learn_out.model_dump())
            learn_gate_err = check_learn_output(
                learn_out.rule_content, learn_hash, prior_learn_hashes, _get_security_gates()
            )
            if learn_gate_err:
                print(f"{CLI_YELLOW}[pipeline] LEARN blocked: {learn_gate_err}{CLI_CLR}")
                return
            prior_learn_hashes.add(learn_hash)
        anchor = learn_out.agents_md_anchor
        if anchor:
            anchor_section = anchor.split(">")[0].strip()
            if anchor_section in agents_md_index:
                anchor_lines = agents_md_index[anchor_section]
                vault_rule = f"[{anchor_section}]\n" + "\n".join(anchor_lines)
                learn_ctx.append(vault_rule)
                print(f"{CLI_BLUE}[pipeline] LEARN: anchor={anchor!r}, vault rule added{CLI_CLR}")
                return
        learn_ctx.append(learn_out.rule_content)
        print(f"{CLI_BLUE}[pipeline] LEARN: rule added (total={len(learn_ctx)}){CLI_CLR}")
```

Все вызовы `_run_learn(static_learn, ...)` замени на `_run_learn(unified_context, ...)`.

- [ ] **Step 8: Замени static_answer → unified_ctx + answer guide в ANSWER фазе**

Найди ANSWER вызов (~строка 739):

```python
answer_out, sgr_answer, tok = _call_llm_phase(
    static_answer, answer_user, executor_model, cfg, AnswerOutput,
    phase="answer", cycle=cycle + 1,
)
```

Замени на:

```python
answer_guide = load_prompt("answer") or "# PHASE: answer"
answer_system: list[dict] = [
    {"type": "text", "text": unified_context},
    {"type": "text", "text": answer_guide, "cache_control": {"type": "ephemeral"}},
]
answer_out, sgr_answer, tok = _call_llm_phase(
    answer_system, answer_user, executor_model, cfg, AnswerOutput,
    phase="answer", cycle=cycle + 1,
)
```

### 7.4 Убери SECURITY CHECK как отдельный шаг

- [ ] **Step 9: Убери check_sql_queries и check_where_literals из pipeline loop**

Найди блок `# ── SECURITY CHECK ──` (~строки 543-563). Удали вызовы:
- `check_sql_queries(sql_queries, security_gates)` → удалить + `continue`
- `check_where_literals(...)` → удалить + `continue`

**Оставь** `check_retry_loop(sql_queries, prior_query_sets, security_gates)` — это anti-loop guard, не content gate.

**Оставь** AGENTS.MD refs check — он проверяет семантику, не security.

После удаления security check блок должен выглядеть:

```python
# ── RETRY LOOP GUARD ─────────────────────────────────────────────────
retry_err = check_retry_loop(sql_queries, prior_query_sets, security_gates)
if retry_err:
    print(f"{CLI_RED}[pipeline] SECURITY hard-stop: {retry_err}{CLI_CLR}")
    last_error = retry_err
    break
prior_query_sets.append(frozenset(sql_queries))
```

- [ ] **Step 10: Убери неиспользуемые импорты из sql_security**

```bash
grep -n "check_sql_queries\|check_where_literals\|check_path_access\|check_grounding_refs\|check_learn_output\|check_retry_loop\|make_json_hash\|load_security_gates" agent/pipeline.py
```

Убери импорты тех функций, которые больше не вызываются в pipeline.py. `check_path_access`, `check_grounding_refs`, `check_learn_output`, `check_retry_loop`, `make_json_hash`, `load_security_gates` — проверь каждую.

Note: `load_security_gates` теперь используется только в `_get_security_gates()`, которую вызывает `_run_learn`. `check_path_access` используется в exec шагах. Оставь нужные.

### 7.5 Переименуй фазы в trace/print

- [ ] **Step 11: Переименуй TEST_GEN → TDD в выводах**

```bash
grep -n "TEST_GEN\|test_gen\|VERIFY\b\|VERIFY_ANSWER" agent/pipeline.py
```

Замени:
- `phase="TEST_GEN"` → `phase="tdd"`
- `"[pipeline] TEST_GEN` → `"[pipeline] TDD`
- `phase="VERIFY"` → `phase="testing"` (если есть отдельная VERIFY фаза)

`VERIFY_ANSWER` оставь как есть — это отдельная семантика.

### 7.6 eval_log — только при success

- [ ] **Step 12: Найди _append_eval_log вызовы**

```bash
grep -n "_append_eval_log" agent/pipeline.py
```

Текущее состояние: `_append_eval_log` вызывается и при success (outcome=ok) и при special outcomes (DENIED_SECURITY, UNSUPPORTED). При failure — не вызывается.

По спеке: `eval_log` пишется только при `outcome=ok`. Special outcomes (DENIED_SECURITY, UNSUPPORTED) — это тоже success cases (задача обработана), поэтому их логировать можно. Основное изменение: убери запись на failure path.

Проверь что в коде нет `_append_eval_log` вызова в секции failure (после `if not success:`). Если есть — удали.

- [ ] **Step 13: Обнови _append_eval_log — добавь поле learn_ctx**

Найди `_append_eval_log` (~сигнатура `def _append_eval_log(task_id, task_text, ..., outcome, ...)`).
Добавь параметр `learn_ctx: list[str]` и запись в entry:

```python
def _append_eval_log(
    task_id: str,
    task_text: str,
    task_type: str,
    outcome: str,
    cycles: int,
    sgr_trace: list[dict],
    learn_ctx: list[str],          # ← добавить
    prephase_result: "PrephaseResult | None" = None,
) -> None:
    entry = {
        "task_id": task_id,
        "task_text": task_text,
        "task_type": task_type,
        "outcome": "ok" if outcome == "OUTCOME_OK" else outcome.lower().replace("outcome_", ""),
        "cycles": cycles,
        "trace": sgr_trace,
        "learn_ctx": learn_ctx,    # ← добавить
        "prephase": {
            "agents_md": prephase_result.agents_md_content[:500] if prephase_result else "",
            "schema_digest": prephase_result.schema_digest if prephase_result else {},
        },
        "evaluator": None,
    }
    ...
```

Обнови все вызовы `_append_eval_log(...)` в `run_pipeline` — передай `learn_ctx=learn_ctx`.

```bash
grep -n "_append_eval_log" agent/pipeline.py
```

### 7.7 Persist learn_ctx при failure

- [ ] **Step 14: При FAILURE сохрани learn_ctx**

В блоке `if not success:` (после цикла) добавь:

```python
if not success:
    print(f"{CLI_RED}[pipeline] All {_MAX_CYCLES} cycles exhausted — clarification{CLI_CLR}")
    if task_id and learn_ctx:
        save_learned_ctx(task_id, learn_ctx)
        print(f"{CLI_BLUE}[pipeline] learn_ctx persisted to data/learned/{task_id}.yaml{CLI_CLR}")
    try:
        vm.answer(AnswerRequest(...))
    except Exception as e:
        ...
```

- [ ] **Step 15: При SUCCESS удали persisted learn_ctx**

В блоке SUCCESS (после `vm.answer()` и `_append_eval_log(...)`):

```python
# ── SUCCESS ───────────────────────────────────────────────────────────
...
_append_eval_log(...)
clear_learned_ctx(task_id)
success = True
break
```

### 7.8 Evaluator — только при success

- [ ] **Step 16: Переключи evaluator thread с failure на success**

Найди (~строки 841-864):

```python
# ── EVALUATOR: only on failure ────────────────────────────────────────────
eval_thread: threading.Thread | None = None
eval_model = _resolve_model_for_phase("evaluator", model)
if not success and _EVAL_ENABLED and eval_model:
```

Измени условие:

```python
# ── EVALUATOR: only on success ────────────────────────────────────────────
eval_thread: threading.Thread | None = None
eval_model = _resolve_model_for_phase("evaluator", model)
if success and _EVAL_ENABLED and eval_model:
```

- [ ] **Step 17: Run all tests**

```bash
uv run python -m pytest tests/ -v -x 2>&1 | tail -30
```

Expected: все тесты проходят, или понятные failure с конкретной причиной (не import errors).

- [ ] **Step 18: Fix тесты которые патчат static_learn/static_sdd/static_answer**

```bash
grep -rn "static_learn\|static_sdd\|static_answer\|MODEL_TEST_GEN\|TDD_ENABLED\|test_gen_model\|_build_sdd_system\|_build_learn_system\|_build_answer_system" tests/
```

Для каждого теста:
- Если патчит `pipeline._build_sdd_system` → заменить на патч `prompt_assembler.assemble_prompt` с возвратом `AssembledPrompt(unified_context="mocked")`
- Если проверяет `MODEL_TEST_GEN` env var → убери (переменная удалена)
- Если патчит `pipeline.call_llm_raw` sequence → обнови количество вызовов (добавился вызов assembler)

Пример обновления `test_pipeline_tdd.py`:

```python
from agent.prompt_assembler import AssembledPrompt

# В каждом тесте добавь патч на assemble_prompt:
with patch("agent.pipeline.assemble_prompt",
           return_value=AssembledPrompt(unified_context="mocked-context")), \
     patch("agent.pipeline.call_llm_raw", side_effect=fake_llm), \
     ...
```

- [ ] **Step 19: Run tests снова**

```bash
uv run python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: все зелёные.

- [ ] **Step 20: Commit**

```bash
git add agent/pipeline.py agent/prompt_assembler.py tests/
git commit -m "refactor(pipeline): integrate assemble_prompt, remove static builders, success-only eval+evallog"
```

---

## Task 8: agent/evaluator.py — убери _append_log, success-only

**Files:**
- Modify: `agent/evaluator.py`

Сейчас `evaluator._append_log` пишет отдельную запись в eval_log. В новом дизайне eval_log пишет только `pipeline._append_eval_log` при success. Evaluator возвращает результат → pipeline thread обновляет существующую запись.

- [ ] **Step 1: Найди _append_log в evaluator.py**

```python
def _append_log(eval_input: EvalInput, result: PipelineEvalOutput) -> None:
    entry = {...}
    ...
    with open(_EVAL_LOG, "a", ...) as f:
        f.write(json.dumps(entry, ...) + "\n")
```

- [ ] **Step 2: Удали _append_log из evaluator.py**

Удали всю функцию `_append_log` (строки 141-160).

- [ ] **Step 3: Убери вызов _append_log из _run()**

В функции `_run()` строка:

```python
_append_log(eval_input, result)
return result
```

Замени на:

```python
return result
```

- [ ] **Step 4: Убери импорт _EVAL_LOG если не используется**

```bash
grep -n "_EVAL_LOG" agent/evaluator.py
```

Если `_EVAL_LOG` больше нигде в evaluator.py не используется — удали строку `_EVAL_LOG = Path(...)`.

- [ ] **Step 5: Verify**

```bash
uv run python -c "from agent.evaluator import run_evaluator, EvalInput; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Run tests**

```bash
uv run python -m pytest tests/ -v -x -q 2>&1 | tail -20
```

- [ ] **Step 7: Commit**

```bash
git add agent/evaluator.py
git commit -m "refactor(evaluator): remove _append_log, evaluator only returns result to pipeline"
```

---

## Task 9: scripts/propose_optimizations.py — auto-apply

**Files:**
- Modify: `scripts/propose_optimizations.py`

По спеке: оптимизации применяются автоматически (verified:true, пишем прямо в data/). Убираем validation gate (validate_recommendation).

- [ ] **Step 1: Обнови _write_rule — verified:true**

Найди `_write_rule()` функцию. Измени `"verified": False` → `"verified": True`:

```python
def _write_rule(num: int, content: str, entry: dict, raw_rec: str) -> Path:
    rule_id = f"sql-{num:03d}"
    dest = _RULES_DIR / f"{rule_id}.yaml"
    with open(dest, "w", encoding="utf-8") as f:
        yaml.dump({
            "id": rule_id, "phase": "sql_plan", "verified": True, "source": "eval",
            "content": content, "created": date.today().isoformat(),
            "raw_recommendation": raw_rec,
        }, f, allow_unicode=True, default_flow_style=False)
    print(f"[propose] created {dest.name}")
    return dest
```

- [ ] **Step 2: Обнови _write_security — verified:true**

Найди `_write_security()`. Измени `"verified": False` → `"verified": True`. Добавь print.

```python
def _write_security(num: int, gate_spec: dict, entry: dict, raw_rec: str) -> Path:
    gate_id = f"sec-{num:03d}"
    dest = _SECURITY_DIR / f"{gate_id}.yaml"
    record: dict = {
        "id": gate_id, "action": "block", "message": gate_spec["message"],
        "verified": True, "source": "eval", "created": date.today().isoformat(),
        "task_text": entry["task_text"][:120],
        "raw_recommendation": raw_rec,
    }
    if gate_spec.get("pattern"):
        record["pattern"] = gate_spec["pattern"]
    if gate_spec.get("check"):
        record["check"] = gate_spec["check"]
    with open(dest, "w", encoding="utf-8") as f:
        yaml.dump(record, f, allow_unicode=True, default_flow_style=False)
    print(f"[propose] created {dest.name}")
    return dest
```

- [ ] **Step 3: Обнови _write_prompt — пиши в data/prompts/ напрямую**

Текущая логика пишет в `data/prompts/optimized/`. Новая — в `data/prompts/<target_file>` (append section).

```python
def _write_prompt(patch_result: dict, entry: dict, raw_rec: str) -> Path:
    target = patch_result["target_file"]
    dest = _PROMPTS_DIR / target
    content = patch_result["content"]
    action = "updated"
    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        if content.strip() in existing:
            print(f"[propose] skipped {target} (already present)")
            return dest
        dest.write_text(existing.rstrip() + "\n\n" + content + "\n", encoding="utf-8")
    else:
        dest.write_text(content + "\n", encoding="utf-8")
        action = "created"
    print(f"[propose] {action} {target}")
    return dest
```

- [ ] **Step 4: Убери validate_recommendation из main()**

В `main()` найди все вызовы `validate_recommendation(...)`. Замени каждый блок:

```python
# Старый код:
original, validation = validate_recommendation(task_id, ...)
if original is None:
    ...write anyway...
elif validation is None:
    ...skip...
elif validation >= original:
    ...write...
else:
    ...reject...

# Новый код (везде для rule, security, prompt):
dest = _write_rule(num, content, entry, raw_rec)  # или _write_security / _write_prompt
new_processed.update(all_hashes)
written += 1
rules_md = knowledge_loader.existing_rules_text()  # reload после записи
```

Применить для всех трёх каналов (rule_clusters, security_clusters, prompt_clusters).

- [ ] **Step 5: Обнови _flatten_recs — читать только outcome=ok**

По спеке eval_log содержит только success записи. Но для надёжности оставь фильтр:

```python
def _flatten_recs(entries: list[dict], channel: str, processed: set[str]) -> list[dict]:
    result = []
    for entry in entries:
        if entry.get("outcome") != "ok":
            continue
        if entry.get(channel, []):
            result.append(entry)
    return result
```

- [ ] **Step 6: Run тесты для propose_optimizations**

```bash
uv run pytest tests/test_propose_optimizations.py -v 2>&1 | tail -30
```

Исправь падающие тесты — они могут проверять `validated: false` или вызовы `validate_recommendation`.

- [ ] **Step 7: Commit**

```bash
git add scripts/propose_optimizations.py tests/test_propose_optimizations.py
git commit -m "refactor(propose): auto-apply optimizations (verified:true, no validation gate)"
```

---

## Task 10: .env.example — обнови конфиг

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Удали секцию TDD Pipeline целиком**

Текущий блок в `.env.example` (строки 22-24):
```
# ─── TDD Pipeline ───────────────────────────────────────────────────────────
TDD_ENABLED=0                        # 1 = генерировать тесты и валидировать ответ перед vm.answer()
MODEL_TEST_GEN=                      # модель для TEST_GEN; если пусто — используется MODEL
```

Удали все три строки (заголовок + обе переменные).

- [ ] **Step 2: Обнови секцию Phase Models — добавь MODEL_ASSEMBLER**

Текущий вид секции (строки 26-29):
```
# ─── Phase Models ────────────────────────────────────────────────────────────
MODEL_SDD=                           # SDD phase model (defaults to MODEL)
MODEL_EXECUTOR=                      # ANSWER phase model (defaults to MODEL)
MODEL_LEARN=                         # LEARN phase model (defaults to MODEL)
```

Целевой вид:
```
# ─── Phase Models ────────────────────────────────────────────────────────────
MODEL_SDD=                           # SDD phase model (defaults to MODEL)
MODEL_EXECUTOR=                      # ANSWER phase model (defaults to MODEL)
MODEL_LEARN=                         # LEARN phase model (defaults to MODEL)
MODEL_ASSEMBLER=                     # unified_context assembler model (defaults to MODEL)
```

- [ ] **Step 3: Verify**

```bash
grep -n "TDD_ENABLED\|MODEL_TEST_GEN" .env.example
```

Expected: пустой вывод.

```bash
grep -n "MODEL_ASSEMBLER" .env.example
```

Expected: одна строка с `MODEL_ASSEMBLER=`.

- [ ] **Step 4: Проверь финальный вид изменённых секций**

```bash
grep -A4 "Phase Models" .env.example
```

Expected:
```
# ─── Phase Models ────────────────────────────────────────────────────────────
MODEL_SDD=                           # SDD phase model (defaults to MODEL)
MODEL_EXECUTOR=                      # ANSWER phase model (defaults to MODEL)
MODEL_LEARN=                         # LEARN phase model (defaults to MODEL)
MODEL_ASSEMBLER=                     # unified_context assembler model (defaults to MODEL)
```

- [ ] **Step 5: Commit**

```bash
git add .env.example
git commit -m "chore(env): remove TDD_ENABLED/MODEL_TEST_GEN, add MODEL_ASSEMBLER"
```

---

## Task 11: Final test run и cleanup

- [ ] **Step 1: Полный прогон тестов**

```bash
uv run python -m pytest tests/ -v 2>&1 | tee /tmp/test_results.txt
tail -20 /tmp/test_results.txt
```

Expected: все тесты зелёные.

- [ ] **Step 2: Проверь что нет устаревших импортов**

```bash
grep -rn "MODEL_TEST_GEN\|TDD_ENABLED\|_build_sdd_system\|_build_learn_system\|_build_answer_system\|static_sdd\|static_learn\|static_answer\|task_type.*lookup\|task_type.*temporal\|task_type.*capture\|task_type.*crm\|task_type.*distill\|task_type.*preject" agent/ scripts/ tests/
```

Expected: пустой вывод (или только в комментариях/строках документации).

- [ ] **Step 3: Проверь что data/prompts/ не содержит core/lookup/catalogue**

```bash
ls data/prompts/
```

Expected: `assembler.md  answer.md  learn.md  pipeline_evaluator.md  sdd.md  tdd.md` (возможно + `domain.md` если создавался).

- [ ] **Step 4: Smoke test — import pipeline без ошибок**

```bash
uv run python -c "
from agent.pipeline import run_pipeline
from agent.prompt_assembler import assemble_prompt, load_learned_ctx, save_learned_ctx, clear_learned_ctx
from agent.prompt import load_prompt, load_task_blocks
print('all imports ok')
"
```

Expected: `all imports ok`

- [ ] **Step 5: Final commit**

```bash
git add -A
git status  # проверь что нет случайных файлов
git commit -m "feat: prompt architecture redesign — unified assembler, TDD mandatory, success-only eval_log"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Covered in |
|---|---|
| Все промты из data/prompts/*.md, ноль хардкода | Task 7 (убраны _build_*_system) |
| Unified prompt собирается LLM task-aware | Task 6 (prompt_assembler.py) |
| LEARN → in-session learn_ctx | Task 7.3 (_run_learn signature) |
| learn_ctx агрегируется в eval_log при success | Task 7.6 + 7.7 |
| eval_log только для успешных задач | Task 7.6 |
| TDD обязателен | Task 7.3 (TDD всегда вызывается, нет if TDD_ENABLED) |
| propose_optimizations автоматически перезаписывает | Task 9 |
| core/lookup/catalogue legacy удалены | Task 1 |
| test_gen.md → tdd.md | Task 1.5 |
| data/config/task_blocks.yaml заменяет _TASK_BLOCKS | Task 2 + Task 5 |
| data/learned/{task_id}.yaml persist/load/clear | Task 6 (save/load/clear_learned_ctx) + Task 7.7 |
| MODEL_ASSEMBLER env var | Task 3 |
| TDD_ENABLED и MODEL_TEST_GEN удалены | Task 3 + Task 10 |
| SDD failure → LEARN (error_type=llm_fail) | Task 7.3 Step 5a |
| TDD failure → LEARN (error_type=llm_fail) | Task 7.3 Step 6 |
| EXECUTE/TESTING/VERIFY_ANSWER failure → LEARN | Task 7.3 Step 7, Task 7 общий |
| learn_ctx поле в eval_log entry | Task 7.6 Step 13 |
| SECURITY CHECK убран как отдельный шаг | Task 7.4 |
| check_retry_loop оставлен | Task 7.4 |
| schema gate оставлен | Task 7 (не трогаем) |
| data/prompts/assembler.md | Task 2.1 |
| Evaluator только при success | Task 7.8 |
| Evaluator убирает _append_log | Task 8 |
| Phase renames: TEST_GEN→TDD, VERIFY→TESTING | Task 7.5 |
| propose: verified:true, stdout logging | Task 9 |
| .env.example обновлён | Task 10 |

### Placeholder scan

Нет TBD/TODO в шагах — все шаги содержат код или команды.

Исключение: `task_blocks.yaml` блок-имена определяются после аудита Task 1. Task 2 даёт явную инструкцию: "вписывай только файлы которые реально существуют".

### Type consistency

- `AssembledPrompt.unified_context: str` — используется во всех phase вызовах как `unified_context`
- `save_learned_ctx(task_id, learn_ctx)` / `clear_learned_ctx(task_id)` — сигнатура одинакова в Task 6 и Task 7
- `assemble_prompt(..., task_id="")` — optional param, не ломает вызовы без task_id
