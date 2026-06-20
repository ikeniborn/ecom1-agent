import agent.reasoning_capture as rc


def test_pop_capture_empty_without_push():
    rc._sink.items = []  # reset thread-local
    assert rc.pop_capture() == {"reasoning": "", "raw_full": ""}


def test_push_then_pop_prefers_item_with_reasoning():
    rc._sink.items = []
    rc._push("", "raw-a")
    rc._push("the reasoning", "raw-b")
    cap = rc.pop_capture()
    assert cap["reasoning"] == "the reasoning"
    assert cap["raw_full"] == "raw-b"
    # pop resets
    assert rc.pop_capture() == {"reasoning": "", "raw_full": ""}


def test_reasoning_from_openai_resp_handles_think_inline():
    class _Resp:
        def model_dump(self):
            return {"choices": [{"message": {"content": "<think>why</think>answer"}}]}

    reasoning, full = rc._reasoning_from_openai_resp(_Resp())
    assert reasoning == "why" and full == "<think>why</think>answer"


def test_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("ECOM_TRACE_REASONING", raising=False)
    assert rc.enabled() is False
    monkeypatch.setenv("ECOM_TRACE_REASONING", "1")
    assert rc.enabled() is True
