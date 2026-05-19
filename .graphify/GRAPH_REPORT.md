# Graph Report - .  (2026-05-19)

## Corpus Check
- Corpus is ~22,772 words - fits in a single context window. You may not need a graph.

## Summary
- 1202 nodes · 1837 edges · 100 communities (61 shown, 39 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 325 edges (avg confidence: 0.81)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Pipeline LLM Phases|Pipeline LLM Phases]]
- [[_COMMUNITY_Trace Logging|Trace Logging]]
- [[_COMMUNITY_Prephase & Schema|Prephase & Schema]]
- [[_COMMUNITY_Learned Knowledge Storage|Learned Knowledge Storage]]
- [[_COMMUNITY_Pydantic Models & Contracts|Pydantic Models & Contracts]]
- [[_COMMUNITY_Optimization Pipeline|Optimization Pipeline]]
- [[_COMMUNITY_Evaluator (removed)|Evaluator (removed)]]
- [[_COMMUNITY_JSON Extraction|JSON Extraction]]
- [[_COMMUNITY_Schema Gate|Schema Gate]]
- [[_COMMUNITY_SQL Security|SQL Security]]
- [[_COMMUNITY_Reference Bug Tests|Reference Bug Tests]]
- [[_COMMUNITY_Prompt Loading|Prompt Loading]]
- [[_COMMUNITY_Optimization Tests (removed)|Optimization Tests (removed)]]
- [[_COMMUNITY_BitGN ConnectHarness|BitGN Connect/Harness]]
- [[_COMMUNITY_Resolve Phase (stub)|Resolve Phase (stub)]]
- [[_COMMUNITY_Module Group 15|Module Group 15]]
- [[_COMMUNITY_Module Group 16|Module Group 16]]
- [[_COMMUNITY_Module Group 17|Module Group 17]]
- [[_COMMUNITY_Module Group 18|Module Group 18]]
- [[_COMMUNITY_Module Group 19|Module Group 19]]
- [[_COMMUNITY_Module Group 20|Module Group 20]]
- [[_COMMUNITY_Module Group 21|Module Group 21]]
- [[_COMMUNITY_Module Group 22|Module Group 22]]
- [[_COMMUNITY_Module Group 23|Module Group 23]]
- [[_COMMUNITY_Module Group 24|Module Group 24]]
- [[_COMMUNITY_Module Group 25|Module Group 25]]
- [[_COMMUNITY_Module Group 26|Module Group 26]]
- [[_COMMUNITY_Module Group 27|Module Group 27]]
- [[_COMMUNITY_Module Group 28|Module Group 28]]
- [[_COMMUNITY_Module Group 29|Module Group 29]]
- [[_COMMUNITY_Module Group 30|Module Group 30]]
- [[_COMMUNITY_Module Group 31|Module Group 31]]
- [[_COMMUNITY_Module Group 32|Module Group 32]]
- [[_COMMUNITY_Module Group 35|Module Group 35]]
- [[_COMMUNITY_Module Group 36|Module Group 36]]
- [[_COMMUNITY_Module Group 37|Module Group 37]]
- [[_COMMUNITY_Module Group 38|Module Group 38]]
- [[_COMMUNITY_Module Group 39|Module Group 39]]
- [[_COMMUNITY_Module Group 40|Module Group 40]]
- [[_COMMUNITY_Module Group 41|Module Group 41]]
- [[_COMMUNITY_Module Group 42|Module Group 42]]
- [[_COMMUNITY_Module Group 43|Module Group 43]]
- [[_COMMUNITY_Module Group 44|Module Group 44]]
- [[_COMMUNITY_Module Group 45|Module Group 45]]
- [[_COMMUNITY_Module Group 47|Module Group 47]]
- [[_COMMUNITY_Module Group 48|Module Group 48]]
- [[_COMMUNITY_Module Group 49|Module Group 49]]
- [[_COMMUNITY_Module Group 50|Module Group 50]]
- [[_COMMUNITY_Module Group 51|Module Group 51]]
- [[_COMMUNITY_Module Group 52|Module Group 52]]
- [[_COMMUNITY_Module Group 53|Module Group 53]]
- [[_COMMUNITY_Module Group 54|Module Group 54]]
- [[_COMMUNITY_Module Group 55|Module Group 55]]
- [[_COMMUNITY_Module Group 56|Module Group 56]]
- [[_COMMUNITY_Module Group 57|Module Group 57]]
- [[_COMMUNITY_Module Group 58|Module Group 58]]
- [[_COMMUNITY_Module Group 59|Module Group 59]]
- [[_COMMUNITY_Module Group 60|Module Group 60]]
- [[_COMMUNITY_Module Group 61|Module Group 61]]
- [[_COMMUNITY_Module Group 73|Module Group 73]]
- [[_COMMUNITY_Module Group 74|Module Group 74]]
- [[_COMMUNITY_Module Group 75|Module Group 75]]
- [[_COMMUNITY_Module Group 76|Module Group 76]]
- [[_COMMUNITY_Module Group 77|Module Group 77]]
- [[_COMMUNITY_Module Group 78|Module Group 78]]
- [[_COMMUNITY_Module Group 79|Module Group 79]]
- [[_COMMUNITY_Module Group 80|Module Group 80]]
- [[_COMMUNITY_Module Group 81|Module Group 81]]
- [[_COMMUNITY_Module Group 82|Module Group 82]]
- [[_COMMUNITY_Module Group 83|Module Group 83]]
- [[_COMMUNITY_Module Group 84|Module Group 84]]
- [[_COMMUNITY_Module Group 85|Module Group 85]]
- [[_COMMUNITY_Module Group 86|Module Group 86]]
- [[_COMMUNITY_Module Group 87|Module Group 87]]
- [[_COMMUNITY_Module Group 88|Module Group 88]]
- [[_COMMUNITY_Module Group 89|Module Group 89]]
- [[_COMMUNITY_Module Group 90|Module Group 90]]
- [[_COMMUNITY_Module Group 91|Module Group 91]]
- [[_COMMUNITY_Module Group 92|Module Group 92]]
- [[_COMMUNITY_Module Group 93|Module Group 93]]
- [[_COMMUNITY_Module Group 94|Module Group 94]]
- [[_COMMUNITY_Module Group 95|Module Group 95]]
- [[_COMMUNITY_Module Group 96|Module Group 96]]
- [[_COMMUNITY_Module Group 97|Module Group 97]]
- [[_COMMUNITY_Module Group 98|Module Group 98]]
- [[_COMMUNITY_Module Group 99|Module Group 99]]

## God Nodes (most connected - your core abstractions)
1. `main` - 36 edges
2. `TraceLogger` - 34 edges
3. `check_schema_compliance()` - 30 edges
4. `load_prompt()` - 24 edges
5. `_write_eval_log()` - 22 edges
6. `_eval_entry()` - 22 edges
7. `_setup()` - 22 edges
8. `_base_patches()` - 21 edges
9. `main()` - 20 edges
10. `run_pipeline()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `agent/pipeline.py` --uses--> `call_llm_raw`  [EXTRACTED]
  /home/ikeniborn/Documents/Project/ecom1-agent/CLAUDE.md → agent/llm.py
- `call_llm_raw` --delegates_to--> `agent/cc_client.py`  [EXTRACTED]
  agent/llm.py → /home/ikeniborn/Documents/Project/ecom1-agent/agent/CLAUDE.md
- `_run_single_task()` --calls--> `TraceLogger`  [INFERRED]
  main.py → agent/trace.py
- `_run_single_task()` --calls--> `set_trace()`  [INFERRED]
  main.py → agent/trace.py
- `_run_single_task()` --calls--> `get_trace()`  [INFERRED]
  main.py → agent/trace.py

## Communities (100 total, 39 thin omitted)

### Community 0 - "Pipeline LLM Phases"
Cohesion: 0.06
Nodes (63): Return per-phase model from env, or default_model if not configured., _resolve_model_for_phase(), _build_answer_user_msg(), _build_learn_user_msg(), _build_sdd_user_msg(), _call_llm_phase(), _csv_has_data(), _exec_result_text() (+55 more)

### Community 1 - "Trace Logging"
Cohesion: 0.06
Nodes (40): get_trace(), Thread-local structured JSONL trace logger for per-task pipeline traces., set_trace(), TraceLogger, _answer_json(), _collect_trace_records(), _exec_ok(), _make_pre() (+32 more)

### Community 2 - "Prephase & Schema"
Cohesion: 0.05
Nodes (62): _build_schema_digest(), _determine_task_type(), _exec_sql_text(), _format_schema_digest(), _infer_role(), merge_schema_from_sqlite_results(), _parse_csv_rows(), PrephaseResult (+54 more)

### Community 3 - "Learned Knowledge Storage"
Cohesion: 0.05
Nodes (56): /AGENTS.MD (vault rules), AnswerOutput, AnswerOutput (Pydantic model), assemble_prompt() function, check_retry_loop (anti-infinite-loop guard), data/config/task_blocks.yaml, data/eval_log.jsonl, data/learned/{task_id}.yaml (+48 more)

### Community 4 - "Pydantic Models & Contracts"
Cohesion: 0.06
Nodes (42): Contract, ContractRound, EvaluatorResponse, ExecutorProposal, AnswerOutput, LearnOutput, MockScenario, PlanStep (+34 more)

### Community 5 - "Optimization Pipeline"
Cohesion: 0.05
Nodes (48): Optimization Pipeline Design, call_llm_raw_cluster, _check_contradiction, _cluster_recs, _dedup_by_content_per_task, _entry_hash, _load_model_cfg, _load_processed (+40 more)

### Community 6 - "Evaluator (removed)"
Cohesion: 0.08
Nodes (42): _append_log(), _build_eval_system(), _compute_eval_metrics(), EvalInput, Post-execution pipeline evaluator. Fail-open: any exception returns None., Compute agents_md_coverage and schema_grounding. Returns dict with both floats., Compute agents_md_coverage and schema_grounding. Returns dict with both floats., Evaluate pipeline trace. Returns PipelineEvalOutput or None on any failure. (+34 more)

### Community 7 - "JSON Extraction"
Cohesion: 0.08
Nodes (42): _extract_json_from_text(), JSON extraction from free-form LLM text output.  Public API:   _obj_mutation_too, Try json5 parse; raises on failure (ImportError or parse error)., Lower tuple = preferred. Used by min() to break ties among same-tier candidates., Extract the most actionable valid JSON object from free-form model output., _richness_key(), _try_json5(), _check_contradiction() (+34 more)

### Community 8 - "Schema Gate"
Cohesion: 0.08
Nodes (42): _build_alias_map(), _check_query(), check_schema_compliance(), _known_cols_by_table(), Schema-aware SQL validator: unknown columns, unverified literals, double-key JOI, Check queries against schema. Returns first error string or None if all pass., Return {alias_lower: table_name_lower} from FROM and JOIN clauses., Check queries against schema. Returns first error string or None if all pass. (+34 more)

### Community 9 - "SQL Security"
Cohesion: 0.07
Nodes (38): check_grounding_refs(), check_learn_output(), check_path_access(), check_retry_loop(), check_sql_queries(), check_where_literals(), _has_where_clause(), _is_select() (+30 more)

### Community 10 - "Reference Bug Tests"
Cohesion: 0.06
Nodes (36): _obj_mutation_tool(), Return the mutation tool name if obj is a write/delete/exec action, else None., _make_pre(), Bug t21: unhandled exception in for-loop must call vm.answer exactly once., Bug t21: unhandled exception in for-loop must call vm.answer exactly once., Bug t21: 'function' field is a string — must not crash, must return None., Bug t21: 'function' field is a string — must not crash, must return None., Normal case: 'function' is a dict with a valid mutation tool name. (+28 more)

### Community 11 - "Prompt Loading"
Cohesion: 0.1
Nodes (30): build_system_prompt(), _load_all(), load_prompt(), load_task_blocks(), Prompt loading utilities., Return prompt block by file stem name. Returns '' if not found., Return prompt block by file stem name. Returns '' if not found., Return list of prompt block stems for given task_type from data/config/task_bloc (+22 more)

### Community 12 - "Optimization Tests (removed)"
Cohesion: 0.07
Nodes (32): _mock_entry(), _mock_scenario(), Valid LLM response → MockScenario., LLM returns None → None., LLM returns non-JSON → None., LLM returns JSON missing required fields → None., _generate_mock_scenario returns None → score=1.0 (fail-open)., candidate passes + baseline fails → score=1.0. (+24 more)

### Community 13 - "BitGN Connect/Harness"
Cohesion: 0.06
Nodes (4): ConnectClient, Minimal Connect RPC client using JSON protocol over httpx., EcomRuntimeClientSync, PcmRuntimeClientSync

### Community 14 - "Resolve Phase (stub)"
Cohesion: 0.12
Nodes (29): _all_values(), _build_resolve_system(), _exec_sql(), _first_value(), Resolve phase: confirm task identifiers against DB before pipeline cycles., Deprecated shim — kept for test backward compat. Use _all_values., Resolve identifiers in task_text against DB. Returns confirmed_values or {} on f, _run() (+21 more)

### Community 15 - "Module Group 15"
Cohesion: 0.09
Nodes (14): Load SQL planning rules from data/rules/ (one YAML file per rule)., RulesLoader, _load_all_rules(), test_all_expected_rule_ids_present(), test_all_rules_verified_and_phase_sql_plan(), test_rules_loader_returns_all_verified(), test_sql015_scoped_to_products(), test_sql017_kinds_table_and_products_fallback() (+6 more)

### Community 16 - "Module Group 16"
Cohesion: 0.09
Nodes (30): AGENTS.MD, build_system_prompt, call_llm_raw, data/prompts/*.md, data/prompts/optimized/, data/rules/*.yaml, data/security/*.yaml, data/eval_log.jsonl (+22 more)

### Community 17 - "Module Group 17"
Cohesion: 0.1
Nodes (19): agents_md_index, bitgn/ (protobuf stubs), HarnessServiceClientSync, _log_stats(), main(), _print_table_header(), _print_table_row(), Execute one benchmark trial. (+11 more)

### Community 18 - "Module Group 18"
Cohesion: 0.12
Nodes (22): _MockResult, MockVM, test_answer_captures_last_answer(), test_answer_does_not_raise(), test_exec_clamps_to_last_result(), test_exec_cycles_through_results(), test_exec_empty_mock_results_returns_empty_string(), test_exec_explain_case_insensitive() (+14 more)

### Community 19 - "Module Group 19"
Cohesion: 0.19
Nodes (27): _base_patches(), _eval_entry(), Accepted (mock_score >= 1.0) → file written., Rejected (mock_score < 1.0) → no file written., --dry-run skips validate_mock entirely., Auto-apply: rule is written directly without calling validate_recommendation., Accepted (score doesn't regress) → file written., --dry-run prints intent but writes nothing. (+19 more)

### Community 20 - "Module Group 20"
Cohesion: 0.11
Nodes (24): call_llm_raw(), _call_raw_single_model(), get_anthropic_model_id(), get_provider(), get_response_format(), _get_static_hint(), is_claude_code_model(), is_claude_model() (+16 more)

### Community 21 - "Module Group 21"
Cohesion: 0.12
Nodes (26): agent/cc_client.py, _call_raw_single_model, _resolve_model_for_phase, call_llm_raw, get_provider, probe_structured_output, agent/llm.py, LLM routing (provider prefix tier system) (+18 more)

### Community 22 - "Module Group 22"
Cohesion: 0.15
Nodes (20): _check_tdd_antipatterns(), Subprocess test runner for TDD pipeline., Run test_code in isolated subprocess. Returns (passed, error_message)., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., run_tests(), False-negative: regex does not match unescaped opposite-quote inside literal. Ac, test_aggregate_antipattern_force_fail() (+12 more)

### Community 23 - "Module Group 23"
Cohesion: 0.19
Nodes (20): _answer_json(), _make_exec_result(), _make_pre(), sql_tests fail → LEARN + SQL_PLAN retry (_skip_sql=False) → sql_tests pass → ANS, answer_tests fail → LEARN + _skip_sql=True → next cycle skips SQL, retries ANSWE, TEST_GEN returns garbage → vm.answer(OUTCOME_NONE_CLARIFICATION), SQL never runs, TEST_GEN LLM call MUST occur even without SDD_ENABLED env var., TDD_ENABLED=0 → pipeline identical to current; run_tests never called. (+12 more)

### Community 24 - "Module Group 24"
Cohesion: 0.16
Nodes (12): Minimal orchestrator for ecom benchmark., Execute a single benchmark task., run_agent(), _make_vm_mock(), run_agent forwards injection params + task_id to run_pipeline., run_agent calls run_pipeline for all tasks., run_agent() result must not contain builder_*/contract_*/eval_rejection_count fi, run_agent() always returns a plain dict (public API unchanged). (+4 more)

### Community 25 - "Module Group 25"
Cohesion: 0.12
Nodes (8): _system_as_str flattens list[dict] blocks to newline-joined text., _system_as_str flattens list[dict] blocks to newline-joined text., _system_as_str returns str unchanged., _system_as_str returns str unchanged., _OLLAMA_KEY attribute must exist on module and use or-fallback logic., test_ollama_key_constant_exists_and_fallback(), test_system_as_str_from_blocks(), test_system_as_str_passthrough_str()

### Community 26 - "Module Group 26"
Cohesion: 0.17
Nodes (10): _make_harness_mocks(), _cluster_recs returns fewer items when LLM merges duplicates., _cluster_recs returns fewer items when LLM merges duplicates., _cluster_recs returns fewer items when LLM merges duplicates., _cluster_recs returns fewer items when LLM merges duplicates., test_cluster_recs_merges_duplicates(), test_validate_recommendation_accepted(), test_validate_recommendation_no_baseline() (+2 more)

### Community 27 - "Module Group 27"
Cohesion: 0.23
Nodes (12): _build_env(), cc_complete(), _collect_stdout(), _parse_envelope(), Claude Code tier — spawn iclaude CLI as stateless LLM.  Bypasses applied (all re, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str (+4 more)

### Community 28 - "Module Group 28"
Cohesion: 0.27
Nodes (10): parse_agents_md(), Parse AGENTS.MD into {section_name: [lines]} for each ## section., test_empty_section_has_empty_lines(), test_empty_string_returns_empty_dict(), test_h1_heading_not_treated_as_section(), test_leading_content_before_first_section_ignored(), test_multiple_sections(), test_no_sections_returns_empty_dict() (+2 more)

### Community 29 - "Module Group 29"
Cohesion: 0.18
Nodes (4): Raw hierarchical paths stored verbatim in sku_refs., AUTO_REFS block must show full paths — LLM copies them verbatim to grounding_ref, test_build_answer_user_msg_preserves_hierarchical_ref(), test_extract_sku_refs_hierarchical_path_preserved()

### Community 30 - "Module Group 30"
Cohesion: 0.22
Nodes (9): _cluster_recs returns items as-is when LLM call fails., _cluster_recs returns items as-is when LLM call fails., _cluster_recs returns items as-is when LLM call fails., All hashes in a cluster group are marked processed after writing the representat, All hashes in a cluster group are marked processed after writing the representat, _cluster_recs returns items as-is when LLM call fails., All hashes in a cluster group are marked processed after writing the representat, test_cluster_recs_all_hashes_marked_on_write() (+1 more)

### Community 31 - "Module Group 31"
Cohesion: 0.25
Nodes (8): data/eval_log.jsonl, data/.eval_optimizations_processed (processed hashes), MODEL_EVALUATOR env var, prompt_optimization channel → data/prompts/optimized/, scripts/propose_optimizations.py, rule_optimization channel → data/rules/sql-NNN.yaml, security_optimization channel → data/security/sec-NNN.yaml, Three optimization channels (rule, security, prompt)

### Community 32 - "Module Group 32"
Cohesion: 0.33
Nodes (5): Verify main.py creates/closes TraceLogger and calls log_header + log_task_result, main.log must contain stats rows but NOT pipeline cycle lines., After _run_single_task: .jsonl created, no .log file, log_header + log_task_resu, test_main_log_contains_only_stats(), test_run_single_task_creates_jsonl_and_removes_log()

### Community 35 - "Module Group 35"
Cohesion: 0.33
Nodes (6): test_all_cycles_exhausted, test_happy_path, test_learn_appends_rule_to_ctx, test_learn_ctx_accumulates, test_learn_skip_leaves_ctx_unchanged, test_schema_fail_triggers_learn_then_retry

### Community 36 - "Module Group 36"
Cohesion: 0.33
Nodes (6): test_cte_with_where_passes, test_no_outer_where_blocked, test_subquery_outer_has_where_passes, test_subquery_with_where_passes, test_where_in_double_quoted_identifier_not_confused, test_where_in_string_literal_not_confused

### Community 38 - "Module Group 38"
Cohesion: 0.6
Nodes (5): check_grounding_refs, clean_refs, p.path SQL column, sku_refs, t16 grounding refs bug

### Community 39 - "Module Group 39"
Cohesion: 0.4
Nodes (5): Ensure propose_optimizations imports rules text from knowledge_loader, not its o, Ensure propose_optimizations imports rules text from knowledge_loader, not its o, Ensure propose_optimizations imports rules text from knowledge_loader, not its o, Ensure propose_optimizations imports rules text from knowledge_loader, not its o, test_main_uses_knowledge_loader_for_rules()

### Community 40 - "Module Group 40"
Cohesion: 0.4
Nodes (5): Rule with contradiction is not written and its hashes are not marked processed., Rule with contradiction is not written and its hashes are not marked processed., Rule with contradiction is not written and its hashes are not marked processed., Rule with contradiction is not written and its hashes are not marked processed., test_contradiction_blocks_write()

### Community 41 - "Module Group 41"
Cohesion: 0.4
Nodes (5): Second rule synthesis receives updated rules_md after first write., Second rule synthesis receives updated rules_md after first write., Second rule synthesis receives updated rules_md after first write., Second rule synthesis receives updated rules_md after first write., test_rules_md_refreshed_between_writes()

### Community 42 - "Module Group 42"
Cohesion: 0.4
Nodes (5): Returns conflict string when LLM finds contradiction., Returns conflict string when LLM finds contradiction., Returns conflict string when LLM finds contradiction., Returns conflict string when LLM finds contradiction., test_check_contradiction_returns_string_on_conflict()

### Community 43 - "Module Group 43"
Cohesion: 0.4
Nodes (5): Returns None when LLM says OK., Returns None when LLM says OK., Returns None when LLM says OK., Returns None when LLM says OK., test_check_contradiction_returns_none_on_ok()

### Community 44 - "Module Group 44"
Cohesion: 0.4
Nodes (5): test_learn_output_agents_md_anchor_defaults_none, test_learn_output_deactivate_list, test_learn_output_new_fields_defaults, test_learn_output_skip_flag, test_learn_output_valid

### Community 45 - "Module Group 45"
Cohesion: 0.5
Nodes (4): Same rec text for same task_id validated only once., Same rec text for same task_id synthesized only once., Same rec text for same task_id validated only once., test_content_hash_dedup_per_task()

### Community 47 - "Module Group 47"
Cohesion: 0.67
Nodes (3): main(), _migrate_file(), Return True if migrated, False if already in new format or skipped.

### Community 48 - "Module Group 48"
Cohesion: 0.5
Nodes (4): test_build_system_prompt_not_imported, test_lookup_routes_to_pipeline, test_run_agent_no_dead_stats, test_write_wiki_fragment_removed

### Community 50 - "Module Group 50"
Cohesion: 0.67
Nodes (3): test_apply_learn_diff_adds_first_entry, test_apply_learn_diff_deactivates_entries, test_apply_learn_diff_id_monotonic

### Community 51 - "Module Group 51"
Cohesion: 0.67
Nodes (3): test_select_count_without_where_blocked, test_select_with_where_passes, test_select_without_where_blocked

## Knowledge Gaps
- **386 isolated node(s):** `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Return prompt block by file stem name. Returns '' if not found.`, `Assemble system prompt from file-based blocks for the given task type.`, `Shared loaders for existing rules/security/prompts content.` (+381 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `HarnessServiceClientSync` connect `Module Group 17` to `BitGN Connect/Harness`, `JSON Extraction`?**
  _High betweenness centrality (0.149) - this node is a cross-community bridge._
- **Why does `_run_single_task()` connect `Module Group 17` to `Trace Logging`?**
  _High betweenness centrality (0.142) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `main` (e.g. with `test_existing_security_text_returns_id_message` and `test_existing_prompts_text_returns_full_content`) actually correct?**
  _`main` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `TraceLogger` (e.g. with `_run_single_task()` and `_collect_trace_records()`) actually correct?**
  _`TraceLogger` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `check_schema_compliance()` (e.g. with `test_valid_query_passes()` and `test_unknown_column_detected()`) actually correct?**
  _`check_schema_compliance()` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `load_prompt()` (e.g. with `_build_static_system()` and `_build_resolve_system()`) actually correct?**
  _`load_prompt()` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Return prompt block by file stem name. Returns '' if not found.` to the rest of the system?**
  _386 weakly-connected nodes found - possible documentation gaps or missing edges._