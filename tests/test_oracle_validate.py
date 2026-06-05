from agent.oracle_validate import parse_score


def test_parse_score_reads_t38_trial():
    class _Tr:
        task_id = "t38"
        score = 1.0
        score_available = True
        score_detail = []

    class _Res:
        trials = [_Tr()]

    assert parse_score(_Res(), "t38") == (1.0, [])


def test_parse_score_missing_task_returns_none():
    class _Res:
        trials = []

    assert parse_score(_Res(), "t38") == (None, [])
