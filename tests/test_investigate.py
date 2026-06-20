# tests/test_investigate.py
import os
from agent.llm import _resolve_model_for_phase, _think_for_phase


def test_investigate_phase_is_fast_tier(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.delenv("ECOM_MODEL_INVESTIGATE", raising=False)
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "fast-model"
    assert _think_for_phase("INVESTIGATE") is False


def test_investigate_phase_override_wins(monkeypatch):
    monkeypatch.setenv("ECOM_MODEL_FAST", "fast-model")
    monkeypatch.setenv("ECOM_MODEL_INVESTIGATE", "explicit-model")
    assert _resolve_model_for_phase("INVESTIGATE", "default-model") == "explicit-model"


# append to tests/test_investigate.py
from agent.investigate import Note, Brief, render_brief


def test_brief_accumulates_notes_and_env():
    brief = Brief()
    brief.notes.append(Note(goal="find incident", tool="exec",
                            args={"path": "/bin/sql"}, observation_digest="3 rows",
                            lesson="incident id lives in fraud_reports",
                            refs_found=["/payments/p_1.json"]))
    brief.env["incident_id"] = "INC-7"
    assert len(brief.notes) == 1
    assert brief.env["incident_id"] == "INC-7"


def test_render_brief_is_compact_and_contains_env_and_lessons():
    brief = Brief()
    brief.notes.append(Note(goal="g", tool="read", args={"path": "/docs/x.md"},
                            observation_digest="policy says N=2", lesson="use N=2",
                            refs_found=[]))
    brief.env["governing_doc"] = "/docs/x.md"
    out = render_brief(brief)
    assert "INVESTIGATION_BRIEF" in out
    assert "use N=2" in out               # lesson surfaced
    assert "governing_doc" in out         # env surfaced
    assert "/docs/x.md" in out


def test_render_brief_empty_is_falsy_marker():
    assert render_brief(Brief()) == ""


# --- Task 3: read-only whitelist + tool dispatch ---
import pytest
from agent.investigate import is_readonly, run_tool, ToolRejected
from agent.mock_vm_spy import MockVMSpy, fixture_key


def test_is_readonly_allows_reads_and_select():
    assert is_readonly("read", {"path": "/docs/x.md"})
    assert is_readonly("tree", {"root": "/docs"})
    assert is_readonly("exec", {"path": "/bin/sql", "stdin": "SELECT * FROM t"})


def test_is_readonly_rejects_mutations():
    assert not is_readonly("write", {"path": "/x", "content": "y"})
    assert not is_readonly("delete", {"path": "/x"})
    assert not is_readonly("exec", {"path": "/bin/sql", "stdin": "UPDATE t SET a=1"})
    assert not is_readonly("exec", {"path": "/bin/id"})   # only /bin/sql exec allowed


def test_run_tool_executes_read_only_and_records():
    # MockVMSpy records/keys RPCs CAPITALIZED ("Read"), though vm.read() is the method.
    fx = {fixture_key("Read", "/docs/x.md"): {"content": "# Policy\nN=2"}}
    vm = MockVMSpy(fx)
    out = run_tool(vm, "read", {"path": "/docs/x.md"})   # investigator tool name is lowercase
    assert "N=2" in out
    assert vm.calls and vm.calls[-1][0] == "Read"


def test_run_tool_rejects_mutation():
    vm = MockVMSpy({})
    with pytest.raises(ToolRejected):
        run_tool(vm, "write", {"path": "/x", "content": "y"})
    assert not any(c[0] == "Write" for c in vm.calls)   # never dispatched


# append to tests/test_investigate.py  (Task 3 security hardening)
def test_is_readonly_rejects_cte_wrapped_dml():
    assert not is_readonly("exec", {"path": "/bin/sql",
                                    "stdin": "WITH x AS (DELETE FROM t RETURNING id) SELECT * FROM x"})


def test_is_readonly_rejects_multi_statement():
    assert not is_readonly("exec", {"path": "/bin/sql", "stdin": "SELECT 1; DROP TABLE t"})


def test_is_readonly_allows_single_trailing_semicolon():
    assert is_readonly("exec", {"path": "/bin/sql", "stdin": "SELECT * FROM t;"})


def test_is_readonly_normalises_sql_binary_path_case():
    assert is_readonly("exec", {"path": "/BIN/SQL", "stdin": "SELECT 1"})


# append to tests/test_investigate.py  (Task 4 stall detection)
from agent.investigate import tool_signature, is_stalled


def test_tool_signature_normalises_sql_whitespace_and_case():
    a = tool_signature("exec", {"path": "/bin/sql", "stdin": "SELECT  *\nFROM t"})
    b = tool_signature("exec", {"path": "/bin/sql", "stdin": "select * from t"})
    assert a == b


def test_is_stalled_on_empty_result():
    assert is_stalled(result="", signature="read:/docs/x.md", seen_signatures=set())


def test_is_stalled_on_repeated_signature():
    assert is_stalled(result="rows", signature="read:/docs/x.md",
                      seen_signatures={"read:/docs/x.md"})


def test_not_stalled_on_fresh_nonempty():
    assert not is_stalled(result="rows", signature="read:/docs/y.md",
                          seen_signatures={"read:/docs/x.md"})
