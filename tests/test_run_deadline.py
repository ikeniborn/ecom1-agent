import time
from concurrent.futures import ThreadPoolExecutor


def _collect_with_deadline(pool, futures, deadline_s):
    import main
    return main._collect_with_deadline(pool, futures, deadline_s)


def test_collect_returns_finished_and_does_not_block_on_hung_task():
    def quick(n):
        return ("t%02d" % n, n)

    def hung(n):
        time.sleep(60)        # simulates a stuck task
        return ("t99", n)

    pool = ThreadPoolExecutor(max_workers=4)
    try:
        futures = {pool.submit(quick, i): "t%02d" % i for i in range(3)}
        futures[pool.submit(hung, 99)] = "t99"
        t0 = time.monotonic()
        done = _collect_with_deadline(pool, futures, deadline_s=2.0)
        elapsed = time.monotonic() - t0
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    assert elapsed < 10.0, "collection must not block on the hung task"
    assert len(done) == 3, "all quick tasks collected"
    assert "t99" not in done, "hung task excluded"


import os


def test_llm_retry_budget_is_bounded():
    import agent.llm as llm
    max_retries = int(os.environ.get("ECOM_LLM_MAX_RETRIES", "2"))
    # worst-case single-call wall clock must leave room for several cycles in TASK_TIMEOUT_S
    assert llm._HTTP_READ_TIMEOUT_S * (max_retries + 1) <= 400.0
