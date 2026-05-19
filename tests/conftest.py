"""Reset module-level state between tests."""
import pytest
import agent.pipeline


@pytest.fixture(autouse=True)
def reset_pipeline_caches():
    agent.pipeline._SDD_ENABLED = True
    yield
    agent.pipeline._SDD_ENABLED = True
