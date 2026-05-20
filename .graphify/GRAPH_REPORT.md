# Graph Report - .  (2026-05-20)

## Corpus Check
- 7 files · ~6,233 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 573 nodes · 898 edges · 36 communities (35 shown, 1 thin omitted)
- Extraction: 79% EXTRACTED · 21% INFERRED · 0% AMBIGUOUS · INFERRED: 193 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Schema & Task Utilities|Schema & Task Utilities]]
- [[_COMMUNITY_LLM Phase Routing|LLM Phase Routing]]
- [[_COMMUNITY_Security & Validation|Security & Validation]]
- [[_COMMUNITY_Schema Gate|Schema Gate]]
- [[_COMMUNITY_Trace Logger|Trace Logger]]
- [[_COMMUNITY_Connect RPC Client|Connect RPC Client]]
- [[_COMMUNITY_JSON Extraction|JSON Extraction]]
- [[_COMMUNITY_Prompt Assembly & Learned Knowledge|Prompt Assembly & Learned Knowledge]]
- [[_COMMUNITY_LLM Call Layer|LLM Call Layer]]
- [[_COMMUNITY_Data Models|Data Models]]
- [[_COMMUNITY_Harness Service Client|Harness Service Client]]
- [[_COMMUNITY_TDD Test Runner|TDD Test Runner]]
- [[_COMMUNITY_Prompt Loading|Prompt Loading]]
- [[_COMMUNITY_Orchestrator|Orchestrator]]
- [[_COMMUNITY_Pipeline Test Helpers|Pipeline Test Helpers]]
- [[_COMMUNITY_Consolidate Phase|Consolidate Phase]]
- [[_COMMUNITY_LLM Module Tests|LLM Module Tests]]
- [[_COMMUNITY_Agents MD Parser|Agents MD Parser]]
- [[_COMMUNITY_CC Client|CC Client]]
- [[_COMMUNITY_Trace Tests|Trace Tests]]
- [[_COMMUNITY_Learned Migration|Learned Migration]]
- [[_COMMUNITY_Test Fixtures|Test Fixtures]]

## God Nodes (most connected - your core abstractions)
1. `TraceLogger` - 33 edges
2. `check_schema_compliance()` - 27 edges
3. `run_pipeline()` - 20 edges
4. `run_prephase()` - 19 edges
5. `check_sql_queries()` - 18 edges
6. `EcomRuntimeClientSync` - 14 edges
7. `PcmRuntimeClientSync` - 13 edges
8. `run_tests()` - 11 edges
9. `parse_agents_md()` - 11 edges
10. `HarnessServiceClientSync` - 11 edges

## Surprising Connections (you probably didn't know these)
- `_run_single_task()` --calls--> `TraceLogger`  [INFERRED]
  main.py → agent/trace.py
- `_run_single_task()` --calls--> `set_trace()`  [INFERRED]
  main.py → agent/trace.py
- `_run_single_task()` --calls--> `run_agent()`  [INFERRED]
  main.py → agent/orchestrator.py
- `_run_single_task()` --calls--> `get_trace()`  [INFERRED]
  main.py → agent/trace.py
- `load_prompt()` --calls--> `test_load_prompt_unknown_returns_empty()`  [INFERRED]
  agent/prompt.py → tests/test_prompt_loader.py

## Communities (36 total, 1 thin omitted)

### Community 0 - "Schema & Task Utilities"
Cohesion: 0.05
Nodes (63): _build_schema_digest(), _determine_task_type(), _exec_sql_text(), _format_schema_digest(), _infer_role(), merge_schema_from_sqlite_results(), _parse_csv_rows(), PrephaseResult (+55 more)

### Community 1 - "LLM Phase Routing"
Cohesion: 0.08
Nodes (52): Return per-phase model from env, or default_model if not configured., _resolve_model_for_phase(), _build_answer_user_msg(), _build_learn_user_msg(), _build_sdd_user_msg(), _call_llm_phase(), _csv_has_data(), _exec_result_text() (+44 more)

### Community 2 - "Security & Validation"
Cohesion: 0.07
Nodes (38): check_grounding_refs(), check_learn_output(), check_path_access(), check_retry_loop(), check_sql_queries(), check_where_literals(), _has_where_clause(), _is_select() (+30 more)

### Community 3 - "Schema Gate"
Cohesion: 0.08
Nodes (38): _build_alias_map(), _check_query(), check_schema_compliance(), _known_cols_by_table(), Schema-aware SQL validator: unknown columns, unverified literals, double-key JOI, Return {alias_lower: table_name_lower} from FROM and JOIN clauses., Check queries against schema. Returns first error string or None if all pass., Return {table_name_lower: {col_name_lower, ...}}. (+30 more)

### Community 4 - "Trace Logger"
Cohesion: 0.11
Nodes (18): get_trace(), Thread-local structured JSONL trace logger for per-task pipeline traces., TraceLogger, _read_records(), test_gate_check_not_blocked(), test_gate_check_record(), test_get_trace_none_by_default(), test_header_record() (+10 more)

### Community 5 - "Connect RPC Client"
Cohesion: 0.06
Nodes (4): ConnectClient, Minimal Connect RPC client using JSON protocol over httpx., EcomRuntimeClientSync, PcmRuntimeClientSync

### Community 6 - "JSON Extraction"
Cohesion: 0.08
Nodes (28): _extract_json_from_text(), _obj_mutation_tool(), JSON extraction from free-form LLM text output.  Public API:   _obj_mutation_too, Try json5 parse; raises on failure (ImportError or parse error)., Return the mutation tool name if obj is a write/delete/exec action, else None., Lower tuple = preferred. Used by min() to break ties among same-tier candidates., Extract the most actionable valid JSON object from free-form model output., _richness_key() (+20 more)

### Community 7 - "Prompt Assembly & Learned Knowledge"
Cohesion: 0.12
Nodes (26): _apply_learn_diff(), assemble_prompt(), AssembledPrompt, load_learned_ctx(), load_learned_entries(), _next_entry_id(), LLM-assembler: builds unified_context from all prompt sources per pipeline cycle, Call LLM assembler to produce unified_context from all sources. (+18 more)

### Community 8 - "LLM Call Layer"
Cohesion: 0.11
Nodes (24): call_llm_raw(), _call_raw_single_model(), get_anthropic_model_id(), get_provider(), get_response_format(), _get_static_hint(), is_claude_code_model(), is_claude_model() (+16 more)

### Community 9 - "Data Models"
Cohesion: 0.17
Nodes (18): Contract, ContractRound, EvaluatorResponse, ExecutorProposal, AnswerOutput, ConsolidateOutput, ConsolidationItem, ExecuteOutput (+10 more)

### Community 10 - "Harness Service Client"
Cohesion: 0.14
Nodes (10): HarnessServiceClientSync, _log_stats(), main(), _print_table_header(), _print_table_row(), Execute one benchmark trial., Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref, _run_single_task() (+2 more)

### Community 11 - "TDD Test Runner"
Cohesion: 0.17
Nodes (18): _check_tdd_antipatterns(), Subprocess test runner for TDD pipeline., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., run_tests(), False-negative: regex does not match unescaped opposite-quote inside literal. Ac, test_aggregate_antipattern_force_fail(), test_aggregate_without_bad_len_passes(), test_answer_tests_signature() (+10 more)

### Community 12 - "Prompt Loading"
Cohesion: 0.16
Nodes (15): load_prompt(), load_task_blocks(), Prompt loading utilities., Return prompt block by file stem name. Returns '' if not found., Return list of prompt block stems for given task_type from data/config/task_bloc, test_email_prompt_not_loaded(), test_inbox_prompt_not_loaded(), test_load_prompt_answer_exists() (+7 more)

### Community 13 - "Orchestrator"
Cohesion: 0.16
Nodes (12): Minimal orchestrator for ecom benchmark., Execute a single benchmark task., run_agent(), _make_vm_mock(), run_agent forwards injection params + task_id to run_pipeline., run_agent calls run_pipeline for all tasks., run_agent() result must not contain builder_*/contract_*/eval_rejection_count fi, run_agent() always returns a plain dict (public API unchanged). (+4 more)

### Community 14 - "Pipeline Test Helpers"
Cohesion: 0.33
Nodes (14): set_trace(), _answer_json(), _collect_trace(), _exec_ok(), _make_pre(), _plan_json(), Verify pipeline instruments TraceLogger at required points., PLAN phase llm_call record written in new pipeline. (+6 more)

### Community 15 - "Consolidate Phase"
Cohesion: 0.24
Nodes (14): _run_consolidate(), _consolidate_merge_json(), _consolidate_skip_json(), _make_entry(), Consolidation item with empty merged_rule is silently skipped., With 1 active entry, no LLM call made., With 0 active entries, no LLM call made., LLM returns skip=true → _apply_learn_diff not called, learn_ctx unchanged. (+6 more)

### Community 16 - "LLM Module Tests"
Cohesion: 0.14
Nodes (6): _system_as_str flattens list[dict] blocks to newline-joined text., _system_as_str returns str unchanged., _OLLAMA_KEY attribute must exist on module and use or-fallback logic., test_ollama_key_constant_exists_and_fallback(), test_system_as_str_from_blocks(), test_system_as_str_passthrough_str()

### Community 18 - "Agents MD Parser"
Cohesion: 0.27
Nodes (10): parse_agents_md(), Parse AGENTS.MD into {section_name: [lines]} for each ## section., test_empty_section_has_empty_lines(), test_empty_string_returns_empty_dict(), test_h1_heading_not_treated_as_section(), test_leading_content_before_first_section_ignored(), test_multiple_sections(), test_no_sections_returns_empty_dict() (+2 more)

### Community 19 - "CC Client"
Cohesion: 0.27
Nodes (8): _build_env(), cc_complete(), _parse_envelope(), Claude Code tier — spawn iclaude CLI as stateless LLM.  Bypasses applied (all re, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str, Extract result text and token usage from iclaude --output-format json.     Envel, _spawn_once()

### Community 20 - "Trace Tests"
Cohesion: 0.33
Nodes (5): Verify main.py creates/closes TraceLogger and calls log_header + log_task_result, main.log must contain stats rows but NOT pipeline cycle lines., After _run_single_task: .jsonl created, no .log file, log_header + log_task_resu, test_main_log_contains_only_stats(), test_run_single_task_creates_jsonl_and_removes_log()

### Community 23 - "Learned Migration"
Cohesion: 0.67
Nodes (3): main(), _migrate_file(), Return True if migrated, False if already in new format or skipped.

## Knowledge Gaps
- **129 isolated node(s):** `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Prompt loading utilities.`, `Return prompt block by file stem name. Returns '' if not found.`, `Return list of prompt block stems for given task_type from data/config/task_bloc` (+124 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_prephase()` connect `Schema & Task Utilities` to `Agents MD Parser`, `Orchestrator`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Why does `run_agent()` connect `Orchestrator` to `Schema & Task Utilities`, `Harness Service Client`, `Connect RPC Client`?**
  _High betweenness centrality (0.105) - this node is a cross-community bridge._
- **Why does `_run_single_task()` connect `Harness Service Client` to `Trace Logger`, `Orchestrator`, `Pipeline Test Helpers`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `TraceLogger` (e.g. with `_run_single_task()` and `_collect_trace()`) actually correct?**
  _`TraceLogger` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `check_schema_compliance()` (e.g. with `test_valid_query_passes()` and `test_unknown_column_detected()`) actually correct?**
  _`check_schema_compliance()` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `run_pipeline()` (e.g. with `test_happy_path()` and `test_sdd_fail_triggers_learn_then_retry()`) actually correct?**
  _`run_pipeline()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `run_prephase()` (e.g. with `run_agent()` and `test_normal_mode_reads_only_agents_md()`) actually correct?**
  _`run_prephase()` has 14 INFERRED edges - model-reasoned connections that need verification._