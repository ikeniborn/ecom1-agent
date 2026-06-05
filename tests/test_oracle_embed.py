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
