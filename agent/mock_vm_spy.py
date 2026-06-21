"""Recording mock VM: replays canned RPC fixtures for the interpreter and replay tests."""
from __future__ import annotations

from typing import Any


def fixture_key(rpc: str, path: str, args: list[str] | None = None) -> str:
    arg_part = "|".join(args) if args else ""
    return f"{rpc}:{path}:{arg_part}"


_DEFAULT_STUB = {"stdout": "", "stderr": "", "content": "", "entries": [], "nodes": [], "matches": []}


class MockVMSpy:
    """Records every RPC call. Looks up canned responses from `fixtures`.

    Used by the deterministic interpreter and replay tests to drive a PlanIR
    against pre-recorded RPC outputs. NOT for production VM dispatch.
    """

    def __init__(self, fixtures: dict[str, Any]) -> None:
        self.fixtures = fixtures
        self.calls: list[tuple[str, dict]] = []

    def _record(self, rpc: str, **kwargs: Any) -> None:
        self.calls.append((rpc, kwargs))

    def _lookup(self, rpc: str, path: str, args: list[str] | None = None) -> Any:
        return self.fixtures.get(fixture_key(rpc, path, args), _DEFAULT_STUB)

    def _emit(self, rpc: str, kwargs: dict, result, *, mutated: bool = False) -> None:
        from agent import trace
        trace.log_vm_auto(rpc, kwargs, result, mutated=mutated)

    # Signatures accept **kwargs so the spy doesn't reject calls that pass valid
    # proto fields it didn't pre-declare (e.g. read(number=True), find(limit=20)).
    # Only the RPC name + key args drive the fixture lookup, not arg signatures.

    def read(self, path: str = "", **kwargs: Any) -> Any:
        self._record("Read", path=path, **kwargs)
        result = self._lookup("Read", path)
        self._emit("Read", {"path": path, **kwargs}, result)
        return result

    def list(self, path: str = "", **kwargs: Any) -> Any:
        self._record("List", path=path, **kwargs)
        result = self._lookup("List", path)
        self._emit("List", {"path": path, **kwargs}, result)
        return result

    def tree(self, root: str = "", **kwargs: Any) -> Any:
        self._record("Tree", root=root, **kwargs)
        result = self._lookup("Tree", root)
        self._emit("Tree", {"root": root, **kwargs}, result)
        return result

    def find(self, root: str = "", **kwargs: Any) -> Any:
        self._record("Find", root=root, **kwargs)
        result = self._lookup("Find", root)
        self._emit("Find", {"root": root, **kwargs}, result)
        return result

    def search(self, root: str = "", **kwargs: Any) -> Any:
        self._record("Search", root=root, **kwargs)
        result = self._lookup("Search", root)
        self._emit("Search", {"root": root, **kwargs}, result)
        return result

    def exec(self, path: str = "", args: list[str] | None = None, stdin: str = "", **kwargs: Any) -> Any:
        args_list = list(args or [])
        self._record("Exec", path=path, args=args_list, stdin=stdin, **kwargs)
        # Fixture-key fallback: a repaired /bin/sql call delivers SQL on stdin with empty
        # args; key the lookup on [stdin] so fixtures recorded under the SQL string match.
        lookup_args = args_list or ([stdin] if stdin else None)
        result = self._lookup("Exec", path, lookup_args)
        mutated = path.startswith("/bin/") and path not in ("/bin/sql", "/bin/id")
        self._emit("Exec", {"path": path, "args": args_list, "stdin": stdin}, result,
                   mutated=mutated)
        return result

    def write(self, path: str = "", content: str = "", **kwargs: Any) -> Any:
        self._record("Write", path=path, content=content, **kwargs)
        result = self._lookup("Write", path)
        self._emit("Write", {"path": path, "content": content, **kwargs}, result, mutated=True)
        return result

    def delete(self, path: str = "", **kwargs: Any) -> Any:
        self._record("Delete", path=path, **kwargs)
        result = self._lookup("Delete", path)
        self._emit("Delete", {"path": path, **kwargs}, result, mutated=True)
        return result

    def stat(self, path: str = "", **kwargs: Any) -> Any:
        self._record("Stat", path=path, **kwargs)
        result = self._lookup("Stat", path)
        self._emit("Stat", {"path": path, **kwargs}, result)
        return result

    def answer(self, message: str = "", outcome: str = "", refs: list[str] | None = None, **kwargs: Any) -> None:
        self._record("Answer", message=message, outcome=outcome, refs=list(refs or []), **kwargs)
