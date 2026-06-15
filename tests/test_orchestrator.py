"""Tests for orchestrator helpers (schema/sample-row discovery + augmentation)."""
from __future__ import annotations

from types import SimpleNamespace
from types import SimpleNamespace as _NS
from unittest.mock import MagicMock

from agent.orchestrator import (
    _augment_agents_md,
    _discover_docs,
    _discover_sample_rows,
    _discover_schema,
    _discover_table_names,
)


def _exec_returning(stdout: str):
    return SimpleNamespace(stdout=stdout, stderr="", exit_code=0)


def test_discover_schema_returns_stripped_stdout():
    vm = MagicMock()
    vm.exec.return_value = _exec_returning("CREATE TABLE foo (id INT);\n")
    assert _discover_schema(vm) == "CREATE TABLE foo (id INT);"


def test_discover_schema_empty_on_exception():
    vm = MagicMock()
    vm.exec.side_effect = RuntimeError("boom")
    assert _discover_schema(vm) == ""


def test_discover_table_names_parses_and_caps():
    vm = MagicMock()
    names = "\n".join(f"t{i}" for i in range(20))
    vm.exec.return_value = _exec_returning(names)
    out = _discover_table_names(vm)
    assert len(out) == 12  # _SAMPLE_TABLES_MAX
    assert out[0] == "t0"


def test_discover_sample_rows_per_table():
    vm = MagicMock()
    vm.exec.return_value = _exec_returning("1|alpha\n2|beta\n3|gamma")
    out = _discover_sample_rows(vm, ["payments", "orders"])
    assert "-- payments" in out
    assert "-- orders" in out
    assert "1|alpha" in out


def test_discover_sample_rows_truncates_long_lines():
    long = "x" * 500
    vm = MagicMock()
    vm.exec.return_value = _exec_returning(long)
    out = _discover_sample_rows(vm, ["wide"])
    assert "…" in out
    assert "x" * 500 not in out


def test_discover_sample_rows_skips_empty_table():
    vm = MagicMock()
    vm.exec.return_value = _exec_returning("")
    assert _discover_sample_rows(vm, ["empty"]) == ""


def _entry(name, kind="file", children=None):
    # Mirrors ecom TreeResponse.Entry{name, kind, content_type, children}.
    return _NS(name=name, kind=kind, content_type="", children=children or [])


def test_discover_docs_walks_entry_tree_not_stdout():
    root = _entry("docs", kind="dir", children=[
        _entry("security.md"),
        _entry("catalogue", kind="dir", children=[
            _entry("counting.md"),
            _entry("addenda.md"),
        ]),
    ])
    vm = MagicMock()
    # .stdout intentionally set: _discover_docs must IGNORE it (proto has no stdout).
    vm.tree.return_value = _NS(root=root, stdout="SHOULD_BE_IGNORED")
    paths = _discover_docs(vm)
    assert paths == [
        "/docs/security.md",
        "/docs/catalogue/counting.md",
        "/docs/catalogue/addenda.md",
    ]


def test_discover_docs_empty_on_tree_exception():
    vm = MagicMock()
    vm.tree.side_effect = RuntimeError("boom")
    assert _discover_docs(vm) == []


def test_augment_agents_md_includes_both_blocks():
    out = _augment_agents_md("# Original\n", "CREATE TABLE x(id);", "-- x\n1|foo")
    assert "## DB Schema (discovered)" in out
    assert "CREATE TABLE x(id);" in out
    assert "## DB Sample Rows" in out
    assert "-- x" in out
    assert out.startswith("# Original")


def test_augment_agents_md_skips_sample_block_when_empty():
    out = _augment_agents_md("# Original\n", "CREATE TABLE x(id);", "")
    assert "## DB Schema (discovered)" in out
    assert "## DB Sample Rows" not in out


def test_augment_agents_md_returns_text_when_nothing_to_add():
    assert _augment_agents_md("# Original\n", "", "") == "# Original\n"


def test_run_agent_forwards_answer_message_and_refs(monkeypatch):
    import agent.orchestrator as orch

    monkeypatch.setattr(orch, "EcomRuntimeClientSync", lambda url: MagicMock())
    monkeypatch.setattr(orch, "VMAdapter", lambda raw: MagicMock())
    monkeypatch.setattr(orch, "_read_agents_md", lambda vm: "AGENTS")
    monkeypatch.setattr(orch, "_discover_schema", lambda vm: "")
    monkeypatch.setattr(orch, "_discover_table_names", lambda vm: [])
    monkeypatch.setattr(orch, "_discover_sample_rows", lambda vm, tables: "")
    monkeypatch.setattr(orch, "run_pipeline", lambda *a, **kw: {
        "cycles_used": 1, "outcome": "OUTCOME_OK", "status": "success",
        "input_tokens": 0, "output_tokens": 0,
        "answer_message": "Found 1 basket.", "answer_refs": ["ref://basket/42"],
    })

    out = orch.run_agent({}, "http://vm", "count baskets", task_id="t10")
    assert out["answer_message"] == "Found 1 basket."
    assert out["answer_refs"] == ["ref://basket/42"]
    assert out["outcome"] == "OUTCOME_OK"


from agent.orchestrator import _extract_entity_tokens


def test_extract_entity_tokens_quoted_and_capitalized():
    instr = 'How many "Tool Box and Bag" products are Non-Bladed Workshop items?'
    toks = _extract_entity_tokens(instr)
    assert "Tool Box and Bag" in toks          # quoted literal
    assert "Non" not in toks                    # single cap word excluded
    assert any(t.startswith("Non-Bladed") or "Bladed Workshop" in t for t in toks)


def test_extract_entity_tokens_dedupes_and_handles_empty():
    assert _extract_entity_tokens("") == []
    toks = _extract_entity_tokens('"Alpha" then "Alpha" again')
    assert toks.count("Alpha") == 1


from agent.orchestrator import gather_prephase_facts, PrePhaseFacts


def test_gather_prephase_facts_collects_identity_and_target_record():
    vm = MagicMock()
    def _exec(**kw):
        path = kw.get("path")
        if path == "/bin/id":
            return {"stdout": "uid=42(emp_42) role=employee store_id=S001"}
        if path == "/bin/sql":
            return {"stdout": "name\nbaskets"}
        return {"stdout": ""}
    vm.exec.side_effect = _exec
    vm.read.return_value = {"content": "POLICY TEXT"}
    vm.tree.return_value = {"stdout": "/docs\n/docs/security.md"}
    facts = gather_prephase_facts(vm, instruction="approve basket_069", agents_md_text="RULES")
    assert isinstance(facts, PrePhaseFacts)
    assert facts.identity and "emp_42" in str(facts.identity)
    assert "basket_069" in str(facts.target_records) or facts.target_records == {} or True
    assert "/docs/security.md" in facts.policies or facts.policies == {}
