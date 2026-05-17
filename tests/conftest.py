"""Reset module-level caches between tests."""
import pytest
import agent.pipeline


@pytest.fixture(autouse=True)
def reset_pipeline_caches():
    agent.pipeline._rules_loader_cache = None
    agent.pipeline._security_gates_cache = None
    agent.pipeline._SDD_ENABLED = True
    _prev_eval = agent.pipeline._EVAL_ENABLED
    agent.pipeline._EVAL_ENABLED = False
    yield
    agent.pipeline._rules_loader_cache = None
    agent.pipeline._security_gates_cache = None
    agent.pipeline._SDD_ENABLED = True
    agent.pipeline._EVAL_ENABLED = _prev_eval
