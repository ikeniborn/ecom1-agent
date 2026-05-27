"""MockVM — stub for EcomRuntimeClientSync used in CODEGEN mock tests."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _ExecResult:
    stdout: str = ""
    stderr: str = ""


@dataclass
class _ReadResult:
    content: str = ""


@dataclass
class _Match:
    path: str
    line: int
    line_text: str


@dataclass
class _SearchResult:
    matches: list[_Match] = field(default_factory=list)


@dataclass
class _Node:
    path: str


@dataclass
class _FindResult:
    nodes: list[_Node] = field(default_factory=list)


@dataclass
class _Entry:
    name: str


@dataclass
class _ListResult:
    entries: list[_Entry] = field(default_factory=list)


class MockVM:
    """Stub for EcomRuntimeClientSync. Returns synthesized data for CODEGEN mock tests.

    Never raises on exec/read/search/etc. — always returns structurally valid responses
    with data synthesized from extracted_params and schema_digest.
    """

    def __init__(self, extracted_params: dict, schema_digest: str) -> None:
        self._params = extracted_params
        self._schema = schema_digest

    def exec(self, req: Any) -> _ExecResult:
        rows = [dict(self._params)] if self._params else [{"id": "mock_001", "value": "mock"}]
        return _ExecResult(stdout=json.dumps(rows))

    def read(self, req: Any) -> _ReadResult:
        path = getattr(req, "path", "/mock/path")
        content = json.dumps({**self._params, "_mock_path": path})
        return _ReadResult(content=content)

    def search(self, req: Any) -> _SearchResult:
        pattern = getattr(req, "pattern", "")
        return _SearchResult(matches=[
            _Match(path="/mock/result.json", line=1, line_text=f"mock match for {pattern}")
        ])

    def find(self, req: Any) -> _FindResult:
        return _FindResult(nodes=[_Node(path="/mock/found.json")])

    def list(self, req: Any) -> _ListResult:
        return _ListResult(entries=[_Entry(name="mock_entry")])

    def tree(self, req: Any) -> str:
        return 'name: "mock_dir" NODE_KIND_DIR\n  name: "mock_file.json" NODE_KIND_FILE'

    def answer(self, req: Any) -> None:
        raise RuntimeError("vm.answer() must not be called from heuristic script")
