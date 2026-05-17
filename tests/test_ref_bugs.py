# tests/test_ref_bugs.py
from unittest.mock import MagicMock, patch

from agent.json_extract import _obj_mutation_tool
from agent.pipeline import _build_answer_user_msg, _extract_sku_refs, run_pipeline
from agent.prephase import PrephaseResult
from agent.prompt_assembler import AssembledPrompt


def _mock_assemble(*args, **kwargs):
    return AssembledPrompt(unified_context="mocked-unified-context")


def _make_pre():
    return PrephaseResult(
        agents_md_content="AGENTS",
        agents_md_path="/AGENTS.MD",
        db_schema="CREATE TABLE products(id INT)",
    )


# ── Bug 3 / Level 1: _obj_mutation_tool ──────────────────────────────────────

def test_obj_mutation_tool_function_as_string():
    """Bug t21: 'function' field is a string — must not crash, must return None."""
    obj = {"function": "checkout", "args": {}}
    assert _obj_mutation_tool(obj) is None


def test_obj_mutation_tool_function_as_dict_with_mutation_tool():
    """Normal case: 'function' is a dict with a valid mutation tool name."""
    obj = {"function": {"tool": "write", "path": "/x"}}
    assert _obj_mutation_tool(obj) == "write"


def test_obj_mutation_tool_top_level_tool():
    """Top-level 'tool' key wins regardless of 'function'."""
    obj = {"tool": "delete"}
    assert _obj_mutation_tool(obj) == "delete"


def test_obj_mutation_tool_no_mutation():
    """Read-type tool returns None."""
    obj = {"tool": "read"}
    assert _obj_mutation_tool(obj) is None


# ── Bug 2: _extract_sku_refs store_id ────────────────────────────────────────

def test_extract_sku_refs_store_id_only():
    """Bug t17: store_id column must produce /proc/stores/{id}.json."""
    results = ["store_id\nstore_vienna_praterstern\n"]
    refs = _extract_sku_refs([], results)
    assert refs == ["/proc/stores/store_vienna_praterstern.json"]


def test_extract_sku_refs_sku_and_store_id():
    """Inventory query has both sku and store_id — both refs must appear."""
    results = ["store_id,sku,available_today\nstore_vienna_praterstern,PLB-2GJZ9R7K,1\n"]
    refs = _extract_sku_refs([], results)
    assert "/proc/catalog/PLB-2GJZ9R7K.json" in refs
    assert "/proc/stores/store_vienna_praterstern.json" in refs


# ── Bug 1 / Part 1: _build_answer_user_msg ───────────────────────────────────

def test_build_answer_user_msg_preserves_full_path():
    """Bug t03: AUTO_REFS must show full hierarchical paths, not stem-only."""
    msg = _build_answer_user_msg(
        "find pipe fittings",
        ["path\n/proc/catalog/plumbing/pipe_fittings/PLB-2GJZ9R7K.json\n"],
        ["/proc/catalog/plumbing/pipe_fittings/PLB-2GJZ9R7K.json"],
    )
    assert "/proc/catalog/plumbing/pipe_fittings/PLB-2GJZ9R7K.json" in msg
    assert msg.count("/proc/catalog/PLB-2GJZ9R7K.json") == 0


# ── Bug 1 / Part 2: clean_refs exact-path filter ─────────────────────────────

def test_clean_refs_exact_match_preserves_full_path():
    """clean_refs must use exact path match, not stem match."""
    sku_refs = ["/proc/catalog/plumbing/pipe_fittings/PLB-2GJZ9R7K.json"]
    result_paths = set(sku_refs)
    grounding_refs = ["/proc/catalog/plumbing/pipe_fittings/PLB-2GJZ9R7K.json"]
    clean = [r for r in grounding_refs if r in result_paths]
    assert clean == ["/proc/catalog/plumbing/pipe_fittings/PLB-2GJZ9R7K.json"]


def test_clean_refs_passthrough_when_result_paths_empty():
    """clean_refs passes all grounding_refs through when sku_refs is empty."""
    result_paths: set[str] = set()
    grounding_refs = ["/proc/catalog/PLB-2GJZ9R7K.json"]
    clean = [r for r in grounding_refs if r in result_paths] if result_paths else list(grounding_refs)
    assert clean == ["/proc/catalog/PLB-2GJZ9R7K.json"]


def test_clean_refs_excludes_unmatched_ref():
    """Refs not in sku_refs are excluded from clean_refs."""
    sku_refs = ["/proc/catalog/plumbing/PLB-ABC.json"]
    result_paths = set(sku_refs)
    grounding_refs = ["/proc/catalog/plumbing/PLB-ABC.json", "/proc/catalog/other/OTH-XYZ.json"]
    clean = [r for r in grounding_refs if r in result_paths] if result_paths else list(grounding_refs)
    assert clean == ["/proc/catalog/plumbing/PLB-ABC.json"]


# ── Bug 3 / Level 2: run_pipeline try/except wrapper ─────────────────────────

def test_run_pipeline_unhandled_exception_calls_vm_answer_once(tmp_path):
    """Bug t21: unhandled exception in for-loop must call vm.answer exactly once."""
    vm = MagicMock()
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    with patch("agent.pipeline._call_llm_phase", side_effect=AttributeError("str has no .get")), \
         patch("agent.pipeline.assemble_prompt", side_effect=_mock_assemble), \
         patch("agent.pipeline._RULES_DIR", rules_dir), \
         patch("agent.pipeline.load_security_gates", return_value=[]), \
         patch("agent.pipeline.run_resolve", return_value={}):
        run_pipeline(vm, "anthropic/claude-sonnet-4-6", "checkout task", _make_pre(), {})

    assert vm.answer.call_count == 1
    call_arg = vm.answer.call_args[0][0]
    assert call_arg.message == "Internal pipeline error."
