"""Tests for orchestrator helpers (schema/sample-row discovery + augmentation)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.orchestrator import (
    _augment_agents_md,
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
