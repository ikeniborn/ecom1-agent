import json
import os
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch

import scripts.propose_optimizations as po


def _write_eval_log(path: Path, entries: list) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _eval_entry(rule_opts=None, security_opts=None, prompt_opts=None):
    return {
        "task_text": "Do you have product X with attr Y=3?",
        "cycles": 2,
        "final_outcome": "OUTCOME_NONE_CLARIFICATION",
        "outcome": "ok",
        "score": 1,
        "rule_optimization": rule_opts or [],
        "security_optimization": security_opts or [],
        "prompt_optimization": prompt_opts or [],
    }


def _setup(tmp_path):
    eval_log = tmp_path / "eval_log.jsonl"
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    security_dir = tmp_path / "security"
    security_dir.mkdir()
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    prompts_optimized_dir = prompts_dir / "optimized"
    prompts_optimized_dir.mkdir()
    processed_file = tmp_path / ".eval_optimizations_processed"
    return eval_log, rules_dir, security_dir, prompts_dir, prompts_optimized_dir, processed_file


def _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prompts_optimized_dir, processed_file):
    return [
        patch.object(po, "_EVAL_LOG", eval_log),
        patch.object(po, "_RULES_DIR", rules_dir),
        patch.object(po, "_SECURITY_DIR", security_dir),
        patch.object(po, "_PROMPTS_DIR", prompts_dir),
        patch.object(po, "_PROMPTS_OPTIMIZED_DIR", prompts_optimized_dir),
        patch.object(po, "_PROCESSED_FILE", processed_file),
        patch.object(po, "_load_model_cfg", return_value={}),
        patch.object(po, "load_dotenv"),
        patch.dict(os.environ, {"MODEL_EVALUATOR": "test-model"}),
    ]


def test_writes_rule_yaml(tmp_path):
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["Never prefix model with brand."])])

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value="Never prefix model with brand."), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    files = list(rules_dir.glob("*.yaml"))
    assert len(files) == 1
    rule = yaml.safe_load(files[0].read_text())
    assert rule["verified"] is True
    assert rule["source"] == "eval"
    assert rule["phase"] == "sql_plan"
    assert "Never prefix model" in rule["content"]
    assert rule["eval_score"] == 1


def test_writes_security_yaml(tmp_path):
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(security_opts=["Add gate for UNION SELECT"])])

    gate_spec = {"pattern": "UNION.*SELECT", "check": None, "message": "UNION SELECT prohibited"}
    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=gate_spec), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    files = list(security_dir.glob("*.yaml"))
    assert len(files) == 1
    gate = yaml.safe_load(files[0].read_text())
    assert gate["verified"] is True
    assert gate["source"] == "eval"
    assert gate["action"] == "block"
    assert gate["pattern"] == "UNION.*SELECT"
    assert "check" not in gate


def test_writes_prompt_md(tmp_path):
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(prompt_opts=["answer.md: add rule for empty grounding_refs"])])

    patch_result = {"target_file": "answer.md", "content": "## Grounding guard\nNever emit empty grounding_refs."}
    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=patch_result), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    dest = prompts_dir / "answer.md"
    assert dest.exists()
    text = dest.read_text()
    assert "Never emit empty grounding_refs" in text


def test_dry_run_writes_nothing(tmp_path):
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(
        rule_opts=["r"], security_opts=["s"], prompt_opts=["p"]
    )])

    gate_spec = {"pattern": "DROP", "check": None, "message": "no drop"}
    patch_result = {"target_file": "sql_plan.md", "content": "## X\nDo X."}
    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value="Never X."), \
         patch.object(po, "_synthesize_security_gate", return_value=gate_spec), \
         patch.object(po, "_synthesize_prompt_patch", return_value=patch_result):
        po.main(dry_run=True)

    assert list(rules_dir.glob("*.yaml")) == []
    assert list(security_dir.glob("*.yaml")) == []
    assert list(prom_dir.glob("*.md")) == []
    assert not processed.exists()


def test_dedup_skips_processed(tmp_path):
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    rec = "Never prefix model."
    entry = _eval_entry(rule_opts=[rec])
    _write_eval_log(eval_log, [entry])
    h = po._entry_hash(entry["task_text"], "rule", rec)
    processed.write_text(h + "\n")

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value="Never X.") as mock_synth, \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    mock_synth.assert_not_called()


def test_missing_model_evaluator_exits(tmp_path):
    eval_log, _rules_dir, _security_dir, _prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["x"])])

    with patch.object(po, "_EVAL_LOG", eval_log), \
         patch.object(po, "load_dotenv"), \
         patch.dict(os.environ):
        os.environ.pop("MODEL_EVALUATOR", None)
        with pytest.raises(SystemExit):
            po.main()


def test_existing_security_text_returns_id_message(tmp_path):
    import agent.knowledge_loader as kl
    sec_dir = tmp_path / "security"
    sec_dir.mkdir()
    (sec_dir / "sec-001.yaml").write_text(
        "id: sec-001\naction: block\nmessage: DDL prohibited\n"
    )
    (sec_dir / "sec-002.yaml").write_text(
        "id: sec-002\ncheck: no_where_clause\naction: block\nmessage: Full scan prohibited\n"
    )
    with patch.object(kl, "_SECURITY_DIR", sec_dir):
        result = kl.existing_security_text()
    assert "sec-001: DDL prohibited" in result
    assert "sec-002: Full scan prohibited" in result


def test_existing_security_text_skips_invalid(tmp_path):
    import agent.knowledge_loader as kl
    sec_dir = tmp_path / "security"
    sec_dir.mkdir()
    (sec_dir / "bad.yaml").write_text("not: valid: yaml: [")
    (sec_dir / "no-msg.yaml").write_text("id: sec-003\naction: block\n")
    with patch.object(kl, "_SECURITY_DIR", sec_dir):
        result = kl.existing_security_text()
    assert result == ""


def test_existing_prompts_text_returns_full_content(tmp_path):
    import agent.knowledge_loader as kl
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "answer.md").write_text("# Answer\n\nDo X.\n")
    (prompts_dir / "sql_plan.md").write_text("# SQL Plan\n\nDo Y.\n")
    optimized_dir = prompts_dir / "optimized"
    optimized_dir.mkdir()
    (optimized_dir / "2026-05-12-01-answer.md").write_text("## Extra\nShould appear.\n")
    with patch.object(kl, "_PROMPTS_DIR", prompts_dir), \
         patch.object(kl, "_PROMPTS_OPTIMIZED_DIR", optimized_dir):
        result = kl.existing_prompts_text()
    assert "=== answer.md ===" in result
    assert "Do X." in result
    assert "=== sql_plan.md ===" in result
    assert "Do Y." in result
    assert "Should appear." in result


def test_existing_prompts_text_empty_dir(tmp_path):
    import agent.knowledge_loader as kl
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    with patch.object(kl, "_PROMPTS_DIR", prompts_dir), \
         patch.object(kl, "_PROMPTS_OPTIMIZED_DIR", prompts_dir / "optimized"):
        result = kl.existing_prompts_text()
    assert result == ""


def test_synthesize_security_gate_receives_existing_context(tmp_path):
    import agent.knowledge_loader as kl
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(security_opts=["Add gate for UNION SELECT"])])

    gate_spec = {"pattern": "UNION.*SELECT", "check": None, "message": "UNION SELECT prohibited"}
    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=gate_spec) as mock_sec, \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(kl, "existing_security_text", return_value="- sec-001: DDL prohibited"), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    args = mock_sec.call_args
    assert args[0][1] == "- sec-001: DDL prohibited"


def test_synthesize_prompt_patch_receives_existing_context(tmp_path):
    import agent.knowledge_loader as kl
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(prompt_opts=["answer.md: add grounding rule"])])

    patch_result = {"target_file": "answer.md", "content": "## Guard\nNever X."}
    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=patch_result) as mock_prompt, \
         patch.object(kl, "existing_prompts_text", return_value="=== answer.md ===\n# Answer\n"), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    args = mock_prompt.call_args
    assert args[0][1] == "=== answer.md ===\n# Answer\n"


def test_main_uses_knowledge_loader_for_rules(tmp_path):
    """Ensure propose_optimizations imports rules text from knowledge_loader, not its own helper."""
    import agent.knowledge_loader as kl
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["Never X."])])

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(kl, "existing_rules_text", return_value="- sql-001: existing rule") as mock_kl, \
         patch.object(po, "_synthesize_rule", return_value="Never X.") as mock_synth, \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    # synthesize_rule must be called with the string returned by knowledge_loader
    args = mock_synth.call_args
    assert args[0][1] == "- sql-001: existing rule"


def test_cluster_recs_merges_duplicates():
    """_cluster_recs returns fewer items when LLM merges duplicates."""
    items = [
        ("Never SELECT star from product.", {}, "hash1"),
        ("Avoid SELECT * from any table.", {}, "hash2"),
        ("Use column-level projections instead of SELECT *.", {}, "hash3"),
    ]
    merged_rec = "Never use SELECT *; specify column projections."
    with patch("scripts.propose_optimizations.call_llm_raw_cluster",
               return_value=json.dumps([merged_rec])):
        result = po._cluster_recs(items, "", "test-model", {})

    assert len(result) == 1
    rep_rec, rep_entry, all_hashes = result[0]
    assert rep_rec == merged_rec
    assert set(all_hashes) == {"hash1", "hash2", "hash3"}


def test_cluster_recs_fallback_on_llm_failure():
    """_cluster_recs returns items as-is when LLM call fails."""
    items = [
        ("rec-A", {"task_text": "t"}, "hA"),
        ("rec-B", {"task_text": "t"}, "hB"),
    ]
    with patch("scripts.propose_optimizations.call_llm_raw_cluster", return_value=None):
        result = po._cluster_recs(items, "", "test-model", {})

    assert len(result) == 2
    assert result[0][2] == ["hA"]
    assert result[1][2] == ["hB"]


def test_cluster_recs_all_hashes_marked_on_write(tmp_path):
    """All hashes in a cluster group are marked processed after writing the representative."""
    import agent.knowledge_loader as kl

    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    entry = _eval_entry(rule_opts=["rec-A", "rec-B"])
    _write_eval_log(eval_log, [entry])

    merged_rec = "merged rule"
    h_a = po._entry_hash(entry["task_text"], "rule", "rec-A")
    h_b = po._entry_hash(entry["task_text"], "rule", "rec-B")

    def fake_cluster(items, *a, **k):
        all_hashes = [h for _, _, h in items]
        return [(merged_rec, items[0][1], all_hashes)]

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_cluster_recs", side_effect=fake_cluster), \
         patch.object(po, "_synthesize_rule", return_value="Never do X."), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(kl, "existing_rules_text", return_value=""), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    saved = set(processed.read_text().splitlines())
    assert h_a in saved
    assert h_b in saved


def test_rules_md_refreshed_between_writes(tmp_path):
    """Second rule synthesis receives updated rules_md after first write."""
    import agent.knowledge_loader as kl

    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["rec-A", "rec-B"])])

    captured_existing = []

    def fake_synthesize_rule(raw_rec, existing_md, model, cfg):
        captured_existing.append(existing_md)
        return f"Rule for {raw_rec}"

    refresh_calls = [0]

    def counting_existing_rules():
        refresh_calls[0] += 1
        return f"refreshed-after-{refresh_calls[0]}"

    # _cluster_recs must return singletons so both recs are processed independently
    def passthrough_cluster(items, *a, **k):
        return [(rec, entry, [h]) for rec, entry, h in items]

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_cluster_recs", side_effect=passthrough_cluster), \
         patch.object(po, "_synthesize_rule", side_effect=fake_synthesize_rule), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(kl, "existing_rules_text", side_effect=counting_existing_rules), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    # initial load + one refresh after first write = at least 2 calls
    assert refresh_calls[0] >= 2
    # second synthesis sees different rules_md than first
    assert captured_existing[0] != captured_existing[1]


def test_security_md_refreshed_between_writes(tmp_path):
    import agent.knowledge_loader as kl

    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(security_opts=["rec-A", "rec-B"])])

    gate_spec = {"pattern": "DROP", "check": None, "message": "no drop"}
    refresh_calls = [0]

    def counting_existing_security():
        refresh_calls[0] += 1
        return f"refreshed-{refresh_calls[0]}"

    def passthrough_cluster(items, *a, **k):
        return [(rec, entry, [h]) for rec, entry, h in items]

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_cluster_recs", side_effect=passthrough_cluster), \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=gate_spec), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(kl, "existing_security_text", side_effect=counting_existing_security), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    assert refresh_calls[0] >= 2


def test_check_contradiction_returns_none_on_ok(tmp_path):
    """Returns None when LLM says OK."""
    with patch("scripts.propose_optimizations.call_llm_raw_cluster", return_value="OK"):
        result = po._check_contradiction("Never SELECT star.", "- sql-001: Always JOIN.", "test-model", {})
    assert result is None


def test_check_contradiction_returns_string_on_conflict(tmp_path):
    """Returns conflict string when LLM finds contradiction."""
    with patch("scripts.propose_optimizations.call_llm_raw_cluster",
               return_value="CONFLICT: sql-001 — opposite instruction"):
        result = po._check_contradiction("Always SELECT star.", "- sql-001: Never SELECT star.", "test-model", {})
    assert result is not None
    assert "sql-001" in result


def test_contradiction_blocks_write(tmp_path):
    """Rule with contradiction is not written and its hashes are not marked processed."""
    import agent.knowledge_loader as kl

    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["conflicting rec"])])
    h = po._entry_hash("Do you have product X with attr Y=3?", "rule", "conflicting rec")

    def fake_cluster(items, *a, **k):
        return [(rec, entry, [hsh]) for rec, entry, hsh in items]

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_cluster_recs", side_effect=fake_cluster), \
         patch.object(po, "_synthesize_rule", return_value="Always SELECT star."), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value="CONFLICT: sql-001 — opposite"), \
         patch.object(kl, "existing_rules_text", return_value="- sql-001: Never SELECT star."):
        po.main(dry_run=False)

    assert list(rules_dir.glob("*.yaml")) == []
    saved = processed.read_text().splitlines() if processed.exists() else []
    assert h not in saved


import time

def test_read_original_score_found(tmp_path):
    logs_dir = tmp_path / "logs"
    run_dir = logs_dir / "20240101_120000_model"
    run_dir.mkdir(parents=True)
    task_file = run_dir / "t01.jsonl"
    task_file.write_text(
        json.dumps({"type": "llm_call", "phase": "sql_plan"}) + "\n" +
        json.dumps({"type": "task_result", "score": 0.75, "outcome": "OUTCOME_OK"}) + "\n"
    )
    score = po.read_original_score("t01", logs_dir=logs_dir)
    assert score == pytest.approx(0.75)

def test_read_original_score_excludes_validate_dirs(tmp_path):
    logs_dir = tmp_path / "logs"
    validate_dir = logs_dir / "validate-20240101"
    validate_dir.mkdir(parents=True)
    (validate_dir / "t01.jsonl").write_text(
        json.dumps({"type": "task_result", "score": 1.0}) + "\n"
    )
    time.sleep(0.01)
    real_dir = logs_dir / "20240101_120000_model"
    real_dir.mkdir()
    (real_dir / "t01.jsonl").write_text(
        json.dumps({"type": "task_result", "score": 0.5}) + "\n"
    )
    score = po.read_original_score("t01", logs_dir=logs_dir)
    assert score == pytest.approx(0.5)

def test_read_original_score_not_found_returns_none(tmp_path):
    logs_dir = tmp_path / "logs"
    run_dir = logs_dir / "20240101_120000_model"
    run_dir.mkdir(parents=True)
    score = po.read_original_score("t99", logs_dir=logs_dir)
    assert score is None

def test_read_original_score_no_logs_dir(tmp_path):
    score = po.read_original_score("t01", logs_dir=tmp_path / "nonexistent")
    assert score is None


from unittest.mock import MagicMock

def _make_harness_mocks(task_id="t01", trial_score=0.9, trial_ids=None):
    if trial_ids is None:
        trial_ids = ["trial-1", "trial-2"]
    mock_run = MagicMock()
    mock_run.run_id = "run-abc"
    mock_run.trial_ids = trial_ids

    def fake_start_trial(req):
        resp = MagicMock()
        resp.task_id = task_id if req.trial_id == trial_ids[0] else "other-task"
        resp.trial_id = req.trial_id
        resp.harness_url = "http://fake"
        resp.instruction = "How many items?"
        return resp

    mock_end = MagicMock()
    mock_end.score = trial_score

    client = MagicMock()
    client.start_run.return_value = mock_run
    client.start_trial.side_effect = fake_start_trial
    client.end_trial.return_value = mock_end
    return client


def test_validate_recommendation_accepted(tmp_path):
    logs_dir = tmp_path / "logs"
    run_dir = logs_dir / "20240101_120000_model"
    run_dir.mkdir(parents=True)
    (run_dir / "t01.jsonl").write_text(
        json.dumps({"type": "task_result", "score": 0.7}) + "\n"
    )
    client = _make_harness_mocks(task_id="t01", trial_score=0.9)
    with patch.object(po, "_LOGS_DIR", logs_dir), \
         patch("bitgn.harness_connect.HarnessServiceClientSync", return_value=client), \
         patch("agent.run_agent") as mock_run_agent:
        original, validation = po.validate_recommendation(
            "t01", injected_session_rules=["Never use SELECT *"]
        )
    assert original == pytest.approx(0.7)
    assert validation == pytest.approx(0.9)
    mock_run_agent.assert_called_once()
    call_kw = mock_run_agent.call_args[1]
    assert call_kw["injected_session_rules"] == ["Never use SELECT *"]
    assert call_kw["task_id"] == "t01"


def test_validate_recommendation_rejected(tmp_path):
    logs_dir = tmp_path / "logs"
    run_dir = logs_dir / "20240101_120000_model"
    run_dir.mkdir(parents=True)
    (run_dir / "t01.jsonl").write_text(
        json.dumps({"type": "task_result", "score": 1.0}) + "\n"
    )
    client = _make_harness_mocks(task_id="t01", trial_score=0.5)
    with patch.object(po, "_LOGS_DIR", logs_dir), \
         patch("bitgn.harness_connect.HarnessServiceClientSync", return_value=client), \
         patch("agent.run_agent"):
        original, validation = po.validate_recommendation("t01")
    assert original == pytest.approx(1.0)
    assert validation == pytest.approx(0.5)


def test_validate_recommendation_task_not_in_trials(tmp_path):
    logs_dir = tmp_path / "logs"
    run_dir = logs_dir / "20240101_120000_model"
    run_dir.mkdir(parents=True)
    (run_dir / "t01.jsonl").write_text(
        json.dumps({"type": "task_result", "score": 0.8}) + "\n"
    )
    client = _make_harness_mocks(task_id="other", trial_score=0.0, trial_ids=["trial-1"])
    with patch.object(po, "_LOGS_DIR", logs_dir), \
         patch("bitgn.harness_connect.HarnessServiceClientSync", return_value=client), \
         patch("agent.run_agent") as mock_run_agent:
        original, validation = po.validate_recommendation("t01")
    assert original == pytest.approx(0.8)
    assert validation is None
    mock_run_agent.assert_not_called()


def test_validate_recommendation_no_baseline(tmp_path):
    client = _make_harness_mocks(task_id="t99", trial_score=0.9, trial_ids=["trial-1"])
    with patch.object(po, "_LOGS_DIR", tmp_path / "empty"), \
         patch("bitgn.harness_connect.HarnessServiceClientSync", return_value=client), \
         patch("agent.run_agent"):
        original, validation = po.validate_recommendation("t99")
    assert original is None
    assert validation == pytest.approx(0.9)


def test_auto_apply_writes_rule_without_validation(tmp_path):
    """Auto-apply: rule is written directly without calling validate_recommendation."""
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    entry = _eval_entry(rule_opts=["Never use SELECT *"])
    entry["task_id"] = "t01"
    _write_eval_log(eval_log, [entry])

    def passthrough_cluster(items, *a, **k):
        return [(rec, ent, [h]) for rec, ent, h in items]

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_cluster_recs", side_effect=passthrough_cluster), \
         patch.object(po, "_synthesize_rule", return_value="Never use SELECT *"), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None), \
         patch.object(po, "validate_recommendation") as mock_val:
        po.main(dry_run=False)

    mock_val.assert_not_called()
    assert len(list(rules_dir.glob("*.yaml"))) == 1


def test_dry_run_skips_write(tmp_path):
    """--dry-run prints intent but writes nothing."""
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    entry = _eval_entry(rule_opts=["Never use SELECT *"])
    entry["task_id"] = "t01"
    _write_eval_log(eval_log, [entry])

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value="Never use SELECT *"), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=True)

    assert list(rules_dir.glob("*.yaml")) == []


def test_content_hash_dedup_per_task(tmp_path):
    """Same rec text for same task_id synthesized only once."""
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    entry1 = _eval_entry(rule_opts=["Never use SELECT *"])
    entry1["task_id"] = "t01"
    entry2 = _eval_entry(rule_opts=["Never use SELECT *"])
    entry2["task_id"] = "t01"
    _write_eval_log(eval_log, [entry1, entry2])

    def passthrough_cluster(items, *a, **k):
        return [(rec, ent, [h]) for rec, ent, h in items]

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_cluster_recs", side_effect=passthrough_cluster), \
         patch.object(po, "_synthesize_rule", return_value="Never use SELECT *") as mock_synth, \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    assert mock_synth.call_count == 1


def test_flatten_only_processes_outcome_ok():
    """_flatten_recs only processes entries where outcome=ok."""
    from scripts.propose_optimizations import _flatten_recs
    entries = [
        {"task_id": "t01", "task_text": "find X", "outcome": "ok",
         "rule_optimization": ["use LIKE"], "security_optimization": [], "prompt_optimization": []},
        {"task_id": "t02", "task_text": "find Y", "outcome": "fail",
         "rule_optimization": ["use LIKE"], "security_optimization": [], "prompt_optimization": []},
        {"task_id": "t03", "task_text": "find Z",
         "rule_optimization": ["use LIKE"], "security_optimization": [], "prompt_optimization": []},
    ]
    recs = _flatten_recs(entries, channel="rule_optimization", processed=set())
    task_ids = [r["task_id"] for r in recs]
    assert "t01" in task_ids
    assert "t02" not in task_ids
    assert "t03" not in task_ids
