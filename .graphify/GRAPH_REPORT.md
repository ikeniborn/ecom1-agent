# Graph Report - .  (2026-05-20)

## Corpus Check
- Corpus is ~23,214 words - fits in a single context window. You may not need a graph.

## Summary
- 640 nodes · 1019 edges · 41 communities (36 shown, 5 thin omitted)
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 221 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Pipeline Orchestration|Pipeline Orchestration]]
- [[_COMMUNITY_SQL Security & Validation|SQL Security & Validation]]
- [[_COMMUNITY_Schema & Prephase|Schema & Prephase]]
- [[_COMMUNITY_LLM Routing & Calls|LLM Routing & Calls]]
- [[_COMMUNITY_Prompt Assembly & Learning|Prompt Assembly & Learning]]
- [[_COMMUNITY_Test Runner & TDD|Test Runner & TDD]]
- [[_COMMUNITY_Trace & Logging|Trace & Logging]]
- [[_COMMUNITY_ECOM VM & Protobuf|ECOM VM & Protobuf]]
- [[_COMMUNITY_JSON Extraction|JSON Extraction]]
- [[_COMMUNITY_Models & Pydantic|Models & Pydantic]]
- [[_COMMUNITY_Agent Orchestration|Agent Orchestration]]
- [[_COMMUNITY_Module Group 11|Module Group 11]]
- [[_COMMUNITY_Module Group 12|Module Group 12]]
- [[_COMMUNITY_Module Group 13|Module Group 13]]
- [[_COMMUNITY_Module Group 14|Module Group 14]]
- [[_COMMUNITY_Module Group 15|Module Group 15]]
- [[_COMMUNITY_Module Group 16|Module Group 16]]
- [[_COMMUNITY_Module Group 17|Module Group 17]]
- [[_COMMUNITY_Module Group 18|Module Group 18]]
- [[_COMMUNITY_Module Group 19|Module Group 19]]
- [[_COMMUNITY_Module Group 20|Module Group 20]]
- [[_COMMUNITY_Module Group 21|Module Group 21]]
- [[_COMMUNITY_Module Group 22|Module Group 22]]
- [[_COMMUNITY_Module Group 24|Module Group 24]]
- [[_COMMUNITY_Module Group 25|Module Group 25]]
- [[_COMMUNITY_Module Group 26|Module Group 26]]
- [[_COMMUNITY_Module Group 28|Module Group 28]]
- [[_COMMUNITY_Module Group 38|Module Group 38]]
- [[_COMMUNITY_Module Group 39|Module Group 39]]
- [[_COMMUNITY_Module Group 40|Module Group 40]]

## God Nodes (most connected - your core abstractions)
1. `TraceLogger` - 33 edges
2. `run_pipeline()` - 32 edges
3. `check_schema_compliance()` - 27 edges
4. `run_prephase()` - 19 edges
5. `check_sql_queries()` - 18 edges
6. `EcomRuntimeClientSync` - 14 edges
7. `load_prompt()` - 13 edges
8. `PcmRuntimeClientSync` - 13 edges
9. `_run_consolidate()` - 12 edges
10. `run_tests()` - 11 edges

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

## Communities (41 total, 5 thin omitted)

### Community 0 - "Pipeline Orchestration"
Cohesion: 0.07
Nodes (60): Return per-phase model from env, or default_model if not configured., _resolve_model_for_phase(), _build_answer_user_msg(), _build_learn_user_msg(), _build_sdd_user_msg(), _call_llm_phase(), _csv_has_data(), _exec_result_text() (+52 more)

### Community 1 - "SQL Security & Validation"
Cohesion: 0.05
Nodes (60): _build_schema_digest(), _determine_task_type(), _exec_sql_text(), _infer_role(), merge_schema_from_sqlite_results(), _parse_csv_rows(), PrephaseResult, Merge CREATE TABLE rows from sqlite_schema CSV output into schema_digest.      R (+52 more)

### Community 2 - "Schema & Prephase"
Cohesion: 0.08
Nodes (35): Contract, ContractRound, EvaluatorResponse, ExecutorProposal, AnswerOutput, ConsolidateOutput, ConsolidationItem, ExecuteOutput (+27 more)

### Community 3 - "LLM Routing & Calls"
Cohesion: 0.07
Nodes (38): check_grounding_refs(), check_learn_output(), check_path_access(), check_retry_loop(), check_sql_queries(), check_where_literals(), _has_where_clause(), _is_select() (+30 more)

### Community 4 - "Prompt Assembly & Learning"
Cohesion: 0.08
Nodes (38): _build_alias_map(), _check_query(), check_schema_compliance(), _known_cols_by_table(), Schema-aware SQL validator: unknown columns, unverified literals, double-key JOI, Return {alias_lower: table_name_lower} from FROM and JOIN clauses., Check queries against schema. Returns first error string or None if all pass., Return {table_name_lower: {col_name_lower, ...}}. (+30 more)

### Community 5 - "Test Runner & TDD"
Cohesion: 0.11
Nodes (18): get_trace(), Thread-local structured JSONL trace logger for per-task pipeline traces., TraceLogger, _read_records(), test_gate_check_not_blocked(), test_gate_check_record(), test_get_trace_none_by_default(), test_header_record() (+10 more)

### Community 6 - "Trace & Logging"
Cohesion: 0.06
Nodes (4): ConnectClient, Minimal Connect RPC client using JSON protocol over httpx., EcomRuntimeClientSync, PcmRuntimeClientSync

### Community 7 - "ECOM VM & Protobuf"
Cohesion: 0.11
Nodes (30): _run_consolidate(), _apply_learn_diff(), load_learned_ctx(), load_learned_entries(), Append new rule entry and deactivate specified entries in data/learned/{task_id}, Return content of active entries from data/learned/{task_id}.yaml., Return all entries (active + inactive) from data/learned/{task_id}.yaml., Append new rule entry and deactivate specified entries in data/learned/{task_id} (+22 more)

### Community 8 - "JSON Extraction"
Cohesion: 0.1
Nodes (26): _apply_learn_diff() (Incremental Learn Persist), bitgn/ (Protobuf Stubs), data/learned/{task_id}.yaml (Knowledge Base), data/prompts/*.md (Phase Guides), JSON Extraction Priority Rationale, json_extract.py, AnswerOutput Pydantic Model, LearnOutput Pydantic Model (+18 more)

### Community 9 - "Models & Pydantic"
Cohesion: 0.09
Nodes (26): _extract_json_from_text(), _obj_mutation_tool(), JSON extraction from free-form LLM text output.  Public API:   _obj_mutation_too, Try json5 parse; raises on failure (ImportError or parse error)., Return the mutation tool name if obj is a write/delete/exec action, else None., Lower tuple = preferred. Used by min() to break ties among same-tier candidates., Extract the most actionable valid JSON object from free-form model output., _richness_key() (+18 more)

### Community 10 - "Agent Orchestration"
Cohesion: 0.11
Nodes (24): call_llm_raw(), _call_raw_single_model(), get_anthropic_model_id(), get_provider(), get_response_format(), _get_static_hint(), is_claude_code_model(), is_claude_model() (+16 more)

### Community 11 - "Module Group 11"
Cohesion: 0.13
Nodes (19): _format_schema_digest(), assemble_prompt(), AssembledPrompt, _build_sources(), load_last_run(), _next_entry_id(), LLM-assembler: builds unified_context from all prompt sources per pipeline cycle, Call LLM assembler to produce unified_context from all sources. (+11 more)

### Community 12 - "Module Group 12"
Cohesion: 0.14
Nodes (10): HarnessServiceClientSync, _log_stats(), main(), _print_table_header(), _print_table_row(), Execute one benchmark trial., Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref, _run_single_task() (+2 more)

### Community 13 - "Module Group 13"
Cohesion: 0.17
Nodes (18): _check_tdd_antipatterns(), Subprocess test runner for TDD pipeline., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., run_tests(), False-negative: regex does not match unescaped opposite-quote inside literal. Ac, test_aggregate_antipattern_force_fail(), test_aggregate_without_bad_len_passes(), test_answer_tests_signature() (+10 more)

### Community 14 - "Module Group 14"
Cohesion: 0.16
Nodes (15): load_prompt(), load_task_blocks(), Prompt loading utilities., Return prompt block by file stem name. Returns '' if not found., Return list of prompt block stems for given task_type from data/config/task_bloc, test_email_prompt_not_loaded(), test_inbox_prompt_not_loaded(), test_load_prompt_answer_exists() (+7 more)

### Community 15 - "Module Group 15"
Cohesion: 0.16
Nodes (12): Minimal orchestrator for ecom benchmark., Execute a single benchmark task., run_agent(), _make_vm_mock(), run_agent forwards injection params + task_id to run_pipeline., run_agent calls run_pipeline for all tasks., run_agent() result must not contain builder_*/contract_*/eval_rejection_count fi, run_agent() always returns a plain dict (public API unchanged). (+4 more)

### Community 16 - "Module Group 16"
Cohesion: 0.33
Nodes (14): set_trace(), _answer_json(), _collect_trace(), _exec_ok(), _make_pre(), _plan_json(), Verify pipeline instruments TraceLogger at required points., PLAN phase llm_call record written in new pipeline. (+6 more)

### Community 17 - "Module Group 17"
Cohesion: 0.14
Nodes (6): _system_as_str flattens list[dict] blocks to newline-joined text., _system_as_str returns str unchanged., _OLLAMA_KEY attribute must exist on module and use or-fallback logic., test_ollama_key_constant_exists_and_fallback(), test_system_as_str_from_blocks(), test_system_as_str_passthrough_str()

### Community 18 - "Module Group 18"
Cohesion: 0.27
Nodes (10): parse_agents_md(), Parse AGENTS.MD into {section_name: [lines]} for each ## section., test_empty_section_has_empty_lines(), test_empty_string_returns_empty_dict(), test_h1_heading_not_treated_as_section(), test_leading_content_before_first_section_ignored(), test_multiple_sections(), test_no_sections_returns_empty_dict() (+2 more)

### Community 19 - "Module Group 19"
Cohesion: 0.27
Nodes (8): _build_env(), cc_complete(), _parse_envelope(), Claude Code tier — spawn iclaude CLI as stateless LLM.  Bypasses applied (all re, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str, Extract result text and token usage from iclaude --output-format json.     Envel, _spawn_once()

### Community 20 - "Module Group 20"
Cohesion: 0.25
Nodes (8): data/eval_log.jsonl, data/.eval_optimizations_processed (processed hashes), MODEL_EVALUATOR env var, prompt_optimization channel → data/prompts/optimized/, scripts/propose_optimizations.py, rule_optimization channel → data/rules/sql-NNN.yaml, security_optimization channel → data/security/sec-NNN.yaml, Three optimization channels (rule, security, prompt)

### Community 21 - "Module Group 21"
Cohesion: 0.29
Nodes (7): cc_client.py (Claude Code Tier), llm.py (LLM Routing), Anthropic SDK Tier, Claude Code CLI Tier, Local Ollama Tier, OpenRouter Tier, models.json (Provider Hints)

### Community 22 - "Module Group 22"
Cohesion: 0.33
Nodes (5): Verify main.py creates/closes TraceLogger and calls log_header + log_task_result, main.log must contain stats rows but NOT pipeline cycle lines., After _run_single_task: .jsonl created, no .log file, log_header + log_task_resu, test_main_log_contains_only_stats(), test_run_single_task_creates_jsonl_and_removes_log()

### Community 24 - "Module Group 24"
Cohesion: 0.6
Nodes (5): check_grounding_refs, clean_refs, p.path SQL column, sku_refs, t16 grounding refs bug

### Community 25 - "Module Group 25"
Cohesion: 0.67
Nodes (3): main(), _migrate_file(), Return True if migrated, False if already in new format or skipped.

## Knowledge Gaps
- **161 isolated node(s):** `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Prompt loading utilities.`, `Return prompt block by file stem name. Returns '' if not found.`, `Return list of prompt block stems for given task_type from data/config/task_bloc` (+156 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_pipeline()` connect `Pipeline Orchestration` to `LLM Routing & Calls`, `Test Runner & TDD`, `ECOM VM & Protobuf`, `Models & Pydantic`, `Module Group 11`, `Module Group 14`, `Module Group 15`, `Module Group 16`?**
  _High betweenness centrality (0.232) - this node is a cross-community bridge._
- **Why does `run_agent()` connect `Module Group 15` to `Pipeline Orchestration`, `SQL Security & Validation`, `Module Group 12`, `Trace & Logging`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Why does `_run_single_task()` connect `Module Group 12` to `Module Group 16`, `Test Runner & TDD`, `Module Group 15`?**
  _High betweenness centrality (0.128) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `TraceLogger` (e.g. with `_run_single_task()` and `_collect_trace()`) actually correct?**
  _`TraceLogger` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `run_pipeline()` (e.g. with `run_agent()` and `test_llm_call_records_written_on_success()`) actually correct?**
  _`run_pipeline()` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `check_schema_compliance()` (e.g. with `test_valid_query_passes()` and `test_unknown_column_detected()`) actually correct?**
  _`check_schema_compliance()` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `run_prephase()` (e.g. with `run_agent()` and `test_normal_mode_reads_only_agents_md()`) actually correct?**
  _`run_prephase()` has 14 INFERRED edges - model-reasoned connections that need verification._