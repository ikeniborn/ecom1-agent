from agent.investigate import _ground_doc_refs
from agent.ir_models import RefSpec


def _policy_refs():
    return [RefSpec(kind="policy_doc", path="/docs/fraud.md")]


def test_ground_sets_env_on_matching_read():
    env = {}
    _ground_doc_refs(env, "read", {"path": "/docs/fraud.md"}, _policy_refs())
    assert env.get("policy_doc:/docs/fraud.md") is True


def test_ground_ignores_nonmatching_path():
    env = {}
    _ground_doc_refs(env, "read", {"path": "/docs/other.md"}, _policy_refs())
    assert env == {}


def test_ground_ignores_nonread_tool():
    env = {}
    _ground_doc_refs(env, "exec", {"path": "/bin/sql"}, _policy_refs())
    assert env == {}


def test_ground_noop_without_policy_refs():
    env = {}
    _ground_doc_refs(env, "read", {"path": "/docs/fraud.md"}, [])
    assert env == {}
