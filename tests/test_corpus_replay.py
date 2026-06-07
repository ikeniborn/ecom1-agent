# tests/test_corpus_replay.py
from tests.replay.conftest import run_old_script, run_plan
from tests.replay.fixtures_t09 import FIXTURES as FX09, PARAMS as P09
from tests.replay.fixtures_t21 import FIXTURES as FX21, PARAMS as P21


def test_t09_replay_matches_known_good():
    assert run_plan("t09", FX09, P09) == run_old_script("t09", FX09, P09)


def test_t21_replay_matches_known_good():
    assert run_plan("t21", FX21, P21) == run_old_script("t21", FX21, P21)
