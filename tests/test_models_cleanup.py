def test_test_output():
    from agent.models import TestOutput
    out = TestOutput(
        reasoning="r",
        sql_tests="def test_sql(results): pass",
        answer_tests="def test_answer(sql_results, answer): pass",
    )
    assert "test_sql" in out.sql_tests
