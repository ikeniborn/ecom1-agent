"""Structural tests for the deterministic Excalidraw generator."""
import json

import pytest

import tools.gen_excalidraw as gx


def test_grid_and_gaps_are_positive_and_grid_snapped():
    assert gx.GRID == 20
    # spec: adjacent boxes keep a gap of at least 40px
    assert gx.ROW_GAP >= 40
    assert gx.COL_GAP >= 40
    assert gx.FRAME_PAD >= 40
    # all spacing is a multiple of the grid step (snap is a no-op on them)
    for v in (gx.ROW_GAP, gx.COL_GAP, gx.FRAME_PAD, gx.FRAME_VGAP, gx.NODE_W, gx.NODE_H):
        assert gx.snap(v) == v


def test_palette_covers_every_legend_kind():
    assert set(gx.KIND) == {"llm", "gate", "store", "branch", "terminal"}
    for kind, spec in gx.KIND.items():
        assert spec["shape"] in {"rectangle", "diamond", "ellipse"}
        assert spec["bg"].startswith("#")
