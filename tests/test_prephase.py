from unittest.mock import MagicMock
from agent.prephase import run_prephase, PrephaseResult


def _make_vm(agents_md="AGENTS CONTENT", bin_sql="SQL CONTENT"):
    vm = MagicMock()
    agents_r = MagicMock(); agents_r.content = agents_md
    bin_r = MagicMock(); bin_r.content = bin_sql
    def _read(req):
        if req.path in ("/AGENTS.MD", "/AGENTS.md"):
            return agents_r
        if req.path == "/bin/sql":
            return bin_r
        raise Exception(f"unexpected read: {req.path}")
    vm.read.side_effect = _read
    return vm


def test_prephase_result_fields():
    """PrephaseResult has exactly the expected fields including agent_id and current_date."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(PrephaseResult)}
    assert fields == {
        "agents_md_content", "agents_md_path", "db_schema",
        "agents_md_index", "schema_digest", "agent_id", "current_date", "task_type",
    }


def test_run_prephase_no_system_prompt_param():
    """run_prephase() takes only (vm, task_text) — no system_prompt_text."""
    import inspect
    sig = inspect.signature(run_prephase)
    assert "system_prompt_text" not in sig.parameters


def test_normal_mode_reads_only_agents_md():
    """Normal mode: exactly 1 vm.read call (AGENTS.MD)."""
    vm = _make_vm()
    result = run_prephase(vm, "find products")
    assert vm.read.call_count == 1
    assert result.agents_md_content == "AGENTS CONTENT"


def test_normal_mode_no_tree_no_context():
    """vm.tree and vm.context are never called."""
    vm = _make_vm()
    run_prephase(vm, "task")
    assert vm.tree.call_count == 0
    assert vm.context.call_count == 0


def test_agents_md_not_found():
    """If AGENTS.MD missing, agents_md_content is empty, no crash."""
    vm = MagicMock()
    vm.read.side_effect = Exception("not found")
    result = run_prephase(vm, "task")
    assert result.agents_md_content == ""
    assert result.agents_md_path == ""


def test_prephase_result_has_db_schema_field():
    """PrephaseResult now has db_schema field."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(PrephaseResult)}
    assert "db_schema" in fields


def test_normal_mode_reads_schema():
    """Normal mode calls vm.exec for schema and digest queries."""
    vm = MagicMock()
    agents_r = MagicMock(); agents_r.content = "AGENTS CONTENT"
    exec_r = MagicMock(); exec_r.stdout = "CREATE TABLE products ..."
    vm.read.return_value = agents_r
    vm.exec.return_value = exec_r
    result = run_prephase(vm, "find products")
    # Called for .schema + PRAGMA table_info (4 tables) + PRAGMA foreign_key_list (4) + SELECT key
    assert vm.exec.call_count >= 1
    assert result.db_schema == "CREATE TABLE products ..."


def test_schema_exec_fail_sets_empty_db_schema():
    """vm.exec exception → db_schema is empty string, no crash."""
    vm = MagicMock()
    agents_r = MagicMock(); agents_r.content = "AGENTS"
    vm.read.return_value = agents_r
    vm.exec.side_effect = Exception("exec failed")
    result = run_prephase(vm, "task")
    assert result.db_schema == ""


def _make_vm_with_schema(agents_md="## Brand Aliases\nheco = Heco", schema="CREATE TABLE products"):
    """VM mock that handles read (AGENTS.MD) and exec (.schema + PRAGMA + SELECT)."""
    vm = MagicMock()
    agents_r = MagicMock()
    agents_r.content = agents_md

    def _read(req):
        if req.path in ("/AGENTS.MD", "/AGENTS.md"):
            return agents_r
        raise Exception(f"unexpected read: {req.path}")

    def _exec(req):
        r = MagicMock()
        r.stdout = ""
        if req.args and req.args[0] == ".schema":
            r.stdout = schema
        elif req.args and "PRAGMA" in req.args[0]:
            r.stdout = "cid,name,type,notnull,dflt_value,pk\n0,sku,TEXT,1,,1\n1,brand,TEXT,0,,0"
        elif req.args and "product_properties" in req.args[0] and "COUNT" in req.args[0]:
            r.stdout = "key,cnt,text_cnt,num_cnt\ndiameter_mm,100,0,100\nscrew_type,80,80,0"
        elif req.args and "foreign_key_list" in req.args[0]:
            r.stdout = ""
        return r

    vm.read.side_effect = _read
    vm.exec.side_effect = _exec
    return vm



def test_agents_md_index_populated():
    """agents_md_index has parsed sections from AGENTS.MD."""
    vm = _make_vm_with_schema()
    result = run_prephase(vm, "find Heco screws")
    assert "brand_aliases" in result.agents_md_index
    assert result.agents_md_index["brand_aliases"] == ["heco = Heco"]


def test_agents_md_index_empty_when_no_agents_md():
    """agents_md_index is empty dict if AGENTS.MD not found."""
    vm = MagicMock()
    vm.read.side_effect = Exception("not found")
    exec_r = MagicMock(); exec_r.stdout = ""
    vm.exec.return_value = exec_r
    result = run_prephase(vm, "task")
    assert result.agents_md_index == {}


def test_schema_digest_has_tables():
    """schema_digest['tables'] has product-related tables."""
    vm = _make_vm_with_schema()
    result = run_prephase(vm, "task")
    assert "tables" in result.schema_digest
    assert "products" in result.schema_digest["tables"]


def test_schema_digest_has_top_keys():
    """schema_digest['top_keys'] lists top property keys."""
    vm = _make_vm_with_schema()
    result = run_prephase(vm, "task")
    assert "top_keys" in result.schema_digest
    assert "diameter_mm" in result.schema_digest["top_keys"]


def test_schema_digest_value_type_map():
    """schema_digest['value_type_map'] maps key to text/number."""
    vm = _make_vm_with_schema()
    result = run_prephase(vm, "task")
    vt = result.schema_digest.get("value_type_map", {})
    assert vt.get("diameter_mm") == "number"
    assert vt.get("screw_type") == "text"


def test_schema_digest_empty_on_exec_failure():
    """schema_digest is empty dict if all exec calls fail."""
    vm = MagicMock()
    agents_r = MagicMock(); agents_r.content = "## Brand Aliases\nheco = Heco"
    vm.read.return_value = agents_r
    vm.exec.side_effect = Exception("exec failed")
    result = run_prephase(vm, "task")
    assert result.schema_digest == {}


def test_prephase_calls_bin_date_and_bin_id():
    """run_prephase() calls vm.exec with /bin/date and /bin/id after AGENTS.MD read."""
    vm = MagicMock()
    agents_r = MagicMock(); agents_r.content = "AGENTS CONTENT"
    vm.read.return_value = agents_r

    date_r = MagicMock(); date_r.stdout = "2026-05-14"
    id_r = MagicMock(); id_r.stdout = "customer-42"

    def _exec(req):
        if req.path == "/bin/date":
            return date_r
        if req.path == "/bin/id":
            return id_r
        r = MagicMock(); r.stdout = ""
        return r

    vm.exec.side_effect = _exec
    result = run_prephase(vm, "find products")

    exec_paths = [c.args[0].path for c in vm.exec.call_args_list]
    assert "/bin/date" in exec_paths
    assert "/bin/id" in exec_paths
    assert result.current_date == "2026-05-14"
    assert result.agent_id == "customer-42"


def test_prephase_bin_date_failure_produces_empty_string():
    """If /bin/date or /bin/id raises, agent_id/current_date are empty strings — no crash."""
    vm = MagicMock()
    agents_r = MagicMock(); agents_r.content = "AGENTS"
    vm.read.return_value = agents_r

    def _exec(req):
        if req.path in ("/bin/date", "/bin/id"):
            raise Exception("not found")
        r = MagicMock(); r.stdout = ""
        return r

    vm.exec.side_effect = _exec
    result = run_prephase(vm, "task")
    assert result.current_date == ""
    assert result.agent_id == ""


def test_prephase_schema_tables_includes_carts():
    """_SCHEMA_TABLES includes carts and cart_items."""
    from agent.prephase import _SCHEMA_TABLES
    assert "carts" in _SCHEMA_TABLES
    assert "cart_items" in _SCHEMA_TABLES


def test_build_schema_digest_assigns_role_products():
    from agent.prephase import _infer_role
    cols = [{"name": "sku", "type": "TEXT"}, {"name": "kind_id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}]
    assert _infer_role(cols) == "products"


def test_build_schema_digest_assigns_role_kinds():
    from agent.prephase import _infer_role
    cols = [{"name": "id", "type": "INTEGER"}, {"name": "category_id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}]
    assert _infer_role(cols) == "kinds"


def test_build_schema_digest_assigns_role_properties():
    from agent.prephase import _infer_role
    cols = [{"name": "sku", "type": "TEXT"}, {"name": "key", "type": "TEXT"}, {"name": "value_text", "type": "TEXT"}]
    assert _infer_role(cols) == "properties"


def test_build_schema_digest_assigns_role_other():
    from agent.prephase import _infer_role
    cols = [{"name": "id", "type": "INTEGER"}, {"name": "label", "type": "TEXT"}]
    assert _infer_role(cols) == "other"


def test_format_schema_digest_includes_role():
    from agent.pipeline import _format_schema_digest
    digest = {
        "tables": {
            "product_kinds": {
                "columns": [{"name": "id", "type": "INTEGER"}, {"name": "category_id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}],
                "role": "kinds",
            }
        },
        "top_keys": [],
        "value_type_map": {},
    }
    out = _format_schema_digest(digest)
    assert "product_kinds" in out
    assert "role=kinds" in out


def test_merge_schema_from_create_table():
    from agent.prephase import merge_schema_from_sqlite_results
    digest = {"tables": {}, "top_keys": [], "value_type_map": {}}
    csv_text = (
        "name,sql\n"
        '"product_kinds","CREATE TABLE product_kinds (id INTEGER PRIMARY KEY, category_id INTEGER, name TEXT)"\n'
    )
    added = merge_schema_from_sqlite_results(digest, [csv_text])
    assert "product_kinds" in added
    assert "product_kinds" in digest["tables"]
    cols = {c["name"] for c in digest["tables"]["product_kinds"]["columns"]}
    assert {"id", "category_id", "name"}.issubset(cols)
    assert digest["tables"]["product_kinds"]["role"] == "kinds"


def test_merge_idempotent():
    from agent.prephase import merge_schema_from_sqlite_results
    digest = {"tables": {}, "top_keys": [], "value_type_map": {}}
    csv_text = (
        "name,sql\n"
        '"product_kinds","CREATE TABLE product_kinds (id INTEGER, category_id INTEGER, name TEXT)"\n'
    )
    merge_schema_from_sqlite_results(digest, [csv_text])
    added2 = merge_schema_from_sqlite_results(digest, [csv_text])
    assert added2 == []
    assert len(digest["tables"]["product_kinds"]["columns"]) == 3


def test_merge_skips_unparseable_sql():
    from agent.prephase import merge_schema_from_sqlite_results
    digest = {"tables": {}, "top_keys": [], "value_type_map": {}}
    csv_text = "name,sql\n\"weird\",\"NOT A VALID CREATE STATEMENT\"\n"
    added = merge_schema_from_sqlite_results(digest, [csv_text])
    assert added == []
    assert "weird" not in digest["tables"]


def test_merge_ignores_non_create_rows():
    from agent.prephase import merge_schema_from_sqlite_results
    digest = {"tables": {}, "top_keys": [], "value_type_map": {}}
    csv_text = (
        "name,sql\n"
        '"idx_x","CREATE INDEX idx_x ON products(sku)"\n'
    )
    added = merge_schema_from_sqlite_results(digest, [csv_text])
    assert added == []


def test_task_type_sql_products():
    from agent.prephase import _determine_task_type, PrephaseResult
    pre = PrephaseResult(schema_digest={"tables": {"products": {"columns": []}}})
    result = _determine_task_type("find SKU ABC-001 in inventory", pre)
    assert result == "sql"


def test_task_type_default_sql():
    from agent.prephase import _determine_task_type, PrephaseResult
    pre = PrephaseResult()
    result = _determine_task_type("do something", pre)
    assert result == "sql"


def test_task_type_read():
    from agent.prephase import _determine_task_type, PrephaseResult
    pre = PrephaseResult()
    result = _determine_task_type("read the file /proc/stores/S01.json", pre)
    assert result == "sql"  # "read" type dropped; defaults to "sql"


def test_prephase_result_has_task_type():
    from agent.prephase import PrephaseResult
    pre = PrephaseResult(task_type="compute")
    assert pre.task_type == "compute"


def test_prephase_result_default_task_type():
    from agent.prephase import PrephaseResult
    pre = PrephaseResult()
    assert pre.task_type == "sql"
