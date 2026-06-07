# tests/test_corpus_replay.py
import pytest

from tests.replay.conftest import run_old_script, run_plan
from tests.replay.fixtures_t09 import FIXTURES as FX09, PARAMS as P09
from tests.replay.fixtures_t21 import FIXTURES as FX21, PARAMS as P21
from tests.replay.fixtures_t25 import FIXTURES as FX25, PARAMS as P25
from tests.replay.fixtures_t47 import FIXTURES as FX47, PARAMS as P47
from tests.replay.fixtures_t51 import FIXTURES as FX51, PARAMS as P51
from tests.replay.fixtures_t53 import FIXTURES as FX53, PARAMS as P53


def test_t09_replay_matches_known_good():
    assert run_plan("t09", FX09, P09) == run_old_script("t09", FX09, P09)


def test_t21_replay_matches_known_good():
    assert run_plan("t21", FX21, P21) == run_old_script("t21", FX21, P21)


@pytest.mark.parametrize("tid,fx,params", [
    ("t25", FX25, P25), ("t47", FX47, P47),
    ("t51", FX51, P51), ("t53", FX53, P53),
])
def test_corpus_replay_matches_known_good(tid, fx, params):
    assert run_plan(tid, fx, params) == run_old_script(tid, fx, params)


@pytest.mark.skip(reason=(
    "t48 not expressible in current IR: message 'EUR %d.%02d' needs integer "
    "euros/cents split (floor-div + mod — no such primitive; div() yields a "
    "float that stringifies as e.g. '12.0' not '12.00'), and each fraud ref "
    "'<path>#row=<RowID>' requires per-row scalar string concatenation, which "
    "the 13-primitive set + static/$ref-only AnswerTemplateIR.refs cannot build."
))
def test_t48_replay_matches_known_good():  # pragma: no cover - coverage gap
    pass
