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

    # Signatures accept **kwargs so the fidelity gate doesn't reject scripts
    # that pass valid proto fields the spy didn't pre-declare (e.g. read(number=True),
    # find(limit=20)). The gate compares RPC multiset, not arg signatures.

    def read(self, path: str = "", **kwargs: Any) -> Any:
        self._record("Read", path=path, **kwargs)
        return self._lookup("Read", path)

    def list(self, path: str = "", **kwargs: Any) -> Any:
        self._record("List", path=path, **kwargs)
        return self._lookup("List", path)

    def tree(self, root: str = "", **kwargs: Any) -> Any:
        self._record("Tree", root=root, **kwargs)
        return self._lookup("Tree", root)

    def find(self, root: str = "", **kwargs: Any) -> Any:
        self._record("Find", root=root, **kwargs)
        return self._lookup("Find", root)

    def search(self, root: str = "", **kwargs: Any) -> Any:
        self._record("Search", root=root, **kwargs)
        return self._lookup("Search", root)

    def exec(self, path: str = "", args: list[str] | None = None, stdin: str = "", **kwargs: Any) -> Any:
        args_list = list(args or [])
        self._record("Exec", path=path, args=args_list, stdin=stdin, **kwargs)
        return self._lookup("Exec", path, args_list)

    def write(self, path: str = "", content: str = "", **kwargs: Any) -> Any:
        self._record("Write", path=path, content=content, **kwargs)
        return self._lookup("Write", path)

    def delete(self, path: str = "", **kwargs: Any) -> Any:
        self._record("Delete", path=path, **kwargs)
        return self._lookup("Delete", path)

    def stat(self, path: str = "", **kwargs: Any) -> Any:
        self._record("Stat", path=path, **kwargs)
        return self._lookup("Stat", path)

    def answer(self, message: str = "", outcome: str = "", refs: list[str] | None = None, **kwargs: Any) -> None:
        self._record("Answer", message=message, outcome=outcome, refs=list(refs or []), **kwargs)
