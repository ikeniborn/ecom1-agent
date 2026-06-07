# Graph Report - .  (2026-06-07)

## Corpus Check
- 0 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 898 nodes · 1450 edges · 68 communities (61 shown, 7 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 263 edges (avg confidence: 0.8)
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
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]

## God Nodes (most connected - your core abstractions)
1. `run_pipeline()` - 48 edges
2. `_AnswerGuard` - 36 edges
3. `TraceLogger` - 32 edges
4. `KnowledgeOracle` - 25 edges
5. `MockVMSpy` - 21 edges
6. `DesignOutput` - 19 edges
7. `_design_with_template_refs()` - 19 edges
8. `check_sql_queries()` - 18 edges
9. `MockVM` - 17 edges
10. `_learn_consolidate()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `_run_single_task()` --calls--> `HarnessServiceClientSync`  [INFERRED]
  main.py → bitgn/harness_connect.py
- `_run_single_task()` --calls--> `run_agent()`  [INFERRED]
  main.py → agent/orchestrator.py
- `main()` --calls--> `HarnessServiceClientSync`  [INFERRED]
  main.py → bitgn/harness_connect.py
- `main()` --calls--> `learn_from_grader()`  [INFERRED]
  main.py → agent/pipeline.py
- `load_prompt()` --calls--> `test_load_prompt_unknown_returns_empty()`  [INFERRED]
  agent/prompt.py → tests/test_prompt_loader.py

## Communities (68 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (69): _AnswerGuard, _compact_learn_ctx(), learn_from_grader(), Distill a LEARN rule from grader-side feedback for the next training cycle., Distill a LEARN rule from grader-side feedback for the next training cycle., Summarize older learn_ctx entries via one LLM call when the list grows     past, Distill a LEARN rule from grader-side feedback for the next training cycle., Proxy passing all RPCs through to `_vm` while intercepting `answer`.      Also c (+61 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (51): Contract, ContractRound, EvaluatorResponse, ExecutorProposal, AgentsMdRef, AnswerOutput, AnswerTemplate, CodegenOutput (+43 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (35): Atom, content_hash(), load_atoms(), Atom model + YAML persistence for the knowledge oracle., save_atoms(), _cosine(), KnowledgeOracle, Knowledge oracle: validated atom bank + two-stage semantic retrieval. (+27 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (5): ConnectClient, Minimal Connect RPC client using JSON protocol over httpx., HarnessServiceClientSync, EcomRuntimeClientSync, PcmRuntimeClientSync

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (23): get_trace(), Thread-local structured JSONL trace logger for per-task pipeline traces., set_trace(), TraceLogger, Execute one benchmark trial. Score is read later from SubmitRun.      `train_cyc, Execute one benchmark trial., Execute one benchmark trial. Score is read later from SubmitRun.      `train_cyc, _run_single_task() (+15 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (38): check_grounding_refs(), check_learn_output(), check_path_access(), check_retry_loop(), check_sql_queries(), check_where_literals(), _has_where_clause(), _is_select() (+30 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (35): build_oracle_block(), _call_llm_raw(), _design_to_tool_plan_json(), CODEGEN phase v2 — translates a tool_plan to a Python `run(vm, params)` module., Indirect through agent.pipeline so test patches on `agent.pipeline.call_llm_raw`, Render retrieved knowledge atoms as a context block for CODEGEN., Translate `design.tool_plan` into a Python module. Returns CodegenOutput or rais, Translate `design.tool_plan` into a Python module. Returns CodegenOutput or rais (+27 more)

### Community 7 - "Community 7"
Cohesion: 0.1
Nodes (30): apply_learn_diff(), _format_entry(), load_entries(), _next_entry_id(), _next_verdict_id(), Per-task learned knowledge store. Replaces helpers from prompt_assembler., Persist last_run metadata. No heuristic_valid, no schema_hash., Record grader feedback as a `source: verdict` entry in entries[].      One activ (+22 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (26): _apply_learn_diff() (Incremental Learn Persist), bitgn/ (Protobuf Stubs), data/learned/{task_id}.yaml (Knowledge Base), data/prompts/*.md (Phase Guides), JSON Extraction Priority Rationale, json_extract.py, AnswerOutput Pydantic Model, LearnOutput Pydantic Model (+18 more)

### Community 9 - "Community 9"
Cohesion: 0.11
Nodes (18): _Entry, _ExecResult, _FindResult, _ListResult, _Match, MockVM, _Node, MockVM — stub for EcomRuntimeClientSync used in CODEGEN mock tests. (+10 more)

### Community 10 - "Community 10"
Cohesion: 0.12
Nodes (23): CodegenError, _extract_json_from_text(), _obj_mutation_tool(), JSON extraction from free-form LLM text output.  Public API:   _obj_mutation_too, Try json5 parse; raises on failure (ImportError or parse error)., Return the mutation tool name if obj is a write/delete/exec action, else None., Lower tuple = preferred. Used by min() to break ties among same-tier candidates., Extract the most actionable valid JSON object from free-form model output. (+15 more)

### Community 11 - "Community 11"
Cohesion: 0.15
Nodes (22): _augment_agents_md(), _discover_sample_rows(), _discover_schema(), _discover_table_names(), Minimal orchestrator — reads AGENTS.MD then dispatches the pipeline., Execute a single benchmark task., Best-effort: ask the VM's SQL tool for the catalog schema.      Returns formatte, Per-table top-N rows. Reveals FK link patterns DESIGN can't infer from     CREAT (+14 more)

### Community 12 - "Community 12"
Cohesion: 0.17
Nodes (10): fixture_key(), MockVMSpy, Recording mock VM used inside the fidelity gate., Records every RPC call. Looks up canned responses from `fixtures`.      Designed, test_all_rpcs_record(), test_answer_recorded_does_not_raise(), test_exec_records_stdin(), test_fixture_lookup_by_rpc_path_args() (+2 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (23): exec_fidelity_in_subprocess(), _expected_answer_call(), FidelityResult, generate_fidelity_test(), Deterministic fidelity gate.  Generates a Python test module from a DesignOutput, Emit a Python module string. Deterministic - same input => byte-equal output., Emit a Python module string. Deterministic - same input => byte-equal output., Combine script + test in a single source, exec in a subprocess, gate on test_fid (+15 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (15): load_prompt(), load_task_blocks(), Prompt loading utilities., Return prompt block by file stem name. Returns '' if not found., Return list of prompt block stems for given task_type from data/config/task_bloc, test_email_prompt_not_loaded(), test_inbox_prompt_not_loaded(), test_load_prompt_answer_exists() (+7 more)

### Community 15 - "Community 15"
Cohesion: 0.15
Nodes (19): load_green_suite(), promote_decision(), Offline distill→candidate→promote gate.  Activates each candidate atom, runs the, Return [(task_id, reference_score), ...]. Missing file → FileNotFoundError     (, Verdict for one candidate, given post-pass scores.      Returns:       "halt", Iterate candidate atoms; promote those that hold green + improve source.      `r, run_promote(), _promote_entry() (+11 more)

### Community 16 - "Community 16"
Cohesion: 0.23
Nodes (13): _FakeVM, _prep(), Integration tests for the intent-driven TDD gate (TDD_ENABLED)., Red answer (no token) → LEARN → next cycle → green. One answer, with token., Test stays red; force-submit at streak >= threshold beats CLARIFICATION., TDD off → no TEST-GEN call; DESIGN + CODEGEN only, answer submitted inline., Minimal VM returning JSON-serializable stdout (run_tests json.dumps the context), DESIGN → TEST-GEN → CODEGEN(green) → intent-test pass → exactly one answer. (+5 more)

### Community 17 - "Community 17"
Cohesion: 0.14
Nodes (4): _normalise_kind(), Kwargs-style adapter over EcomRuntimeClientSync.  Generated heuristic scripts +, Map free-form kind strings ('file', 'dir', ...) to NodeKind enum values.      LL, VMAdapter

### Community 18 - "Community 18"
Cohesion: 0.15
Nodes (11): _AnswerRefsError, _ground_security_refs(), Guarantee a DENIED_SECURITY answer cites the security policy it applied., Raised when the script's vm.answer call has invalid refs.      Grader-side feedb, Raised when the script's vm.answer call has invalid refs.      Grader-side feedb, Guarantee a DENIED_SECURITY answer cites the security policy it applied., Raised when the script's vm.answer call has invalid refs.      Grader-side feedb, Capture the answer; submit to the real VM now unless deferred. (+3 more)

### Community 19 - "Community 19"
Cohesion: 0.21
Nodes (10): _build_env(), cc_complete(), _parse_envelope(), Claude Code tier — spawn iclaude CLI as stateless LLM.  Bypasses applied (all re, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Spawn iclaude once. Returns (stdout_lines, exit_code, fail_reason).     fail_rea, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str, Stateless LLM call via iclaude subprocess.      Returns assistant text (JSON str (+2 more)

### Community 20 - "Community 20"
Cohesion: 0.27
Nodes (10): parse_agents_md(), Parse AGENTS.MD into {section_name: [lines]} for each ## section., test_empty_section_has_empty_lines(), test_empty_string_returns_empty_dict(), test_h1_heading_not_treated_as_section(), test_leading_content_before_first_section_ignored(), test_multiple_sections(), test_no_sections_returns_empty_dict() (+2 more)

### Community 21 - "Community 21"
Cohesion: 0.2
Nodes (10): _get_static_hint(), _load_capability_cache(), probe_structured_output(), Load persisted cache, filtering stale entries (>7 days)., Load persisted cache, filtering stale entries (>7 days)., Persist current cache to disk. Non-critical — failure is silently ignored., Persist current cache to disk. Non-critical — failure is silently ignored., Detect if model supports response_format. Returns 'json_object' or 'none'.     C (+2 more)

### Community 23 - "Community 23"
Cohesion: 0.18
Nodes (11): _build_answer_user_msg(), _build_sdd_user_msg(), _csv_has_data(), ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER pipeline. Returns (stats dict, None)., ASSEMBLE → SDD → PLAN → EXECUTE → ANSWER pipeline. Returns (stats dict, None)., Per-task pipeline. Exactly one vm.answer() call before returning.      Returns m, Per-task pipeline. Exactly one vm.answer() call before returning.      Returns m, Run test_sql + test_answer against captured runtime data via test_runner.      R (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.2
Nodes (4): codegen returns {"script_code": "...python with {dict} braces..."} in a     ```j, String-aware depth: a literal '}' inside a quoted value must not close     the o, test_extract_object_with_braces_and_close_brace_in_string_unfenced(), test_extract_script_code_with_braces_in_fenced_json()

### Community 25 - "Community 25"
Cohesion: 0.22
Nodes (10): _call_raw_single_model(), get_anthropic_model_id(), get_provider(), is_claude_model(), Determine LLM provider for a model call.     Explicit cfg['provider'] wins; fall, Determine LLM provider for a model call.     Explicit cfg['provider'] wins; fall, Lightweight LLM call with 3-tier routing and transient-error retry.     Returns, Lightweight LLM call with 3-tier routing and transient-error retry.     Returns (+2 more)

### Community 26 - "Community 26"
Cohesion: 0.31
Nodes (8): _build_alias_map(), _check_query(), check_schema_compliance(), _known_cols_by_table(), Schema-aware SQL validator: unknown columns, unverified literals, double-key JOI, Return {alias_lower: table_name_lower} from FROM and JOIN clauses., Check queries against schema. Returns first error string or None if all pass., Return {table_name_lower: {col_name_lower, ...}}.

### Community 27 - "Community 27"
Cohesion: 0.33
Nodes (8): Return per-phase model from env, or default_model if not configured., Return per-phase model from env, or default_model if not configured., _resolve_model_for_phase(), _build_learn_user_msg(), _call_llm_phase(), DESIGN → CODEGEN → fidelity → ANSWER pipeline (terminal one-shot ANSWER)., _run_consolidate(), _run_learn()

### Community 28 - "Community 28"
Cohesion: 0.32
Nodes (6): Verify main.py creates/closes TraceLogger and calls log_header + log_task_result, main.log must contain stats rows but NOT pipeline cycle lines., main.log must contain stats rows but NOT pipeline cycle lines., After _run_single_task + _finalize_task_trace: .jsonl has header + task_result;, test_main_log_contains_only_stats(), test_run_single_task_creates_jsonl_and_removes_log()

### Community 29 - "Community 29"
Cohesion: 0.25
Nodes (7): _extract_payload(), _mock_run(), Exec the script's top-level module; call its `run(vm, params)`., Exec the script's top-level module; call its `run(vm, params)`., Exec the script's top-level module; call its `run(vm, params)`., Replay the script against MockVMSpy(fixtures), returning (answer, sql_results)., _run_script_on_vm()

### Community 30 - "Community 30"
Cohesion: 0.25
Nodes (8): _extract_discovery_results(), _extract_sql_literals(), Return literal SQL strings passed to vm.exec(path='/bin/sql', args=[...])., Return literal SQL strings passed to vm.exec(path='/bin/sql', args=[...])., Return literal SQL strings passed to vm.exec(path='/bin/sql', args=[...])., Compat stub — discovery phase removed from SDD pipeline., test_extract_sql_literals_basic(), test_extract_sql_literals_ignores_fstrings()

### Community 31 - "Community 31"
Cohesion: 0.25
Nodes (8): data/eval_log.jsonl, data/.eval_optimizations_processed (processed hashes), MODEL_EVALUATOR env var, prompt_optimization channel → data/prompts/optimized/, scripts/propose_optimizations.py, rule_optimization channel → data/rules/sql-NNN.yaml, security_optimization channel → data/security/sec-NNN.yaml, Three optimization channels (rule, security, prompt)

### Community 32 - "Community 32"
Cohesion: 0.32
Nodes (6): grade_candidate(), parse_score(), Grader-oracle harness: run a candidate answer on a fresh StartRun, read the real, Start a run, answer `task_id` via answer_builder(vm)->(msg, outcome, refs),, test_parse_score_missing_task_returns_none(), test_parse_score_reads_t38_trial()

### Community 33 - "Community 33"
Cohesion: 0.43
Nodes (5): llm_rerank(), Stage-2 LLM re-rank of cosine candidate atoms., _a(), test_rerank_ignores_unknown_ids(), test_rerank_keeps_ids_returned_by_llm()

### Community 34 - "Community 34"
Cohesion: 0.29
Nodes (7): Flatten system prompt blocks to plain string for non-caching tiers., Flatten system prompt blocks to plain string for non-caching tiers., _system_as_str(), _system_as_str flattens list[dict] blocks to newline-joined text., _system_as_str returns str unchanged., test_system_as_str_from_blocks(), test_system_as_str_passthrough_str()

### Community 35 - "Community 35"
Cohesion: 0.29
Nodes (7): _exec_result_text(), _infer_action_type(), Infer action type from plain string: sql | read | exec., Infer action type from plain string: sql | read | exec | list | search | find |, Summarize older learn_ctx entries via one LLM call when the list grows     past, Execute plan_out.action. approach/steps available for diagnostic context., _run_execute()

### Community 36 - "Community 36"
Cohesion: 0.29
Nodes (7): cc_client.py (Claude Code Tier), llm.py (LLM Routing), Anthropic SDK Tier, Claude Code CLI Tier, Local Ollama Tier, OpenRouter Tier, models.json (Provider Hints)

### Community 37 - "Community 37"
Cohesion: 0.33
Nodes (4): isolate_oracle_embeddings(), Reset module-level state between tests., Redirect the oracle's default embeddings cache to a tmp file so tests that     b, Redirect the oracle's default embeddings cache to a tmp file so tests that     b

### Community 38 - "Community 38"
Cohesion: 0.33
Nodes (6): call_llm_json(), call_llm_raw(), Call LLM with MODEL_FALLBACK retry (FIX-417). Primary model through all tiers fi, Call LLM with MODEL_FALLBACK retry (FIX-417). Primary model through all tiers fi, Call the LLM and parse a JSON object from the reply. Returns {} on failure., Call the LLM and parse a JSON object from the reply. Returns {} on failure.

### Community 39 - "Community 39"
Cohesion: 0.33
Nodes (6): _identical_sql_set(), _normalise(), Multiset equality after whitespace collapse + strip; case-sensitive., Multiset equality after whitespace collapse + strip; case-sensitive., Multiset equality after whitespace collapse + strip; case-sensitive., test_identical_sql_set_normalises_whitespace()

### Community 40 - "Community 40"
Cohesion: 0.33
Nodes (6): True only when the prior failure is plausibly SQL-content-driven.      The anti-, _retry_guard_applies(), check_retry_loop must NOT fire when the prior failure is orthogonal to     SQL c, Plausibly SQL-content-driven failures keep the anti-loop guard active., test_retry_guard_fires_on_sql_driven_errors(), test_retry_guard_skips_sql_orthogonal_errors()

### Community 41 - "Community 41"
Cohesion: 0.5
Nodes (4): _check_tdd_antipatterns(), Subprocess test runner for TDD pipeline., Run test_code in isolated subprocess. Returns (passed, error_message, warnings)., run_tests()

### Community 42 - "Community 42"
Cohesion: 0.6
Nodes (3): test_settle_no_verdict_on_perfect_score(), test_settle_writes_verdict_on_failure(), _trial()

### Community 43 - "Community 43"
Cohesion: 0.67
Nodes (3): main(), _migrate_file(), Return True if migrated, False if already in new format or skipped.

### Community 44 - "Community 44"
Cohesion: 0.5
Nodes (4): _is_retryable_vm_error(), True when a real-VM exception is a deterministic input or transient     failure, The ECOM runtime phrases a missing file/record as 'read failed: not found'., test_is_retryable_vm_error_covers_ecom_not_found()

### Community 46 - "Community 46"
Cohesion: 0.67
Nodes (3): is_claude_code_model(), True for claude-code/* aliases routed to iclaude subprocess., True for claude-code/* aliases routed to iclaude subprocess.

### Community 47 - "Community 47"
Cohesion: 0.67
Nodes (3): get_response_format(), Build response_format dict for the given mode, or None if mode='none'., Build response_format dict for the given mode, or None if mode='none'.

### Community 48 - "Community 48"
Cohesion: 0.67
Nodes (3): is_ollama_model(), True for Ollama-format models (name:tag, no slash).     Examples: qwen3.5:9b, de, True for Ollama-format models (name:tag, no slash).     Examples: qwen3.5:9b, de

### Community 49 - "Community 49"
Cohesion: 0.67
Nodes (3): embed_texts(), Return a list of embedding vectors (one per input) via the Ollama OpenAI-compat, Return a list of embedding vectors (one per input) via the Ollama OpenAI-compat

### Community 50 - "Community 50"
Cohesion: 0.67
Nodes (3): _format_confirmed_values(), Compat stub — confirmed_values removed from SDD pipeline., Compat stub — confirmed_values removed from SDD pipeline.

### Community 51 - "Community 51"
Cohesion: 0.67
Nodes (3): Compat stub — RESOLVE phase removed from SDD pipeline., Compat stub — RESOLVE phase removed from SDD pipeline., run_resolve()

## Knowledge Gaps
- **240 isolated node(s):** `Create run dir, open main.log for stats, wrap stdout for [task_id] terminal pref`, `Execute one benchmark trial.`, `Prompt loading utilities.`, `Return prompt block by file stem name. Returns '' if not found.`, `Return list of prompt block stems for given task_type from data/config/task_bloc` (+235 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `run_pipeline()` connect `Community 23` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 10`, `Community 11`, `Community 13`, `Community 14`, `Community 16`, `Community 18`, `Community 27`, `Community 29`, `Community 30`, `Community 35`, `Community 39`, `Community 40`, `Community 44`?**
  _High betweenness centrality (0.279) - this node is a cross-community bridge._
- **Why does `run_agent()` connect `Community 11` to `Community 17`, `Community 3`, `Community 4`, `Community 23`?**
  _High betweenness centrality (0.126) - this node is a cross-community bridge._
- **Why does `KnowledgeOracle` connect `Community 2` to `Community 1`, `Community 15`, `Community 23`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `run_pipeline()` (e.g. with `run_agent()` and `test_outcome_override_terminal()`) actually correct?**
  _`run_pipeline()` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `_AnswerGuard` (e.g. with `test_answer_guard_passes_resolved_refs()` and `test_answer_guard_raises_on_unresolved_placeholder()`) actually correct?**
  _`_AnswerGuard` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `TraceLogger` (e.g. with `_run_single_task()` and `test_set_and_get_trace()`) actually correct?**
  _`TraceLogger` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `KnowledgeOracle` (e.g. with `run_pipeline()` and `_learn_consolidate()`) actually correct?**
  _`KnowledgeOracle` has 13 INFERRED edges - model-reasoned connections that need verification._