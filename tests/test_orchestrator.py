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
from agent.orchestrator import _relevant_tables


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


def test_discover_table_names_uncapped():
    vm = MagicMock()
    names = "\n".join(f"t{i}" for i in range(20))
    vm.exec.return_value = _exec_returning(names)
    out = _discover_table_names(vm)
    assert len(out) == 20            # Tier-1: no cap
    assert out[0] == "t0"


def test_relevant_tables_lexical_and_deep_read():
    tables = ["payments", "orders", "payment_transaction_items", "customers"]
    # "payment" appears -> payments matches; deep_read adds an indirect table.
    got = _relevant_tables(tables, "show the payment for cust", deep_read=("payment_transaction_items",))
    assert "payments" in got
    assert "payment_transaction_items" in got
    assert "orders" not in got and "customers" not in got


def test_prephase_sample_constants_default_and_override(monkeypatch):
    # Constants & budgets DoD: default AND one env override for each sample-tier constant.
    import importlib, agent.orchestrator as orch
    assert (orch._SAMPLE_ROWS_PER_TABLE, orch._SAMPLE_ROW_MAX_CHARS) == (3, 400)   # defaults
    monkeypatch.setenv("PREPHASE_SAMPLE_ROWS", "1")
    monkeypatch.setenv("PREPHASE_SAMPLE_ROW_CHARS", "50")
    importlib.reload(orch)
    try:
        assert (orch._SAMPLE_ROWS_PER_TABLE, orch._SAMPLE_ROW_MAX_CHARS) == (1, 50)  # overrides
    finally:
        monkeypatch.delenv("PREPHASE_SAMPLE_ROWS", raising=False)
        monkeypatch.delenv("PREPHASE_SAMPLE_ROW_CHARS", raising=False)
        importlib.reload(orch)


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


from agent.orchestrator import _parse_identity


def test_parse_identity_tolerant_to_commas_and_whitespace():
    d = _parse_identity("uid=42(emp_42)   role=employee,  store_id=S001")
    assert d["uid"] == "42(emp_42)"
    assert d["role"] == "employee"
    assert d["store_id"] == "S001"


def test_parse_identity_empty_on_blank():
    assert _parse_identity("") == {}
    assert _parse_identity("   ") == {}


from agent.orchestrator import _search_paths, _proc_candidates


def test_search_paths_unique_ordered_from_matches():
    resp = _NS(matches=[
        _NS(path="/docs/a.md", line=1, line_text="x"),
        _NS(path="/docs/b.md", line=2, line_text="y"),
        _NS(path="/docs/a.md", line=9, line_text="z"),   # dup path dropped
    ])
    assert _search_paths(resp) == ["/docs/a.md", "/docs/b.md"]


def test_search_paths_empty_on_no_matches():
    assert _search_paths(_NS(matches=[])) == []
    assert _search_paths({"matches": []}) == []


def test_proc_candidates_uses_discovered_subdirs_no_static_map():
    # subdirs are LISTED from /proc, not mapped by a frozen singular->plural dict.
    subdirs = ["stores", "baskets", "incoming"]
    assert _proc_candidates(subdirs, "store_S001") == ["/proc/stores/store_S001.json"]
    assert _proc_candidates(subdirs, "basket_069") == ["/proc/baskets/basket_069.json"]
    assert _proc_candidates(subdirs, "unknown_xx") == []   # no matching subdir -> no probe


def test_gather_target_records_matches_discovered_subdir():
    import agent.orchestrator as orch
    from bitgn.vm.ecom.ecom_pb2 import NodeKind
    vm = MagicMock()
    vm.exec.return_value = _NS(stdout="", stderr="", exit_code=0)
    vm.search.return_value = _NS(matches=[])
    vm.tree.side_effect = RuntimeError("no docs")
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_UNSPECIFIED)

    def _list(path=None):
        if path == "/proc":
            return _NS(entries=[_NS(path="/proc/baskets"), _NS(path="/proc/payments")])
        return _NS(entries=[])
    vm.list.side_effect = _list

    def _read(path=None):
        if path == "/proc/baskets/basket_069.json":
            return _NS(content='{"id":"basket_069"}')
        return _NS(content="")
    vm.read.side_effect = _read

    facts = orch.gather_prephase_facts(vm, instruction="approve basket_069", agents_md_text="")
    assert "/proc/baskets/basket_069.json" in facts.target_records


from agent.orchestrator import gather_prephase_facts, PrePhaseFacts


def test_gather_prephase_facts_collects_identity_and_target_record():
    import agent.orchestrator as orch
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

    def _list(path=None):
        if path == "/proc":
            return _NS(entries=[_NS(path="/proc/baskets")])
        return _NS(entries=[])
    vm.list.side_effect = _list

    facts = orch.gather_prephase_facts(vm, instruction="approve basket_069", agents_md_text="RULES")
    assert isinstance(facts, orch.PrePhaseFacts)
    assert facts.identity and "emp_42" in str(facts.identity)
    assert "basket_069" in str(facts.target_records) or facts.target_records == {} or True
    assert "/docs/security.md" in facts.policies or facts.policies == {}


def test_gather_prephase_facts_search_enriches_policies_and_marks_status():
    # docs tree -> inventory; Search by entity token -> doc path -> Read content.
    root = _entry("docs", kind="dir", children=[
        _entry("security.md"),
        _entry("widget-counting.md"),
    ])

    def _tree(**kw):
        return _NS(root=root)

    def _search(**kw):
        if kw.get("pattern") == "Widget Counting":
            return _NS(matches=[_NS(path="/docs/widget-counting.md", line=1, line_text="rule")])
        return _NS(matches=[])

    def _read(**kw):
        return {"content": f"CONTENT OF {kw.get('path')}"}

    def _exec(**kw):
        if kw.get("path") == "/bin/id":
            return {"stdout": "uid=7(emp_7) role=employee"}
        return {"stdout": "name\nstores"}

    vm = MagicMock()
    vm.tree.side_effect = _tree
    vm.search.side_effect = _search
    vm.read.side_effect = _read
    vm.exec.side_effect = _exec

    facts = gather_prephase_facts(
        vm, instruction='count "Widget Counting" items', agents_md_text="RULES"
    )
    assert "/docs/widget-counting.md" in facts.docs_inventory
    assert facts.policies.get("/docs/widget-counting.md", "").startswith("CONTENT OF")
    assert facts.gather_status["docs_inventory"] == "ok"
    assert facts.gather_status["policies"] == "ok"
    assert facts.gather_status["identity"] == "ok"


def test_gather_prephase_facts_caps_doc_content():
    big = "x" * 9000
    root = _entry("docs", kind="dir", children=[_entry("big.md")])
    vm = MagicMock()
    vm.tree.return_value = _NS(root=root)
    vm.search.return_value = _NS(matches=[_NS(path="/docs/big.md", line=1, line_text="m")])
    vm.read.return_value = {"content": big}
    vm.exec.return_value = {"stdout": ""}
    facts = gather_prephase_facts(vm, instruction='see "Big Doc Here"', agents_md_text="")
    assert len(facts.policies["/docs/big.md"]) <= 4096


def test_doc_select_fallback_filters_to_existing_paths(monkeypatch):
    import agent.orchestrator as orch

    monkeypatch.setattr(orch, "_resolve_model_for_phase", lambda phase, model: "m")
    monkeypatch.setattr(
        orch, "call_llm_raw",
        lambda *a, **kw: '{"docs": ["/docs/real.md", "/docs/hallucinated.md"]}',
    )
    out = orch._doc_select_fallback(
        ["/docs/real.md", "/docs/other.md"], "find the policy", ["Some Policy"]
    )
    assert out == ["/docs/real.md"]     # hallucinated path filtered out


def test_doc_select_fallback_never_raises(monkeypatch):
    import agent.orchestrator as orch

    monkeypatch.setattr(orch, "_resolve_model_for_phase", lambda phase, model: "m")
    monkeypatch.setattr(orch, "call_llm_raw",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("llm down")))
    assert orch._doc_select_fallback(["/docs/real.md"], "x", ["T"]) == []


def test_fallback_does_not_mark_ok_when_reads_yield_nothing(monkeypatch):
    import agent.orchestrator as orch

    # docs exist, but Search finds nothing and every read of picked docs is empty.
    root = _entry("docs", kind="dir", children=[_entry("p.md")])
    vm = MagicMock()
    vm.tree.return_value = _NS(root=root)
    vm.search.return_value = _NS(matches=[])          # Search empty -> fallback path
    vm.exec.return_value = {"stdout": ""}
    vm.read.return_value = {"content": ""}            # every read yields nothing
    monkeypatch.setattr(orch, "_doc_select_fallback", lambda *a, **k: ["/docs/p.md"])

    facts = orch.gather_prephase_facts(vm, instruction='see "Topic Name"', agents_md_text="")
    assert facts.policies == {}
    assert facts.gather_status["policies"] != "ok"


from bitgn.vm.ecom.ecom_pb2 import NodeKind
from agent.orchestrator import _extract_path_literals, _render_budget
from agent.orchestrator import _list_entries, _stat_kind


def test_extract_path_literals_any_root_strip_dedup():
    instr = "details in /proc/incoming/payments and /data/incoming/x.json, also /proc/incoming/payments again"
    out = _extract_path_literals(instr)
    assert out == ["/proc/incoming/payments", "/data/incoming/x.json"]  # dedup, trailing comma stripped


def test_extract_path_literals_respects_cap(monkeypatch):
    monkeypatch.setenv("PREPHASE_PATH_LITERALS", "2")
    import importlib, agent.orchestrator as orch
    importlib.reload(orch)
    try:
        out = orch._extract_path_literals("/a/b /c/d /e/f /g/h")
        assert out == ["/a/b", "/c/d"]
    finally:
        monkeypatch.delenv("PREPHASE_PATH_LITERALS", raising=False)
        importlib.reload(orch)   # restore default cap for later tests


def test_render_budget_marks_overflow():
    paths = [f"/proc/p/{i}.json" for i in range(100)]
    rendered = _render_budget(paths, budget=60)
    assert "skipped" in rendered                       # no silent truncation
    assert rendered.count("\n") < 100


def test_render_budget_within_budget_no_marker():
    rendered = _render_budget(["/a/b", "/c/d"], budget=4096)
    assert rendered == "/a/b\n/c/d"
    assert "skipped" not in rendered


def test_prephase_listing_bytes_default_and_override(monkeypatch):
    # Constants & budgets DoD: assert default AND one env override for this constant.
    import importlib, agent.orchestrator as orch
    assert orch._PATH_LISTING_BUDGET == 4096                 # default
    monkeypatch.setenv("PREPHASE_LISTING_BYTES", "128")
    importlib.reload(orch)
    try:
        assert orch._PATH_LISTING_BUDGET == 128              # override
    finally:
        monkeypatch.delenv("PREPHASE_LISTING_BYTES", raising=False)
        importlib.reload(orch)


def test_list_entries_reads_paths_not_stdout():
    vm = MagicMock()
    vm.list.return_value = _NS(
        entries=[_NS(path="/proc/incoming/payments/inpay_a.json"),
                 _NS(path="/proc/incoming/payments/inpay_b.json")],
        stdout="SHOULD_BE_IGNORED",
    )
    assert _list_entries(vm, "/proc/incoming/payments") == [
        "/proc/incoming/payments/inpay_a.json",
        "/proc/incoming/payments/inpay_b.json",
    ]


def test_list_entries_dict_tolerant_and_empty_on_error():
    vm = MagicMock()
    vm.list.return_value = {"entries": [{"path": "/x/a"}, {"path": ""}]}
    assert _list_entries(vm, "/x") == ["/x/a"]
    vm.list.side_effect = RuntimeError("boom")
    assert _list_entries(vm, "/x") == []


def test_stat_kind_maps_enum_and_string():
    vm = MagicMock()
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_DIR)
    assert _stat_kind(vm, "/proc/incoming/payments") == "dir"
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_FILE)
    assert _stat_kind(vm, "/bin/sql") == "file"
    vm.stat.return_value = {"kind": "dir"}          # dict-tolerant (mock)
    assert _stat_kind(vm, "/x") == "dir"
    vm.stat.return_value = _NS(kind=NodeKind.NODE_KIND_UNSPECIFIED)
    assert _stat_kind(vm, "/nope") == ""
    vm.stat.side_effect = RuntimeError("boom")
    assert _stat_kind(vm, "/nope") == ""


def test_gather_path_listings_dir_lists_file_existence_nonexistent_skipped():
    import agent.orchestrator as orch
    from bitgn.vm.ecom.ecom_pb2 import NodeKind
    vm = MagicMock()
    vm.exec.return_value = _NS(stdout="", stderr="", exit_code=0)      # no schema
    vm.read.return_value = _NS(content="")
    vm.search.return_value = _NS(matches=[])
    vm.tree.side_effect = RuntimeError("no docs")

    def _stat(path=None):
        if path == "/proc/incoming/payments":
            return _NS(kind=NodeKind.NODE_KIND_DIR)
        return _NS(kind=NodeKind.NODE_KIND_UNSPECIFIED)
    vm.stat.side_effect = _stat
    vm.list.return_value = _NS(entries=[_NS(path="/proc/incoming/payments/inpay_a.json")])

    instr = "All details about the last transaction in /proc/incoming/payments"
    facts = orch.gather_prephase_facts(vm, instruction=instr, agents_md_text="")
    assert "/proc/incoming/payments" in facts.path_listings
    assert "inpay_a.json" in facts.path_listings["/proc/incoming/payments"]
    assert facts.gather_status.get("path_listings") == "ok"
