# Graph Report - .  (2026-06-05)

## Corpus Check
- 0 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 673 nodes · 1076 edges · 47 communities (40 shown, 7 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 190 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]

## God Nodes (most connected - your core abstractions)
1. `run_pipeline()` - 34 edges
2. `TraceLogger` - 32 edges
3. `_AnswerGuard` - 29 edges
4. `MockVMSpy` - 21 edges
5. `check_sql_queries()` - 18 edges
6. `DesignOutput` - 18 edges
7. `MockVM` - 17 edges
8. `_design_with_template_refs()` - 17 edges
9. `HarnessServiceClientSync` - 14 edges
10. `EcomRuntimeClientSync` - 14 edges

## Surprising Connections (you probably didn't know these)
- `_run_single_task()` --calls--> `HarnessServiceClientSync`  [INFERRED]
  main.py → bitgn/harness_connect.py
- `_run_single_task()` --calls--> `run_agent()`  [INFERRED]
  main.py → agent/orchestrator.py
- `main()` --calls--> `learn_from_grader()`  [INFERRED]
  main.py → agent/pipeline.py
- `load_prompt()` --calls--> `test_load_prompt_unknown_returns_empty()`  [INFERRED]
  agent/prompt.py → tests/test_prompt_loader.py
- `load_prompt()` --calls--> `test_load_prompt_sdd_exists()`  [INFERRED]
  agent/prompt.py → tests/test_prompt_loader.py

## Communities (47 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.08
Nodes (46): DesignOutput, _AnswerGuard, _compact_learn_ctx(), Proxy passing all RPCs through to `_vm` while intercepting `answer`.      Also c, _design_with_template_refs(), _entries(), Real regression: template ['/proc/catalog', '$path'], script returned only '/pro, No $placeholder in template, but success_criteria mentions 'full path' → require (+38 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (44): Return per-phase model from env, or default_model if not configured., _resolve_model_for_phase(), _AnswerRefsError, _build_answer_user_msg(), _build_learn_user_msg(), _build_sdd_user_msg(), _call_llm_phase(), _csv_has_data() (+36 more)

### Community 2 - "Community 2"
Cohesion: 0.1
Nodes (22): get_trace(), Thread-local structured JSONL trace logger for per-task pipeline traces., set_trace(), TraceLogger, Execute one benchmark trial. Score is read later from SubmitRun.      `train_cyc, Execute one benchmark trial., _run_single_task(), _read_records() (+14 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (38): check_grounding_refs(), check_learn_output(), check_path_access(), check_retry_loop(), check_sql_queries(), check_where_literals(), _has_where_clause(), _is_select() (+30 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (30): call_llm_raw(), _call_raw_single_model(), get_anthropic_model_id(), get_provider(), get_response_format(), _get_static_hint(), is_claude_code_model(), is_claude_model() (+22 more)

### Community 5 - "Community 5"
Cohesion: 0.1
Nodes (30): Contract, ContractRound, EvaluatorResponse, ExecutorProposal, AgentsMdRef, AnswerOutput, AnswerTemplate, CodegenOutput (+22 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (4): ConnectClient, Minimal Connect RPC client using JSON protocol over httpx., EcomRuntimeClientSync, PcmRuntimeClientSync

### Community 7 - "Community 7"
Cohesion: 0.1
Nodes (26): _call_llm_raw(), CodegenError, _design_to_tool_plan_json(), CODEGEN phase v2 — translates a tool_plan to a Python `run(vm, params)` module., Indirect through agent.pipeline so test patches on `agent.pipeline.call_llm_raw`, Translate `design.tool_plan` into a Python module. Returns CodegenOutput or rais, run_codegen(), _call_llm_raw() (+18 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (26): _apply_learn_diff() (Incremental Learn Persist), bitgn/ (Protobuf Stubs), data/learned/{task_id}.yaml (Knowledge Base), data/prompts/*.md (Phase Guides), JSON Extraction Priority Rationale, json_extract.py, AnswerOutput Pydantic Model, LearnOutput Pydantic Model (+18 more)

### Community 9 - "Community 9"
Cohesion: 0.11
Nodes (18): _Entry, _ExecResult, _FindResult, _ListResult, _Match, MockVM, _Node, MockVM — stub for EcomRuntimeClientSync used in CODEGEN mock tests. (+10 more)

### Community 10 - "Community 10"
Cohesion: 0.1
Nodes (13): HarnessServiceClientSync, _finalize_task_trace(), _log_stats(), main(), _print_table_header(), _print_table_row(), One StartRun → trial loop → SubmitRun. Returns (scores, submit_result).      `tr, Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref (+5 more)

### Community 11 - "Community 11"
Cohesion: 0.13
Nodes (23): apply_learn_diff(), _format_entry(), load_entries(), _next_entry_id(), _next_verdict_id(), Per-task learned knowledge store. Replaces helpers from prompt_assembler., Persist last_run metadata. No heuristic_valid, no schema_hash., Record grader feedback as a `source: verdict` entry in entries[].      One activ (+15 more)

### Community 12 - "Community 12"
Cohesion: 0.17
Nodes (10): fixture_key(), MockVMSpy, Recording mock VM used inside the fidelity gate., Records every RPC call. Looks up canned responses from `fixtures`.      Designed, test_all_rpcs_record(), test_answer_recorded_does_not_raise(), test_exec_records_stdin(), test_fixture_lookup_by_rpc_path_args() (+2 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (22): _augment_agents_md(), _discover_sample_rows(), _discover_schema(), _discover_table_names(), Minimal orchestrator — reads AGENTS.MD then dispatches the pipeline., Execute a single benchmark task., Best-effort: ask the VM's SQL tool for the catalog schema.      Returns formatte, Per-table top-N rows. Reveals FK link patterns DESIGN can't infer from     CREAT (+14 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (15): load_prompt(), load_task_blocks(), Prompt loading utilities., Return prompt block by file stem name. Returns '' if not found., Return list of prompt block stems for given task_type from data/config/task_bloc, test_email_prompt_not_loaded(), test_inbox_prompt_not_loaded(), test_load_prompt_answer_exists() (+7 more)

### Community 15 - "Community 15"
Cohesion: 0.18
Nodes (19): exec_fidelity_in_subprocess(), _expected_answer_call(), FidelityResult, generate_fidelity_test(), Deterministic fidelity gate.  Generates a Python test module from a DesignOutput, Emit a Python module string. Deterministic - same input => byte-equal output., Combine script + test in a single source, exec in a subprocess, gate on test_fid, _serialize_expected() (+11 more)

### Community 16 - "Community 16"
Cohesion: 0.14
Nodes (10): LearnConsolidateOutput, _seed(), test_apply_learn_diff_appends_new_entry(), test_apply_learn_diff_deactivates_prior(), test_apply_learn_diff_skip_writes_nothing(), test_load_entries_active_only(), test_write_verdict_appends_entry(), test_write_verdict_deactivates_prior_verdict() (+2 more)

### Community 17 - "Community 17"
Cohesion: 0.14
Nodes (4): _normalise_kind(), Kwargs-style adapter over EcomRuntimeClientSync.  Generated heuristic scripts +, Map free-form kind strings ('file', 'dir', ...) to NodeKind enum values.      LL, VMAdapter

### Community 18 - "Community 18"
Cohesion: 0.21
Nodes (10): _build_env(), cc_complete(), _parse_envelope(), Claude Code tier — spawn iclaude CLI as stateless LLM.  Bypasses applied (all re, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str (+2 more)

### Community 19 - "Community 19"
Cohesion: 0.27
Nodes (10): parse_agents_md(), Parse AGENTS.MD into {section_name: [lines]} for each ## section., test_empty_section_has_empty_lines(), test_empty_string_returns_empty_dict(), test_h1_heading_not_treated_as_section(), test_leading_content_before_first_section_ignored(), test_multiple_sections(), test_no_sections_returns_empty_dict() (+2 more)

### Community 20 - "Community 20"
Cohesion: 0.24
Nodes (9): _extract_json_from_text(), _obj_mutation_tool(), JSON extraction from free-form LLM text output.  Public API:   _obj_mutation_too, Try json5 parse; raises on failure (ImportError or parse error)., Return the mutation tool name if obj is a write/delete/exec action, else None., Lower tuple = preferred. Used by min() to break ties among same-tier candidates., Extract the most actionable valid JSON object from free-form model output., _richness_key() (+1 more)

### Community 21 - "Community 21"
Cohesion: 0.31
Nodes (8): _build_alias_map(), _check_query(), check_schema_compliance(), _known_cols_by_table(), Schema-aware SQL validator: unknown columns, unverified literals, double-key JOI, Return {alias_lower: table_name_lower} from FROM and JOIN clauses., Check queries against schema. Returns first error string or None if all pass., Return {table_name_lower: {col_name_lower, ...}}.

### Community 22 - "Community 22"
Cohesion: 0.32
Nodes (6): Verify main.py creates/closes TraceLogger and calls log_header + log_task_result, main.log must contain stats rows but NOT pipeline cycle lines., main.log must contain stats rows but NOT pipeline cycle lines., After _run_single_task + _finalize_task_trace: .jsonl has header + task_result;, test_main_log_contains_only_stats(), test_run_single_task_creates_jsonl_and_removes_log()

### Community 23 - "Community 23"
Cohesion: 0.25
Nodes (8): data/eval_log.jsonl, data/.eval_optimizations_processed (processed hashes), MODEL_EVALUATOR env var, prompt_optimization channel → data/prompts/optimized/, scripts/propose_optimizations.py, rule_optimization channel → data/rules/sql-NNN.yaml, security_optimization channel → data/security/sec-NNN.yaml, Three optimization channels (rule, security, prompt)

### Community 24 - "Community 24"
Cohesion: 0.29
Nodes (7): cc_client.py (Claude Code Tier), llm.py (LLM Routing), Anthropic SDK Tier, Claude Code CLI Tier, Local Ollama Tier, OpenRouter Tier, models.json (Provider Hints)

### Community 26 - "Community 26"
Cohesion: 0.5
Nodes (4): _check_tdd_antipatterns(), Subprocess test runner for TDD pipeline., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., run_tests()

### Community 27 - "Community 27"
Cohesion: 0.6
Nodes (5): check_grounding_refs, clean_refs, p.path SQL column, sku_refs, t16 grounding refs bug

### Community 28 - "Community 28"
Cohesion: 0.6
Nodes (3): test_settle_no_verdict_on_perfect_score(), test_settle_writes_verdict_on_failure(), _trial()

### Community 29 - "Community 29"
Cohesion: 0.67
Nodes (3): main(), _migrate_file(), Return True if migrated, False if already in new format or skipped.

## Knowledge Gaps
- **146 isolated node(s):** `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Prompt loading utilities.`, `Return prompt block by file stem name. Returns '' if not found.`, `Return list of prompt block stems for given task_type from data/config/task_bloc` (+141 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_pipeline()` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 7`, `Community 11`, `Community 13`, `Community 14`, `Community 15`?**
  _High betweenness centrality (0.214) - this node is a cross-community bridge._
- **Why does `run_agent()` connect `Community 13` to `Community 1`, `Community 2`, `Community 6`, `Community 17`?**
  _High betweenness centrality (0.150) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `run_pipeline()` (e.g. with `run_agent()` and `test_outcome_override_terminal()`) actually correct?**
  _`run_pipeline()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `TraceLogger` (e.g. with `_run_single_task()` and `test_set_and_get_trace()`) actually correct?**
  _`TraceLogger` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `_AnswerGuard` (e.g. with `test_answer_guard_passes_resolved_refs()` and `test_answer_guard_raises_on_unresolved_placeholder()`) actually correct?**
  _`_AnswerGuard` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `MockVMSpy` (e.g. with `test_records_calls_in_order()` and `test_exec_records_stdin()`) actually correct?**
  _`MockVMSpy` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Prompt loading utilities.` to the rest of the system?**
  _146 weakly-connected nodes found - possible documentation gaps or missing edges._