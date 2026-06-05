# Pipeline Flow — ecom1-agent

## 1. Общий поток агента

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
flowchart TD
    ENTRY["main.py\nThreadPoolExecutor"]
    ORCH["orchestrator.py\nrun_agent()"]
    PRE["prephase.py\nrun_prephase()"]
    PIPE["pipeline.py\nrun_pipeline()"]
    RESULT["stats dict\nreturn"]

    ENTRY --> ORCH
    ORCH --> PRE
    PRE --> ORCH
    ORCH --> PIPE
    PIPE --> RESULT

    subgraph pre_sub["PREPHASE"]
        P1["fetch /AGENTS.MD"]
        P2["fetch /bin/date, /bin/id"]
        P3["fetch /bin/sql .schema"]
        P4["PRAGMA table_info\nforeign_key_list"]
        P5["infer task_type\nsql | compute"]
        P6["PrePhaseResult"]
        P1 --> P2 --> P3 --> P4 --> P5 --> P6
    end

    PRE -.->|executes| pre_sub

    classDef entry   fill:#89b4fa,color:#1e1e2e,stroke:#74c7ec,stroke-width:2px
    classDef phase   fill:#313244,color:#cdd6f4,stroke:#89b4fa
    classDef result  fill:#a6e3a1,color:#1e1e2e,stroke:#40a02b
    classDef sub     fill:#1e1e2e,color:#cdd6f4,stroke:#585b70

    class ENTRY entry
    class ORCH,PRE,PIPE phase
    class RESULT result
```

---

## 2. Fast Path vs Full Pipeline

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
flowchart TD
    START["run_pipeline()"]

    CHECK_ID{"task_id\nexists?"}
    CHECK_VALID{"last_run\nheuristic_valid=True\n+ script exists?"}

    FP["FAST PATH\nexec data/heuristics/tid.py"]
    FP_OK{"success?"}
    FP_RET["return\ncycles=0\ntokens=0"]

    FULL["FULL PIPELINE\nup to MAX_CYCLES=3"]

    START --> CHECK_ID
    CHECK_ID -- No --> FULL
    CHECK_ID -- Yes --> CHECK_VALID
    CHECK_VALID -- No --> FULL
    CHECK_VALID -- Yes --> FP
    FP --> FP_OK
    FP_OK -- Yes --> FP_RET
    FP_OK -- No --> FULL

    classDef decision fill:#f9e2af,color:#1e1e2e,stroke:#df8e1d
    classDef fast     fill:#a6e3a1,color:#1e1e2e,stroke:#40a02b
    classDef full     fill:#89b4fa,color:#1e1e2e,stroke:#74c7ec
    classDef start    fill:#313244,color:#cdd6f4,stroke:#89b4fa

    class CHECK_ID,CHECK_VALID,FP_OK decision
    class FP,FP_RET fast
    class FULL full
    class START start
```

---

## 3. Полный цикл пайплайна (один цикл из MAX_CYCLES)

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
flowchart TD
    CYCLE_START["Цикл N / MAX_CYCLES"]

    ASSEMBLE["ASSEMBLE\nprompt_assembler.py\n1x LLM call"]
    IDD["IDD\nIntent Detection\n1x LLM call"]
    IDD_HARD{"hard_stop?"}
    IDD_FAIL{"parse fail?"}

    SDD["SDD\nSpec Design\n1x LLM call"]
    SDD_SEC{"DENIED_SECURITY?"}
    SDD_UNS{"UNSUPPORTED?"}
    SDD_FAIL{"parse fail?"}

    PLAN["PLAN\nAction selection\n1x LLM call"]
    PLAN_EMPTY{"action\nempty?"}
    PLAN_RETRY{"retry loop\ndetected?"}
    PLAN_INJ["inject issuer_id\ninject store_id filter"]

    CODEGEN["CODEGEN\ngenerate heuristic script\n1x LLM call"]
    LINT_LOOP["lint retry loop\nup to CODEGEN_LINT_RETRIES=3"]
    LINT_OK{"ast.parse\nOK + mock test OK?"}
    LINT_FAIL{"max retries\nreached?"}

    ANSWER["ANSWER\nexec script on real VM\n0x LLM call"]
    ANS_HARD{"hard error\n_HARD_ERROR_PREFIX?"}
    ANS_SOFT{"soft error?"}
    ANS_OK["SUCCESS\noutcome from script"]

    LEARN["LEARN\n1x LLM call\nappend rule to learn_ctx"]
    CONSOLIDATE["CONSOLIDATE\n1x LLM call if 2+ rules\nmerge overlapping rules"]
    NEXT_CYCLE["next cycle\nor exhaust"]

    HARD_STOP_ANS["vm.answer()\nhard_stop code\nbreak SUCCESS"]
    SEC_ANS["vm.answer()\nDENIED_SECURITY\nbreak SUCCESS"]
    UNS_ANS["vm.answer()\nUNSUPPORTED\nbreak SUCCESS"]
    HARD_ERR_BREAK["break loop\nno success"]
    SUCCESS_BREAK["vm.answer()\nbreak SUCCESS"]

    CYCLE_START --> ASSEMBLE --> IDD
    IDD --> IDD_HARD
    IDD_HARD -- Yes --> HARD_STOP_ANS
    IDD_HARD -- No --> IDD_FAIL
    IDD_FAIL -- Yes --> LEARN

    IDD_FAIL -- No --> SDD
    SDD --> SDD_SEC
    SDD_SEC -- Yes --> SEC_ANS
    SDD_SEC -- No --> SDD_UNS
    SDD_UNS -- Yes --> UNS_ANS
    SDD_UNS -- No --> SDD_FAIL
    SDD_FAIL -- Yes --> LEARN

    SDD_FAIL -- No --> PLAN
    PLAN --> PLAN_EMPTY
    PLAN_EMPTY -- Yes --> LEARN
    PLAN_EMPTY -- No --> PLAN_RETRY
    PLAN_RETRY -- Yes --> LEARN
    PLAN_RETRY -- No --> PLAN_INJ --> CODEGEN

    CODEGEN --> LINT_LOOP --> LINT_OK
    LINT_OK -- No --> LINT_FAIL
    LINT_FAIL -- No --> LINT_LOOP
    LINT_FAIL -- Yes --> LEARN
    LINT_OK -- Yes --> ANSWER

    ANSWER --> ANS_HARD
    ANS_HARD -- Yes --> HARD_ERR_BREAK
    ANS_HARD -- No --> ANS_SOFT
    ANS_SOFT -- Yes --> LEARN
    ANS_SOFT -- No --> ANS_OK --> SUCCESS_BREAK

    LEARN --> CONSOLIDATE --> NEXT_CYCLE

    classDef phase    fill:#313244,color:#cdd6f4,stroke:#89b4fa
    classDef decision fill:#f9e2af,color:#1e1e2e,stroke:#df8e1d
    classDef success  fill:#a6e3a1,color:#1e1e2e,stroke:#40a02b
    classDef danger   fill:#f38ba8,color:#1e1e2e,stroke:#d20f39
    classDef learn    fill:#94e2d5,color:#1e1e2e,stroke:#179299
    classDef inject   fill:#585b70,color:#cdd6f4,stroke:#6c7086

    class ASSEMBLE,IDD,SDD,PLAN,CODEGEN,ANSWER phase
    class IDD_HARD,IDD_FAIL,SDD_SEC,SDD_UNS,SDD_FAIL,PLAN_EMPTY,PLAN_RETRY,LINT_OK,LINT_FAIL,ANS_HARD,ANS_SOFT decision
    class HARD_STOP_ANS,SEC_ANS,UNS_ANS,ANS_OK,SUCCESS_BREAK success
    class HARD_ERR_BREAK danger
    class LEARN,CONSOLIDATE learn
    class PLAN_INJ,LINT_LOOP inject
```

---

## 4. Состояния исхода и heuristic_valid

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
stateDiagram-v2
    [*] --> Running

    Running --> OUTCOME_OK : ANSWER script success
    Running --> OUTCOME_DENIED_SECURITY : SDD DENIED_SECURITY
    Running --> OUTCOME_NONE_UNSUPPORTED : SDD UNSUPPORTED
    Running --> OUTCOME_NONE_CLARIFICATION : IDD hard_stop
    Running --> OUTCOME_NONE_CLARIFICATION : all cycles fail
    Running --> OUTCOME_NONE_CLARIFICATION : ANSWER hard error

    OUTCOME_OK --> SaveValid : heuristic_valid = True
    OUTCOME_DENIED_SECURITY --> SaveValid : heuristic_valid = True
    OUTCOME_NONE_UNSUPPORTED --> SaveValid : heuristic_valid = True
    OUTCOME_NONE_CLARIFICATION --> SaveInvalid : heuristic_valid = False

    SaveValid --> [*]
    SaveInvalid --> [*]
```

---

## 5. LEARN и CONSOLIDATE — логика обучения

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
flowchart TD
    FAIL_IN["failure detected\nerror_type set"]

    ET{"error_type?"}
    LLM_FAIL["llm_fail\nskip rule extraction\nreturn early"]
    SEM["semantic\nextract rule from LLM"]

    ANCHOR{"anchor in\nagents_md_index?"}
    USE_VAULT["use vault rule\nas extracted rule"]
    USE_LLM["use LLM-extracted rule"]

    VALIDATE{"rule valid?\nlen >= 20\ncorrect prefix?"}
    SKIP["skip — invalid rule"]
    APPEND["append rNNN entry\nto learn_ctx"]
    DEACTIVATE["deactivate conflicting\nentries in YAML"]

    WRITE_YAML["write data/learned/tid.yaml\nincremental"]

    COUNT{"active rules\n>= 2?"}
    CONSOLIDATE_LLM["CONSOLIDATE LLM call\nmerge overlapping rules\ndeactivate originals"]
    SKIP_CON["skip CONSOLIDATE"]

    NEXT["next cycle"]

    FAIL_IN --> ET
    ET -- llm_fail --> LLM_FAIL --> NEXT
    ET -- semantic --> SEM --> ANCHOR
    ANCHOR -- Yes --> USE_VAULT --> VALIDATE
    ANCHOR -- No --> USE_LLM --> VALIDATE
    VALIDATE -- No --> SKIP --> NEXT
    VALIDATE -- Yes --> APPEND --> DEACTIVATE --> WRITE_YAML --> COUNT
    COUNT -- Yes --> CONSOLIDATE_LLM --> NEXT
    COUNT -- No --> SKIP_CON --> NEXT

    classDef decision fill:#f9e2af,color:#1e1e2e,stroke:#df8e1d
    classDef learn    fill:#94e2d5,color:#1e1e2e,stroke:#179299
    classDef skip     fill:#585b70,color:#cdd6f4,stroke:#6c7086
    classDef write    fill:#89b4fa,color:#1e1e2e,stroke:#74c7ec

    class ET,ANCHOR,VALIDATE,COUNT decision
    class SEM,APPEND,DEACTIVATE,CONSOLIDATE_LLM learn
    class LLM_FAIL,SKIP,SKIP_CON skip
    class WRITE_YAML,USE_VAULT,USE_LLM write
```

---

## 6. Сборка контекста (ASSEMBLE)

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
flowchart LR
    subgraph sources["Источники (приоритет сверху вниз)"]
        S1["1) TASK_TEXT + TASK_TYPE"]
        S2["2) LAST_RUN metadata"]
        S3["3) LEARNED rules\ndata/learned/tid.yaml"]
        S4["4) VAULT /AGENTS.MD"]
        S5["5) SCHEMA_DIGEST\nPRAGMA table_info"]
        S6["6) DB_SCHEMA"]
        S7["7) AGENT_CONTEXT\ndate, runtime_identity, store_id"]
    end

    ASSEMBLER_LLM["ASSEMBLER LLM call\nMODEL_ASSEMBLER"]

    UC["unified_context\n# LEARNED\n# BASE"]

    S1 & S2 & S3 & S4 & S5 & S6 & S7 --> ASSEMBLER_LLM --> UC

    classDef source fill:#313244,color:#cdd6f4,stroke:#585b70
    classDef llm    fill:#89b4fa,color:#1e1e2e,stroke:#74c7ec
    classDef output fill:#a6e3a1,color:#1e1e2e,stroke:#40a02b

    class S1,S2,S3,S4,S5,S6,S7 source
    class ASSEMBLER_LLM llm
    class UC output
```

---

## 7. CODEGEN — внутренний lint-цикл

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
flowchart TD
    CG_START["CODEGEN LLM call\nunified_context + codegen_guide"]
    PARSE_JSON["parse JSON response\nextract script + test code"]
    AST["ast.parse(script)\nast.parse(test_code)"]
    AST_OK{"syntax OK?"}
    MOCK["run mock test\nMockVM execution"]
    MOCK_OK{"mock test OK?"}
    WRITE["write data/heuristics/tid.py\nwrite data/heuristics/tid_test.py"]
    SUCCESS["CODEGEN success\nproceed to ANSWER"]

    RETRY_N{"attempt < \nCODEGEN_LINT_RETRIES?"}
    RETRY_LLM["retry LLM call\nwith PREVIOUS_LINT_ERROR"]
    LEARN_CG["error_type=semantic\nto LEARN"]

    CG_START --> PARSE_JSON --> AST --> AST_OK
    AST_OK -- Yes --> MOCK --> MOCK_OK
    MOCK_OK -- Yes --> WRITE --> SUCCESS
    AST_OK -- No --> RETRY_N
    MOCK_OK -- No --> RETRY_N
    RETRY_N -- Yes --> RETRY_LLM --> PARSE_JSON
    RETRY_N -- No --> LEARN_CG

    classDef phase    fill:#313244,color:#cdd6f4,stroke:#89b4fa
    classDef decision fill:#f9e2af,color:#1e1e2e,stroke:#df8e1d
    classDef success  fill:#a6e3a1,color:#1e1e2e,stroke:#40a02b
    classDef danger   fill:#f38ba8,color:#1e1e2e,stroke:#d20f39
    classDef retry    fill:#585b70,color:#cdd6f4,stroke:#6c7086

    class CG_START,PARSE_JSON,AST,MOCK,WRITE phase
    class AST_OK,MOCK_OK,RETRY_N decision
    class SUCCESS success
    class LEARN_CG danger
    class RETRY_LLM retry
```

---

## 8. VM API (proto-api-reference.md) — точки вызова в пайплайне

> Все RPC задокументированы в `docs/proto-api-reference.md` (источник: `proto/bitgn/vm/ecom/ecom.proto`).

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'background': '#1e1e2e',
  'primaryColor': '#313244',
  'primaryTextColor': '#cdd6f4',
  'primaryBorderColor': '#89b4fa',
  'lineColor': '#888888',
  'secondaryColor': '#181825',
  'tertiaryColor': '#45475a'
}}}%%
flowchart TD
    PROTO["docs/proto-api-reference.md\nEcomRuntime RPC API"]

    subgraph prephase_calls["PREPHASE — vm calls"]
        PP1["vm.read()\n/AGENTS.MD или /AGENTS.md"]
        PP2["vm.exec()\n/bin/date"]
        PP3["vm.exec()\n/bin/id"]
        PP4["vm.read()\n/proc/employees/EMP.json"]
        PP5["vm.exec()\n/bin/sql .schema"]
        PP6["vm.exec()\n/bin/sql PRAGMA table_info(T)"]
    end

    subgraph heuristic_calls["HEURISTIC SCRIPT (CODEGEN-generated) — vm calls"]
        HS1["vm.read(path)\nчтение файлов в runtime"]
        HS2["vm.exec(path, args)\nзапуск /bin/sql, /bin/discount, ..."]
        HS3["vm.write(path, content)\nзапись файлов"]
        HS4["vm.delete(path)\nудаление"]
        HS5["vm.list(path) / vm.tree(root)\nобзор директорий"]
        HS6["vm.find() / vm.search()\nпоиск файлов/текста"]
    end

    subgraph answer_calls["vm.answer() — точки финального ответа"]
        A1["FAST PATH success"]
        A2["IDD hard_stop"]
        A3["SDD DENIED_SECURITY"]
        A4["SDD UNSUPPORTED"]
        A5["ANSWER phase success"]
        A6["cycles exhausted → CLARIFICATION"]
        A7["unhandled exception"]
    end

    PROTO -.->|документирует| prephase_calls
    PROTO -.->|документирует| heuristic_calls
    PROTO -.->|документирует| answer_calls

    classDef proto   fill:#89b4fa,color:#1e1e2e,stroke:#74c7ec,stroke-width:2px
    classDef vmcall  fill:#313244,color:#cdd6f4,stroke:#585b70
    classDef answer  fill:#a6e3a1,color:#1e1e2e,stroke:#40a02b

    class PROTO proto
    class PP1,PP2,PP3,PP4,PP5,PP6,HS1,HS2,HS3,HS4,HS5,HS6 vmcall
    class A1,A2,A3,A4,A5,A6,A7 answer
```

### Сводка: какой RPC где используется

| RPC | Фаза | Что вызывает |
|-----|------|-------------|
| `Read` | PREPHASE | `/AGENTS.MD`, `/proc/employees/EMP.json` |
| `Read` | HEURISTIC | произвольные файлы runtime |
| `Exec` | PREPHASE | `/bin/date`, `/bin/id`, `/bin/sql .schema`, `/bin/sql PRAGMA` |
| `Exec` | HEURISTIC | `/bin/sql`, `/bin/discount`, прочие runtime-tools |
| `Write` | HEURISTIC | запись данных в runtime |
| `Delete` | HEURISTIC | удаление файлов |
| `List` / `Tree` | HEURISTIC | обзор директорий |
| `Find` / `Search` | HEURISTIC | поиск по имени / regex |
| `Answer` | FAST PATH, IDD, SDD, ANSWER, CLARIFICATION | финальный ответ хaрнессу |
| `Context` | — | **Deprecated**, не используется |

---

## 9. Таблица фаз — LLM-вызовы и выходные данные

| Фаза | LLM-вызов | Модель | Выходные данные | Ошибка → |
|------|-----------|--------|-----------------|----------|
| ASSEMBLE | 1x | MODEL_ASSEMBLER | unified_context | — |
| IDD | 1x | MODEL | IddOutput (decision, intent, params) | LEARN(llm_fail/semantic) |
| SDD | 1x | MODEL_SDD | SddOutput (actions, error_code) | LEARN(llm_fail/semantic) |
| PLAN | 1x | MODEL_PLAN | PlanOutput (action anchor) | LEARN(semantic) |
| CODEGEN | 1x + retries | MODEL_CODEGEN | heuristic script .py | LEARN(semantic) |
| ANSWER | 0x | — | outcome, answer | LEARN(semantic) / break |
| LEARN | 1x | MODEL_LEARN | rule → learn_ctx | — |
| CONSOLIDATE | 0–1x | MODEL_CONSOLIDATE | merged rules | — |
