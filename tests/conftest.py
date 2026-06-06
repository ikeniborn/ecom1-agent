"""Reset module-level state between tests."""
import pytest
import agent.pipeline


@pytest.fixture(autouse=True)
def reset_pipeline_caches():
    agent.pipeline._SDD_ENABLED = True
    yield
    agent.pipeline._SDD_ENABLED = True


@pytest.fixture(autouse=True)
def isolate_oracle_embeddings(tmp_path_factory, monkeypatch):
    """Redirect the oracle's default embeddings cache to a tmp file so tests that
    build a default-path KnowledgeOracle never read or write the repo's
    data/oracle/embeddings.json."""
    import agent.oracle
    emb = tmp_path_factory.mktemp("oracle_emb") / "embeddings.json"
    monkeypatch.setattr(agent.oracle, "_DEFAULT_EMBEDDINGS", emb)
    yield
