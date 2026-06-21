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


from agent.investigate import _forced_doc_read


def test_forced_read_targets_ungrounded_policy_doc():
    act = _forced_doc_read({}, _policy_refs())
    assert act == {"tool": "read", "args": {"path": "/docs/fraud.md"}}


def test_forced_read_none_when_already_grounded():
    assert _forced_doc_read({"policy_doc:/docs/fraud.md": True}, _policy_refs()) is None


def test_forced_read_none_without_policy_refs():
    assert _forced_doc_read({}, []) is None
