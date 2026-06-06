from unittest.mock import patch
import agent.llm as llm


def test_embed_texts_calls_ollama_and_returns_vectors():
    fake = {"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]}

    class _Resp:
        status_code = 200

        def json(self):
            return fake

        def raise_for_status(self):
            pass

    with patch("agent.llm.httpx.post", return_value=_Resp()) as post:
        vecs = llm.embed_texts(["a", "b"], model="nomic-embed-text",
                               base_url="http://localhost:11434/v1")
    assert vecs == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert post.called


def test_nomic_prefix_applied_to_inputs():
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"data": [{"embedding": [0.0]}]}
        def raise_for_status(self):
            pass

    def _fake_post(url, json, headers, timeout):
        captured["input"] = json["input"]
        return _Resp()

    with patch("agent.llm.httpx.post", side_effect=_fake_post):
        llm.embed_texts(["hello"], model="nomic-embed-text", prefix="search_query")
    assert captured["input"] == ["search_query: hello"]


def test_non_nomic_model_gets_raw_text():
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"data": [{"embedding": [0.0]}]}
        def raise_for_status(self):
            pass

    def _fake_post(url, json, headers, timeout):
        captured["input"] = json["input"]
        return _Resp()

    with patch("agent.llm.httpx.post", side_effect=_fake_post):
        llm.embed_texts(["hello"], model="mxbai-embed-large", prefix="search_query")
    assert captured["input"] == ["hello"]
