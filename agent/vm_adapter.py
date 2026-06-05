"""Kwargs-style adapter over EcomRuntimeClientSync.

Generated heuristic scripts + pipeline terminals use kwargs (matching MockVMSpy):
    vm.exec(path="/bin/sql", args=[...])
    vm.answer(message=..., outcome=..., refs=[...])

Real client takes protobuf requests. This adapter bridges the two.
"""
from __future__ import annotations

from bitgn.vm.ecom.ecom_pb2 import (
    ReadRequest, ListRequest, TreeRequest, FindRequest, SearchRequest,
    ExecRequest, WriteRequest, DeleteRequest, StatRequest, AnswerRequest,
    NodeKind,
)


_NODE_KIND_ALIASES = {
    "": NodeKind.NODE_KIND_UNSPECIFIED,
    "any": NodeKind.NODE_KIND_UNSPECIFIED,
    "all": NodeKind.NODE_KIND_UNSPECIFIED,
    "unspecified": NodeKind.NODE_KIND_UNSPECIFIED,
    "node_kind_unspecified": NodeKind.NODE_KIND_UNSPECIFIED,
    "file": NodeKind.NODE_KIND_FILE,
    "node_kind_file": NodeKind.NODE_KIND_FILE,
    "dir": NodeKind.NODE_KIND_DIR,
    "directory": NodeKind.NODE_KIND_DIR,
    "folder": NodeKind.NODE_KIND_DIR,
    "node_kind_dir": NodeKind.NODE_KIND_DIR,
}


def _normalise_kind(kwargs: dict) -> dict:
    """Map free-form kind strings ('file', 'dir', ...) to NodeKind enum values.

    LLM-generated scripts commonly emit lower-case English ('file', 'dir');
    protobuf only accepts the enum int or full label. Without this bridge,
    every Find/Tree call dies with 'unknown enum label "file"'.
    """
    if "kind" not in kwargs:
        return kwargs
    k = kwargs["kind"]
    if isinstance(k, str):
        kwargs = dict(kwargs)
        kwargs["kind"] = _NODE_KIND_ALIASES.get(k.lower().strip(), k)
    return kwargs


class VMAdapter:
    def __init__(self, client):
        self._c = client

    def read(self, **kwargs):
        return self._c.read(ReadRequest(**kwargs))

    def list(self, **kwargs):
        return self._c.list(ListRequest(**kwargs))

    def tree(self, **kwargs):
        return self._c.tree(TreeRequest(**_normalise_kind(kwargs)))

    def find(self, **kwargs):
        return self._c.find(FindRequest(**_normalise_kind(kwargs)))

    def search(self, **kwargs):
        return self._c.search(SearchRequest(**kwargs))

    def exec(self, **kwargs):
        return self._c.exec(ExecRequest(**kwargs))

    def write(self, **kwargs):
        return self._c.write(WriteRequest(**kwargs))

    def delete(self, **kwargs):
        return self._c.delete(DeleteRequest(**kwargs))

    def stat(self, **kwargs):
        return self._c.stat(StatRequest(**kwargs))

    def answer(self, **kwargs):
        return self._c.answer(AnswerRequest(**kwargs))
