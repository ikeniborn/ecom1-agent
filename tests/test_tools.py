from agent.tools import TOOL_CATALOG, build_tool_catalog_block, validate_step


def test_known_rpc_valid_args_ok():
    assert validate_step("Read", {"path": "/d.md"}) is None
    assert validate_step("Exec", {"path": "/bin/sql", "stdin": "SELECT 1"}) is None
    assert validate_step("Exec", {"path": "/bin/sql", "args": ["SELECT 1"]}) is None


def test_unknown_rpc_rejected():
    err = validate_step("Foo", {"path": "/x"})
    assert err is not None and "not in catalog" in err and "Foo" in err


def test_bad_arg_key_rejected():
    err = validate_step("Read", {"pathh": "/x"})
    assert err is not None and "pathh" in err and "Read" in err


def test_missing_required_arg_rejected():
    err = validate_step("Read", {})
    assert err is not None and "required" in err.lower() and "path" in err


def test_catalog_block_is_markdown_listing_all_rpcs():
    block = build_tool_catalog_block()
    assert "TOOL CATALOG" in block
    for rpc in TOOL_CATALOG:
        assert rpc in block
    # the r012 /bin/sql lesson must be encoded as a structural note
    assert "stdin" in block and "/bin/sql" in block


def test_exec_catalog_documents_sql_stdin_channel():
    exec_entry = TOOL_CATALOG["Exec"]
    note = (exec_entry.get("note") or "").lower()
    assert "stdin" in note and "/bin/sql" in note


def test_catalog_keys_subset_of_proto_fields():
    """General drift guard: every required|optional arg key must be a real field on
    the matching proto Request, so validate_step never permits a key the runtime rejects."""
    from bitgn.vm.ecom.ecom_pb2 import (
        ReadRequest, ListRequest, TreeRequest, FindRequest, SearchRequest,
        ExecRequest, WriteRequest, DeleteRequest, StatRequest,
    )

    req_cls = {
        "Read": ReadRequest, "List": ListRequest, "Tree": TreeRequest,
        "Find": FindRequest, "Search": SearchRequest, "Exec": ExecRequest,
        "Write": WriteRequest, "Delete": DeleteRequest, "Stat": StatRequest,
    }
    for rpc, entry in TOOL_CATALOG.items():
        fields = {f.name for f in req_cls[rpc].DESCRIPTOR.fields}
        keys = entry["required"] | entry["optional"]
        missing = keys - fields
        assert not missing, f"{rpc} catalog keys not in proto: {missing}"


def test_all_catalog_examples_are_valid():
    """Every catalog `example` must itself pass validate_step — guards copy-paste drift."""
    for rpc, entry in TOOL_CATALOG.items():
        ex = entry["example"]
        assert validate_step(ex["rpc"], ex["args"]) is None, f"{rpc} example invalid"
