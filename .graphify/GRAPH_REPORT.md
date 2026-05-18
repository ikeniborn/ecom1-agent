# Graph Report - .  (2026-05-18)

## Corpus Check
- Corpus is ~29,892 words - fits in a single context window. You may not need a graph.

## Summary
- 1204 nodes · 2102 edges · 72 communities (63 shown, 9 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 389 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_SQL Security Checks|SQL Security Checks]]
- [[_COMMUNITY_Contract & Evaluator Models|Contract & Evaluator Models]]
- [[_COMMUNITY_Prephase & Schema Digest|Prephase & Schema Digest]]
- [[_COMMUNITY_Trace Logging|Trace Logging]]
- [[_COMMUNITY_JSON Extraction|JSON Extraction]]
- [[_COMMUNITY_Optimization Pipeline|Optimization Pipeline]]
- [[_COMMUNITY_Schema Gate|Schema Gate]]
- [[_COMMUNITY_Prompt Assembler Core|Prompt Assembler Core]]
- [[_COMMUNITY_Pipeline Test Helpers|Pipeline Test Helpers]]
- [[_COMMUNITY_Prompt Loading|Prompt Loading]]
- [[_COMMUNITY_LLM & Pipeline Core|LLM & Pipeline Core]]
- [[_COMMUNITY_Evaluator|Evaluator]]
- [[_COMMUNITY_Optimization Test Mocks|Optimization Test Mocks]]
- [[_COMMUNITY_Pipeline Discovery & Resolve|Pipeline Discovery & Resolve]]
- [[_COMMUNITY_Value Resolution|Value Resolution]]
- [[_COMMUNITY_Rules Loader|Rules Loader]]
- [[_COMMUNITY_Claude Client Config|Claude Client Config]]
- [[_COMMUNITY_Mock VM|Mock VM]]
- [[_COMMUNITY_Bitgn Harness|Bitgn Harness]]
- [[_COMMUNITY_Optimization Test Patches|Optimization Test Patches]]
- [[_COMMUNITY_Test Runner (TDD)|Test Runner (TDD)]]
- [[_COMMUNITY_TDD Test Helpers|TDD Test Helpers]]
- [[_COMMUNITY_Answer Phase|Answer Phase]]
- [[_COMMUNITY_Core Agent Loop|Core Agent Loop]]
- [[_COMMUNITY_CC Client|CC Client]]
- [[_COMMUNITY_LLM Provider Routing|LLM Provider Routing]]
- [[_COMMUNITY_Prompt Assembler Learn Ctx|Prompt Assembler Learn Ctx]]
- [[_COMMUNITY_Optimization Test Scenarios|Optimization Test Scenarios]]
- [[_COMMUNITY_ECOM Runtime Client|ECOM Runtime Client]]
- [[_COMMUNITY_PCM Runtime Client|PCM Runtime Client]]
- [[_COMMUNITY_Pipeline Models Config|Pipeline Models Config]]
- [[_COMMUNITY_AGENTS.MD Parser|AGENTS.MD Parser]]
- [[_COMMUNITY_Output Models|Output Models]]
- [[_COMMUNITY_Orchestrator Tests|Orchestrator Tests]]
- [[_COMMUNITY_Pipeline Phase Data|Pipeline Phase Data]]
- [[_COMMUNITY_LLM Rationale Nodes|LLM Rationale Nodes]]
- [[_COMMUNITY_LLM Module Tests|LLM Module Tests]]
- [[_COMMUNITY_Eval Log & Rules Data|Eval Log & Rules Data]]
- [[_COMMUNITY_LLM Capability Probing|LLM Capability Probing]]
- [[_COMMUNITY_Optimization Test Rationale A|Optimization Test Rationale A]]
- [[_COMMUNITY_Anthropic LLM Client|Anthropic LLM Client]]
- [[_COMMUNITY_Connect Client|Connect Client]]
- [[_COMMUNITY_README Docs|README Docs]]
- [[_COMMUNITY_Trace Tests|Trace Tests]]
- [[_COMMUNITY_Orchestrator|Orchestrator]]
- [[_COMMUNITY_Knowledge Loader|Knowledge Loader]]
- [[_COMMUNITY_Optimization Test Rationale B|Optimization Test Rationale B]]
- [[_COMMUNITY_Optimization Test Rationale C|Optimization Test Rationale C]]
- [[_COMMUNITY_Optimization Test Rationale D|Optimization Test Rationale D]]
- [[_COMMUNITY_Optimization Test Rationale E|Optimization Test Rationale E]]
- [[_COMMUNITY_Optimization Test Rationale F|Optimization Test Rationale F]]
- [[_COMMUNITY_Optimization Test Rationale G|Optimization Test Rationale G]]
- [[_COMMUNITY_Task Grounding Refs|Task Grounding Refs]]
- [[_COMMUNITY_LLM Cache|LLM Cache]]
- [[_COMMUNITY_LLM Response Format|LLM Response Format]]
- [[_COMMUNITY_Optimization Test Rationale H|Optimization Test Rationale H]]
- [[_COMMUNITY_LLM Routing Design|LLM Routing Design]]
- [[_COMMUNITY_Bitgn Proto|Bitgn Proto]]
- [[_COMMUNITY_CLAUDE.md Root|CLAUDE.md Root]]
- [[_COMMUNITY_CLAUDE.md Agent|CLAUDE.md Agent]]
- [[_COMMUNITY_Models JSON Config|Models JSON Config]]

## God Nodes (most connected - your core abstractions)
1. `run_pipeline()` - 68 edges
2. `main` - 36 edges
3. `TraceLogger` - 34 edges
4. `check_schema_compliance()` - 31 edges
5. `load_prompt()` - 29 edges
6. `check_sql_queries()` - 22 edges
7. `_write_eval_log()` - 22 edges
8. `_eval_entry()` - 22 edges
9. `_setup()` - 22 edges
10. `_base_patches()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `get_trace()` --calls--> `test_get_trace_none_by_default()`  [INFERRED]
  agent/trace.py → tests/test_trace.py
- `agent/pipeline.py` --uses--> `prompt.py:load_prompt()`  [INFERRED]
  /home/ikeniborn/Documents/Project/ecom1-agent/CLAUDE.md → agent/CLAUDE.md
- `_run_single_task()` --calls--> `TraceLogger`  [INFERRED]
  main.py → agent/trace.py
- `_run_single_task()` --calls--> `set_trace()`  [INFERRED]
  main.py → agent/trace.py
- `_run_single_task()` --calls--> `run_agent()`  [INFERRED]
  main.py → agent/orchestrator.py

## Communities (72 total, 9 thin omitted)

### Community 0 - "SQL Security Checks"
Cohesion: 0.05
Nodes (55): check_grounding_refs(), check_learn_output(), check_path_access(), check_retry_loop(), check_sql_queries(), check_where_literals(), _has_where_clause(), _is_select() (+47 more)

### Community 1 - "Contract & Evaluator Models"
Cohesion: 0.07
Nodes (57): Contract, ContractRound, EvaluatorResponse, ExecutorProposal, _compute_eval_metrics(), Compute agents_md_coverage and schema_grounding. Returns dict with both floats., Compute agents_md_coverage and schema_grounding. Returns dict with both floats., AnswerOutput (+49 more)

### Community 2 - "Prephase & Schema Digest"
Cohesion: 0.05
Nodes (62): _build_schema_digest(), _determine_task_type(), _exec_sql_text(), _format_schema_digest(), _infer_role(), merge_schema_from_sqlite_results(), _parse_csv_rows(), PrephaseResult (+54 more)

### Community 3 - "Trace Logging"
Cohesion: 0.07
Nodes (38): set_trace(), TraceLogger, _answer_json(), _collect_trace_records(), _exec_ok(), _make_pre(), Verify pipeline instruments TraceLogger at all required points., gate_check record for schema gate written every cycle. (+30 more)

### Community 4 - "JSON Extraction"
Cohesion: 0.07
Nodes (46): _extract_json_from_text(), JSON extraction from free-form LLM text output.  Public API:   _obj_mutation_too, Try json5 parse; raises on failure (ImportError or parse error)., Lower tuple = preferred. Used by min() to break ties among same-tier candidates., Extract the most actionable valid JSON object from free-form model output., _richness_key(), _try_json5(), call_llm_raw() (+38 more)

### Community 5 - "Optimization Pipeline"
Cohesion: 0.05
Nodes (48): Optimization Pipeline Design, call_llm_raw_cluster, _check_contradiction, _cluster_recs, _dedup_by_content_per_task, _entry_hash, _load_model_cfg, _load_processed (+40 more)

### Community 6 - "Schema Gate"
Cohesion: 0.08
Nodes (42): _build_alias_map(), _check_query(), check_schema_compliance(), _known_cols_by_table(), Schema-aware SQL validator: unknown columns, unverified literals, double-key JOI, Check queries against schema. Returns first error string or None if all pass., Return {alias_lower: table_name_lower} from FROM and JOIN clauses., Check queries against schema. Returns first error string or None if all pass. (+34 more)

### Community 7 - "Prompt Assembler Core"
Cohesion: 0.05
Nodes (41): _obj_mutation_tool(), Return the mutation tool name if obj is a write/delete/exec action, else None., AssembledPrompt, _mock_assemble(), _mock_assemble(), _make_pre(), _mock_assemble(), Bug t21: unhandled exception in for-loop must call vm.answer exactly once. (+33 more)

### Community 8 - "Pipeline Test Helpers"
Cohesion: 0.1
Nodes (39): _answer_json(), _make_exec_result(), _make_pre(), 3 cycles all fail → OUTCOME_NONE_CLARIFICATION without ANSWER LLM call., All cycles fail → clarification outcome, no eval_thread (EVAL_ENABLED=0)., DDL query → security gate blocks → LEARN → retry → success., learn_ctx grows across cycles; each SDD user_msg contains all prior rules., LEARN updates session_rules but does not write rule files (append_rule removed). (+31 more)

### Community 9 - "Prompt Loading"
Cohesion: 0.1
Nodes (30): build_system_prompt(), _load_all(), load_prompt(), load_task_blocks(), Prompt loading utilities., Return prompt block by file stem name. Returns '' if not found., Return prompt block by file stem name. Returns '' if not found., Return list of prompt block stems for given task_type from data/config/task_bloc (+22 more)

### Community 10 - "LLM & Pipeline Core"
Cohesion: 0.12
Nodes (32): Return per-phase model from env, or default_model if not configured., _resolve_model_for_phase(), _append_eval_log(), _build_learn_user_msg(), _build_sdd_user_msg(), _build_sql_user_msg(), _build_static_system(), _call_llm_phase() (+24 more)

### Community 11 - "Evaluator"
Cohesion: 0.1
Nodes (32): _append_log(), _build_eval_system(), EvalInput, Post-execution pipeline evaluator. Fail-open: any exception returns None., Evaluate pipeline trace. Returns PipelineEvalOutput or None on any failure., Evaluate pipeline trace. Returns PipelineEvalOutput or None on any failure., _run(), run_evaluator() (+24 more)

### Community 12 - "Optimization Test Mocks"
Cohesion: 0.08
Nodes (29): _mock_entry(), _mock_scenario(), Valid LLM response → MockScenario., LLM returns None → None., LLM returns non-JSON → None., LLM returns JSON missing required fields → None., _generate_mock_scenario returns None → score=1.0 (fail-open)., candidate passes + baseline fails → score=1.0. (+21 more)

### Community 13 - "Pipeline Discovery & Resolve"
Cohesion: 0.07
Nodes (29): _extract_discovery_results(), _format_confirmed_values(), Update confirmed_values in-place from DISTINCT query results., Update confirmed_values in-place from DISTINCT query results., Compat stub — discovery phase removed from SDD pipeline., Compat stub — confirmed_values removed from SDD pipeline., When compacted_ctx is [], _run_learn falls back to append., When compacted_ctx is None, _run_learn falls back to append. (+21 more)

### Community 14 - "Value Resolution"
Cohesion: 0.12
Nodes (29): _all_values(), _build_resolve_system(), _exec_sql(), _first_value(), Resolve phase: confirm task identifiers against DB before pipeline cycles., Deprecated shim — kept for test backward compat. Use _all_values., Resolve identifiers in task_text against DB. Returns confirmed_values or {} on f, _run() (+21 more)

### Community 15 - "Rules Loader"
Cohesion: 0.08
Nodes (25): Load SQL planning rules from data/rules/ (one YAML file per rule)., RulesLoader, _build_static_system('sql_plan') includes security gates; 'learn' does not., _build_static_system does not include IN-SESSION RULE (those go to user_msg)., _build_static_system returns list[dict], last block has cache_control., When injected_prompt_addendum is non-empty, appends to guide block., When injected_prompt_addendum is empty, no injection section., _build_static_system injects AGENT CONTEXT block for sql_plan phase when agent_i (+17 more)

### Community 16 - "Claude Client Config"
Cohesion: 0.09
Nodes (30): AGENTS.MD, build_system_prompt, call_llm_raw, data/prompts/*.md, data/prompts/optimized/, data/rules/*.yaml, data/security/*.yaml, data/eval_log.jsonl (+22 more)

### Community 17 - "Mock VM"
Cohesion: 0.12
Nodes (22): _MockResult, MockVM, test_answer_captures_last_answer(), test_answer_does_not_raise(), test_exec_clamps_to_last_result(), test_exec_cycles_through_results(), test_exec_empty_mock_results_returns_empty_string(), test_exec_explain_case_insensitive() (+14 more)

### Community 18 - "Bitgn Harness"
Cohesion: 0.1
Nodes (19): agents_md_index, bitgn/ (protobuf stubs), HarnessServiceClientSync, _log_stats(), main(), _print_table_header(), _print_table_row(), Execute one benchmark trial. (+11 more)

### Community 19 - "Optimization Test Patches"
Cohesion: 0.19
Nodes (27): _base_patches(), _eval_entry(), Accepted (mock_score >= 1.0) → file written., Rejected (mock_score < 1.0) → no file written., --dry-run skips validate_mock entirely., Auto-apply: rule is written directly without calling validate_recommendation., Accepted (score doesn't regress) → file written., --dry-run prints intent but writes nothing. (+19 more)

### Community 20 - "Test Runner (TDD)"
Cohesion: 0.15
Nodes (20): _check_tdd_antipatterns(), Subprocess test runner for TDD pipeline., Run test_code in isolated subprocess. Returns (passed, error_message)., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., run_tests(), False-negative: regex does not match unescaped opposite-quote inside literal. Ac, test_aggregate_antipattern_force_fail() (+12 more)

### Community 21 - "TDD Test Helpers"
Cohesion: 0.21
Nodes (20): _answer_json(), _make_exec_result(), _make_pre(), sql_tests fail → LEARN + SQL_PLAN retry (_skip_sql=False) → sql_tests pass → ANS, answer_tests fail → LEARN + _skip_sql=True → next cycle skips SQL, retries ANSWE, TEST_GEN returns garbage → vm.answer(OUTCOME_NONE_CLARIFICATION), SQL never runs, TEST_GEN LLM call MUST occur even without SDD_ENABLED env var., TDD_ENABLED=0 → pipeline identical to current; run_tests never called. (+12 more)

### Community 22 - "Answer Phase"
Cohesion: 0.19
Nodes (14): _build_answer_user_msg(), _extract_sku_refs(), Extract catalogue paths from SQL results. Uses 'path' column when present,     f, Extract catalogue paths from SQL results. Uses 'path' column when present,     f, Raw hierarchical paths stored verbatim in sku_refs., AUTO_REFS block must show full paths — LLM copies them verbatim to grounding_ref, test_build_answer_user_msg_no_refs(), test_build_answer_user_msg_preserves_hierarchical_ref() (+6 more)

### Community 23 - "Core Agent Loop"
Cohesion: 0.15
Nodes (15): /AGENTS.MD (vault rules), check_retry_loop (anti-infinite-loop guard), llm.py:call_llm_raw(), loop.py / dispatch.py removed, orchestrator.py:run_agent(), Pipeline Phase Execution Order, agent/pipeline.py, prephase.py:run_prephase() (+7 more)

### Community 24 - "CC Client"
Cohesion: 0.23
Nodes (12): _build_env(), cc_complete(), _collect_stdout(), _parse_envelope(), Claude Code tier — spawn iclaude CLI as stateless LLM.  Bypasses applied (all re, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str (+4 more)

### Community 25 - "LLM Provider Routing"
Cohesion: 0.19
Nodes (12): get_provider(), is_claude_code_model(), is_claude_model(), is_ollama_model(), True for Ollama-format models (name:tag, no slash).     Examples: qwen3.5:9b, de, True for Ollama-format models (name:tag, no slash).     Examples: qwen3.5:9b, de, True for claude-code/* aliases routed to iclaude subprocess., True for claude-code/* aliases routed to iclaude subprocess. (+4 more)

### Community 26 - "Prompt Assembler Learn Ctx"
Cohesion: 0.22
Nodes (11): assemble_prompt(), _build_sources(), clear_learned_ctx(), load_learned_ctx(), LLM-assembler: builds unified_context from all prompt sources per pipeline cycle, Call LLM assembler to produce unified_context from all sources., Load persisted learn_ctx from prior failed run, or [] if none., Delete data/learned/{task_id}.yaml on pipeline success. (+3 more)

### Community 27 - "Optimization Test Scenarios"
Cohesion: 0.21
Nodes (8): _make_harness_mocks(), test_existing_prompts_text_empty_dir(), test_existing_security_text_returns_id_message(), test_existing_security_text_skips_invalid(), test_validate_recommendation_accepted(), test_validate_recommendation_no_baseline(), test_validate_recommendation_rejected(), test_validate_recommendation_task_not_in_trials()

### Community 30 - "Pipeline Models Config"
Cohesion: 0.19
Nodes (13): AnswerOutput (Pydantic model), assemble_prompt() function, data/config/task_blocks.yaml, data/prompts/*.md, data/security/*.yaml, learn_ctx (in-session error learning), LearnOutput (Pydantic model), ANSWER phase (+5 more)

### Community 31 - "AGENTS.MD Parser"
Cohesion: 0.27
Nodes (10): parse_agents_md(), Parse AGENTS.MD into {section_name: [lines]} for each ## section., test_empty_section_has_empty_lines(), test_empty_string_returns_empty_dict(), test_h1_heading_not_treated_as_section(), test_leading_content_before_first_section_ignored(), test_multiple_sections(), test_no_sections_returns_empty_dict() (+2 more)

### Community 32 - "Output Models"
Cohesion: 0.18
Nodes (12): AnswerOutput, agent/evaluator.py, JSON extraction priority (mutation > read), agent/json_extract.py, LearnOutput, agent/models.py, PipelineEvalOutput, SDD phase (+4 more)

### Community 33 - "Orchestrator Tests"
Cohesion: 0.24
Nodes (7): _make_vm_mock(), run_agent calls run_pipeline for all tasks., run_agent() result must not contain builder_*/contract_*/eval_rejection_count fi, run_agent() always returns a plain dict (public API unchanged)., test_lookup_routes_to_pipeline(), test_run_agent_no_dead_stats(), test_run_agent_returns_dict()

### Community 34 - "Pipeline Phase Data"
Cohesion: 0.2
Nodes (11): data/learned/{task_id}.yaml, ASSEMBLE phase, EXECUTE phase, SCHEMA CHECK phase, TDD phase, VALIDATE phase, agent/prompt_assembler.py, run_pipeline() function (+3 more)

### Community 35 - "LLM Rationale Nodes"
Cohesion: 0.2
Nodes (10): Flatten system prompt blocks to plain string for non-caching tiers., Flatten system prompt blocks to plain string for non-caching tiers., Flatten system prompt blocks to plain string for non-caching tiers., _system_as_str(), _system_as_str flattens list[dict] blocks to newline-joined text., _system_as_str flattens list[dict] blocks to newline-joined text., _system_as_str returns str unchanged., _system_as_str returns str unchanged. (+2 more)

### Community 37 - "Eval Log & Rules Data"
Cohesion: 0.2
Nodes (8): data/eval_log.jsonl, data/rules/*.yaml, eval_log written only on success, _rules_loader_cache / _security_gates_cache (module-level), scripts/propose_optimizations.py, rules_loader.py:RulesLoader, agent/rules_loader.py, Reset module-level caches between tests.

### Community 38 - "LLM Capability Probing"
Cohesion: 0.22
Nodes (9): _get_static_hint(), probe_structured_output(), Persist current cache to disk. Non-critical — failure is silently ignored., Persist current cache to disk. Non-critical — failure is silently ignored., Persist current cache to disk. Non-critical — failure is silently ignored., Detect if model supports response_format. Returns 'json_object' or 'none'.     C, Detect if model supports response_format. Returns 'json_object' or 'none'.     C, Detect if model supports response_format. Returns 'json_object' or 'none'.     C (+1 more)

### Community 39 - "Optimization Test Rationale A"
Cohesion: 0.22
Nodes (9): _cluster_recs returns items as-is when LLM call fails., _cluster_recs returns items as-is when LLM call fails., _cluster_recs returns items as-is when LLM call fails., All hashes in a cluster group are marked processed after writing the representat, All hashes in a cluster group are marked processed after writing the representat, _cluster_recs returns items as-is when LLM call fails., All hashes in a cluster group are marked processed after writing the representat, test_cluster_recs_all_hashes_marked_on_write() (+1 more)

### Community 40 - "Anthropic LLM Client"
Cohesion: 0.25
Nodes (8): _call_raw_single_model(), get_anthropic_model_id(), Lightweight LLM call with 3-tier routing and transient-error retry.     Returns, Lightweight LLM call with 3-tier routing and transient-error retry.     Returns, Lightweight LLM call with 3-tier routing and transient-error retry.     Returns, Map alias (e.g. 'anthropic/claude-haiku-4.5') to Anthropic API model ID., Map alias (e.g. 'anthropic/claude-haiku-4.5') to Anthropic API model ID., Map alias (e.g. 'anthropic/claude-haiku-4.5') to Anthropic API model ID.

### Community 42 - "README Docs"
Cohesion: 0.25
Nodes (8): data/eval_log.jsonl, data/.eval_optimizations_processed (processed hashes), MODEL_EVALUATOR env var, prompt_optimization channel → data/prompts/optimized/, scripts/propose_optimizations.py, rule_optimization channel → data/rules/sql-NNN.yaml, security_optimization channel → data/security/sec-NNN.yaml, Three optimization channels (rule, security, prompt)

### Community 43 - "Trace Tests"
Cohesion: 0.33
Nodes (5): Verify main.py creates/closes TraceLogger and calls log_header + log_task_result, main.log must contain stats rows but NOT pipeline cycle lines., After _run_single_task: .jsonl created, no .log file, log_header + log_task_resu, test_main_log_contains_only_stats(), test_run_single_task_creates_jsonl_and_removes_log()

### Community 46 - "Orchestrator"
Cohesion: 0.33
Nodes (5): Minimal orchestrator for ecom benchmark., Execute a single benchmark task., run_agent(), run_agent forwards injection params + task_id to run_pipeline., test_run_agent_passes_injection_params()

### Community 48 - "Optimization Test Rationale B"
Cohesion: 0.4
Nodes (5): Rule with contradiction is not written and its hashes are not marked processed., Rule with contradiction is not written and its hashes are not marked processed., Rule with contradiction is not written and its hashes are not marked processed., Rule with contradiction is not written and its hashes are not marked processed., test_contradiction_blocks_write()

### Community 49 - "Optimization Test Rationale C"
Cohesion: 0.4
Nodes (5): Returns conflict string when LLM finds contradiction., Returns conflict string when LLM finds contradiction., Returns conflict string when LLM finds contradiction., Returns conflict string when LLM finds contradiction., test_check_contradiction_returns_string_on_conflict()

### Community 50 - "Optimization Test Rationale D"
Cohesion: 0.4
Nodes (5): Second rule synthesis receives updated rules_md after first write., Second rule synthesis receives updated rules_md after first write., Second rule synthesis receives updated rules_md after first write., Second rule synthesis receives updated rules_md after first write., test_rules_md_refreshed_between_writes()

### Community 51 - "Optimization Test Rationale E"
Cohesion: 0.4
Nodes (5): Returns None when LLM says OK., Returns None when LLM says OK., Returns None when LLM says OK., Returns None when LLM says OK., test_check_contradiction_returns_none_on_ok()

### Community 52 - "Optimization Test Rationale F"
Cohesion: 0.4
Nodes (5): Ensure propose_optimizations imports rules text from knowledge_loader, not its o, Ensure propose_optimizations imports rules text from knowledge_loader, not its o, Ensure propose_optimizations imports rules text from knowledge_loader, not its o, Ensure propose_optimizations imports rules text from knowledge_loader, not its o, test_main_uses_knowledge_loader_for_rules()

### Community 53 - "Optimization Test Rationale G"
Cohesion: 0.4
Nodes (5): _cluster_recs returns fewer items when LLM merges duplicates., _cluster_recs returns fewer items when LLM merges duplicates., _cluster_recs returns fewer items when LLM merges duplicates., _cluster_recs returns fewer items when LLM merges duplicates., test_cluster_recs_merges_duplicates()

### Community 54 - "Task Grounding Refs"
Cohesion: 0.6
Nodes (5): check_grounding_refs, clean_refs, p.path SQL column, sku_refs, t16 grounding refs bug

### Community 55 - "LLM Cache"
Cohesion: 0.5
Nodes (4): _load_capability_cache(), Load persisted cache, filtering stale entries (>7 days)., Load persisted cache, filtering stale entries (>7 days)., Load persisted cache, filtering stale entries (>7 days).

### Community 56 - "LLM Response Format"
Cohesion: 0.5
Nodes (4): get_response_format(), Build response_format dict for the given mode, or None if mode='none'., Build response_format dict for the given mode, or None if mode='none'., Build response_format dict for the given mode, or None if mode='none'.

### Community 57 - "Optimization Test Rationale H"
Cohesion: 0.5
Nodes (4): Same rec text for same task_id validated only once., Same rec text for same task_id synthesized only once., Same rec text for same task_id validated only once., test_content_hash_dedup_per_task()

### Community 58 - "LLM Routing Design"
Cohesion: 0.5
Nodes (4): agent/cc_client.py, agent/llm.py, LLM routing (provider prefix tier system), models.json

## Knowledge Gaps
- **385 isolated node(s):** `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Return prompt block by file stem name. Returns '' if not found.`, `Assemble system prompt from file-based blocks for the given task type.`, `SGR LLM call: returns (parsed_output_or_None, sgr_trace_entry, tok_info).` (+380 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_pipeline()` connect `LLM & Pipeline Core` to `SQL Security Checks`, `Prephase & Schema Digest`, `Trace Logging`, `JSON Extraction`, `Schema Gate`, `Prompt Assembler Core`, `Pipeline Test Helpers`, `Prompt Loading`, `Pipeline Discovery & Resolve`, `Value Resolution`, `Orchestrator`, `Mock VM`, `Test Runner (TDD)`, `TDD Test Helpers`, `Answer Phase`, `Prompt Assembler Learn Ctx`?**
  _High betweenness centrality (0.364) - this node is a cross-community bridge._
- **Why does `_run_single_task()` connect `Bitgn Harness` to `LLM & Pipeline Core`, `Trace Logging`, `Orchestrator`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Why does `run_agent()` connect `Orchestrator` to `Orchestrator Tests`, `Prephase & Schema Digest`, `JSON Extraction`, `LLM & Pipeline Core`, `Bitgn Harness`, `ECOM Runtime Client`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Are the 34 inferred relationships involving `run_pipeline()` (e.g. with `run_resolve()` and `check_sql_queries()`) actually correct?**
  _`run_pipeline()` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `main` (e.g. with `test_existing_security_text_returns_id_message` and `test_existing_prompts_text_returns_full_content`) actually correct?**
  _`main` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `TraceLogger` (e.g. with `_run_single_task()` and `_collect_trace_records()`) actually correct?**
  _`TraceLogger` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `check_schema_compliance()` (e.g. with `test_valid_query_passes()` and `test_unknown_column_detected()`) actually correct?**
  _`check_schema_compliance()` has 25 INFERRED edges - model-reasoned connections that need verification._