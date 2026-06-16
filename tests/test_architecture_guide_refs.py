"""Verify every `path:line` reference in the architecture guide resolves — both
that the line exists (bounds) and, where the guide names a symbol next to the
ref, that the symbol actually lives on/near that line (identity)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "architecture" / "agent-architecture-guide.md"

# matches `agent/pipeline.py:928` and `agent/pipeline.py:1052-1098` inside backticks
REF = re.compile(r"`([\w./]+\.py):(\d+)(?:-(\d+))?`")

# `path.py:line` immediately followed (optionally via an em-dash) by a backticked
# symbol, e.g.  `agent/pipeline.py:214` — `run_pipeline`  or  `agent/oracle.py:90` `retrieve`
SYM = re.compile(r"`([\w./]+\.py):(\d+)`(?:\s*—)?\s+`([^`]+)`")


def _refs():
    text = GUIDE.read_text(encoding="utf-8")
    for m in REF.finditer(text):
        path, lo, hi = m.group(1), int(m.group(2)), m.group(3)
        yield path, lo, int(hi) if hi else lo


def _sym_refs():
    """Yield (path, line, identifier) for refs that name an adjacent symbol.

    Skips pairs where the 'symbol' is actually another path reference."""
    text = GUIDE.read_text(encoding="utf-8")
    for m in SYM.finditer(text):
        path, line, sym = m.group(1), int(m.group(2)), m.group(3)
        if "/" in sym or ".py" in sym:          # the next token is another ref, not a symbol
            continue
        ident = re.match(r"[A-Za-z_]\w*", sym)   # leading identifier of e.g. `main()` -> main
        if not ident:
            continue
        yield path, line, ident.group()


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


def test_named_symbols_live_on_referenced_line():
    """Stronger than bounds: the named symbol must appear on the referenced line
    (±2 lines, to tolerate decorators / multi-line signatures)."""
    wrong = []
    seen = 0
    for path, line, ident in _sym_refs():
        f = ROOT / path
        if not f.exists():
            wrong.append(f"{path} (no such file)")
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        seen += 1
        window = lines[max(0, line - 3): line + 2]   # lines (line-2)..(line+2), 1-based
        if not any(ident in ln for ln in window):
            wrong.append(f"{path}:{line} should contain {ident!r}; got {lines[line-1].strip()!r}")
    assert not wrong, "symbol/line drift:\n" + "\n".join(wrong)
    # guard against the regex silently matching nothing
    assert seen >= 10, f"expected >=10 named-symbol refs, found {seen}"


def test_guide_has_some_references():
    assert sum(1 for _ in _refs()) >= 20   # guard against an empty/garbled guide
