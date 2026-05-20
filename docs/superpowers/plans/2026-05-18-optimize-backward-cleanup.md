---
review:
  plan_hash: dcc5e8eae6bab1e6
  spec_hash: cb0d9f06756bbbf0
  last_run: 2026-05-18
  phases:
    structure:     { status: passed }
    coverage:      { status: passed }
    dependencies:  { status: passed }
    verifiability: { status: passed }
    consistency:   { status: passed }
  section_hashes:
    Task1: 86a5d776085c6ff7
    Task2: 709bce234d13a24b
  findings: []
---

# Optimize Backward Cleanup & Prompt Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backward cleanup for rules/security (soft-disable superseded items after each write) and replace append-only prompt patching with full LLM-driven file rewrites.

**Architecture:** Two independent additions to `scripts/propose_optimizations.py`. Part 1 adds `_find_superseded` + `_soft_disable` called after every `_write_rule`/`_write_security`. Part 2 replaces the per-cluster prompt loop with a group-by-target + `_rewrite_prompt_file` approach; `_write_prompt` is removed.

**Tech Stack:** Python, PyYAML, `call_llm_raw_cluster` (already imported), `agent.knowledge_loader`

---

### Task 1: `_find_superseded` + `_soft_disable` + integrate into rules/security loops

**Spec:** `docs/superpowers/specs/2026-05-18-optimize-backward-cleanup-design.md` §Part 1

**Files:**
- Modify: `scripts/propose_optimizations.py`
- Test: `tests/test_propose_optimizations.py`

---

- [ ] **Step 1: Write failing tests for `_find_superseded`**

Add to `tests/test_propose_optimizations.py`:

```python
def test_find_superseded_returns_ids():
    with patch("scripts.propose_optimizations.call_llm_raw_cluster",
               return_value='["sql-001", "sql-002"]'):
        result = po._find_superseded("Never use SELECT *.", "- sql-001: ...\n- sql-002: ...", "model", {})
    assert result == ["sql-001", "sql-002"]


def test_find_superseded_empty_existing():
    result = po._find_superseded("Never use SELECT *.", "", "model", {})
    assert result == []


def test_find_superseded_llm_failure_returns_empty():
    with patch("scripts.propose_optimizations.call_llm_raw_cluster", return_value=None):
        result = po._find_superseded("content", "existing", "model", {})
    assert result == []


def test_find_superseded_non_list_returns_empty():
    with patch("scripts.propose_optimizations.call_llm_raw_cluster", return_value='"sql-001"'):
        result = po._find_superseded("content", "existing", "model", {})
    assert result == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/ikeniborn/Documents/Project/ecom1-agent
uv run pytest tests/test_propose_optimizations.py::test_find_superseded_returns_ids -v
```
Expected: `AttributeError: module 'scripts.propose_optimizations' has no attribute '_find_superseded'`

- [ ] **Step 3: Implement `_find_superseded`**

Add after `_check_contradiction` in `scripts/propose_optimizations.py` (after line ~231):

```python
def _find_superseded(new_content: str, existing_md: str, model: str, cfg: dict) -> list[str]:
    """One LLM call. Returns list of IDs from existing_md superseded by new_content. Returns [] on failure."""
    if not existing_md:
        return []
    from agent.json_extract import _extract_json_from_text
    system = (
        "Given newly written content and existing items, identify which existing items "
        "are now superseded or contradicted by the new content.\n"
        "Return a JSON array of IDs (e.g. [\"sql-015\"]). Return [] if none.\n"
        "Return only the JSON array, no other text."
        + f"\n\nExisting items:\n{existing_md}"
    )
    raw = call_llm_raw_cluster(system, f"New content:\n{new_content}", model, cfg, max_tokens=256)
    if not raw:
        return []
    try:
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        parsed = _extract_json_from_text(raw)
    if not isinstance(parsed, list):
        return []
    return [s for s in parsed if isinstance(s, str)]
```

- [ ] **Step 4: Run `_find_superseded` tests to confirm pass**

```bash
uv run pytest tests/test_propose_optimizations.py -k "find_superseded" -v
```
Expected: 4 PASSED

- [ ] **Step 5: Write failing tests for `_soft_disable`**

Add to `tests/test_propose_optimizations.py`:

```python
def test_soft_disable_sets_verified_false(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "sql-001.yaml").write_text(
        "id: sql-001\nphase: sql_plan\nverified: true\ncontent: Never X.\n"
    )
    result = po._soft_disable("sql-001", rules_dir)
    assert result is True
    data = yaml.safe_load((rules_dir / "sql-001.yaml").read_text())
    assert data["verified"] is False


def test_soft_disable_returns_false_when_not_found(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    result = po._soft_disable("sql-999", rules_dir)
    assert result is False


def test_soft_disable_leaves_other_files_unchanged(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "sql-001.yaml").write_text("id: sql-001\nverified: true\n")
    (rules_dir / "sql-002.yaml").write_text("id: sql-002\nverified: true\n")
    po._soft_disable("sql-001", rules_dir)
    data = yaml.safe_load((rules_dir / "sql-002.yaml").read_text())
    assert data["verified"] is True
```

- [ ] **Step 6: Run tests to confirm fail**

```bash
uv run pytest tests/test_propose_optimizations.py -k "soft_disable" -v
```
Expected: `AttributeError: module ... has no attribute '_soft_disable'`

- [ ] **Step 7: Implement `_soft_disable`**

Add immediately after `_find_superseded` in `scripts/propose_optimizations.py`:

```python
def _soft_disable(rule_id: str, directory: Path) -> bool:
    """Finds YAML file with matching id field, sets verified: false. Returns True if patched."""
    for f in directory.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id") == rule_id:
                data["verified"] = False
                with open(f, "w", encoding="utf-8") as fh:
                    yaml.dump(data, fh, allow_unicode=True, default_flow_style=False)
                return True
        except Exception:
            pass
    return False
```

- [ ] **Step 8: Run `_soft_disable` tests**

```bash
uv run pytest tests/test_propose_optimizations.py -k "soft_disable" -v
```
Expected: 3 PASSED

- [ ] **Step 9: Write failing integration tests for rules/security loops**

Add to `tests/test_propose_optimizations.py`:

```python
def test_main_calls_find_superseded_after_rule_write(tmp_path):
    """_find_superseded is called with the new rule content after writing."""
    import agent.knowledge_loader as kl
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["Never use SELECT *"])])

    captured_new_content = []

    def fake_find_superseded(new_content, existing_md, model, cfg):
        captured_new_content.append(new_content)
        return []

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value="Never use SELECT *."), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None), \
         patch.object(po, "_find_superseded", side_effect=fake_find_superseded):
        po.main(dry_run=False)

    assert len(captured_new_content) == 1
    assert "Never use SELECT *" in captured_new_content[0]


def test_main_soft_disables_superseded_rule(tmp_path):
    """When _find_superseded returns an id, _soft_disable is called for that id."""
    import agent.knowledge_loader as kl
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["Never use SELECT *"])])

    (rules_dir / "sql-001.yaml").write_text(
        "id: sql-001\nphase: sql_plan\nverified: true\ncontent: Old rule.\n"
    )

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value="Never use SELECT *."), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None), \
         patch.object(po, "_find_superseded", return_value=["sql-001"]):
        po.main(dry_run=False)

    data = yaml.safe_load((rules_dir / "sql-001.yaml").read_text())
    assert data["verified"] is False


def test_main_dry_run_calls_find_superseded_but_no_disable(tmp_path):
    """dry-run: _find_superseded runs, _soft_disable not called."""
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(rule_opts=["Never use SELECT *"])])

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value="Never use SELECT *."), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None), \
         patch.object(po, "_find_superseded", return_value=["sql-001"]) as mock_find, \
         patch.object(po, "_soft_disable") as mock_disable:
        po.main(dry_run=True)

    mock_find.assert_called_once()
    mock_disable.assert_not_called()


def test_main_calls_find_superseded_after_security_write(tmp_path):
    """_find_superseded is called after writing a security gate."""
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(security_opts=["Block UNION SELECT"])])

    gate_spec = {"pattern": "UNION.*SELECT", "check": None, "message": "UNION SELECT prohibited"}

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=gate_spec), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None), \
         patch.object(po, "_check_contradiction", return_value=None), \
         patch.object(po, "_find_superseded", return_value=[]) as mock_find:
        po.main(dry_run=False)

    mock_find.assert_called_once()
```

- [ ] **Step 10: Run integration tests to confirm fail**

```bash
uv run pytest tests/test_propose_optimizations.py -k "find_superseded or soft_disable" -v
```
Expected: new integration tests fail (functions exist but not wired in main)

- [ ] **Step 11: Wire `_find_superseded` + `_soft_disable` into rules loop**

In `scripts/propose_optimizations.py`, replace the rule write block in `main()`:

Old (lines ~479-483):
```python
        else:
            dest = _write_rule(num, content, entry, raw_rec)
            new_processed.update(all_hashes)
            written += 1
            rules_md = knowledge_loader.existing_rules_text()
```

New:
```python
        else:
            dest = _write_rule(num, content, entry, raw_rec)
            superseded = _find_superseded(content, rules_md, model, cfg)
            for sid in superseded:
                if _soft_disable(sid, _RULES_DIR):
                    print(f"  → disabled {sid} (superseded)")
            new_processed.update(all_hashes)
            written += 1
            rules_md = knowledge_loader.existing_rules_text()
```

Also update the dry-run branch (lines ~477-478):
```python
        if dry_run:
            print(f"  → [DRY RUN] sql-{num:03d}.yaml: {content[:100]}")
            superseded = _find_superseded(content, rules_md, model, cfg)
            for sid in superseded:
                print(f"  → [DRY RUN] would disable {sid} (superseded)")
```

- [ ] **Step 12: Wire into security loop**

Replace the security write block in `main()`:

Old (lines ~499-503):
```python
        else:
            dest = _write_security(num, gate_spec, entry, raw_rec)
            new_processed.update(all_hashes)
            written += 1
            security_md = knowledge_loader.existing_security_text()
```

New:
```python
        else:
            dest = _write_security(num, gate_spec, entry, raw_rec)
            superseded = _find_superseded(gate_spec.get("message", ""), security_md, model, cfg)
            for sid in superseded:
                if _soft_disable(sid, _SECURITY_DIR):
                    print(f"  → disabled {sid} (superseded)")
            new_processed.update(all_hashes)
            written += 1
            security_md = knowledge_loader.existing_security_text()
```

Also update dry-run branch:
```python
        if dry_run:
            print(f"  → [DRY RUN] sec-{num:03d}.yaml: {gate_spec.get('message', '')}")
            superseded = _find_superseded(gate_spec.get("message", ""), security_md, model, cfg)
            for sid in superseded:
                print(f"  → [DRY RUN] would disable {sid} (superseded)")
```

- [ ] **Step 13: Run all tests**

```bash
uv run pytest tests/test_propose_optimizations.py -v
```
Expected: all existing tests PASS + all new tests PASS

- [ ] **Step 14: Commit**

```bash
git add scripts/propose_optimizations.py tests/test_propose_optimizations.py
git commit -m "feat(optimize): add backward cleanup — _find_superseded + _soft_disable after rule/security writes"
```

---

### Task 2: `_rewrite_prompt_file` + group-by-target prompt loop + remove `_write_prompt`

**Spec:** `docs/superpowers/specs/2026-05-18-optimize-backward-cleanup-design.md` §Part 2

**Files:**
- Modify: `scripts/propose_optimizations.py`
- Test: `tests/test_propose_optimizations.py`

---

- [ ] **Step 1: Write failing tests for `_rewrite_prompt_file`**

Add to `tests/test_propose_optimizations.py`:

```python
def test_rewrite_prompt_file_returns_rewritten_content(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "answer.md").write_text("# Answer\n\nOld rule.\n")

    with patch.object(po, "_PROMPTS_DIR", prompts_dir), \
         patch("scripts.propose_optimizations.call_llm_raw_cluster",
               return_value="# Answer\n\nNew rule.\n"):
        result = po._rewrite_prompt_file("answer.md", ["Add new rule"], "model", {})

    assert result == "# Answer\n\nNew rule.\n"


def test_rewrite_prompt_file_reads_existing_file(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    existing_content = "# Answer\n\nExisting content.\n"
    (prompts_dir / "answer.md").write_text(existing_content)

    captured_user = []

    def fake_llm(system, user_msg, model, cfg, **kwargs):
        captured_user.append(user_msg)
        return "rewritten"

    with patch.object(po, "_PROMPTS_DIR", prompts_dir), \
         patch("scripts.propose_optimizations.call_llm_raw_cluster", side_effect=fake_llm):
        po._rewrite_prompt_file("answer.md", ["Add new rule"], "model", {})

    assert existing_content in captured_user[0] or "Existing content" in captured_user[0]


def test_rewrite_prompt_file_handles_missing_file(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    with patch.object(po, "_PROMPTS_DIR", prompts_dir), \
         patch("scripts.propose_optimizations.call_llm_raw_cluster",
               return_value="# New content\n"):
        result = po._rewrite_prompt_file("new.md", ["Add rule"], "model", {})

    assert result == "# New content\n"


def test_rewrite_prompt_file_returns_none_on_llm_failure(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    with patch.object(po, "_PROMPTS_DIR", prompts_dir), \
         patch("scripts.propose_optimizations.call_llm_raw_cluster", return_value=None):
        result = po._rewrite_prompt_file("answer.md", ["rule"], "model", {})

    assert result is None
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
uv run pytest tests/test_propose_optimizations.py -k "rewrite_prompt_file" -v
```
Expected: `AttributeError: module ... has no attribute '_rewrite_prompt_file'`

- [ ] **Step 3: Implement `_rewrite_prompt_file`**

Add to `scripts/propose_optimizations.py` after `_synthesize_prompt_patch` (around line ~316):

```python
def _rewrite_prompt_file(
    target: str,
    new_recs: list[str],
    model: str,
    cfg: dict,
) -> str | None:
    """Reads data/prompts/<target> (empty string if missing).
    LLM rewrites entire file incorporating new_recs with priority.
    Returns complete rewritten content, or None on failure."""
    dest = _PROMPTS_DIR / target
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    recs_block = "\n".join(f"- {r}" for r in new_recs)
    system = (
        "Rewrite the prompt file below, incorporating the new recommendations (which take priority). "
        "Remove duplicates and contradictions. Return only the complete file content with no commentary."
    )
    user_msg = f"New recommendations:\n{recs_block}\n\nExisting file ({target}):\n{existing}"
    raw = call_llm_raw_cluster(system, user_msg, model, cfg, max_tokens=2048, plain_text=True)
    if not raw:
        return None
    return raw
```

- [ ] **Step 4: Run `_rewrite_prompt_file` tests**

```bash
uv run pytest tests/test_propose_optimizations.py -k "rewrite_prompt_file" -v
```
Expected: 4 PASSED

- [ ] **Step 5: Write failing integration tests for new prompt loop**

Add to `tests/test_propose_optimizations.py`:

```python
def test_main_prompt_none_marks_processed_immediately(tmp_path):
    """When _synthesize_prompt_patch returns None, hashes are marked processed."""
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(prompt_opts=["vague rec"])])
    h = po._entry_hash("Do you have product X with attr Y=3?", "prompt", "vague rec")

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=None):
        po.main(dry_run=False)

    saved = set(processed.read_text().splitlines()) if processed.exists() else set()
    assert h in saved


def test_main_prompt_rewrites_file_via_rewrite_prompt_file(tmp_path):
    """main() calls _rewrite_prompt_file and writes result to data/prompts/<target>."""
    import agent.knowledge_loader as kl
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(prompt_opts=["Add grounding guard"])])

    patch_result = {"target_file": "answer.md", "content": "## Guard\nNever emit empty."}

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=patch_result), \
         patch.object(po, "_rewrite_prompt_file", return_value="# Answer\n\nNever emit empty.\n") as mock_rewrite, \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    mock_rewrite.assert_called_once()
    call_args = mock_rewrite.call_args[0]
    assert call_args[0] == "answer.md"
    assert "Add grounding guard" in call_args[1]

    dest = prompts_dir / "answer.md"
    assert dest.exists()
    assert "Never emit empty" in dest.read_text()


def test_main_prompt_groups_multiple_recs_for_same_target(tmp_path):
    """Two prompt recs for same target_file → one _rewrite_prompt_file call with both."""
    import agent.knowledge_loader as kl
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    entry1 = _eval_entry(prompt_opts=["rec-A"])
    entry2 = _eval_entry(prompt_opts=["rec-B"])
    _write_eval_log(eval_log, [entry1, entry2])

    patch_result = {"target_file": "answer.md", "content": "## X\nDo X."}

    def passthrough_cluster(items, *a, **k):
        return [(rec, ent, [h]) for rec, ent, h in items]

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_cluster_recs", side_effect=passthrough_cluster), \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=patch_result), \
         patch.object(po, "_rewrite_prompt_file", return_value="rewritten") as mock_rewrite, \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    assert mock_rewrite.call_count == 1
    call_args = mock_rewrite.call_args[0]
    recs_passed = call_args[1]
    assert len(recs_passed) == 2


def test_main_prompt_dry_run_prints_preview_no_write(tmp_path):
    """dry-run: _rewrite_prompt_file is called, preview printed, no file written."""
    eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed = _setup(tmp_path)
    _write_eval_log(eval_log, [_eval_entry(prompt_opts=["Add rule"])])

    patch_result = {"target_file": "answer.md", "content": "## X\nDo X."}

    patches = _base_patches(eval_log, rules_dir, security_dir, prompts_dir, prom_dir, processed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8], \
         patch.object(po, "_synthesize_rule", return_value=None), \
         patch.object(po, "_synthesize_security_gate", return_value=None), \
         patch.object(po, "_synthesize_prompt_patch", return_value=patch_result), \
         patch.object(po, "_rewrite_prompt_file", return_value="# Answer\n\nPreview.\n"), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=True)

    assert not (prompts_dir / "answer.md").exists()


def test_write_prompt_removed():
    """_write_prompt no longer exists after refactor."""
    assert not hasattr(po, "_write_prompt"), "_write_prompt should be removed"
```

- [ ] **Step 6: Run tests to confirm fail**

```bash
uv run pytest tests/test_propose_optimizations.py -k "rewrite_prompt_file or prompt_none or prompt_groups or prompt_dry_run or write_prompt_removed" -v
```
Expected: tests fail (old `_write_prompt` still exists, new loop not wired)

- [ ] **Step 7: Update existing `test_writes_prompt_md` to use new API**

In `tests/test_propose_optimizations.py`, replace `test_writes_prompt_md` (lines 103-120):

```python
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
         patch.object(po, "_rewrite_prompt_file",
                      return_value="# Answer\n\nNever emit empty grounding_refs.\n"), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    dest = prompts_dir / "answer.md"
    assert dest.exists()
    text = dest.read_text()
    assert "Never emit empty grounding_refs" in text
```

- [ ] **Step 8: Update `test_synthesize_prompt_patch_receives_existing_context` to add `_rewrite_prompt_file` mock**

The test at line 253 has `prompt_opts` set, so the prompt loop runs. In the new code `_rewrite_prompt_file` is called (not mocked → would call real LLM). Add mock:

Replace in `tests/test_propose_optimizations.py` (test at line ~253):
```python
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
         patch.object(po, "_rewrite_prompt_file", return_value="# Answer\n\nNever X.\n"), \
         patch.object(po, "_check_contradiction", return_value=None):
        po.main(dry_run=False)

    args = mock_prompt.call_args
    assert args[0][1] == "=== answer.md ===\n# Answer\n"
```

- [ ] **Step 9: Implement new prompt loop in `main()` + remove `_write_prompt`**

In `scripts/propose_optimizations.py`, replace the prompt loop section in `main()`:

Old (lines ~505-522):
```python
    for raw_rec, entry, all_hashes in prompt_clusters:
        print(f"[prompt] {raw_rec[:80]}...")
        patch_result = _synthesize_prompt_patch(raw_rec, prompts_md, model, cfg)
        if patch_result is None:
            new_processed.update(all_hashes)
            print("  → skip (null/vague)")
            continue
        conflict = _check_contradiction(patch_result.get("content", ""), prompts_md, model, cfg)
        if conflict:
            print(f"  → skip (contradiction: {conflict})")
            continue
        if dry_run:
            print(f"  → [DRY RUN] {patch_result['target_file']}: {patch_result['content'][:80]}")
        else:
            dest = _write_prompt(patch_result, entry, raw_rec)
            new_processed.update(all_hashes)
            written += 1
            prompts_md = knowledge_loader.existing_prompts_text()
```

New:
```python
    # Collect target_file → [(raw_rec, all_hashes)] using _synthesize_prompt_patch for routing only
    target_to_recs: dict[str, list[tuple[str, list[str]]]] = {}
    for raw_rec, entry, all_hashes in prompt_clusters:
        print(f"[prompt] {raw_rec[:80]}...")
        patch_result = _synthesize_prompt_patch(raw_rec, prompts_md, model, cfg)
        if patch_result is None:
            new_processed.update(all_hashes)
            print("  → skip (null/vague)")
            continue
        target = patch_result["target_file"]
        target_to_recs.setdefault(target, []).append((raw_rec, all_hashes))

    for target, rec_groups in target_to_recs.items():
        all_recs = [r for r, _ in rec_groups]
        all_hashes_flat = [h for _, hs in rec_groups for h in hs]
        rewritten = _rewrite_prompt_file(target, all_recs, model, cfg)
        if rewritten is None:
            print(f"  → skip {target} (rewrite failed)")
            continue
        if dry_run:
            print(f"  → [DRY RUN] {target}: {rewritten[:200]}")
        else:
            (_PROMPTS_DIR / target).write_text(rewritten, encoding="utf-8")
            print(f"[propose] rewrote {target}")
            new_processed.update(all_hashes_flat)
            written += 1
            prompts_md = knowledge_loader.existing_prompts_text()
```

Also delete the `_write_prompt` function (lines 353-368).

- [ ] **Step 10: Run all tests**

```bash
uv run pytest tests/test_propose_optimizations.py -v
```
Expected: all tests PASS. Note: `test_dry_run_writes_nothing` should still pass since `_PROMPTS_OPTIMIZED_DIR` is still patched and no files are written in dry-run.

- [ ] **Step 11: Verify `_write_prompt` truly gone**

```bash
grep -n "_write_prompt" scripts/propose_optimizations.py
```
Expected: no output

- [ ] **Step 12: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 13: Commit**

```bash
git add scripts/propose_optimizations.py tests/test_propose_optimizations.py
git commit -m "feat(optimize): replace append-only prompt patch with full file rewrite via _rewrite_prompt_file"
```
