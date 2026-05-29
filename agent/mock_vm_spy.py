"""Recording mock VM used inside the fidelity gate."""
from __future__ import annotations

from typing import Any


def fixture_key(rpc: str, path: str, args: list[str] | None = None) -> str:
    arg_part = "|".join(args) if args else ""
    return f"{rpc}:{path}:{arg_part}"


_DEFAULT_STUB = {"stdout": "", "stderr": "", "content": "", "entries": [], "nodes": [], "matches": []}


class MockVMSpy:
    """Records every RPC call. Looks up canned responses from `fixtures`.

    Designed for use inside the deterministic fidelity test produced by
    `agent.fidelity.generate_fidelity_test`. NOT for production VM dispatch.
    """

    def __init__(self, fixtures: dict[str, Any]) -> None:
        self.fixtures = fixtures
        self.calls: list[tuple[str, dict]] = []

    def _record(self, rpc: str, **kwargs: Any) -> None:
        self.calls.append((rpc, kwargs))

    def _lookup(self, rpc: str, path: str, args: list[str] | None = None) -> Any:
        return self.fixtures.get(fixture_key(rpc, path, args), _DEFAULT_STUB)

    def read(self, path: str) -> Any:
        self._record("Read", path=path)
        return self._lookup("Read", path)

    def list(self, path: str) -> Any:
        self._record("List", path=path)
        return self._lookup("List", path)

    def tree(self, root: str, level: int = 0) -> Any:
        self._record("Tree", root=root, level=level)
        return self._lookup("Tree", root)

    def find(self, root: str, name: str = "", kind: str = "", limit: int = 0) -> Any:
        self._record("Find", root=root, name=name, kind=kind, limit=limit)
        return self._lookup("Find", root)

    def search(self, root: str, pattern: str = "", limit: int = 0) -> Any:
        self._record("Search", root=root, pattern=pattern, limit=limit)
        return self._lookup("Search", root)

    def exec(self, path: str, args: list[str] | None = None, stdin: str = "") -> Any:
        args_list = list(args or [])
        self._record("Exec", path=path, args=args_list, stdin=stdin)
        return self._lookup("Exec", path, args_list)

    def write(self, path: str, content: str = "", if_match_sha256: str = "") -> Any:
        self._record("Write", path=path, content=content, if_match_sha256=if_match_sha256)
        return self._lookup("Write", path)

    def delete(self, path: str) -> Any:
        self._record("Delete", path=path)
        return self._lookup("Delete", path)

    def stat(self, path: str) -> Any:
        self._record("Stat", path=path)
        return self._lookup("Stat", path)

    def answer(self, message: str, outcome: str, refs: list[str] | None = None) -> None:
        self._record("Answer", message=message, outcome=outcome, refs=list(refs or []))
