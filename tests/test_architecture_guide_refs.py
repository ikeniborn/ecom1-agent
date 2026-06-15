"""Verify every `path:line` reference in the architecture guide resolves."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "architecture" / "agent-architecture-guide.md"

# matches `agent/pipeline.py:928` and `agent/pipeline.py:1052-1098` inside backticks
REF = re.compile(r"`([\w./]+\.py):(\d+)(?:-(\d+))?`")


def _refs():
    text = GUIDE.read_text(encoding="utf-8")
    for m in REF.finditer(text):
        path, lo, hi = m.group(1), int(m.group(2)), m.group(3)
        yield path, lo, int(hi) if hi else lo


def test_guide_exists():
    assert GUIDE.exists()


def test_every_reference_resolves():
    missing = []
    for path, lo, hi in _refs():
        f = ROOT / path
        if not f.exists():
            missing.append(f"{path} (no such file)")
            continue
        n = len(f.read_text(encoding="utf-8").splitlines())
        if hi > n:
            missing.append(f"{path}:{hi} exceeds file length {n}")
    assert not missing, "stale references:\n" + "\n".join(missing)


def test_guide_has_some_references():
    assert sum(1 for _ in _refs()) >= 20   # guard against an empty/garbled guide
