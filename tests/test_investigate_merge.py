import agent.investigate as inv


def test_digest_and_route_returns_note_env_and_next_action(monkeypatch):
    def _fake_call_json(system, user, phase, escalate):
        return {
            "observation_digest": "40 rows",
            "lesson": "doc still unread",
            "env_updates": {"rows_found": "40"},
            "next_action": {"tool": "read", "args": {"path": "/docs/fraud.md"}},
        }

    monkeypatch.setattr(inv, "_call_json", _fake_call_json)
    note, env_updates, next_action = inv.digest_and_route(
        goal="g", tool="exec", args={"path": "/bin/sql"}, observation="rows...",
        escalate=False)
    assert note.observation_digest == "40 rows"
    assert env_updates == {"rows_found": "40"}
    assert next_action == {"tool": "read", "args": {"path": "/docs/fraud.md"}}


def test_digest_and_route_done_when_no_next_action(monkeypatch):
    monkeypatch.setattr(inv, "_call_json",
                        lambda *a, **k: {"observation_digest": "d", "lesson": "l"})
    note, env_updates, next_action = inv.digest_and_route(
        goal="g", tool="read", args={"path": "/x"}, observation="o", escalate=False)
    assert next_action is None
