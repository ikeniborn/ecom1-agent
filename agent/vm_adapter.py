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
)


class VMAdapter:
    def __init__(self, client):
        self._c = client

    def read(self, **kwargs):
        return self._c.read(ReadRequest(**kwargs))

    def list(self, **kwargs):
        return self._c.list(ListRequest(**kwargs))

    def tree(self, **kwargs):
        return self._c.tree(TreeRequest(**kwargs))

    def find(self, **kwargs):
        return self._c.find(FindRequest(**kwargs))

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
